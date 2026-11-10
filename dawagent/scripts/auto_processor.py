#!/usr/bin/env python3
"""
auto_processor.py — DAWAGENT Hit-Record Studio Mastering & Stem Processor.

Polls the sessions/ directory (every 4s) for pending handoff.json files and processes
them using a transparent 2-pass linear loudness mastering chain (-10.0 LUFS, -0.8 dBTP,
sub-90Hz mono crossover, harmonic soft-clipping, zero double-compression), exports
24-bit/48kHz FLAC + 320kbps MP3, and writes notification.json + production_receipt.json.

Runs as a daemon inside the dawagent container.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths ──
SESSIONS_DIR = Path(os.environ.get("DAWAGENT_SESSIONS", "/opt/dawagent/sessions"))
EXPORTS_DIR = Path(os.environ.get("DAWAGENT_EXPORTS", "/opt/dawagent/exports"))
LOG_FILE = Path(os.environ.get("AUTO_PROCESSOR_LOG", "/opt/dawagent/auto_processor.log"))
POLL_INTERVAL = int(os.environ.get("AUTO_PROCESSOR_POLL", "4"))
MANIFEST_NAME = "handoff.json"

# ── Studio Hit-Record Mastering Targets (VØIDRIDE Streaming/Club) ──
DEFAULT_LUFS = -10.0
DEFAULT_TRUE_PEAK = -0.8
DEFAULT_LRA = 9.0

DEFAULT_VOLUMES = {
    "drums": 1.0,
    "bass": 0.92,
    "vocals": 1.05,
    "other": 0.85,
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[auto_processor {ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def update_manifest_status(manifest_path, status, extra=None):
    """Update the handoff manifest status atomically."""
    with open(manifest_path) as f:
        manifest = json.load(f)
    manifest["status"] = status
    manifest[f"{status}_at"] = datetime.now().isoformat()
    if extra:
        manifest.update(extra)
    tmp_path = manifest_path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(manifest, f, indent=2)
    tmp_path.replace(manifest_path)
    return manifest


def find_stems(session_dir):
    """Find discrete audio stems in the session's interchange directory."""
    interchange = session_dir / "interchange"
    if not interchange.exists():
        return []

    stems = []
    for ext in ["*.wav", "*.flac", "*.mp3", "*.ogg", "*.aiff"]:
        for p in interchange.glob(ext):
            # Never accidentally include a full mix file if one was dropped in interchange/
            if p.name.lower().startswith(("mix_", "master_", "premaster")):
                continue
            stems.append(p)
    return sorted(stems)


def get_stem_volume(stem_path, manifest):
    """Get the volume for a stem from the manifest or defaults."""
    stem_name = stem_path.stem.lower()
    # Pre-arranged daw_stems (01_main, 02_texture, etc.) already have dynamic arrangement envelopes baked in
    if len(stem_name) > 3 and stem_name[:2].isdigit() and stem_name[2] == "_":
        return 1.0

    stem_volumes = manifest.get("stem_volumes", {})
    if stem_name in stem_volumes:
        return stem_volumes[stem_name]
    for role, vol in stem_volumes.items():
        if role.lower() in stem_name or stem_name in role.lower():
            return vol
    for key, vol in DEFAULT_VOLUMES.items():
        if key in stem_name:
            return vol
    return 1.0


def build_premix_from_stems(stems, manifest, premix_out, use_sidechain=True):
    """Sum discrete stems cleanly to a 32-bit float premaster WAV without double-compression."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for stem in stems:
        cmd.extend(["-i", str(stem)])

    n = len(stems)
    filters = []
    core_labels = []
    bed_labels = []

    for i, stem in enumerate(stems):
        vol = get_stem_volume(stem, manifest)
        sname = stem.stem.lower()
        filters.append(f"[{i}:a]volume={vol}[s{i}]")
        if any(k in sname for k in ("texture", "atmosphere", "spatial", "b_section", "ear_candy", "other", "instrument")):
            bed_labels.append(f"[s{i}]")
        else:
            core_labels.append(f"[s{i}]")

    if use_sidechain and core_labels and bed_labels:
        if len(core_labels) > 1:
            cw = " ".join("1.0" for _ in core_labels)
            filters.append(f"{''.join(core_labels)}amix=inputs={len(core_labels)}:duration=longest:normalize=0:weights={cw}[core_bus]")
        else:
            filters.append(f"{core_labels[0]}acopy[core_bus]")

        if len(bed_labels) > 1:
            bw = " ".join("1.0" for _ in bed_labels)
            filters.append(f"{''.join(bed_labels)}amix=inputs={len(bed_labels)}:duration=longest:normalize=0:weights={bw}[bed_bus]")
        else:
            filters.append(f"{bed_labels[0]}acopy[bed_bus]")

        filters.append("[core_bus]asplit=2[core_main][sc_raw]")
        filters.append("[sc_raw]lowpass=f=135,highpass=f=30[sc_key]")
        filters.append("[bed_bus][sc_key]sidechaincompress=threshold=0.04:ratio=3.2:attack=5:release=185:detection=peak:mix=0.68[bed_ducked]")
        filters.append("[core_main][bed_ducked]amix=inputs=2:duration=longest:normalize=0:weights=1.0 1.0[out]")
    else:
        mix_inputs = "".join(f"[s{i}]" for i in range(n))
        weights_str = " ".join("1.0" for _ in range(n))
        filters.append(f"{mix_inputs}amix=inputs={n}:duration=longest:normalize=0:weights={weights_str}[out]")

    cmd.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[out]",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le",
        str(premix_out),
    ])
    return cmd


def measure_loudness(filepath, pre_chain=""):
    """Run Pass 1 EBU R128 loudness measurement and return stats dict."""
    af = f"{pre_chain},loudnorm=I=-10:TP=-0.8:LRA=9:print_format=json" if pre_chain else "loudnorm=I=-10:TP=-0.8:LRA=9:print_format=json"
    cmd = ["ffmpeg", "-hide_banner", "-i", str(filepath), "-af", af, "-f", "null", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        j_start = res.stderr.rfind("{")
        j_end = res.stderr.rfind("}") + 1
        if j_start >= 0 and j_end > j_start:
            return json.loads(res.stderr[j_start:j_end])
    except Exception:
        pass
    return {}


def master_two_pass(input_wav, manifest, flac_output):
    """Apply transparent 2-pass linear loudness mastering with sub-90Hz mono lock & harmonic soft-clip."""
    mastering = manifest.get("mastering_profile", {})
    lufs = float(mastering.get("lufs", DEFAULT_LUFS))
    tp = float(mastering.get("true_peak", DEFAULT_TRUE_PEAK))
    lra = float(mastering.get("lra", DEFAULT_LRA))

    plan_text = json.dumps(manifest.get("processing_plan", {})).lower()
    sub_gain = 1.5 if ("sub" in plan_text or "808" in plan_text or lufs >= -11.0) else 1.1
    air_gain = 1.3 if ("air" in plan_text or "spatial" in plan_text or "shimmer" in plan_text) else 1.0
    side_w = 1.14 if ("stereo" in plan_text or "wide" in plan_text or "haas" in plan_text) else 1.10

    # Tone & spatial sculpt BEFORE loudness normalization (NO heavy compressor — preserves transient punch!)
    pre_stages = [
        "highpass=f=24:p=2",
        f"equalizer=f=50:t=q:w=1.1:g={sub_gain}",
        "equalizer=f=265:t=q:w=1.6:g=-1.3",
        "equalizer=f=3200:t=q:w=1.2:g=0.9",
        f"equalizer=f=10500:t=h:w=0.7:g={air_gain}",
        f"stereotools=mlev=1.0:slev={side_w}",
    ]
    pre_chain = ",".join(pre_stages)

    # Pass 1 measurement
    stats = measure_loudness(input_wav, pre_chain=pre_chain)
    in_i = stats.get("input_i")
    in_tp = stats.get("input_tp")
    in_lra = stats.get("input_lra")
    in_thresh = stats.get("input_thresh")
    t_off = stats.get("target_offset")

    if all(v is not None and str(v) not in ("-inf", "inf", "nan") for v in (in_i, in_tp, in_lra, in_thresh, t_off)):
        ln_filter = (
            f"loudnorm=I={lufs}:TP={tp}:LRA={lra}"
            f":measured_I={in_i}:measured_TP={in_tp}:measured_LRA={in_lra}"
            f":measured_thresh={in_thresh}:offset={t_off}:linear=true"
        )
        log(f"  📐 Pass 1: {in_i} LUFS (TP {in_tp} dBTP, LRA {in_lra} LU) → Pass 2 linear target {lufs} LUFS")
    else:
        ln_filter = f"loudnorm=I={lufs}:TP={tp}:LRA={lra}"

    # Sub-90Hz mono crossover + Pass 2 linear loudnorm + harmonic soft-clip + brickwall true-peak ceiling
    fc = (
        f"[0:a]{pre_chain},acrossover=split=90[low][high];"
        f"[low]pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1[lowm];"
        f"[lowm][high]amix=inputs=2:duration=longest:normalize=0:weights=1 1,"
        f"{ln_filter},"
        f"asoftclip=type=sin:param=0.82,"
        f"alimiter=limit={tp}dB:level=false[out]"
    )

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_wav),
        "-filter_complex", fc,
        "-map", "[out]",
        "-ar", "48000", "-ac", "2", "-sample_fmt", "s32",
        str(flac_output),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        # Clean fallback without acrossover if needed
        fb_af = f"{pre_chain},{ln_filter},asoftclip=type=sin:param=0.82,alimiter=limit={tp}dB:level=false"
        cmd_fb = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_wav),
            "-af", fb_af,
            "-ar", "48000", "-ac", "2", "-sample_fmt", "s32",
            str(flac_output),
        ]
        res = subprocess.run(cmd_fb, capture_output=True, text=True, timeout=300)
    return res


def build_ffmpeg_mp3_cmd(flac_path, mp3_path):
    """Convert FLAC to 320kbps MP3."""
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(flac_path),
        "-codec:a", "libmp3lame", "-b:a", "320k",
        "-ar", "48000",
        str(mp3_path),
    ]


def write_notification(export_dir, session_name, manifest, flac_path, mp3_path, post_stats=None):
    """Write notification.json and production_receipt.json."""
    master_prof = manifest.get("mastering_profile", {
        "lufs": DEFAULT_LUFS,
        "true_peak": DEFAULT_TRUE_PEAK,
        "lra": DEFAULT_LRA,
    })
    notification = {
        "session": session_name,
        "source": manifest.get("source", "dawagent"),
        "album": manifest.get("album", ""),
        "bpm": manifest.get("bpm", 134),
        "key": manifest.get("key", ""),
        "genre": manifest.get("genre", ""),
        "status": "exported",
        "processed_at": datetime.now().isoformat(),
        "exports": [
            {"type": "flac", "path": str(flac_path), "filename": flac_path.name},
        ],
        "stems_processed": manifest.get("stem_count", 0),
        "mastering_profile": master_prof,
        "measured_master": post_stats or {},
    }
    if mp3_path and mp3_path.exists():
        notification["exports"].append(
            {"type": "mp3", "path": str(mp3_path), "filename": mp3_path.name}
        )

    notif_path = export_dir / "notification.json"
    with open(notif_path, "w") as f:
        json.dump(notification, f, indent=2)

    receipt_path = export_dir / "production_receipt.json"
    with open(receipt_path, "w") as f:
        json.dump(notification, f, indent=2)

    log(f"  ✓ Wrote notification.json & production_receipt.json")
    return notif_path


def process_job(session_dir, manifest_path):
    """Process a single handoff job: premaster/mix → 2-pass studio master → export."""
    session_name = session_dir.name

    with open(manifest_path) as f:
        manifest = json.load(f)

    log(f"Processing: {session_name}")
    log(f"  Source: {manifest.get('source', '?')} | BPM: {manifest.get('bpm', '?')} | "
        f"Key: {manifest.get('key', '?')} | Stems: {manifest.get('stem_count', '?')}")

    update_manifest_status(manifest_path, "processing")

    stems = find_stems(session_dir)
    premaster_rel = manifest.get("premaster_filename")
    premaster_local = (session_dir / premaster_rel) if premaster_rel else None

    if not stems and not (premaster_local and premaster_local.exists()):
        log(f"  ✗ No stems or premaster found in {session_dir}")
        update_manifest_status(manifest_path, "failed", {"error": "No stems found in interchange directory"})
        return False

    export_dir = EXPORTS_DIR / session_name
    export_dir.mkdir(parents=True, exist_ok=True)

    flac_output = export_dir / f"{session_name}_MASTER.flac"
    mp3_output = export_dir / f"{session_name}_MASTER.mp3"

    if flac_output.exists() and flac_output.stat().st_size > 10000:
        log(f"  ⏭ Already exported: {flac_output.name}")
        update_manifest_status(manifest_path, "processed")
        return True

    temp_premix = None
    try:
        if premaster_local and premaster_local.exists():
            log(f"  🎚️ Using unmastered 3D sidechain premaster: {premaster_local.name}")
            master_input = premaster_local
        elif len(stems) == 1:
            log(f"  🎚️ Mastering single stem: {stems[0].name}")
            master_input = stems[0]
        else:
            log(f"  🎚️ Summing {len(stems)} discrete stems: {[s.name for s in stems]}")
            temp_premix = session_dir / "_daw_premix_tmp.wav"
            mix_cmd = build_premix_from_stems(stems, manifest, temp_premix, use_sidechain=True)
            m_res = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=300)
            if m_res.returncode != 0:
                mix_cmd = build_premix_from_stems(stems, manifest, temp_premix, use_sidechain=False)
                m_res = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=300)
            if m_res.returncode != 0 or not temp_premix.exists():
                log(f"  ✗ Premix failed: {m_res.stderr[-250:]}")
                update_manifest_status(manifest_path, "failed", {"error": f"Premix failed: {m_res.stderr[-200:]}"})
                return False
            master_input = temp_premix

        log(f"  🚀 Running 2-pass linear hit-record mastering...")
        result = master_two_pass(master_input, manifest, flac_output)
        if result.returncode != 0:
            log(f"  ✗ Mastering failed: {result.stderr[-300:]}")
            update_manifest_status(manifest_path, "failed", {"error": f"ffmpeg failed: {result.stderr[-200:]}"})
            return False

        if not flac_output.exists() or flac_output.stat().st_size < 1000:
            log(f"  ✗ Output file missing or empty")
            update_manifest_status(manifest_path, "failed", {"error": "Output file missing or too small"})
            return False

        post_raw = measure_loudness(flac_output)
        post_stats = {}
        if post_raw.get("input_i") is not None:
            post_stats = {
                "integrated_lufs": post_raw.get("input_i"),
                "true_peak_db": post_raw.get("input_tp"),
                "lra": post_raw.get("input_lra"),
            }
            log(f"  📊 Post-Master Verified: {post_stats['integrated_lufs']} LUFS | TP {post_stats['true_peak_db']} dBTP | LRA {post_stats['lra']} LU")

        flac_size_mb = flac_output.stat().st_size / (1024 * 1024)
        log(f"  ✓ FLAC exported: {flac_output.name} ({flac_size_mb:.1f} MB)")

        mp3_cmd = build_ffmpeg_mp3_cmd(flac_output, mp3_output)
        mp3_result = subprocess.run(mp3_cmd, capture_output=True, text=True, timeout=120)
        if mp3_result.returncode == 0 and mp3_output.exists():
            mp3_size_mb = mp3_output.stat().st_size / (1024 * 1024)
            log(f"  ✓ MP3 exported: {mp3_output.name} ({mp3_size_mb:.1f} MB)")
        else:
            log(f"  ⚠ MP3 conversion failed (non-fatal)")
            mp3_output = None

        shutil.copy2(str(manifest_path), str(export_dir / "handoff.json"))
        write_notification(export_dir, session_name, manifest, flac_output, mp3_output, post_stats=post_stats)

        update_manifest_status(manifest_path, "processed", {
            "export_dir": str(export_dir),
            "flac": str(flac_output),
            "mp3": str(mp3_output) if mp3_output else None,
            "measured_master": post_stats,
        })

        log(f"  ✓ Job complete: {session_name}")
        return True

    except subprocess.TimeoutExpired:
        log(f"  ✗ Processing timed out")
        update_manifest_status(manifest_path, "failed", {"error": "Processing timed out"})
        return False
    except Exception as e:
        log(f"  ✗ Unexpected error: {e}")
        update_manifest_status(manifest_path, "failed", {"error": str(e)})
        return False
    finally:
        if temp_premix and temp_premix.exists():
            try:
                temp_premix.unlink()
            except Exception:
                pass


def scan_and_process():
    """Scan for pending jobs and process them."""
    if not SESSIONS_DIR.exists():
        return 0

    processed = 0
    for session_dir in sorted(SESSIONS_DIR.iterdir()):
        if not session_dir.is_dir():
            continue

        manifest_path = session_dir / MANIFEST_NAME
        if not manifest_path.exists():
            continue

        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log(f"⚠ Bad manifest in {session_dir.name}: {e}")
            continue

        status = manifest.get("status", "")
        if status != "pending":
            continue

        if process_job(session_dir, manifest_path):
            processed += 1

    return processed


def main():
    log("=" * 50)
    log("DAWAGENT Studio Auto-Processor starting (2-pass -10 LUFS)")
    log(f"Sessions: {SESSIONS_DIR}")
    log(f"Exports:  {EXPORTS_DIR}")
    log(f"Poll:     {POLL_INTERVAL}s")
    log("=" * 50)

    initial = scan_and_process()
    if initial:
        log(f"Processed {initial} pending jobs on startup")

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            count = scan_and_process()
            if count:
                log(f"Processed {count} job(s) this cycle")
        except Exception as e:
            log(f"✗ Scan error: {e}")


if __name__ == "__main__":
    main()
