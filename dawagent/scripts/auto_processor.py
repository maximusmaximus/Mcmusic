#!/usr/bin/env python3
"""
auto_processor.py — DAWAGENT automated job processor.

Polls the sessions/ directory for pending handoff.json files and processes
them using ffmpeg: mixes stems, applies mastering chain, exports FLAC + MP3,
and writes notification.json for the hermes-music notify_processed daemon.

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
POLL_INTERVAL = int(os.environ.get("AUTO_PROCESSOR_POLL", "30"))
MANIFEST_NAME = "handoff.json"

# ── Default mastering targets ──
DEFAULT_LUFS = -14
DEFAULT_TRUE_PEAK = -1
DEFAULT_LRA = 11

# ── Default stem volumes (gain coefficients) ──
DEFAULT_VOLUMES = {
    "drums": 1.0,
    "bass": 0.9,
    "vocals": 1.1,
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
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def find_stems(session_dir):
    """Find audio stems in the session's interchange directory."""
    interchange = session_dir / "interchange"
    if not interchange.exists():
        return []

    stems = []
    for ext in ["*.wav", "*.flac", "*.mp3", "*.ogg", "*.aiff"]:
        stems.extend(interchange.glob(ext))
    return sorted(stems)


def get_stem_volume(stem_path, manifest):
    """Get the volume for a stem from the manifest or defaults."""
    stem_name = stem_path.stem.lower()
    stem_volumes = manifest.get("stem_volumes", {})

    # Try exact match first
    if stem_name in stem_volumes:
        return stem_volumes[stem_name]

    # Try matching by role keywords
    for role, vol in stem_volumes.items():
        if role.lower() in stem_name or stem_name in role.lower():
            return vol

    # Try defaults
    for key, vol in DEFAULT_VOLUMES.items():
        if key in stem_name:
            return vol

    # Unity gain fallback
    return 1.0


def build_ffmpeg_mix_cmd(stems, manifest, output_path):
    """Build an ffmpeg command to mix stems with volumes and mastering chain."""
    mastering = manifest.get("mastering_profile", {})
    lufs = mastering.get("lufs", DEFAULT_LUFS)
    tp = mastering.get("true_peak", DEFAULT_TRUE_PEAK)
    lra = mastering.get("lra", DEFAULT_LRA)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]

    # Add all stem inputs
    for stem in stems:
        cmd.extend(["-i", str(stem)])

    # Build filter chain
    n = len(stems)
    filters = []

    # Per-stem volume adjustment
    for i, stem in enumerate(stems):
        vol = get_stem_volume(stem, manifest)
        filters.append(f"[{i}:a]volume={vol}[s{i}]")

    # Mix all stems
    mix_inputs = "".join(f"[s{i}]" for i in range(n))
    filters.append(
        f"{mix_inputs}amix=inputs={n}:duration=longest:dropout_transition=3,"
        f"loudnorm=I={lufs}:TP={tp}:LRA={lra}[out]"
    )

    filter_complex = ";".join(filters)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ar", "48000",
        "-sample_fmt", "s32",
        str(output_path)
    ])

    return cmd


def build_ffmpeg_mp3_cmd(flac_path, mp3_path):
    """Convert FLAC to 320kbps MP3."""
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(flac_path),
        "-codec:a", "libmp3lame", "-b:a", "320k",
        "-ar", "48000",
        str(mp3_path)
    ]


def write_notification(export_dir, session_name, manifest, flac_path, mp3_path):
    """Write notification.json for hermes-music's notify_processed daemon."""
    notification = {
        "session": session_name,
        "source": manifest.get("source", "dawagent"),
        "album": manifest.get("album", ""),
        "bpm": manifest.get("bpm", 120),
        "key": manifest.get("key", ""),
        "genre": manifest.get("genre", ""),
        "status": "exported",
        "processed_at": datetime.now().isoformat(),
        "exports": [
            {"type": "flac", "path": str(flac_path), "filename": flac_path.name},
        ],
        "stems_processed": manifest.get("stem_count", 0),
        "mastering_profile": manifest.get("mastering_profile", {
            "lufs": DEFAULT_LUFS,
            "true_peak": DEFAULT_TRUE_PEAK,
            "lra": DEFAULT_LRA,
        }),
    }
    if mp3_path and mp3_path.exists():
        notification["exports"].append(
            {"type": "mp3", "path": str(mp3_path), "filename": mp3_path.name}
        )

    notif_path = export_dir / "notification.json"
    with open(notif_path, "w") as f:
        json.dump(notification, f, indent=2)
    log(f"  ✓ Wrote notification.json")
    return notif_path


def process_job(session_dir, manifest_path):
    """Process a single handoff job: mix stems → master → export."""
    session_name = session_dir.name

    with open(manifest_path) as f:
        manifest = json.load(f)

    log(f"Processing: {session_name}")
    log(f"  Source: {manifest.get('source', '?')} | BPM: {manifest.get('bpm', '?')} | "
        f"Key: {manifest.get('key', '?')} | Stems: {manifest.get('stem_count', '?')}")

    # Mark as processing
    update_manifest_status(manifest_path, "processing")

    # Find stems
    stems = find_stems(session_dir)
    if not stems:
        log(f"  ✗ No stems found in {session_dir / 'interchange'}")
        update_manifest_status(manifest_path, "failed",
                               {"error": "No stems found in interchange directory"})
        return False

    log(f"  Found {len(stems)} stems: {[s.name for s in stems]}")

    # Check if mix file exists (pre-mixed by hermes-music)
    mix_file = manifest.get("mix_file")
    if mix_file and Path(mix_file).exists():
        log(f"  Using pre-mixed file: {Path(mix_file).name}")
        use_premix = True
    else:
        use_premix = False

    # Create export directory
    export_dir = EXPORTS_DIR / session_name
    export_dir.mkdir(parents=True, exist_ok=True)

    # Output paths
    flac_output = export_dir / f"{session_name}_MASTER.flac"
    mp3_output = export_dir / f"{session_name}_MASTER.mp3"

    # Skip if already exported
    if flac_output.exists():
        log(f"  ⏭ Already exported: {flac_output.name}")
        update_manifest_status(manifest_path, "processed")
        return True

    try:
        if use_premix:
            # Just master the pre-mixed file
            mastering = manifest.get("mastering_profile", {})
            lufs = mastering.get("lufs", DEFAULT_LUFS)
            tp = mastering.get("true_peak", DEFAULT_TRUE_PEAK)
            lra = mastering.get("lra", DEFAULT_LRA)

            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(mix_file),
                "-af", f"loudnorm=I={lufs}:TP={tp}:LRA={lra}",
                "-ar", "48000", "-sample_fmt", "s32",
                str(flac_output)
            ]
        else:
            # Mix stems + master
            cmd = build_ffmpeg_mix_cmd(stems, manifest, flac_output)

        log(f"  Running ffmpeg mix+master...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            log(f"  ✗ ffmpeg failed: {result.stderr[-300:]}")
            update_manifest_status(manifest_path, "failed",
                                   {"error": f"ffmpeg failed: {result.stderr[-200:]}"})
            return False

        if not flac_output.exists() or flac_output.stat().st_size < 1000:
            log(f"  ✗ Output file missing or empty")
            update_manifest_status(manifest_path, "failed",
                                   {"error": "Output file missing or too small"})
            return False

        flac_size_mb = flac_output.stat().st_size / (1024 * 1024)
        log(f"  ✓ FLAC exported: {flac_output.name} ({flac_size_mb:.1f} MB)")

        # Convert to MP3
        log(f"  Converting to MP3...")
        mp3_cmd = build_ffmpeg_mp3_cmd(flac_output, mp3_output)
        mp3_result = subprocess.run(mp3_cmd, capture_output=True, text=True, timeout=120)
        if mp3_result.returncode == 0 and mp3_output.exists():
            mp3_size_mb = mp3_output.stat().st_size / (1024 * 1024)
            log(f"  ✓ MP3 exported: {mp3_output.name} ({mp3_size_mb:.1f} MB)")
        else:
            log(f"  ⚠ MP3 conversion failed (non-fatal)")
            mp3_output = None

        # Copy handoff manifest to export dir for reference
        shutil.copy2(str(manifest_path), str(export_dir / "handoff.json"))

        # Write notification for hermes-music
        write_notification(export_dir, session_name, manifest, flac_output, mp3_output)

        # Mark as processed
        update_manifest_status(manifest_path, "processed", {
            "export_dir": str(export_dir),
            "flac": str(flac_output),
            "mp3": str(mp3_output) if mp3_output else None,
        })

        log(f"  ✓ Job complete: {session_name}")
        return True

    except subprocess.TimeoutExpired:
        log(f"  ✗ Processing timed out (600s)")
        update_manifest_status(manifest_path, "failed", {"error": "Processing timed out"})
        return False
    except Exception as e:
        log(f"  ✗ Unexpected error: {e}")
        update_manifest_status(manifest_path, "failed", {"error": str(e)})
        return False


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
    log("DAWAGENT Auto-Processor starting")
    log(f"Sessions: {SESSIONS_DIR}")
    log(f"Exports:  {EXPORTS_DIR}")
    log(f"Poll:     {POLL_INTERVAL}s")
    log("=" * 50)

    # Process any existing pending jobs immediately
    initial = scan_and_process()
    if initial:
        log(f"Processed {initial} pending jobs on startup")

    # Main polling loop
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
