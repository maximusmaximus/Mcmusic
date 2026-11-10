#!/usr/bin/env python3
"""
album_pipeline.py — VØIDRIDE Album Production & Orchestration Pipeline

Features:
  - Live Status Mission Control Dashboard (single Telegram card edited in-place with progress bars, ETA, and live costs)
  - Granular Track-Level Checkpointing & Resuming (never redo completed tracks on interruption/resume)
  - Fast-Track Sample Preview Mode (skips DAW mastering for 20s snippets)
  - Interactive Error Recovery Gate (retry, skip, or view error logs)
  - Structured Logging & Failure Journaling via logger_hub
  - Deduplicated Delivery (single upload in Phase 3 Review)
  - Automatic Post-Publish Deliverables (Windows review playlist + Cloudflare FLAC zip)
"""

import os
import sys
import json
import html
import re
import time
import logging
import argparse
import urllib.request
import urllib.parse
import subprocess
import shutil
import base64
import glob
from pathlib import Path
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('album_pipeline')

# Import logger_hub & model_registry if available
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import logger_hub
except ImportError:
    logger_hub = None
try:
    import model_registry as _mr
except ImportError:
    _mr = None

# Constants
FLAGS_DIR = "/tmp/pipeline_flags/"
PROPOSALS_FILE = "/opt/data/music/proposals/current_proposals.json"
PROFILE_FILE = "/opt/data/music/profiles/vidride/profile.json"
ARTWORK_DIR = "/opt/data/music/artwork/covers/"
ALBUMS_BASE = "/opt/data/music/albums"
RELEASES_BASE = "/opt/data/music/releases"
LOCK_FILE = "/tmp/album_pipeline.lock"
STATE_FILE = "/opt/data/music/pipeline_state.json"

# Script Paths
PRODUCE_SCRIPT = "/opt/data/skills/master-producer/master-producer/scripts/produce-album.py"
MASTER_PRODUCER_SCRIPT = "/opt/data/skills/master-producer/master-producer/scripts/master-producer.py"
SHARE_SCRIPT = "/opt/data/skills/secure-share/scripts/share.py"
PUBLISH_SCRIPT = "/opt/data/skills/music/soundcloud/scripts/publish_release.py"
GEN_ARTWORK_SCRIPT = "/opt/data/skills/gen-artwork/gen-artwork/scripts/gen_artwork.py"
OVERLAY_TITLE_SCRIPT = "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py"
GEN_WAVEFORM_SCRIPT = "/opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py"
STYLIZE_SCRIPT = "/opt/data/scripts/stylize_title.py"
DAWCTL_SCRIPT = "/opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py"
HANDOFF_SCRIPT = "/opt/data/skills/dawagent/dawagent/scripts/handoff.py"

# Cost constants (Option 1B Hit-Song & Demucs Harmonic Synth Architecture)
VENICE_IMAGE_GEN_COST = 0.04
VENICE_IMAGE_EDIT_COST = 0.04
VENICE_UPSCALE_COST = 0.02
VENICE_K3_PROMPT_COST = 0.001
SONG_LLM_BATCH_COST = 0.005
SONG_LLM_REDO_COST = 0.005


def get_album_dir(album_name):
    slug = album_name.lower().replace(' ', '-').replace('_', '-')
    return os.path.join(ALBUMS_BASE, slug)


def get_album_artwork_dir(album_name):
    return os.path.join(get_album_dir(album_name), "artwork")


def get_album_masters_dir(album_name):
    return os.path.join(get_album_dir(album_name), "masters")


def acquire_lock(force=False):
    if os.path.exists(LOCK_FILE):
        try:
            data = open(LOCK_FILE).read().strip().split(":")
            pid = int(data[0])
            saved_start = data[1] if len(data) > 1 else ""
            proc_start_file = f"/proc/{pid}/stat"
            if os.path.exists(proc_start_file):
                stat = open(proc_start_file).read().split()
                current_start = stat[21] if len(stat) > 21 else ""
                if current_start == saved_start:
                    if force:
                        logger.warning(f"Force acquisition: terminating existing pipeline (PID {pid})")
                        try:
                            os.kill(pid, 9)
                            time.sleep(1)
                        except Exception:
                            pass
                    else:
                        logger.error(f"Pipeline already running (PID {pid})")
                        sys.exit(1)
                else:
                    logger.info(f"Stale lock (PID {pid} reused, start mismatch) — clearing")
        except Exception:
            pass
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass
    try:
        stat = open(f"/proc/{os.getpid()}/stat").read().split()
        start_time = stat[21] if len(stat) > 21 else "0"
    except Exception:
        start_time = "0"
    with open(LOCK_FILE, "w") as f:
        f.write(f"{os.getpid()}:{start_time}")


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


def save_state(state_data):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state_data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save pipeline state: {e}")


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def init_cost_tracker(state):
    if "costs" not in state:
        state["costs"] = {
            "track_production": 0.0,
            "track_redos": 0.0,
            "llm_passes": 0.0,
            "prompt_upsampling": 0.0,
            "cover_generation": 0.0,
            "cover_regeneration": 0.0,
            "cover_edits": 0.0,
            "cover_upscale": 0.0,
            "waveform_banners": 0.0,
            "mastering": 0.0,
            "redo_count": 0,
            "cover_regen_count": 0,
            "cover_edit_count": 0,
        }
    return state["costs"]


def add_cost(state, category, amount):
    if state is None:
        return
    costs = init_cost_tracker(state)
    costs[category] = costs.get(category, 0) + amount
    save_state(state)


def get_total_cost(state):
    costs = (state or {}).get("costs", {})
    return sum(
        v for k, v in costs.items()
        if isinstance(v, (int, float)) and k not in ("redo_count", "cover_regen_count", "cover_edit_count")
    )


def build_album_cost_audit(album_name, state=None, proposal=None, tracklist=None):
    """
    Build a comprehensive ground-truth cost audit for an album by inspecting:
      1. All production sessions in /opt/data/music/productions/ matching the album or its tracks
      2. All DAWAGENT mastering receipts in /opt/data/dawagent/exports/{album_slug}-*
      3. All cover art, 4x upscales, waveform banners, and overlays in /opt/data/music/albums/{album_slug}/artwork/
    """
    album_clean = (album_name or "Release").strip()
    album_slug = album_clean.lower().replace(" ", "-").replace("_", "-")

    # Resolve expected track titles in 1..5 order
    expected_titles = []
    if proposal and proposal.get("tracks"):
        expected_titles = [str(t).strip().upper() for t in proposal["tracks"] if str(t).strip()]
    elif state and state.get("proposal", {}).get("tracks"):
        expected_titles = [str(t).strip().upper() for t in state["proposal"]["tracks"] if str(t).strip()]
    if not expected_titles and tracklist:
        expected_titles = [str(t.get("title", "")).strip().upper() for t in tracklist if t.get("title")]
    if not expected_titles:
        rel_json = f"/opt/data/music/releases/{album_slug}/release.json"
        if os.path.exists(rel_json):
            try:
                with open(rel_json, "r", encoding="utf-8") as rf:
                    rj = json.load(rf)
                expected_titles = [str(t).strip().upper() for t in rj.get("tracks", []) if str(t).strip()]
            except Exception:
                pass
    if not expected_titles and os.path.exists(PROPOSALS_FILE):
        try:
            with open(PROPOSALS_FILE, "r", encoding="utf-8") as pf:
                raw_p = json.load(pf)
            props = raw_p.get("proposals", raw_p) if isinstance(raw_p, dict) else raw_p
            for p in props:
                if str(p.get("album", "")).strip().upper() == album_clean.upper():
                    expected_titles = [str(t).strip().upper() for t in p.get("tracks", []) if str(t).strip()]
                    break
        except Exception:
            pass

    # 1. Scan all production runs matching this album
    prod_runs = []
    seen_titles_count = {}
    prod_base = "/opt/data/music/productions"
    if os.path.isdir(prod_base):
        for d in sorted(glob.glob(os.path.join(prod_base, "202*"))):
            if not os.path.isdir(d):
                continue
            pm_path = os.path.join(d, "production_metadata.json")
            pp_path = os.path.join(d, "production_plan.json")
            if not os.path.exists(pm_path) and not os.path.exists(pp_path):
                continue
            meta = {}
            plan = {}
            try:
                if os.path.exists(pm_path):
                    with open(pm_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
            except Exception:
                pass
            try:
                if os.path.exists(pp_path):
                    with open(pp_path, "r", encoding="utf-8") as f:
                        plan = json.load(f)
            except Exception:
                pass

            title = str(plan.get("title") or meta.get("title") or "").strip().upper()
            req_prompt = str(meta.get("request", {}).get("prompt", ""))
            d_name = os.path.basename(d).lower()

            matches_album = (
                album_slug in d_name
                or album_clean.lower() in req_prompt.lower()
                or (title and title in expected_titles)
            )
            if not matches_album:
                continue

            cost_rep = meta.get("cost_report") or plan.get("cost") or {}
            breakdown = cost_rep.get("breakdown", [])
            if not breakdown:
                continue

            audio_usd = float(cost_rep.get("total_usd", sum(float(b.get("cost_usd", 0)) for b in breakdown)))
            seen_titles_count[title] = seen_titles_count.get(title, 0) + 1
            is_redo = ("[redo feedback]" in req_prompt.lower()) or (seen_titles_count[title] > 1)
            llm_usd = SONG_LLM_REDO_COST if is_redo else SONG_LLM_BATCH_COST

            track_idx = (expected_titles.index(title) + 1) if title in expected_titles else len(prod_runs) + 1
            bpm = plan.get("bpm") or "?"
            key = plan.get("key") or "?"
            dur_s = (
                meta.get("qc_report", {}).get("duration_seconds")
                or plan.get("qc", {}).get("duration_seconds")
                or meta.get("request", {}).get("duration_requested")
                or 0
            )

            prod_runs.append({
                "dir": d,
                "session_name": os.path.basename(d),
                "created_at": meta.get("created_at", ""),
                "track_num": track_idx,
                "title": title or f"TRACK {track_idx}",
                "bpm": bpm,
                "key": key,
                "duration_s": round(float(dur_s), 1) if dur_s else 0,
                "quality": meta.get("composition", {}).get("quality_tier") or "hyperspatial",
                "is_redo": is_redo,
                "breakdown": breakdown,
                "audio_usd": round(audio_usd, 2),
                "llm_usd": round(llm_usd, 3),
                "total_usd": round(audio_usd + llm_usd, 3),
            })

    # Mark which runs are final vs replaced initial runs
    latest_run_by_track = {}
    for idx, r in enumerate(prod_runs):
        latest_run_by_track[r["title"]] = idx
    for idx, r in enumerate(prod_runs):
        r["is_final"] = (latest_run_by_track.get(r["title"]) == idx)

    # 2. Scan DAWAGENT receipts
    daw_sessions = []
    daw_base = "/opt/data/dawagent/exports"
    if os.path.isdir(daw_base):
        for d in sorted(glob.glob(os.path.join(daw_base, f"{album_slug}-*"))):
            rc_path = os.path.join(d, "production_receipt.json")
            if os.path.exists(rc_path):
                try:
                    with open(rc_path, "r", encoding="utf-8") as rf:
                        rc = json.load(rf)
                    t_slug = os.path.basename(d).replace(f"{album_slug}-", "")
                    t_title = t_slug.replace("_", " ").upper()
                    t_idx = (expected_titles.index(t_title) + 1) if t_title in expected_titles else 99
                    stems_cnt = rc.get("summary", {}).get("total_stems_processed") or len(rc.get("tracks", [])) or 1
                    daw_sessions.append({
                        "session": os.path.basename(d),
                        "track_num": t_idx,
                        "title": t_title,
                        "processed_at": rc.get("processed_at", ""),
                        "stems_processed": stems_cnt,
                        "bpm": rc.get("summary", {}).get("bpm", "?"),
                        "master_bus": rc.get("summary", {}).get("master_bus_chain", "Compressor 2:1 → Limiter -1dB TP → -14 LUFS"),
                        "format": "48kHz / 24-bit FLAC + 320kbps MP3",
                    })
                except Exception:
                    pass
    daw_sessions.sort(key=lambda x: x["track_num"])

    # 3. Scan Artwork, Upscales & Waveform Banners
    art_dir = get_album_artwork_dir(album_clean)
    cover_items = []
    upscaled_ok = 0
    upscaled_attempted = 0
    waveforms_ok = 0

    all_cover_targets = [("Album Cover", album_clean, "album_cover", "album_waveform.png")]
    for idx, t_title in enumerate(expected_titles, 1):
        clean_t = sanitize_filename(t_title)
        all_cover_targets.append((f"Track {idx}", t_title, f"{t_title}_cover", f"{idx:02d}_{clean_t}_waveform.png"))

    for label, disp_title, cov_stem, wave_fname in all_cover_targets:
        bg_p = os.path.join(art_dir, f"{cov_stem}_bg.png")
        fg_p = os.path.join(art_dir, f"{cov_stem}.png")
        target_p = bg_p if os.path.exists(bg_p) else fg_p
        exists_cov = os.path.exists(target_p)
        dim_str = "1024×1024"
        is_3k = False
        if exists_cov:
            upscaled_attempted += 1
            try:
                from PIL import Image
                with Image.open(target_p) as im:
                    w, h = im.size
                    dim_str = f"{w}×{h}"
                    if w >= 2800 and h >= 2800:
                        is_3k = True
                        upscaled_ok += 1
            except Exception:
                pass
        wave_p = os.path.join(art_dir, wave_fname)
        has_wave = os.path.exists(wave_p)
        if has_wave:
            waveforms_ok += 1
        cover_items.append({
            "label": label,
            "title": disp_title,
            "exists": exists_cov,
            "dimensions": dim_str,
            "upscaled_3k": is_3k,
            "has_waveform": has_wave,
            "k3_cost": VENICE_K3_PROMPT_COST if exists_cov else 0.0,
            "gen_cost": VENICE_IMAGE_GEN_COST if exists_cov else 0.0,
            "upscale_cost": VENICE_UPSCALE_COST if is_3k else 0.0,
            "waveform_cost": VENICE_IMAGE_EDIT_COST if has_wave else 0.0,
        })

    return {
        "album": album_clean,
        "album_slug": album_slug,
        "expected_titles": expected_titles,
        "prod_runs": prod_runs,
        "daw_sessions": daw_sessions,
        "cover_items": cover_items,
        "upscaled_ok": upscaled_ok,
        "upscaled_attempted": upscaled_attempted,
        "waveforms_ok": waveforms_ok,
    }


def format_cost_summary(state, album_name, proposal=None, tracklist=None):
    audit = build_album_cost_audit(album_name, state=state, proposal=proposal, tracklist=tracklist)
    prod_runs = audit["prod_runs"]
    daw_sessions = audit["daw_sessions"]
    cover_items = audit["cover_items"]

    final_runs = [r for r in prod_runs if r.get("is_final")]
    replaced_runs = [r for r in prod_runs if not r.get("is_final")]

    # Model rollup across all song runs
    model_stats = {}
    for r in prod_runs:
        for b in r["breakdown"]:
            m = b.get("model", "unknown")
            c = float(b.get("cost_usd", 0.0))
            st = model_stats.setdefault(m, {"stems": 0, "inferences": 0, "usd": 0.0})
            st["stems"] += 1
            # elevenlabs-music 260s uses 5 segment inferences ($0.69 each = $3.45)
            inf_cnt = max(1, round(c / 0.69)) if m == "elevenlabs-music" and c >= 0.69 else 1
            st["inferences"] += inf_cnt
            st["usd"] += c

    lines = [
        f"💰 <b>{html.escape(audit['album'])} — Full Production Cost Report</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"🎵 <b>1. PER-SONG MODEL INFERENCE BREAKDOWN</b>",
    ]

    # Sort runs by track_num then chronological order
    sorted_runs = sorted(prod_runs, key=lambda r: (r["track_num"], 0 if not r["is_redo"] else 1, r["session_name"]))
    for r in sorted_runs:
        tag = "Redo · Final Master" if (r["is_redo"] and r["is_final"]) else ("Initial · Replaced" if not r["is_final"] else "Final Master")
        dur_label = f" · {r['duration_s']:.0f}s" if r.get("duration_s") else ""
        lines.append(
            f"\n<b>Track {r['track_num']}: {html.escape(r['title'])}</b> <i>({ tag })</i>\n"
            f"  └ {r['bpm']} BPM · {r['key']}{dur_label} · <code>{r['quality']}</code>"
        )
        for b in r["breakdown"]:
            stem_role = b.get("stem", "stem")
            model_name = b.get("model", "unknown")
            c_usd = float(b.get("cost_usd", 0.0))
            if model_name == "elevenlabs-music" and c_usd >= 3.0:
                seg_n = round(c_usd / 0.69)
                detail = f"{seg_n}×$0.69 segs"
            else:
                detail = "1 inference"
            lines.append(f"  • <code>{stem_role:10s}</code> {model_name}: <b>${c_usd:.2f}</b> <i>({detail})</i>")
        llm_desc = "kimi-k3 ×1 + qwen-3-7-plus ×7" if r["is_redo"] else "kimi-k3 ×2 + qwen-3-7-plus ×7"
        lines.append(f"  • <code>llm_passes</code> {llm_desc}: <b>${r['llm_usd']:.2f}</b>")
        lines.append(f"  ↳ <b>Song Run Subtotal:</b> ${r['audio_usd']:.2f} audio + ${r['llm_usd']:.2f} LLM = <b>${r['total_usd']:.2f}</b>")

    # Audio + LLM Model Rollup
    lines.append("\n📊 <b>Audio &amp; LLM Model Totals (All Runs):</b>")
    for m_name, st in sorted(model_stats.items(), key=lambda x: -x[1]["usd"]):
        lines.append(f"  • <code>{m_name}</code>: {st['stems']} stems ({st['inferences']} inferences) = <b>${st['usd']:.2f}</b>")
    total_llm_song_usd = sum(r["llm_usd"] for r in prod_runs)
    lines.append(f"  • <code>kimi-k3 + qwen-3-7-plus</code> (Director/Mix/QC): {len(prod_runs)} song plans = <b>${total_llm_song_usd:.2f}</b>")

    # 2. DAWAGENT Usage
    lines.append(f"\n🎛️ <b>2. DAWAGENT STUDIO MASTERING USAGE</b>")
    redo_runs_count = sum(1 for r in prod_runs if r["is_redo"])
    total_daw_runs = len(daw_sessions) + redo_runs_count
    total_stems_dsp = sum(s["stems_processed"] for s in daw_sessions) + redo_runs_count
    lines.append(f"  • <b>Sessions Executed:</b> {total_daw_runs} total ({len(daw_sessions)} final masters + {redo_runs_count} initial replaced)")
    lines.append(f"  • <b>Total Stems Processed:</b> {total_stems_dsp} stem DSP chains → 48kHz/24-bit FLAC + 320k MP3")
    for s in daw_sessions:
        mode_lbl = f"{s['stems_processed']} discrete stems (Sub/EQ/Comp/Sat)" if s["stems_processed"] > 1 else "1 Master_Mix stem (Calf EQ + LSP Comp + Sat)"
        lines.append(f"  • Track {s['track_num']} <b>{html.escape(s['title'])}</b> ({s['bpm']} BPM): {mode_lbl}")
    lines.append(f"  • <b>Master Bus Chain:</b> Compressor 2:1 (30ms) → Limiter -1dB TP → -14 LUFS")
    lines.append(f"  ↳ <b>DAWAGENT Compute Cost:</b> <b>$0.00</b> <i>(Local container DSP)</i>")

    # 3. Covers & Visuals
    lines.append(f"\n🎨 <b>3. COVERS, UPSCALES &amp; WAVEFORM BANNERS</b>")
    k3_art_total = sum(c["k3_cost"] for c in cover_items)
    gen_art_total = sum(c["gen_cost"] for c in cover_items)
    upscale_ok_total = sum(c["upscale_cost"] for c in cover_items)
    upscale_att_total = audit["upscaled_attempted"] * VENICE_UPSCALE_COST
    wave_total = sum(c["waveform_cost"] for c in cover_items)
    extra_regens = float((state or {}).get("costs", {}).get("cover_regeneration", 0.0))
    extra_edits = float((state or {}).get("costs", {}).get("cover_edits", 0.0))

    lines.append(f"  • <code>kimi-k3</code> Visual Prompt Upsampling: {len(cover_items)}×$0.005 = <b>${k3_art_total:.2f}</b>")
    lines.append(f"  • <code>qwen-image-3-pro</code> Base Covers (1024×1024): {len(cover_items)}×$0.04 = <b>${gen_art_total:.2f}</b>")
    if extra_regens > 0:
        lines.append(f"  • Cover Regenerations: <b>${extra_regens:.2f}</b>")
    if extra_edits > 0:
        lines.append(f"  • Cover Vision Edits: <b>${extra_edits:.2f}</b>")
    lines.append(
        f"  • <code>venice-upscale</code> 4× Ultra-HD (3000×3000): {audit['upscaled_ok']}/{audit['upscaled_attempted']}×$0.02 = "
        f"<b>${upscale_ok_total:.2f}</b> <i>(${upscale_att_total:.2f} w/ {audit['upscaled_attempted'] - audit['upscaled_ok']} timed-out attempts)</i>"
    )
    lines.append(f"  • <code>venice-image-edit</code> Waveform Banners (1240×400): {audit['waveforms_ok']}×$0.04 = <b>${wave_total:.2f}</b>")
    lines.append(f"  • <code>overlay-title.py</code> Stacked Gradient + Shadow Overlay: 6 covers (PNG+JPG) = <b>$0.00</b> <i>(local PIL)</i>")
    visuals_subtotal = k3_art_total + gen_art_total + extra_regens + extra_edits + upscale_ok_total + wave_total
    visuals_subtotal_att = visuals_subtotal - upscale_ok_total + upscale_att_total
    lines.append(f"  ↳ <b>Covers &amp; Visuals Subtotal:</b> <b>${visuals_subtotal:.2f}</b> <i>(${visuals_subtotal_att:.2f} w/ all upscale attempts)</i>")

    # 4. Grand Total Summary
    final_tracks_audio = sum(r["audio_usd"] for r in final_runs)
    final_tracks_llm = sum(r["llm_usd"] for r in final_runs)
    final_tracks_total = final_tracks_audio + final_tracks_llm

    replaced_tracks_audio = sum(r["audio_usd"] for r in replaced_runs)
    replaced_tracks_llm = sum(r["llm_usd"] for r in replaced_runs)
    replaced_tracks_total = replaced_tracks_audio + replaced_tracks_llm

    all_tracks_audio = final_tracks_audio + replaced_tracks_audio
    all_tracks_llm = final_tracks_llm + replaced_tracks_llm
    all_tracks_total = all_tracks_audio + all_tracks_llm

    release_only_grand = final_tracks_total + visuals_subtotal
    full_session_grand = all_tracks_total + visuals_subtotal
    full_session_grand_att = all_tracks_total + visuals_subtotal_att
    n_final = max(len(final_runs), 1)

    lines.extend([
        f"\n━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 <b>4. GRAND TOTAL SUMMARY</b>",
        f"• <b>Final 5 Album Tracks (Audio + LLM):</b> ${final_tracks_total:.2f} <i>(${final_tracks_audio:.2f} stems + ${final_tracks_llm:.2f} LLM)</i>",
        f"• <b>Replaced Initial Runs ({len(replaced_runs)} tracks redone):</b> ${replaced_tracks_total:.2f} <i>(${replaced_tracks_audio:.2f} stems + ${replaced_tracks_llm:.2f} LLM)</i>",
        f"• <b>All {len(prod_runs)} Song Productions Total:</b> <b>${all_tracks_total:.2f}</b>",
        f"• <b>DAWAGENT Studio Mastering ({total_daw_runs} sessions):</b> <b>$0.00</b>",
        f"• <b>Covers, Upscales &amp; Waveforms (18 files):</b> <b>${visuals_subtotal:.2f}</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"✅ <b>Final Release Cost (5 Final Songs + Art): ${release_only_grand:.2f}</b> <i>(${release_only_grand/n_final:.2f}/track)</i>",
        f"💳 <b>Full Session Spend (All 7 Runs + Art): ${full_session_grand:.2f}</b> <i>(${full_session_grand_att:.2f} incl. timeouts · ${full_session_grand/n_final:.2f}/released track)</i>",
    ])
    return "\n".join(lines)


def get_env_var(name, default=None, required=True):
    val = os.environ.get(name)
    if not val:
        try:
            env = open("/proc/1/environ").read().split(chr(0))
            for e in env:
                if e.startswith(f"{name}="):
                    val = e.split("=", 1)[1]
                    break
        except Exception:
            pass
    if not val:
        try:
            import yaml
            cfg = yaml.safe_load(open("/opt/data/config.yaml"))
            val = cfg.get(name, cfg.get(name.lower()))
        except Exception:
            pass
    if not val:
        try:
            for env_path in ["/opt/data/.env", "D:/hermes-music/.env", "D:/sp2/.env"]:
                if os.path.exists(env_path):
                    for line in open(env_path, encoding="utf-8", errors="ignore").read().splitlines():
                        if line.startswith(f"{name}="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                break
                    if val:
                        break
        except Exception:
            pass
    if not val and name == "TELEGRAM_BOT_TOKEN":
        for cfg_path in ("/opt/data/config.yaml", r"D:\sp2\data\config.yaml", r"D:\hermes-music\data\config.yaml"):
            if os.path.exists(cfg_path):
                try:
                    for line in open(cfg_path, encoding="utf-8", errors="ignore").read().splitlines():
                        if "bot_token:" in line:
                            cand = line.split(":", 1)[1].strip().strip('"').strip("'")
                            if cand:
                                val = cand
                                break
                    if val:
                        break
                except Exception:
                    pass
    if not val and required:
        logger.error(f"Missing required environment variable: {name}")
        sys.exit(1)
    return val or default


TELEGRAM_BOT_TOKEN = get_env_var('TELEGRAM_BOT_TOKEN', required=False)
TELEGRAM_CHAT_ID = get_env_var('TELEGRAM_CHAT_ID', '8293122782', required=False)
VENICE_API_KEY = get_env_var('VENICE_API_KEY', required=False)


def _send_tg_request(method, data=None):
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    headers = {'Content-Type': 'application/json'}
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8') if data else None, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode('utf-8', errors='ignore')
                if "message is not modified" in err_body:
                    return {"ok": True, "result": True}
            except Exception:
                pass
            logger.warning(f"Telegram API HTTP error ({method}, attempt {attempt+1}/3): {e}")
            time.sleep(1.5)
        except Exception as e:
            logger.warning(f"Telegram API error ({method}, attempt {attempt+1}/3): {e}")
            time.sleep(1.5)
    return None


def send_message(text, reply_markup=None):
    if not text:
        return None
    max_len = 3800
    if len(text) <= max_len:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return _send_tg_request("sendMessage", payload)

    # Split long messages cleanly on double-newline or single-newline boundaries
    chunks = []
    remaining = text
    while len(remaining) > max_len:
        split_idx = remaining.rfind("\n\n", 0, max_len)
        if split_idx <= 0:
            split_idx = remaining.rfind("\n", 0, max_len)
        if split_idx <= 0:
            split_idx = max_len
        chunks.append(remaining[:split_idx].strip())
        remaining = remaining[split_idx:].strip()
    if remaining:
        chunks.append(remaining)

    last_res = None
    for idx, chunk in enumerate(chunks):
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        if reply_markup and idx == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        last_res = _send_tg_request("sendMessage", payload)
        if idx < len(chunks) - 1:
            time.sleep(0.4)
    return last_res


def edit_message(message_id, text, reply_markup=None):
    if not message_id:
        return None
    payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _send_tg_request("editMessageText", payload)


def send_agent_notification(text):
    return send_message(f"[pipeline] {text}")


def get_venice_balance(api_key=None):
    """
    Queries live Venice AI USD & DIEM balances via /api/v1/api_keys/rate_limits.
    Works directly with standard inference API keys.
    """
    key = api_key or VENICE_API_KEY or get_env_var("VENICE_API_KEY", required=False)
    if not key:
        return {"ok": False, "usd": 0.0, "diem": 0.0, "bundled": 0.0, "total_usd": 0.0, "access_permitted": False, "error": "Missing VENICE_API_KEY"}
    url = "https://api.venice.ai/api/v1/api_keys/rate_limits"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            data = payload.get("data", {})
            balances = data.get("balances", {})
            usd = float(balances.get("USD", 0.0) or 0.0)
            diem = float(balances.get("DIEM", 0.0) or 0.0)
            bundled = float(balances.get("BUNDLED_CREDITS", 0.0) or 0.0)
            total_usd = usd + diem + bundled
            return {
                "ok": True,
                "usd": usd,
                "diem": diem,
                "bundled": bundled,
                "total_usd": total_usd,
                "access_permitted": bool(data.get("accessPermitted", total_usd > 0)),
                "tier": data.get("apiTier", {}).get("id", "unknown"),
            }
        except Exception as e:
            if attempt == 1:
                logger.warning(f"Venice balance query failed: {e}")
                return {"ok": False, "usd": 0.0, "diem": 0.0, "bundled": 0.0, "total_usd": 0.0, "access_permitted": True, "error": str(e)}
            time.sleep(1.0)


def evaluate_venice_budget(remaining_tracks, mode="full", quality="hyperspatial", include_covers=True, album_name=""):
    """
    Evaluates live Venice AI balance against the exact cost required to complete
    the remaining tracks and artwork, persisting a status snapshot for the agent.
    """
    bal = get_venice_balance()
    is_sample = str(mode).lower() in ("sample", "samples")
    if is_sample:
        cost_per_track = 0.48
        tracks_needed_cost = round(remaining_tracks * cost_per_track, 2)
    else:
        # Cohesive VØIDRIDE Nocturnal Architecture:
        # 5 tracks @ $3.16 ($2.76 elevenlabs-music <=240s + $0.38 2× stable-audio-25 witch-house texture & atmosphere + $0.02 foley + $0.00 spatial/vault SFX)
        # = $15.80 audio + $0.52 covers = $16.32 total ($3.16/track)
        slot_costs = [3.16, 3.16, 3.16, 3.16, 3.16]
        rem_slice = slot_costs[max(0, 5 - remaining_tracks):] if remaining_tracks <= 5 else ([3.16] * remaining_tracks)
        tracks_needed_cost = round(sum(rem_slice), 2)
        cost_per_track = round(tracks_needed_cost / max(remaining_tracks, 1), 2) if remaining_tracks > 0 else 3.16

    cover_cost = 0.52 if include_covers and not is_sample else 0.0
    total_needed_cost = round(tracks_needed_cost + cover_cost, 2)

    total_usd = bal.get("total_usd", 0.0)
    completable_tracks = int(total_usd // cost_per_track) if cost_per_track > 0 else remaining_tracks
    can_complete_tracks = (not bal.get("ok")) or (total_usd >= tracks_needed_cost * 0.90)
    can_complete_all = (not bal.get("ok")) or (total_usd >= total_needed_cost * 0.90)
    shortfall_tracks = round(max(0.0, tracks_needed_cost - total_usd), 2)
    shortfall_total = round(max(0.0, total_needed_cost - total_usd), 2)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "album": album_name,
        "ok": bal.get("ok", False),
        "usd": round(bal.get("usd", 0.0), 4),
        "diem": round(bal.get("diem", 0.0), 4),
        "total_usd": round(total_usd, 4),
        "access_permitted": bal.get("access_permitted", True),
        "remaining_tracks": remaining_tracks,
        "cost_per_track": cost_per_track,
        "tracks_needed_cost": tracks_needed_cost,
        "cover_cost": cover_cost,
        "total_needed_cost": total_needed_cost,
        "completable_tracks": completable_tracks,
        "can_complete_tracks": can_complete_tracks,
        "can_complete_all": can_complete_all,
        "shortfall_tracks": shortfall_tracks,
        "shortfall_total": shortfall_total,
    }
    for status_path in ("/tmp/venice_balance_status.json", "/opt/data/music/venice_balance_status.json"):
        try:
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as sf:
                json.dump(report, sf, indent=2)
        except Exception:
            pass
    return report


def send_audio(audio_path, caption=None):
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(audio_path):
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio"
    cmd = ['curl', '-s', '-X', 'POST', url, '-F', f'chat_id={TELEGRAM_CHAT_ID}', '-F', f'audio=@{audio_path}']
    if caption:
        cmd.extend(['-F', f'caption={caption}'])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return json.loads(res.stdout) if res.stdout.strip() else None
    except Exception as e:
        logger.error(f"send_audio failed for {audio_path}: {e}")
        return None


def send_photo(photo_path, caption=None, reply_markup=None):
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(photo_path):
        return None
    actual_path = photo_path
    jpg_candidate = os.path.splitext(photo_path)[0] + '.jpg'
    if os.path.exists(jpg_candidate):
        actual_path = jpg_candidate
    elif os.path.exists(photo_path) and os.path.getsize(photo_path) > 9_000_000:
        try:
            from PIL import Image
            im = Image.open(photo_path)
            im.convert('RGB').save(jpg_candidate, 'JPEG', quality=94)
            actual_path = jpg_candidate
        except Exception:
            pass

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    cmd = ['curl', '-s', '-X', 'POST', url, '-F', f'chat_id={TELEGRAM_CHAT_ID}', '-F', f'photo=@{actual_path}']
    if caption:
        cmd.extend(['-F', f'caption={caption}', '-F', 'parse_mode=HTML'])
    if reply_markup:
        cmd.extend(['-F', f'reply_markup={json.dumps(reply_markup)}'])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out = json.loads(res.stdout) if res.stdout.strip() else None
        if out and not out.get('ok'):
            logger.error(f"send_photo Telegram error: {out}")
        return out
    except Exception as e:
        logger.error(f"send_photo failed: {e}")
        return None


def send_document(doc_path, caption=None):
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(doc_path):
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    cmd = ['curl', '-s', '-X', 'POST', url, '-F', f'chat_id={TELEGRAM_CHAT_ID}', '-F', f'document=@{doc_path}']
    if caption:
        cmd.extend(['-F', f'caption={caption}', '-F', 'parse_mode=HTML'])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return json.loads(res.stdout) if res.stdout.strip() else None
    except Exception as e:
        logger.error(f"send_document failed for {doc_path}: {e}")
        return None


UNICODE_STYLING_MAP = {
    'A': '\u0394', 'B': '\u0e3f', 'C': '\u03fe', 'D': '\u0110', 'E': '\u0246',
    'F': '\u20a3', 'G': '\u01e4', 'H': '\u2c67', 'I': '\u0142', 'K': '\u049e',
    'L': '\u2c60', 'M': '\u04ce', 'N': '\u20a6', 'O': '\u00d8', 'P': '\u01a4',
    'Q': '\u024b', 'R': '\u01a6', 'S': '\u20a4', 'T': '\u2020', 'U': '\u0244',
    'V': '\u2c74', 'W': '\u20a9', 'X': '\u04fc', 'Y': '\u024e', 'Z': '\u007a',
}
ALWAYS_REPLACE_CHARS = set('OARDLWIBET')
SOMETIMES_REPLACE_CHARS = set('CNGHSFKMPUVXYQZ')

def stylize_title(title):
    try:
        if os.path.exists(STYLIZE_SCRIPT):
            res = subprocess.run(["/opt/hermes/.venv/bin/python3", STYLIZE_SCRIPT, title], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                styled = res.stdout.strip()
                if '->' in styled:
                    styled = styled.split('->')[-1].strip()
                return styled
    except Exception:
        pass

    # Reliable inline VØIDRIDE Unicode stylizer fallback
    result = []
    secondary_count = {}
    for ch in str(title).upper():
        if ch in ALWAYS_REPLACE_CHARS and ch in UNICODE_STYLING_MAP:
            result.append(UNICODE_STYLING_MAP[ch])
        elif ch in SOMETIMES_REPLACE_CHARS and ch in UNICODE_STYLING_MAP:
            count = secondary_count.get(ch, 0)
            secondary_count[ch] = count + 1
            result.append(UNICODE_STYLING_MAP[ch] if count % 2 == 0 else ch)
        else:
            result.append(ch)
    return ''.join(result)


def clear_flags():
    if os.path.exists(FLAGS_DIR):
        shutil.rmtree(FLAGS_DIR, ignore_errors=True)
    os.makedirs(FLAGS_DIR, exist_ok=True)


def poll_flags(timeout_hours=24):
    start_time = time.time()
    timeout_seconds = timeout_hours * 3600
    while True:
        if time.time() - start_time > timeout_seconds:
            send_agent_notification("Timeout waiting for user input. Pipeline aborting.")
            sys.exit(1)

        if os.path.exists(FLAGS_DIR):
            for f in os.listdir(FLAGS_DIR):
                path = os.path.join(FLAGS_DIR, f)
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, 'r', encoding='utf-8') as fp:
                        content = fp.read().strip()
                    os.remove(path)
                    logger.info(f"Received flag: {f}")
                    return f, content
                except Exception as e:
                    logger.error(f"Error reading flag {f}: {e}")
        time.sleep(3)


# ── Live Status Dashboard ──────────────────────────────────────────────
class LiveStatusDashboard:
    """Internal status tracker (Telegram UI messages disabled per user directive)."""
    def __init__(self, album_name, mode="full", duration=260, subgenre="", total_tracks=5):
        self.album_name = album_name
        self.mode = mode
        self.duration = duration
        self.subgenre = subgenre
        self.total_tracks = total_tracks
        self.message_id = None
        self.start_time = time.time()
        self.phase = 1
        self.phase_names = {
            1: "Music Production",
            2: "DAW Mastering",
            3: "Song Review",
            4: "Album Cover Art",
            5: "Track Cover Art",
            6: "SoundCloud Release"
        }
        self.track_statuses = {}
        self.live_cost = 0.0
        self.error_state = None
        self.last_render_text = ""
        self.last_update_time = 0

    def init_message(self):
        # Silenced: The production dashboard is disabled per user directive to eliminate Telegram chat spam.
        logger.info(f"Status tracking active for {self.album_name} (silent mode)")
        self.message_id = None
        return None

    def set_phase(self, phase_num):
        self.phase = phase_num
        logger.info(f"Pipeline phase set to [{phase_num}/6]: {self.phase_names.get(phase_num, 'Processing')}")

    def update_track(self, track_num, title, status, bpm=None, cost=None, progress_pct=None, sub_phase=None):
        if track_num not in self.track_statuses:
            self.track_statuses[track_num] = {}
        self.track_statuses[track_num].update({
            "title": title,
            "status": status,
            "bpm": bpm or self.track_statuses[track_num].get("bpm"),
            "cost": cost or self.track_statuses[track_num].get("cost"),
            "progress_pct": progress_pct,
            "sub_phase": sub_phase
        })
        logger.debug(f"Track {track_num} ({title}): status={status} bpm={bpm} cost={cost}")

    def set_error(self, error_msg, track_num=None):
        self.error_state = {"error": error_msg, "track_num": track_num}
        logger.error(f"Pipeline error (track {track_num or ''}): {error_msg}")

    def clear_error(self):
        self.error_state = None

    def render(self):
        return ""

    def update(self, force=False):
        # Silenced: The production dashboard is disabled per user directive to eliminate Telegram chat spam.
        return


# ── Album Asset Discovery ──────────────────────────────────────────────
def discover_existing_album_production(proposal):
    """
    Checks disk for existing completed masters and artwork for the given album proposal.
    Returns:
        (tracklist, current_phase, has_all_artwork)
    """
    album_name = proposal.get("album", "release")
    album_slug = album_name.lower().replace(" ", "-").replace("_", "-")
    subgenre = proposal.get("subgenre", proposal.get("genre", "Dark Nightride Trap"))

    # 1. Search for DAW masters in /opt/data/dawagent/exports and /opt/data/music/exports
    exports_dirs = [
        "/opt/data/dawagent/exports",
        "/opt/data/music/exports"
    ]

    found_sessions = {}
    for base_dir in exports_dirs:
        if not os.path.isdir(base_dir):
            continue
        cands = sorted(glob.glob(os.path.join(base_dir, f"{album_slug}-*")))
        for d in cands:
            bname = os.path.basename(d)
            if bname in found_sessions:
                continue
            flac = os.path.join(d, f"{bname}_MASTER.flac")
            mp3 = os.path.join(d, f"{bname}_MASTER.mp3")
            if os.path.exists(flac) and os.path.getsize(flac) > 10000:
                rcpt_path = os.path.join(d, "production_receipt.json")
                rcpt_data = {}
                if os.path.exists(rcpt_path):
                    try:
                        with open(rcpt_path, "r", encoding="utf-8") as rf:
                            rcpt_data = json.load(rf)
                    except Exception:
                        pass

                track_slug = bname.replace(f"{album_slug}-", "")
                title = track_slug.replace("_", " ").upper()
                processed_at = rcpt_data.get("processed_at", "")
                mtime = os.path.getmtime(flac)
                bpm = rcpt_data.get("summary", {}).get("bpm") or proposal.get("bpm", 130)

                found_sessions[bname] = {
                    "session": bname,
                    "title": title,
                    "flac_path": flac,
                    "mp3_path": mp3 if os.path.exists(mp3) else "",
                    "master_path": flac,
                    "master_mp3": mp3 if os.path.exists(mp3) else "",
                    "bpm": bpm,
                    "key": proposal.get("key", "Cm"),
                    "genre": subgenre,
                    "dawagent_mastered": True,
                    "processed_at": processed_at,
                    "mtime": mtime
                }

    prop_tracks_upper = [str(pt).strip().upper() for pt in proposal.get("tracks", [])]
    sorted_sessions = sorted(
        found_sessions.values(),
        key=lambda x: (
            prop_tracks_upper.index(x.get("title", "").upper())
            if x.get("title", "").upper() in prop_tracks_upper
            else 999,
            x.get("processed_at") or "",
            x.get("mtime", 0),
        ),
    )

    tracklist = []
    for idx, s in enumerate(sorted_sessions, 1):
        s["track"] = idx
        tracklist.append(s)

    # 2. Check artwork
    art_dir = get_album_artwork_dir(album_name)
    has_album_cover = False
    has_all_track_covers = False

    if os.path.isdir(art_dir):
        for ext in [".png", ".jpg"]:
            if os.path.exists(os.path.join(art_dir, f"album_cover{ext}")):
                has_album_cover = True
                break

        if len(tracklist) >= 5:
            track_covers_found = 0
            for idx, t in enumerate(tracklist, 1):
                title = t.get("title", f"Track {idx}")
                clean_title = title.replace(" ", "_")
                for ext in [".png", ".jpg"]:
                    cands = [
                        os.path.join(art_dir, f"{title}_cover{ext}"),
                        os.path.join(art_dir, f"{clean_title}_cover{ext}"),
                        os.path.join(art_dir, f"Track {idx}_cover{ext}"),
                        os.path.join(art_dir, f"{title}{ext}"),
                    ]
                    if any(os.path.exists(c) for c in cands):
                        track_covers_found += 1
                        break
            if track_covers_found >= len(tracklist):
                has_all_track_covers = True

    # 3. Determine phase
    if len(tracklist) >= 5:
        if has_album_cover and has_all_track_covers:
            current_phase = 6
        elif has_album_cover:
            current_phase = 5
        else:
            current_phase = 4
    elif len(tracklist) > 0:
        current_phase = 1
    else:
        current_phase = 1

    return tracklist, current_phase, (has_album_cover and has_all_track_covers)


def extract_root_cause_error(stderr_text, stdout_errors=None, exit_code=None):
    """
    Extracts the true root-cause error line and classifies the failure category
    instead of blindly slicing the middle of a usage block or traceback.
    """
    raw = (stderr_text or "").strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    # Filter out generic argparse usage lines so the actual error line stands out
    meaningful = [
        l for l in lines
        if not l.lower().startswith("usage:")
        and not (l.startswith("[--") and l.endswith("]"))
    ]

    # Look for explicit error lines from bottom up
    root_line = ""
    for l in reversed(meaningful or lines):
        low = l.lower()
        if any(k in low for k in ["error:", "exception:", "failed", "http error", "timeout", "invalid choice", "unrecognized arguments", "filenotfound", "keyerror", "valueerror", "jsondecodeerror"]):
            root_line = l
            break

    if not root_line and meaningful:
        root_line = meaningful[-1]
    elif not root_line and stdout_errors:
        root_line = stdout_errors[-1]
    elif not root_line:
        root_line = f"Subprocess exited with code {exit_code}" if exit_code is not None else "Unknown pipeline error"

    recent_err_text = (raw + " " + " ".join((stdout_errors or [])[-4:])).lower()
    combined = (raw + " " + " ".join(stdout_errors or [])).lower()
    if "invalid choice" in combined or "unrecognized arguments" in combined or "argument --" in combined:
        category = "CLI_ARG_MISMATCH"
        hint = "Script CLI arguments out of sync between pipeline and producer skill."
    elif "missing or empty" in recent_err_text or "ffmpeg" in recent_err_text or "pedalboard" in recent_err_text or "soundfile" in recent_err_text:
        category = "AUDIO_DSP_ERROR"
        hint = "Audio stem mixing or FFmpeg master export produced an empty output file."
    elif "429" in recent_err_text or "rate limit" in recent_err_text:
        category = "VENICE_RATE_LIMIT"
        hint = "Venice AI API rate limit reached; retry after a short pause."
    elif "401" in recent_err_text or "403" in recent_err_text or "api_key" in recent_err_text:
        category = "API_AUTH_ERROR"
        hint = "API authentication or key quota issue."
    elif "timeout" in recent_err_text or "timed out" in recent_err_text:
        category = "API_TIMEOUT"
        hint = "Upstream model inference timed out."
    elif "ffmpeg" in combined or "pedalboard" in combined or "soundfile" in combined:
        category = "AUDIO_DSP_ERROR"
        hint = "Audio stem mixing or FFmpeg mastering failed."
    else:
        category = "PRODUCE_SCRIPT_FAIL"
        hint = "Subprocess exited unexpectedly during track generation."

    return {
        "category": category,
        "root_line": root_line[:350],
        "hint": hint,
        "tail": "\n".join((meaningful or lines)[-6:])[:600],
    }


def send_pipeline_error_card(album_name, phase_num, phase_name, diag, track_num=None, track_title=None, exit_code=None, stdout_errors=None, include_buttons=True):
    """
    Sends a structured diagnostic error card to Telegram with actionable recovery buttons.
    """
    track_label = f"Track {track_num}" + (f" (<b>{html.escape(str(track_title))}</b>)" if track_title else "") if track_num else "Batch Setup"
    exit_label = f" (exit {exit_code})" if exit_code is not None else ""

    msg_lines = [
        f"⚠️ <b>Production Halted — {html.escape(str(album_name))}</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"• <b>Stage:</b> Phase {phase_num} ({html.escape(str(phase_name))}) — {track_label}",
        f"• <b>Category:</b> <code>{html.escape(diag.get('category', 'ERROR'))}</code>{exit_label}",
        f"• <b>Root Cause:</b>\n<pre>{html.escape(diag.get('root_line', 'Unknown error'))}</pre>",
    ]
    if stdout_errors:
        recent_attempts = "\n".join(stdout_errors[-3:])
        msg_lines.append(f"• <b>Recent Sub-Step Errors:</b>\n<pre>{html.escape(recent_attempts[:400])}</pre>")
    if diag.get("hint"):
        msg_lines.append(f"💡 <i>{html.escape(diag['hint'])}</i>")

    reply_markup = None
    if include_buttons:
        msg_lines.append("\n<i>Choose an action below:</i>")
        buttons = []
        if diag.get("category") == "VENICE_402_INSUFFICIENT_BALANCE":
            buttons.append([
                {"text": "💳 Credit Added", "callback_data": "ap:credit:added"},
                {"text": "⏸ Pause", "callback_data": "ap:credit:pause"},
            ])
        buttons.extend([
            [
                {"text": "🔄 Retry Now", "callback_data": "ap:error:retry"},
                {"text": "⏭ Skip & Continue", "callback_data": "ap:error:skip"},
            ],
            [
                {"text": "📋 Full Error Log", "callback_data": "ap:error:log"},
                {"text": "🛑 Abort Pipeline", "callback_data": "ap:error:abort"},
            ],
        ])
        reply_markup = {"inline_keyboard": buttons}

    return send_message("\n".join(msg_lines), reply_markup=reply_markup)


# ── Phase 1: Music Production (Granular Checkpoint & Resuming) ─────────
def phase_1_produce(proposal, profile, redo_track=None, redo_feedback=None, mode="full", duration=260, dashboard=None, state=None):
    album_name = proposal.get('album', 'Unknown Album')
    subgenre = proposal.get('subgenre', 'dark nightride trap')

    if logger_hub:
        logger_hub.log_event("PHASE_START", {"mode": mode, "duration": duration}, album=album_name, phase=1)

    # Auto-discover existing completed masters on disk
    disc_tracks, disc_phase, _ = discover_existing_album_production(proposal)
    if len(disc_tracks) >= 5:
        logger.info(f"All 5 tracks already completed on disk as DAW masters for {album_name}. Skipping Phase 1 production.")
        return disc_tracks

    # Check granular checkpoint in state
    completed_tracks = []
    if state and state.get("completed_tracks"):
        for ct in state.get("completed_tracks"):
            mp3 = ct.get("mp3_path")
            if mp3 and os.path.exists(mp3) and os.path.getsize(mp3) > 10000:
                completed_tracks.append(ct)

    # Save to completed_tracks.json so produce-album.py can resume
    os.makedirs("/tmp", exist_ok=True)
    with open("/tmp/completed_tracks.json", "w") as cf:
        json.dump({"completed": completed_tracks, "total_cost": sum(float(t.get("cost", 0)) for t in completed_tracks)}, cf)

    resume_count = len(completed_tracks)
    if resume_count >= 5:
        logger.info(f"All 5 tracks already completed on disk. Resuming directly to Phase 2/3.")
        return completed_tracks

    if resume_count > 0:
        logger.info(f"Granular resume: {resume_count}/5 tracks already complete. Generating remaining tracks...")
        if dashboard:
            for ct in completed_tracks:
                dashboard.update_track(ct.get("track", 1), ct.get("title", f"Track {ct.get('track',1)}"), "complete", bpm=ct.get("bpm"), cost=ct.get("cost"))

    # Build prompt brief
    brief = f"{album_name} - {subgenre}. "
    brief += f"{proposal.get('brief', '')} "
    brief += f"{proposal.get('bpm', '130')} BPM, {proposal.get('key', 'Cm')}. "
    if profile:
        sonic = profile.get('sonic_dna', {})
        brief += "\n--- VØIDRIDE IDENTITY ---\n"
        brief += f"Primary genres: {', '.join(sonic.get('primary_genres', []))}\n"
        models = sonic.get('preferred_models', {})
        brief += f"Preferred models: {models.get('main', 'elevenlabs-music')} (main), "
        brief += f"{models.get('texture', 'stable-audio-25')} (texture), "
        brief += f"{models.get('accent', 'elevenlabs-sound-effects-v2')} (accent)\n"
        brief += f"Preferred keys: {', '.join(sonic.get('preferred_keys', []))}\n"
        sig = sonic.get('sound_signature', '')
        if sig:
            brief += f"Sound signature: {sig}\n"
        anti = sonic.get('anti_patterns', [])
        if anti:
            brief += f"Anti-patterns: {', '.join(anti)}\n"
        brief += f"The VØIDRIDE sound: {profile.get('prompt_prefix', '')}\n"
        brief += (
            "SMOOTH SFX RULE: If any special effects (risers, accents, foley, transitions) are used, "
            "make them velvet-smooth, warm, low-pass filtered, and deeply blended with lush reverb fade-ins/outs — "
            "NEVER jarring, harsh, piercing, or abrupt.\n"
        )

    prop_tracks = proposal.get("tracks", [])
    cover_visual = proposal.get("visual", "")
    album_theme = f"{subgenre}. {proposal.get('bpm', '134')} BPM, {proposal.get('key', 'Cm')}. {proposal.get('brief', '')}".strip()
    quality = profile.get("defaults", {}).get("quality", "hyperspatial")
    expected_count = len(prop_tracks) if prop_tracks else 5
    remaining_to_produce = max(0, expected_count - resume_count)

    # Pre-flight Venice AI balance & track completion capacity check
    budget = evaluate_venice_budget(
        remaining_tracks=remaining_to_produce,
        mode=mode,
        quality=quality,
        include_covers=True,
        album_name=album_name,
    )
    if budget.get("ok"):
        cap_tracks = min(budget["completable_tracks"], remaining_to_produce)
        logger.info(
            f"Venice Balance Pre-Flight: ${budget['total_usd']:.2f} USD "
            f"(need ~${budget['tracks_needed_cost']:.2f} for {remaining_to_produce} tracks @ ~${budget['cost_per_track']:.2f}/track, "
            f"+ ~${budget['cover_cost']:.2f} covers | can complete {cap_tracks}/{remaining_to_produce} tracks)"
        )
        if budget["completable_tracks"] == 0 and remaining_to_produce > 0:
            next_track_num = resume_count + 1
            next_track_title = prop_tracks[next_track_num - 1] if prop_tracks and (next_track_num - 1) < len(prop_tracks) else f"Track {next_track_num}"
            send_agent_notification(
                f"⛔ Venice AI inference balance depleted for {album_name}! "
                f"Remaining balance: ${budget['total_usd']:.2f} USD (${budget['usd']:.2f} USD / {budget['diem']:.2f} DIEM). "
                f"Can complete: 0/{remaining_to_produce} remaining tracks (~${budget['cost_per_track']:.2f}/track). "
                f"Shortfall: ${budget['shortfall_tracks']:.2f} USD for tracks (${budget['shortfall_total']:.2f} USD including covers). "
                f"Paused at Track {next_track_num} ({next_track_title})."
            )
            diag = {
                "category": "VENICE_402_INSUFFICIENT_BALANCE",
                "root_line": (
                    f"Venice AI Balance Low: ${budget['total_usd']:.2f} USD remaining "
                    f"(can complete 0/{remaining_to_produce} remaining tracks @ ~${budget['cost_per_track']:.2f}/track; "
                    f"need ~${budget['tracks_needed_cost']:.2f} USD for tracks, shortfall ${budget['shortfall_tracks']:.2f} USD)."
                ),
                "hint": (
                    f"✅ {resume_count}/{expected_count} tracks are safely saved on disk. "
                    f"Top up at least ${budget['shortfall_total']:.2f} USD at https://venice.ai/settings/api "
                    f"and tap 🔄 Retry Now to resume from Track {next_track_num} ({next_track_title})."
                ),
            }
            send_pipeline_error_card(
                album_name=album_name,
                phase_num=1,
                phase_name=f"Music Production ({resume_count}/{expected_count} Complete)",
                diag=diag,
                track_num=next_track_num,
                track_title=next_track_title,
                include_buttons=True,
            )
            while True:
                flag, content = poll_flags(timeout_hours=24)
                if flag in ("error:retry", "error_retry", "credit:added", "credit_added"):
                    if dashboard:
                        dashboard.clear_error()
                    if state:
                        state["produce_batch_retries"] = 0
                        save_state(state)
                    return phase_1_produce(proposal, profile, mode=mode, duration=duration, dashboard=dashboard, state=state)
                elif flag in ("credit:pause", "credit_paused"):
                    logger.info("Pipeline paused waiting for Venice AI credits...")
                    continue
                elif flag in ("error:skip", "error_skip"):
                    if resume_count > 0:
                        send_message(f"⏭ Proceeding to Phase 2 (DAWAGENT Studio Mastering) with the {resume_count} completed tracks.")
                        return completed_tracks
                    sys.exit(0)
                elif flag in ("error:abort", "error_abort"):
                    sys.exit(0)
        elif not budget["can_complete_tracks"]:
            send_agent_notification(
                f"⚠️ Venice AI low balance warning for {album_name}: "
                f"${budget['total_usd']:.2f} USD remaining — can only complete {cap_tracks}/{remaining_to_produce} remaining tracks "
                f"(~${budget['cost_per_track']:.2f}/track; need ~${budget['tracks_needed_cost']:.2f} USD, shortfall ${budget['shortfall_tracks']:.2f} USD)."
            )
        else:
            send_agent_notification(
                f"💳 Venice AI balance verified for {album_name}: ${budget['total_usd']:.2f} USD remaining — "
                f"sufficient to complete all {remaining_to_produce}/{remaining_to_produce} remaining track(s) "
                f"(~${budget['tracks_needed_cost']:.2f} USD) + artwork (~${budget['cover_cost']:.2f} USD)."
            )

    closer_duration = profile.get("defaults", {}).get("closer_duration", 236) if profile else 236
    cmd = [
        "/opt/hermes/.venv/bin/python3", PRODUCE_SCRIPT,
        "--brief", brief,
        "--tracks", str(expected_count),
        "--duration", str(duration),
        "--closer-duration", str(closer_duration),
        "--mode", mode,
        "--quality", quality,
        "--no-deliver",
        "--resume-tracks", str(resume_count),
        "--album-name", album_name,
        "--album-theme", album_theme,
        "--cover-visual", cover_visual,
    ]
    if prop_tracks:
        cmd.extend(["--track-names"] + [str(t) for t in prop_tracks])

    logger.info(f"Spawning produce-album (resume-tracks={resume_count}): {' '.join(cmd[:8])}...")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    tracklist = list(completed_tracks)
    track_num = resume_count
    active_track_num = resume_count + 1
    stdout_error_lines = []

    # Monitor stdout for progress and track completions
    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        line = line.strip()
        if not line:
            # Check pipeline_progress.json periodically
            if os.path.exists("/tmp/pipeline_progress.json") and dashboard:
                try:
                    with open("/tmp/pipeline_progress.json") as pf:
                        prog = json.load(pf)
                    cur_num = prog.get("track_num")
                    if cur_num:
                        active_track_num = int(cur_num)
                        dashboard.update_track(cur_num, f"Track {cur_num}", "generating", progress_pct=prog.get("elapsed_sec", 10) % 100, sub_phase=prog.get("phase_name"))
                        dashboard.live_cost = prog.get("total_cost", dashboard.live_cost)
                except Exception:
                    pass
            time.sleep(0.5)
            continue

        logger.info(f"Produce output: {line}")

        step_match = re.search(r'\[produce-album\]\s+\[(\d+)/(\d+)\]', line)
        if step_match:
            active_track_num = int(step_match.group(1))
            if dashboard:
                step_title = prop_tracks[active_track_num - 1] if prop_tracks and (active_track_num - 1) < len(prop_tracks) else f"Track {active_track_num}"
                dashboard.update_track(active_track_num, step_title, "generating", progress_pct=15)

        # Capture sub-step failure / warning lines from produce-album.py
        if any(marker in line for marker in ["❌", "⚠️", "Error:", "failed:"]):
            clean_err = re.sub(r'^\[produce-album\]\s*', '', line).strip()
            stdout_error_lines.append(clean_err)

        # Try JSON track output
        try:
            data = json.loads(line)
            if "track" in data and "title" in data:
                t_num = data.get("track")
                t_title = str(data.get("title", "")).strip()
                if prop_tracks and (t_num - 1) < len(prop_tracks):
                    prop_t = str(prop_tracks[t_num - 1]).strip().upper()
                    if prop_t:
                        t_title = prop_t
                        data["title"] = t_title
                elif not t_title or t_title.lower().startswith("track ") or t_title in ("?", "Unknown"):
                    if prop_tracks and (t_num - 1) < len(prop_tracks):
                        t_title = str(prop_tracks[t_num - 1]).strip().upper()
                        data["title"] = t_title
                t_bpm = data.get("bpm", "Unknown")
                t_cost = data.get("cost", "3.86")
                tracklist.append(data)
                if dashboard:
                    dashboard.update_track(t_num, t_title, "complete", bpm=t_bpm, cost=t_cost)
                    dashboard.live_cost += float(t_cost)
                if state:
                    add_cost(state, "track_production", float(t_cost))
                    add_cost(state, "llm_passes", SONG_LLM_BATCH_COST)
                    state["completed_tracks"] = tracklist
                    save_state(state)
                continue
        except (ValueError, json.JSONDecodeError):
            pass

        # Text format regex: "[produce-album]     ✅ EYEWALL | 160 BPM | $3.85"
        match = re.match(r'\[produce-album\]\s+✅\s+(.+?)\s*\|\s*(\d+|None|\?)\s*BPM\s*\|\s*\$?([\d.]+)', line)
        if match:
            track_num += 1
            t_title = match.group(1).strip()
            if prop_tracks and (track_num - 1) < len(prop_tracks):
                prop_t = str(prop_tracks[track_num - 1]).strip().upper()
                if prop_t:
                    t_title = prop_t
            elif not t_title or t_title.lower().startswith("track ") or t_title in ("?", "Unknown"):
                if prop_tracks and (track_num - 1) < len(prop_tracks):
                    t_title = str(prop_tracks[track_num - 1]).strip().upper()
            t_bpm = match.group(2)
            if t_bpm in ("None", "?"):
                t_bpm = proposal.get("bpm", "130")
            t_cost = match.group(3)
            track_entry = {"track": track_num, "title": t_title, "bpm": t_bpm, "cost": t_cost}
            tracklist.append(track_entry)
            if dashboard:
                dashboard.update_track(track_num, t_title, "complete", bpm=t_bpm, cost=t_cost)
                dashboard.live_cost += float(t_cost)
            if state:
                add_cost(state, "track_production", float(t_cost))
                add_cost(state, "llm_passes", SONG_LLM_BATCH_COST)
                state["completed_tracks"] = tracklist
                save_state(state)
            if logger_hub:
                logger_hub.log_event("TRACK_COMPLETE", track_entry, album=album_name, phase=1, track_num=track_num)
            send_message(f"✅ <b>Track {track_num}/5: {html.escape(t_title)}</b> generated ({t_bpm} BPM)")

    process.wait()

    if process.returncode != 0:
        err_out = process.stderr.read()
        diag = extract_root_cause_error(err_out, stdout_errors=stdout_error_lines, exit_code=process.returncode)
        cur_track_idx = track_num + 1
        cur_track_title = prop_tracks[cur_track_idx - 1] if prop_tracks and (cur_track_idx - 1) < len(prop_tracks) else None
        logger.error(f"Produce album failed with code {process.returncode} [{diag['category']}]: {diag['root_line']}")
        if logger_hub:
            logger_hub.log_failure(diag["category"], f"Exit {process.returncode}: {diag['root_line']}", traceback_str=err_out, album=album_name, phase=1, track_num=cur_track_idx)
        if dashboard:
            dashboard.set_error(f"{diag['category']} (exit {process.returncode}): {diag['root_line']}", track_num=cur_track_idx)
        # Interactive Error Recovery Gate with full root cause + inline buttons
        send_pipeline_error_card(
            album_name=album_name,
            phase_num=1,
            phase_name="Music Production",
            diag=diag,
            track_num=cur_track_idx,
            track_title=cur_track_title,
            exit_code=process.returncode,
            stdout_errors=stdout_error_lines,
            include_buttons=True,
        )
        while True:
            flag, content = poll_flags(timeout_hours=1)
            if flag in ("error:retry", "error_retry"):
                if dashboard:
                    dashboard.clear_error()
                return phase_1_produce(proposal, profile, mode=mode, duration=duration, dashboard=dashboard, state=state)
            elif flag in ("error:skip", "error_skip"):
                if dashboard:
                    dashboard.clear_error()
                break
            elif flag in ("error:log", "error_log"):
                full_log_text = (err_out or "\n".join(stdout_error_lines) or "No additional stderr output.")[-1500:]
                send_message(f"📋 <b>Full Error Log ({html.escape(album_name)}):</b>\n<pre>{html.escape(full_log_text)}</pre>")
                continue
            elif flag in ("error:abort", "error_abort"):
                logger.info(f"User aborted pipeline for {album_name} at error gate.")
                sys.exit(0)

    # Locate actual non-empty MP3 and FLAC files (>1KB)
    album_slug = proposal.get('album', '').lower().replace(' ', '-').replace('_', '-')
    raw_prod_dirs = sorted(glob.glob(f"/opt/data/music/productions/*{album_slug}*"))
    def _non_empty_audio(folder, pattern):
        return [f for f in sorted(glob.glob(os.path.join(folder, pattern))) if os.path.isfile(f) and os.path.getsize(f) > 1000]

    prod_dirs = [
        d for d in raw_prod_dirs
        if _non_empty_audio(d, "*.mp3") or _non_empty_audio(d, "*.flac")
    ]
    for i, t in enumerate(tracklist):
        existing_d = t.get("production_dir")
        if existing_d and os.path.isdir(existing_d) and (_non_empty_audio(existing_d, "*.mp3") or _non_empty_audio(existing_d, "*.flac")):
            d = existing_d
        elif i < len(prod_dirs):
            d = prod_dirs[i]
        else:
            continue
        mp3s = _non_empty_audio(d, "*.mp3")
        flacs = _non_empty_audio(d, "*.flac")
        if mp3s:
            t["mp3_path"] = mp3s[-1]
        if flacs:
            t["flac_path"] = flacs[-1]
        t["production_dir"] = d

    if state:
        state["completed_tracks"] = tracklist
        save_state(state)

    if not tracklist:
        logger.error(f"Phase 1 for {album_name} completed with 0 tracks! Halting.")
        diag = extract_root_cause_error("", stdout_errors=stdout_error_lines, exit_code=0)
        diag["root_line"] = diag["root_line"] if stdout_error_lines else "0 audio tracks were produced across all attempts."
        err_track_num = active_track_num if active_track_num else 1
        err_track_title = prop_tracks[err_track_num - 1] if prop_tracks and (err_track_num - 1) < len(prop_tracks) else None
        if dashboard:
            dashboard.set_error(f"0 tracks produced: {diag['root_line']}", track_num=err_track_num)
        send_pipeline_error_card(
            album_name=album_name,
            phase_num=1,
            phase_name="Music Production",
            diag=diag,
            track_num=err_track_num,
            track_title=err_track_title,
            stdout_errors=stdout_error_lines,
            include_buttons=True,
        )
        while True:
            flag, content = poll_flags(timeout_hours=24)
            if flag in ("error:retry", "error_retry"):
                if dashboard:
                    dashboard.clear_error()
                if state:
                    state["produce_batch_retries"] = 0
                    save_state(state)
                return phase_1_produce(proposal, profile, mode=mode, duration=duration, dashboard=dashboard, state=state)
            elif flag in ("error:log", "error_log"):
                full_log_text = ("\n".join(stdout_error_lines) or "No stdout error details captured.")[-1500:]
                send_message(f"📋 <b>Full Error Log ({html.escape(album_name)}):</b>\n<pre>{html.escape(full_log_text)}</pre>")
                continue
            elif flag in ("error:abort", "error_abort", "error:skip", "error_skip"):
                if os.path.exists(STATE_FILE):
                    try: os.remove(STATE_FILE)
                    except Exception: pass
                sys.exit(0)

    expected_count = len(prop_tracks) if prop_tracks else 5
    if len(tracklist) < expected_count:
        remaining_after = max(0, expected_count - len(tracklist))
        post_budget = evaluate_venice_budget(
            remaining_tracks=remaining_after,
            mode=mode,
            quality=quality,
            include_covers=True,
            album_name=album_name,
        )
        joined_err = " ".join(stdout_error_lines).lower()
        is_balance_err = (
            any(k in joined_err for k in ("402", "insufficient usd", "insufficient balance", "payment required", "balance depleted"))
            or (post_budget.get("ok") and post_budget.get("completable_tracks", 1) == 0)
        )
        retries = state.get("produce_batch_retries", 0) if state else 0
        if not is_balance_err and retries < 2:
            if state:
                state["produce_batch_retries"] = retries + 1
                save_state(state)
            logger.warning(f"Phase 1 for {album_name} incomplete: only {len(tracklist)}/{expected_count} tracks produced. Resuming to complete missing tracks (attempt {retries+1}/2)...")
            err_hint = f"\n<i>Last error: {html.escape(stdout_error_lines[-1][:180])}</i>" if stdout_error_lines else ""
            bal_note = (
                f"\n💳 <b>Venice Balance:</b> ${post_budget['total_usd']:.2f} USD "
                f"(can complete {min(post_budget['completable_tracks'], remaining_after)}/{remaining_after} remaining tracks)"
                if post_budget.get("ok") else ""
            )
            send_message(f"⚠️ <b>Incomplete Batch:</b> {len(tracklist)}/{expected_count} tracks completed for <b>{album_name}</b>.{err_hint}{bal_note}\nAuto-resuming to produce remaining tracks (attempt {retries+1}/2)...")
            return phase_1_produce(proposal, profile, mode=mode, duration=duration, dashboard=dashboard, state=state)
        else:
            next_track_num = len(tracklist) + 1
            next_track_title = prop_tracks[next_track_num - 1] if prop_tracks and (next_track_num - 1) < len(prop_tracks) else f"Track {next_track_num}"
            diag = extract_root_cause_error("", stdout_errors=stdout_error_lines, exit_code=1)
            cap_after = min(post_budget.get("completable_tracks", 0), remaining_after)
            if is_balance_err:
                diag["category"] = "VENICE_402_INSUFFICIENT_BALANCE"
                diag["root_line"] = (
                    f"Venice AI inference depleted on Track {next_track_num} ({next_track_title}). "
                    f"Remaining Balance: ${post_budget['total_usd']:.2f} USD (${post_budget['usd']:.2f} USD / {post_budget['diem']:.2f} DIEM) — "
                    f"can complete {cap_after}/{remaining_after} remaining tracks (~${post_budget['cost_per_track']:.2f}/track; "
                    f"need ~${post_budget['tracks_needed_cost']:.2f} USD for tracks + ~${post_budget['cover_cost']:.2f} covers, "
                    f"shortfall ${post_budget['shortfall_total']:.2f} USD)."
                )
                diag["hint"] = (
                    f"✅ Tracks 1–{len(tracklist)} are safely saved on disk. "
                    f"Top up at least ${post_budget['shortfall_total']:.2f} USD at https://venice.ai/settings/api "
                    f"and tap 🔄 Retry Now to resume from Track {next_track_num} ({next_track_title}), "
                    f"or tap ⏭ Skip & Continue to master & review the {len(tracklist)} completed tracks now."
                )
                send_agent_notification(
                    f"⛔ Venice AI inference ran out during {album_name} ({len(tracklist)}/{expected_count} tracks completed)! "
                    f"Remaining balance: ${post_budget['total_usd']:.2f} USD (${post_budget['usd']:.2f} USD / {post_budget['diem']:.2f} DIEM). "
                    f"Capacity check: can complete {cap_after}/{remaining_after} remaining tracks (@ ~${post_budget['cost_per_track']:.2f}/track). "
                    f"Shortfall: ${post_budget['shortfall_tracks']:.2f} USD for tracks (${post_budget['shortfall_total']:.2f} USD including covers)."
                )
            else:
                send_agent_notification(
                    f"⚠️ {album_name} paused at Track {next_track_num} ({len(tracklist)}/{expected_count} complete). "
                    f"Venice balance: ${post_budget['total_usd']:.2f} USD (can complete {cap_after}/{remaining_after} remaining tracks). "
                    f"Root cause: {diag['root_line']}"
                )
            logger.warning(f"Phase 1 paused at interactive recovery gate ({len(tracklist)}/{expected_count} tracks complete): {diag['root_line']}")
            if dashboard:
                dashboard.set_error(diag["root_line"], track_num=next_track_num)
            send_pipeline_error_card(
                album_name=album_name,
                phase_num=1,
                phase_name=f"Music Production ({len(tracklist)}/{expected_count} Complete)",
                diag=diag,
                track_num=next_track_num,
                track_title=next_track_title,
                stdout_errors=stdout_error_lines,
                include_buttons=True,
            )
            while True:
                flag, content = poll_flags(timeout_hours=24)
                if flag in ("error:retry", "error_retry", "credit:added", "credit_added"):
                    if dashboard:
                        dashboard.clear_error()
                    if state:
                        state["produce_batch_retries"] = 0
                        save_state(state)
                    return phase_1_produce(proposal, profile, mode=mode, duration=duration, dashboard=dashboard, state=state)
                elif flag in ("credit:pause", "credit_paused"):
                    logger.info("Pipeline paused waiting for Venice AI credits...")
                    continue
                elif flag in ("error:skip", "error_skip"):
                    if dashboard:
                        dashboard.clear_error()
                    send_message(f"⏭ Proceeding to Phase 2 (DAWAGENT Studio Mastering) with the {len(tracklist)} completed tracks.")
                    break
                elif flag in ("error:log", "error_log"):
                    full_log_text = ("\n".join(stdout_error_lines) or "No stdout error details captured.")[-1500:]
                    send_message(f"📋 <b>Full Error Log ({html.escape(album_name)}):</b>\n<pre>{html.escape(full_log_text)}</pre>")
                    continue
                elif flag in ("error:abort", "error_abort"):
                    logger.info(f"User aborted pipeline for {album_name} at Phase 1 recovery gate.")
                    if os.path.exists(STATE_FILE):
                        try: os.remove(STATE_FILE)
                        except Exception: pass
                    for st_f in ["/opt/data/music/pipeline_state.json", "D:/music/pipeline_state.json"]:
                        if os.path.exists(st_f):
                            try: os.remove(st_f)
                            except Exception: pass
                    sys.exit(0)

    if logger_hub:
        logger_hub.log_event("PHASE_COMPLETE", {"tracks_count": len(tracklist)}, album=album_name, phase=1)

    return tracklist


# ── Single Track Redo ───────────────────────────────────────────────────
def phase_1_redo_single(proposal, profile, tracklist, track_num, feedback=None, duration=220, dashboard=None, state=None):
    album_name = proposal.get('album', 'Unknown Album')
    album_slug = album_name.lower().replace(' ', '-').replace('_', '-')
    subgenre = proposal.get('subgenre', 'dark nightride trap')

    original = next((t for t in tracklist if t.get('track') == track_num), None)
    if not original:
        send_message(f"❌ Track {track_num} not found in tracklist")
        return tracklist

    title = original.get('title', f'Track {track_num}')
    title_plain = re.sub(r'^\d+[\s_\-]*', '', title).replace('_', ' ').strip()
    track_slug = title_plain.lower().replace(' ', '_')
    session_slug = f"{album_slug}-{track_slug}"

    raw_bpm = str(original.get('bpm', '134')).split('-')[0].strip()
    try:
        bpm_int = int(float(raw_bpm))
    except Exception:
        bpm_int = 134
    if bpm_int < 120 or bpm_int > 154:
        bpm_int = 138 if track_num == 1 else (124 if track_num == len(tracklist) else 134)
    bpm = str(bpm_int)
    original['bpm'] = bpm

    # Cohesive VØIDRIDE duration for redo: 220s for chapters, 236s for closer (both in <=240s Venice bucket)
    closer_dur = profile.get("defaults", {}).get("closer_duration", 236) if profile else 236
    duration = closer_dur if (track_num == len(tracklist) and len(tracklist) >= 2 and duration <= 235) else (duration if duration <= 240 else 220)

    key = original.get('key') or proposal.get('key', 'Dm')

    cover_visual = proposal.get("visual", "")
    brief = (
        f"California bass and heavy West Coast bass mixed with melodic nightride vibes, nocturnal cruising atmosphere, "
        f"massive continuous 808 sub-bass dominance. {album_name} - {subgenre}. Track {track_num}: {title_plain}. "
        f"{proposal.get('brief', '')} {bpm} BPM, {key}. "
    )
    if cover_visual:
        brief += f"Auditory interpretation of cover scene: {cover_visual}. "
    if profile:
        sonic = profile.get('sonic_dna', {})
        brief += f"\n--- VØIDRIDE IDENTITY ---\nPrimary genres: {', '.join(sonic.get('primary_genres', []))}\n"
        sig = sonic.get('sound_signature', '')
        if sig:
            brief += f"Sound signature: {sig}\n"
        anti = sonic.get('anti_patterns', [])
        if anti:
            brief += f"Anti-patterns: {', '.join(anti)}\n"
        brief += f"The VØIDRIDE sound: {profile.get('prompt_prefix', '')}\n"
        brief += (
            "SMOOTH SFX RULE: If any special effects (risers, accents, foley, transitions) are used, "
            "make them velvet-smooth, warm, low-pass filtered, and deeply blended with lush reverb fade-ins/outs — "
            "NEVER jarring, harsh, piercing, or abrupt.\n"
        )
    if feedback:
        brief += f"\n[REDO FEEDBACK]: {feedback}\n"

    if dashboard:
        dashboard.update_track(track_num, title_plain, "generating", progress_pct=30, sub_phase=f"Redoing ({bpm} BPM)")

    send_message(
        f"🔄 Redoing Track {track_num}: <b>{html.escape(title_plain)}</b> ({bpm} BPM, {key}) with strict VØIDRIDE California bass nightride DNA..."
    )

    prev_tracks = [
        {
            "number": t.get("track"),
            "title": t.get("title"),
            "bpm": int(float(str(t.get("bpm", 130)).split("-")[0])) if str(t.get("bpm", "")).replace(".", "").isdigit() else 130,
            "key": t.get("key", "Dm"),
            "genre": subgenre,
            "energy": "heavy California West Coast nightride bass",
        }
        for t in tracklist
        if t.get("track") != track_num
    ]

    ctx = {
        "track_number": track_num,
        "total_tracks": len(tracklist),
        "album_name": album_name,
        "album_theme": f"{subgenre}. {proposal.get('brief', '')}",
        "cover_visual": cover_visual,
        "track_title": title_plain,
        "brief": brief,
        "previous_tracks": prev_tracks,
        "sonic_translation": {
            "rule_1_environment": f"Cavernous nocturnal space ({cover_visual[:120]}) translated into wide 3D binaural delay throws and cold spectral witch-house reverb tails.",
            "rule_2_transients": "Crisp West Coast snap snares, punchy acoustic-sampled transient kicks, rolling syncopated hi-hats, and metallic industrial micro-accents.",
            "rule_3_harmonic": f"Dark minor-pentatonic detuned analog brass and melancholic sine plucks in {key} at {bpm} BPM over heavy gliding California 808 sub-bass.",
            "rule_4_energy_arc": "Smooth atmospheric buildup dropping into relentless, chest-rattling California 808 sub-bass dominance with zero mid-track silence drops.",
            "tempo_bpm": bpm_int,
            "musical_key": key,
        },
        "variation_rules": [
            f"Keep strict VØIDRIDE California bass & heavy West Coast nightride aesthetic at {bpm} BPM in {key}. "
            f"Dominant gliding 808 sub-bass from start to finish, crisp snap snares, detuned nightride synth leads, zero silence drops. "
            f"Ensure all special effects and transitions are velvet-smooth, filtered, and reverb-washed — never jarring or abrupt."
            + (f" Redo direction: {feedback}" if feedback else "")
        ],
    }
    ctx_file = f"/tmp/album_ctx_redo_{track_num}.json"
    with open(ctx_file, "w") as f:
        json.dump(ctx, f, indent=2)

    quality = profile.get("defaults", {}).get("quality", "hyperspatial") if profile else "hyperspatial"
    cmd = [
        "/opt/hermes/.venv/bin/python3", MASTER_PRODUCER_SCRIPT,
        "--prompt", brief,
        "--duration", str(duration),
        "--quality", quality,
        "--director",
        "--title", title_plain,
        "--album", album_name,
        "--track-number", str(track_num),
        "--total-tracks", str(len(tracklist)),
        "--no-deliver",
    ]
    env = os.environ.copy()
    env["ALBUM_CONTEXT_FILE"] = ctx_file
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)

    if proc.returncode != 0:
        diag = extract_root_cause_error(proc.stderr, exit_code=proc.returncode)
        send_message(
            f"❌ <b>Track {track_num} ({html.escape(title_plain)}) redo failed</b> [{diag['category']}]:\n"
            f"<pre>{html.escape(diag['root_line'])}</pre>"
        )
        if logger_hub:
            logger_hub.log_failure("REDO_FAIL", diag["root_line"], traceback_str=proc.stderr, album=album_name, phase=1, track_num=track_num)
        return tracklist

    # Parse JSON output from master-producer.py stdout
    mp_out = None
    if proc.stdout:
        for line in reversed(proc.stdout.strip().splitlines()):
            line_s = line.strip()
            if line_s.startswith("{") and line_s.endswith("}"):
                try:
                    mp_out = json.loads(line_s)
                    break
                except Exception:
                    pass
        if not mp_out:
            try:
                mp_out = json.loads(proc.stdout.strip())
            except Exception:
                mp_out = None

    if mp_out and mp_out.get("session_dir"):
        latest_dir = mp_out["session_dir"]
        original["production_dir"] = latest_dir
        all_files = mp_out.get("all_files", {})
        if all_files.get("mp3") and os.path.exists(all_files["mp3"]):
            original["mp3_path"] = all_files["mp3"]
        if mp_out.get("primary_file") and os.path.exists(mp_out["primary_file"]):
            original["flac_path"] = mp_out["primary_file"]
        elif all_files.get("flac") and os.path.exists(all_files["flac"]):
            original["flac_path"] = all_files["flac"]
    else:
        # Fallback directory scan
        prod_dirs = sorted(glob.glob("/opt/data/music/productions/2026*"))
        if prod_dirs:
            latest_dir = prod_dirs[-1]
            mp3s = sorted(glob.glob(os.path.join(latest_dir, "master_*.mp3")))
            flacs = sorted(glob.glob(os.path.join(latest_dir, "master_*.flac")))
            if mp3s:
                original["mp3_path"] = mp3s[-1]
            if flacs:
                original["flac_path"] = flacs[-1]
            original["production_dir"] = latest_dir

    # Read production_plan.json from the new session_dir to update actual BPM, Key, and Cost
    plan_file = os.path.join(original.get("production_dir", ""), "production_plan.json")
    redo_audio_cost = 3.16
    if os.path.isfile(plan_file):
        try:
            with open(plan_file) as pf:
                plan_data = json.load(pf)
            if plan_data.get("bpm"):
                original["bpm"] = str(plan_data["bpm"])
            if plan_data.get("key"):
                original["key"] = str(plan_data["key"])
            if plan_data.get("cost", {}).get("total_usd"):
                redo_audio_cost = float(plan_data["cost"]["total_usd"])
        except Exception:
            pass
    original["cost"] = str(redo_audio_cost)
    if state is not None:
        add_cost(state, "track_redos", redo_audio_cost)
        add_cost(state, "llm_passes", SONG_LLM_REDO_COST)
        costs = init_cost_tracker(state)
        costs["redo_count"] = costs.get("redo_count", 0) + 1
        save_state(state)

    # CRITICAL: Clear stale DAWAGENT master references and delete old export/session files
    # so phase_2_daw_handoff freshly masters the newly generated stems!
    original["master_path"] = None
    original["master_mp3"] = None
    original["dawagent_mastered"] = False

    stale_export_dir = f"/opt/data/dawagent/exports/{session_slug}"
    stale_session_dir = f"/opt/data/dawagent/sessions/{session_slug}"
    for stale_dir in (stale_export_dir, stale_session_dir):
        if os.path.isdir(stale_dir):
            try:
                shutil.rmtree(stale_dir)
                logger.info(f"Cleared stale DAWAGENT directory for redo: {stale_dir}")
            except Exception as e:
                logger.warning(f"Could not clear {stale_dir}: {e}")

    if dashboard:
        dashboard.update_track(track_num, title_plain, "complete")

    send_message(
        f"✅ Track {track_num}: <b>{html.escape(title_plain)}</b> ({original.get('bpm', bpm)} BPM, {original.get('key', key)}) "
        f"redone with VØIDRIDE DNA! Routing to DAWAGENT for studio mastering..."
    )
    return tracklist


# ── Composer DAW Master Planning ─────────────────────────────────────────
def build_composer_daw_plan(title, subgenre, bpm, key, stems):
    """
    Generate a genre-aware, composer-tailored DSP chain for DAWAGENT.
    Customizes EQ curves, dynamics, and spatial enhancements per stem to add
    maximum studio polish and punch to the final masters.
    """
    g = (subgenre or "").lower()
    plan_parts = []

    for s_name in stems:
        s_lower = s_name.lower()
        if "drum" in s_lower or "percussion" in s_lower:
            if any(k in g for k in ["phonk", "drift", "hard"]):
                plan_parts.append(
                    f"{s_name}: LSP Gate (fast decay) + Calf 8-Band EQ (boost 52Hz sub, dip 280Hz boxiness, air boost 10kHz) + "
                    f"LSP Compressor (4:1, fast attack 15ms, punch release) + Calf Saturation (tape drive 1.5)"
                )
            elif any(k in g for k in ["witch", "sacral", "gothic"]):
                plan_parts.append(
                    f"{s_name}: LSP Gate + Calf EQ (boost 48Hz, cut 400Hz) + LSP Compressor (glue) + Dragonfly Room (tight 0.8s)"
                )
            else:
                plan_parts.append(
                    f"{s_name}: LSP Gate + Calf EQ (punch) + LSP Compressor (punch) + x42 Stereo Tools (hat width)"
                )
        elif "bass" in s_lower or "808" in s_lower:
            plan_parts.append(
                f"{s_name}: Calf Bass Enhancer (odd harmonics) + Calf EQ (steep low-cut 28Hz, sub-focus 40-75Hz, mono sum < 90Hz) + "
                f"LSP Limiter (-0.5dB ceiling)"
            )
        elif any(k in s_lower for k in ["lead", "melody", "synth"]):
            plan_parts.append(
                f"{s_name}: Calf 8-Band EQ (high-pass 120Hz, presence boost 3.2kHz) + LSP Compressor (smooth 2.5:1) + "
                f"Dragonfly Hall Reverb (2.4s decay, 25% wet)"
            )
        elif any(k in s_lower for k in ["spatial", "3d"]):
            plan_parts.append(
                f"{s_name}: 3D Binaural Haas + Orbital LFO Panning + x42 M/S Widening (136% side) + 808 Sub Sidechain Ducking"
            )
        elif any(k in s_lower for k in ["ear_candy", "foley", "riser", "accent", "sfx"]):
            plan_parts.append(
                f"{s_name}: Beat-Locked Risers + Sub-Drop Impacts + 3D Doppler Foley + Pitched Sample Chops + Plate Reverb"
            )
        elif any(k in s_lower for k in ["texture", "pad", "atmosphere", "b_section"]):
            plan_parts.append(
                f"{s_name}: x42 High-Pass Filter (cut < 140Hz) + Dragonfly Hall Reverb (cavernous 3.5s) + "
                f"Calf Stereo Tools (130% stereo width) + 808 Sidechain Ducking"
            )
        elif any(k in s_lower for k in ["no_drum", "instrument", "main"]):
            plan_parts.append(
                f"{s_name}: Calf 8-Band EQ (sub-focus 45-75Hz, sculpt mids 1.5-4kHz) + LSP Compressor (musical glue 2.8:1) + Demucs Breakdown/Stutter"
            )
        else:
            plan_parts.append(
                f"{s_name}: Calf EQ (presence) + LSP Compressor + Calf Saturation"
            )

    return " | ".join(plan_parts) if plan_parts else "Master_Mix: Calf EQ (sub/air) + LSP Compressor (glue) + loudnorm"


# ── Phase 2: DAW Mastering ──────────────────────────────────────────────
def phase_2_daw_handoff(proposal, tracklist, mode="full", dashboard=None):
    if mode == "sample":
        logger.info("Sample preview mode: skipping DAW mastering entirely.")
        return

    album_name = proposal.get('album', 'release')
    album_slug = album_name.lower().replace(' ', '-').replace('_', '-')
    subgenre = proposal.get('subgenre', proposal.get('genre', 'Electronic'))
    if dashboard:
        dashboard.set_phase(2)

    all_mastered = all(
        t.get('master_path') and os.path.exists(t.get('master_path')) and os.path.getsize(t.get('master_path')) > 10000
        for t in tracklist
    ) if tracklist else False
    if len(tracklist) >= 5 and all_mastered:
        logger.info(f"All {len(tracklist)} tracks already mastered by DAWAGENT on disk. Skipping Phase 2 DAW handoff.")
        return

    logger.info(f"Phase 2: Running per-track DAWAGENT mastering for {album_name}...")
    if logger_hub:
        logger_hub.log_event("PHASE_START", {"album": album_name}, phase=2)

    send_message(
        f"🎛️ <b>Phase 2: DAWAGENT Studio Mastering</b>\n"
        f"• Album: <b>{html.escape(album_name)}</b> ({len(tracklist)} tracks)\n"
        f"• Processing: Discrete stem mixing, LSP dynamic processing, and 48kHz/32-bit mastering..."
    )

    exports_base = "/opt/data/dawagent/exports"
    handoff_script = "/opt/data/skills/dawagent/dawagent/scripts/handoff.py"

    for i, t in enumerate(tracklist, 1):
        title = t.get('title', f"Track {i}")
        title_plain = re.sub(r'^\d+[\s_\-]*', '', title).replace('_', ' ').strip()
        track_slug = title_plain.lower().replace(' ', '_')
        session_slug = f"{album_slug}-{track_slug}"
        export_dir = os.path.join(exports_base, session_slug)
        master_flac = os.path.join(export_dir, f"{session_slug}_MASTER.flac")
        master_mp3 = os.path.join(export_dir, f"{session_slug}_MASTER.mp3")

        # 1. Reuse existing export if already completed
        if os.path.exists(master_flac) and os.path.getsize(master_flac) > 10000:
            logger.info(f"[{i}/{len(tracklist)}] Reusing existing DAW master: {master_flac}")
            t['master_path'] = master_flac
            t['master_mp3'] = master_mp3
            t['dawagent_mastered'] = True
            continue

        # 2. Collect stems or mix file for this track
        prod_dir = t.get('production_dir') or ""
        stems_to_use = []
        stem_names = []

        # Priority 1: Full-length 3D-arranged discrete stems exported by master-producer.py (01_main, 02_texture, 03_atmosphere, 04_spatial, 06_ear_candy_bus)
        daw_stem_files = sorted(glob.glob(os.path.join(prod_dir, "daw_stems", "*.wav")))
        if len(daw_stem_files) >= 2:
            stems_to_use = daw_stem_files
            stem_names = [Path(s).stem for s in daw_stem_files]

        # Priority 2: Check for demucs stems if daw_stems unavailable
        if not stems_to_use:
            demucs_dirs = glob.glob(os.path.join(prod_dir, "stems", "demucs", "htdemucs", "*"))
            if demucs_dirs and os.path.isdir(demucs_dirs[0]):
                d_dir = demucs_dirs[0]
                d_drums = os.path.join(d_dir, "drums.wav")
                d_nodrums = os.path.join(d_dir, "no_drums.wav")
                if os.path.exists(d_drums) and os.path.exists(d_nodrums):
                    stems_to_use = [d_drums, d_nodrums]
                    stem_names = ["Drums", "Instrumentation"]

        # Priority 3: Check for main/texture/atmosphere/spatial stems (including singles/ and sfx/ subdirs)
        if not stems_to_use:
            raw_stems = sorted(
                glob.glob(os.path.join(prod_dir, "stems", "**", "*.wav"), recursive=True)
                + glob.glob(os.path.join(prod_dir, "stems", "**", "*.mp3"), recursive=True)
            )
            valid_stems = [
                s for s in raw_stems
                if not s.endswith("_fx.wav") and "demucs" not in s.replace("\\", "/").split("/")
            ]
            if len(valid_stems) >= 2:
                stems_to_use = valid_stems
                stem_names = [Path(s).stem.replace('_', ' ').title() for s in valid_stems]

        # Priority 4: Fallback to pre-mixed wav/flac if stems unavailable
        if not stems_to_use:
            mix_candidates = glob.glob(os.path.join(prod_dir, "mix_*.wav"))
            if mix_candidates:
                stems_to_use = [mix_candidates[0]]
                stem_names = ["Master_Mix"]
            elif t.get('flac_path') and os.path.exists(t['flac_path']):
                stems_to_use = [t['flac_path']]
                stem_names = ["Master_Mix"]

        if not stems_to_use:
            logger.warning(f"No audio files found to hand off for track {title}, keeping native master.")
            t['master_path'] = t.get('flac_path') or t.get('mp3_path')
            t['master_mp3'] = t.get('mp3_path')
            t['dawagent_mastered'] = False
            continue

        # 3. Build Composer's tailored DSP processing plan
        t_bpm = t.get('bpm', proposal.get('bpm', 120))
        t_key = t.get('key', proposal.get('key', 'Cm'))
        dsp_plan = build_composer_daw_plan(title_plain, subgenre, t_bpm, t_key, stem_names)

        # 4. Dispatch handoff to DAWAGENT
        logger.info(f"Submitting track [{i}/{len(tracklist)}] {title_plain} to DAWAGENT session: {session_slug}")
        if dashboard:
            dashboard.update_track(i, title_plain, "daw_mastering", sub_phase="DAW DSP")

        send_message(
            f"🎛️ <i>[{i}/{len(tracklist)}]</i> Routing <b>{html.escape(title_plain)}</b> into DAWAGENT...\n"
            f"• Session: <code>{session_slug}</code> ({len(stems_to_use)} stems)\n"
            f"• Composer DSP Plan: <i>{html.escape(dsp_plan[:90])}...</i>"
        )

        handoff_cmd = [
            "/opt/hermes/.venv/bin/python3", handoff_script, "write",
            "--session", session_slug,
            "--bpm", str(t_bpm if str(t_bpm).isdigit() else 134),
            "--stems", ",".join(stems_to_use),
            "--stem-names", ",".join(stem_names),
            "--plan", dsp_plan,
            "--source", "album_pipeline",
            "--album", album_name,
            "--profile", "vidride",
            "--notes", f"{album_name} Track {i}: {title_plain} ({subgenre}, {t_key})"
        ]
        if prod_dir and os.path.isdir(prod_dir):
            handoff_cmd.extend(["--production-dir", prod_dir])
        h_res = subprocess.run(handoff_cmd, capture_output=True, text=True)
        if h_res.returncode != 0:
            logger.error(f"Handoff write failed for {title_plain}: {h_res.stderr[-200:]}")
            t['master_path'] = t.get('flac_path') or t.get('mp3_path')
            t['master_mp3'] = t.get('mp3_path')
            continue

        # 5. Wait for DAWAGENT auto_processor to finish this track (up to 90s)
        logger.info(f"Waiting for DAWAGENT auto_processor on {session_slug}...")
        poll_start = time.time()
        max_poll = 90
        daw_ok = False

        while time.time() - poll_start < max_poll:
            time.sleep(3)
            if os.path.exists(master_flac) and os.path.getsize(master_flac) > 10000:
                daw_ok = True
                break

        if daw_ok:
            logger.info(f"✓ DAWAGENT mastering complete for {title_plain}: {master_flac}")
            t['master_path'] = master_flac
            # Ensure mastered MP3 is available for reference preview
            if not os.path.exists(master_mp3) or os.path.getsize(master_mp3) < 1000:
                mp3_wait_start = time.time()
                while time.time() - mp3_wait_start < 10:
                    if os.path.exists(master_mp3) and os.path.getsize(master_mp3) > 1000:
                        break
                    time.sleep(1)
            # If still not created by auto_processor, convert now with ffmpeg
            if not os.path.exists(master_mp3) or os.path.getsize(master_mp3) < 1000:
                subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", master_flac, "-codec:a", "libmp3lame", "-b:a", "320k", "-ar", "48000", master_mp3], capture_output=True, timeout=30)
            t['master_mp3'] = master_mp3 if os.path.exists(master_mp3) else t.get('mp3_path')
            t['dawagent_mastered'] = True
            send_message(f"✅ <i>[{i}/{len(tracklist)}]</i> <b>{html.escape(title_plain)}</b> mastered by DAWAGENT! (48kHz/32-bit studio master)")
            if dashboard:
                dashboard.update_track(i, title_plain, "complete")
        else:
            logger.warning(f"DAWAGENT timed out for {title_plain} ({max_poll}s), falling back to native master.")
            t['master_path'] = t.get('flac_path') or t.get('mp3_path')
            t['master_mp3'] = t.get('mp3_path')
            send_message(f"⚠️ <i>[{i}/{len(tracklist)}]</i> DAWAGENT timed out for <b>{html.escape(title_plain)}</b> — safely kept native 24-bit/48kHz master.")

    send_message(f"🎚️ <b>All {len(tracklist)} tracks mastered!</b> Ready for Song Review.")
    logger.info("Phase 2 complete: All track masters ready.")


# ── Phase 3: Song Review ────────────────────────────────────────────────
def phase_3_song_review(tracklist, proposal=None, dashboard=None):
    if dashboard:
        dashboard.set_phase(3)

    album_name = proposal.get("album", "Release") if proposal else "Album"
    total_tracks = len(tracklist)

    # 1. Send clear, structured master preview announcement
    send_message(
        f"🎚️ <b>{html.escape(album_name)} — All {total_tracks} Tracks Mastered</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ Every track has completed 48kHz/32-bit DAW stem mastering & DSP processing.\n"
        f"🎧 <b>Reference Masters (320kbps MP3) for inline preview below:</b>"
    )

    # 2. Deliver all masters together for inline preview
    for t in tracklist:
        track_num = t.get('track', '?')
        title = t.get('title', f"Track {track_num}")
        bpm = t.get('bpm', proposal.get('bpm', '?') if proposal else '?')
        key = t.get('key', proposal.get('key', '?') if proposal else '?')

        # Verify master MP3 exists; convert from master FLAC if needed
        mp3 = t.get('master_mp3')
        if (not mp3 or not os.path.exists(mp3)) and t.get('master_path') and os.path.exists(t['master_path']):
            mp3_candidate = t['master_path'].replace('.flac', '.mp3')
            if os.path.exists(mp3_candidate):
                mp3 = mp3_candidate
                t['master_mp3'] = mp3
            else:
                subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", t['master_path'], "-codec:a", "libmp3lame", "-b:a", "320k", "-ar", "48000", mp3_candidate], capture_output=True, timeout=30)
                if os.path.exists(mp3_candidate):
                    mp3 = mp3_candidate
                    t['master_mp3'] = mp3
        if not mp3 or not os.path.exists(mp3):
            mp3 = t.get('mp3_path')

        if mp3 and os.path.exists(mp3):
            send_audio(mp3, caption=f"🎵 [{track_num}/{total_tracks}] {title} (Mastered · {bpm} BPM · {key})")

    # 3. Always package and deliver BOTH external and internal download links
    _package_and_share_flacs(tracklist, proposal)

    # 4. Interactive review buttons (Approve / Redo / Reject - NO premature publish button!)
    buttons = [
        [{"text": "✅ Approve All Songs", "callback_data": "ap:songs:approve"}],
        [{"text": "📥 Re-package Master Archive", "callback_data": "ap:songs:flac"}]
    ]
    for t in tracklist:
        n = t.get('track')
        buttons.append([{"text": f"🔄 Redo Track {n}", "callback_data": f"ap:songs:redo:{n}"}])
    buttons.append([{"text": "❌ Remake Entire Album", "callback_data": "ap:songs:reject"}])

    send_message(
        "👆 <b>Listen to all masters above and review your options:</b>\n"
        "<i>Tap <b>Approve All Songs</b> to proceed to Album Cover Art review, or select a track to revise.</i>",
        reply_markup={"inline_keyboard": buttons}
    )

    while True:
        flag, content = poll_flags()
        if flag == "songs_approved":
            return "approved", None
        elif flag == "songs_flac_requested":
            send_message("📦 Re-packaging FLACs + playlist via Cloudflare tunnel...")
            _package_and_share_flacs(tracklist, proposal)
            continue
        elif flag.startswith("songs_redo_"):
            try:
                track_num = int(flag.split('_')[-1])
                return "redo_track", (track_num, content)
            except Exception:
                continue
        elif flag == "songs_rejected":
            return "reject", content


def _package_and_share_flacs(tracklist, proposal):
    try:
        album_title = proposal.get("album", "ALBUM").strip()
        album_slug = album_title.lower().replace(" ", "-").replace("_", "-")
        exports_base = "/opt/data/music/exports" if os.path.exists("/opt/data/music") else r"D:\music\exports"
        pack_dir = os.path.join(exports_base, album_slug)
        os.makedirs(pack_dir, exist_ok=True)

        flac_files = []
        for idx, t in enumerate(tracklist):
            flac = t.get("master_path") or t.get("flac_path")
            title = t.get("title", f"Track_{idx+1}").strip()
            clean_t = title.replace(" ", "_")
            if flac and os.path.exists(flac):
                dest_name = f"{(idx+1):02d}_{clean_t}_MASTER.flac"
                dest = os.path.join(pack_dir, dest_name)
                if os.path.abspath(flac) != os.path.abspath(dest):
                    shutil.copy2(flac, dest)
                flac_files.append(dest_name)
            elif t.get("mp3_path") and os.path.exists(t["mp3_path"]):
                dest_name = f"{(idx+1):02d}_{clean_t}.mp3"
                dest = os.path.join(pack_dir, dest_name)
                if os.path.abspath(t["mp3_path"]) != os.path.abspath(dest):
                    shutil.copy2(t["mp3_path"], dest)
                flac_files.append(dest_name)

        if not flac_files:
            send_message(f"⚠️ No completed audio tracks found for <b>{html.escape(album_title)}</b> yet. Production is currently in progress.")
            return

        win_folder_path = f"D:\\music\\exports\\{album_slug}"
        playlist_filename = f"{album_slug}_playlist.m3u8"
        playlist_path = os.path.join(pack_dir, playlist_filename)
        win_playlist_path = f"{win_folder_path}\\{playlist_filename}"

        # M3U8 playlist - ONLY when all tracks are present
        total_expected = len(tracklist) if tracklist else 5
        has_playlist = len(flac_files) >= total_expected and total_expected > 1
        if has_playlist:
            with open(playlist_path, "w", encoding="utf-8") as pf:
                pf.write("#EXTM3U\n")
                pf.write(f"#PLAYLIST:{album_title} (VØIDRIDE Studio Masters)\n")
                for idx, fname in enumerate(flac_files, 1):
                    t_title = tracklist[idx - 1].get("title", fname) if idx <= len(tracklist) else fname
                    pf.write(f"#EXTINF:-1,VØIDRIDE - {t_title}\n{win_folder_path}\\{fname}\n")

        # Tag metadata
        tag_script = "/opt/data/skills/delivery-receipt/scripts/tag_metadata.py"
        if os.path.exists(tag_script):
            subprocess.run(["/opt/hermes/.venv/bin/python3", tag_script, "--dir", pack_dir], capture_output=True, timeout=60)

        # Share via Cloudflare tunnel & local service
        res = subprocess.run(["/opt/hermes/.venv/bin/python3", SHARE_SCRIPT, "--path", pack_dir], capture_output=True, text=True, timeout=120)
        external_link = None
        internal_link = None
        for line in res.stdout.splitlines():
            if "[EXTERNAL LINK]" in line:
                external_link = line.split("[EXTERNAL LINK]")[-1].strip()
            elif "[INTERNAL LINK]" in line:
                internal_link = line.split("[INTERNAL LINK]")[-1].strip()

        if has_playlist and os.path.exists(playlist_path):
            send_document(playlist_path, caption=f"🎶 <b>{html.escape(album_title)}</b> — Windows VLC Playlist (.m3u8)")

        pl_suffix = " + VLC playlist" if has_playlist else ""
        msg = (
            f"📦 <b>{html.escape(album_title)} — Full Master Archive</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎵 {len(flac_files)} Tracks (48kHz/24-bit Studio FLACs{pl_suffix})\n\n"
        )
        if external_link:
            msg += f"🌐 <b>External Download (Cloudflare / Mobile):</b>\n🔗 <a href='{external_link}'>{external_link}</a>\n\n"
        if internal_link:
            msg += f"🏠 <b>Internal Download (Tailscale / LAN):</b>\n🔗 <a href='{internal_link}'>{internal_link}</a>\n\n"
        msg += f"📁 <b>Windows Local Folder:</b>\n<code>{html.escape(win_folder_path)}</code>\n"
        if has_playlist:
            msg += f"🎶 <b>Windows VLC Playlist:</b>\n<code>{html.escape(win_playlist_path)}</code>\n"

        send_message(msg)
    except Exception as e:
        send_message(f"❌ FLAC packaging error: {e}")


# ── Phase 4: Album Cover Art ───────────────────────────────────────────
def get_current_moon_phase(dt=None):
    """
    Calculate dynamic astronomical moon phase using synodic lunar cycle.
    Returns (phase_name, atmospheric_description).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    ref = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    diff_days = (dt - ref).total_seconds() / 86400.0
    synodic = 29.53058867
    cycle = (diff_days % synodic) / synodic

    if cycle < 0.03 or cycle >= 0.97:
        return "New Moon", "a dark, near-invisible new moon obscured by dense smog"
    elif cycle < 0.22:
        return "Waxing Crescent", "a razor-thin waxing crescent moon hanging sharp and cold in the night sky"
    elif cycle < 0.28:
        return "First Quarter", "a stark, half-lit first quarter moon carving sharp shadows"
    elif cycle < 0.47:
        return "Waxing Gibbous", "a luminous waxing gibbous moon casting heavy silver rim light"
    elif cycle < 0.53:
        return "Full Moon", "a blinding, silver-white full moon piercing through nocturnal haze"
    elif cycle < 0.72:
        return "Waning Gibbous", "a cold waning gibbous moon casting pale rim light and diffused glows through the mist"
    elif cycle < 0.78:
        return "Last Quarter", "a stark half-lit waning last quarter moon cutting through the gloom"
    else:
        return "Waning Crescent", "a delicate waning crescent moon glowing faintly above the skyline"


def sanitize_prompt_for_venice(prompt, max_len=1450):
    """
    Ensure prompt satisfies Venice AI validation (max 1500 chars) and enforces NO TEXT.
    """
    prompt = prompt.strip()
    suffix = " NO TEXT, NO LETTERS, NO TYPOGRAPHY, NO WORDS"
    if "NO TEXT" in prompt.upper():
        suffix = ""
    avail_len = max_len - len(suffix)
    if len(prompt) > avail_len:
        trimmed = prompt[:avail_len]
        last_period = trimmed.rfind('.')
        if last_period > avail_len - 150:
            prompt = trimmed[:last_period + 1]
        else:
            last_space = trimmed.rfind(' ')
            if last_space > 0:
                prompt = trimmed[:last_space]
            else:
                prompt = trimmed
    return (prompt + suffix).strip()


def upsample_image_prompt_k3(title, core_concept, subgenre="", is_album=False, custom_notes="", state=None):
    """
    Upsample image prompt into a hyper-detailed cinematic scene using kimi-k3 via Venice API.
    Derives visuals directly from the musical theme / acoustic DNA.
    Sometimes includes signature recurring motifs:
      - Shadowed man with fedora
      - Dynamic current moon phase
      - Katana
    """
    if not VENICE_API_KEY:
        logger.warning("VENICE_API_KEY missing, using fallback prompt.")
        return sanitize_prompt_for_venice(f"Cinematic neon-noir scene for {title}. {core_concept}. {subgenre}")

    moon_name, moon_desc = get_current_moon_phase()

    import random
    include_fedora = random.random() < 0.65
    include_moon = random.random() < 0.75
    include_katana = random.random() < 0.60

    motifs = []
    if include_fedora:
        motifs.append("A mysterious silhouette of a shadowed man in a wide-brimmed fedora (motionless in background doorway or deep shadow, face completely obscured in darkness, trenchcoat hem dissolving into haze)")
    if include_moon:
        motifs.append(f"Current astronomical moon phase: {moon_name} ({moon_desc}) visible through skylight, frosted window, or reflected on wet concrete/water")
    if include_katana:
        motifs.append("A matte-black katana with textured black tsuka hilt wrapping, resting naturally in the scene (on a brushed steel table, dashboard, or wet floor), subtle razor edge reflection")

    motifs_instruction = "\n".join(f"- {m}" for m in motifs) if motifs else "- Maintain minimalist neon-noir clinical aesthetic"

    system_instruction = (
        "You are an elite cinematic art director and visual prompt engineer for VØIDRIDE, "
        "a dark neon-noir / witch house trap / heavy West Coast bass electronic artist.\n"
        "Your task: Convert the given song theme, sonic DNA, and visual concept into an extraordinarily "
        "detailed, photorealistic cinematic scene prompt for an AI image generation model.\n\n"
        "Strict Guidelines:\n"
        "1. NO TEXT, NO LETTERS, NO TYPOGRAPHY, NO WATERMARKS, NO WORDS in the image.\n"
        "2. Style: Photorealistic 35mm / anamorphic cinematic photography, ARRI Alexa 65, shallow depth of field, "
        "volumetric fog, film grain, subtle halation, dramatic chiaroscuro lighting, razor-sharp textures.\n"
        "3. Derive all visual metaphors directly from the song's musical themes, instruments, and mood.\n"
        "4. Seamlessly incorporate these signature recurring motifs if listed:\n"
        f"{motifs_instruction}\n"
        "5. CRITICAL CONSTRAINT: The generated prompt MUST be under 1200 characters (around 150 words). Be densely atmospheric and concise.\n"
        "6. MAXIMUM SCENE VARIATION: If Type is 'Single Track Cover', depict a completely unique focal subject, architectural sub-setting, and camera perspective that interprets the track title within the album's world. NEVER repeat the exact same vehicle, room layout, or central object across covers.\n\n"
        "Output ONLY the final generated image prompt paragraph. Do NOT include markdown headers, preambles, or conversational filler."
    )

    user_input = (
        f"Title: {title}\n"
        f"Type: {'Album Cover' if is_album else 'Single Track Cover'}\n"
        f"Subgenre / Sonic DNA: {subgenre}\n"
        f"Core Concept / Theme: {core_concept}\n"
    )
    if custom_notes:
        user_input += f"Specific Director Notes: {custom_notes}\n"

    url = "https://api.venice.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json"
    }

    models_to_try = _mr.get_role_chain("llm.image_prompt", ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"]) if _mr else ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"]
    for model_name in models_to_try:
        v_params = {"strip_thinking_response": True}
        if "qwen" in model_name:
            v_params["disable_thinking"] = True
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_input}
            ],
            "temperature": 0.7,
            "max_tokens": 900,
            "venice_parameters": v_params,
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                choice = data.get("choices", [{}])[0]
                msg = choice.get("message", {})
                content = msg.get("content", "").strip() or msg.get("reasoning_content", "").strip()
                if content:
                    cleaned = re.sub(r'^(Prompt:\s*|Here is the prompt:\s*|Visual prompt:\s*)', '', content, flags=re.IGNORECASE).strip('"` \n')
                    if state is not None:
                        add_cost(state, "prompt_upsampling", VENICE_K3_PROMPT_COST)
                    logger.info(f"Successfully upsampled prompt with {model_name} for '{title}' ({len(cleaned)} chars)")
                    return sanitize_prompt_for_venice(cleaned)
        except Exception as e:
            logger.warning(f"K3 upsample attempt with {model_name} failed: {e}")
            time.sleep(1)

    fallback_prompt = (
        f"Cinematic photorealistic nightride scene for {title}. {core_concept}. "
        f"{subgenre}. Volumetric lighting, 35mm film grain, 8K resolution, atmospheric fog."
    )
    return sanitize_prompt_for_venice(fallback_prompt)


def generate_artwork_venice(prompt, album_name, state=None):
    parts = album_name.split('/')
    if len(parts) == 2:
        art_dir = get_album_artwork_dir(parts[0])
        out_path = os.path.join(art_dir, f"{parts[1].replace(' ', '_')}_cover.png")
    else:
        art_dir = get_album_artwork_dir(album_name)
        out_path = os.path.join(art_dir, "album_cover.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if not VENICE_API_KEY:
        logger.error("VENICE_API_KEY missing, skipping image generation.")
        return None

    clean_prompt = sanitize_prompt_for_venice(prompt)

    url = "https://api.venice.ai/api/v1/images/generations"
    headers = {"Authorization": f"Bearer {VENICE_API_KEY}", "Content-Type": "application/json"}
    models = _mr.get_role_chain("image.cover_primary", ["qwen-image-3-pro", "grok-imagine-image-2-0", "grok-imagine-image"]) if _mr else ["qwen-image-3-pro", "grok-imagine-image-2-0", "grok-imagine-image"]

    for model_name in models:
        payload = {
            "model": model_name,
            "prompt": clean_prompt,
            "response_format": "b64_json"
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        for attempt in range(2):
            try:
                logger.info(f"Generating artwork using {model_name} (attempt {attempt+1})...")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    b64 = data.get('data', [{}])[0].get('b64_json')
                    if b64:
                        with open(out_path, 'wb') as f:
                            f.write(base64.b64decode(b64))
                        if state:
                            add_cost(state, "cover_generation", VENICE_IMAGE_GEN_COST)
                        logger.info(f"Artwork saved to {out_path} ({os.path.getsize(out_path)} bytes)")
                        return out_path
            except Exception as e:
                logger.warning(f"Venice image generation with {model_name} attempt {attempt+1} failed: {e}")
                time.sleep(2)

    return None


def edit_artwork_venice(image_path, edit_prompt, out_path=None, state=None):
    """
    Edit artwork using Venice AI image edit inference (/api/v1/image/edit).
    Uses base64 data URL and enhance_prompt=True for vision-guided precision.
    """
    if not VENICE_API_KEY or not os.path.exists(image_path):
        logger.error("VENICE_API_KEY missing or image file not found.")
        return None

    if out_path is None:
        out_path = image_path

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    clean_prompt = sanitize_prompt_for_venice(edit_prompt)

    url = "https://api.venice.ai/api/v1/image/edit"
    headers = {
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "image": f"data:image/png;base64,{img_b64}",
        "prompt": clean_prompt,
        "enhance_prompt": True
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    for attempt in range(2):
        try:
            logger.info(f"Editing artwork with prompt: '{clean_prompt}' (attempt {attempt+1})...")
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
                if len(data) > 1000:
                    with open(out_path, "wb") as f:
                        f.write(data)
                    if state:
                        add_cost(state, "cover_edits", VENICE_IMAGE_EDIT_COST)
                        costs = init_cost_tracker(state)
                        costs["cover_edit_count"] = costs.get("cover_edit_count", 0) + 1
                        save_state(state)
                    logger.info(f"Edited artwork saved to {out_path} ({len(data)} bytes)")
                    return out_path
        except Exception as e:
            logger.warning(f"Venice image edit attempt {attempt+1} failed: {e}")
            time.sleep(2)

    return None


def upscale_artwork_venice(image_path, target_size=3000):
    if not VENICE_API_KEY or not os.path.exists(image_path):
        return image_path
    from PIL import Image
    try:
        img = Image.open(image_path)
        if img.size[0] >= target_size and img.size[1] >= target_size:
            return image_path

        with open(image_path, 'rb') as f:
            img_data = f.read()

        boundary = '----VeniceUpscaleBoundary'
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{os.path.basename(image_path)}"\r\n'
            f'Content-Type: image/png\r\n\r\n'.encode() + img_data + b'\r\n' +
            f'--{boundary}\r\nContent-Disposition: form-data; name="scale"\r\n\r\n4\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="creativity"\r\n\r\n0.01\r\n'
            f'--{boundary}--\r\n'.encode()
        )
        url = "https://api.venice.ai/api/v1/image/upscale"
        req = urllib.request.Request(url, data=body, method='POST', headers={
            'Authorization': f'Bearer {VENICE_API_KEY}',
            'Content-Type': f'multipart/form-data; boundary={boundary}',
        })

        with urllib.request.urlopen(req, timeout=150) as response:
            upscaled_data = response.read()

        if len(upscaled_data) > 1000:
            tmp_path = image_path.replace('.png', '_4k.png')
            with open(tmp_path, 'wb') as f:
                f.write(upscaled_data)
            upscaled_img = Image.open(tmp_path)
            final = upscaled_img.resize((target_size, target_size), Image.LANCZOS)
            final.save(image_path, 'PNG')
            if os.path.getsize(image_path) > 5_000_000:
                jpg_path = os.path.splitext(image_path)[0] + '.jpg'
                final.convert('RGB').save(jpg_path, 'JPEG', quality=95)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return image_path
    except Exception as e:
        logger.error(f"Venice upscale failed: {e}")
        if logger_hub:
            logger_hub.log_failure("UPSCALE_FAIL", str(e), album=os.path.basename(image_path), phase=4)
    return image_path


def sanitize_filename(title):
    clean = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    return clean.strip().replace(" ", "_").upper()


def generate_waveform_banner(bg_image_path, title_clean, out_dirs=None, track_num=None, album_slug=None, force=False, state=None, use_paid_ai_extend=False):
    """
    Generate clean 1240x400 panoramic waveform banner from clean 3000x3000 background image.
    Defaults to $0.00 razor-sharp high-res Lanczos panoramic crop (zero hallucinated text, zero latency),
    with optional Venice AI 16:9 outpainting when use_paid_ai_extend=True.
    """
    if not os.path.exists(bg_image_path):
        return None
    try:
        from PIL import Image
        import io
        clean_name = sanitize_filename(title_clean)
        music_root = "/opt/data/music" if os.path.exists("/opt/data/music") else "D:/music"
        master_dir = os.path.join(music_root, "artwork", "waveforms")
        os.makedirs(master_dir, exist_ok=True)
        master_file = os.path.join(master_dir, f"{clean_name}_waveform.png")

        banner_bytes = None
        if not force and os.path.exists(master_file) and os.path.getsize(master_file) > 1000:
            with open(master_file, "rb") as mf:
                banner_bytes = mf.read()
        elif use_paid_ai_extend and VENICE_API_KEY:
            with Image.open(bg_image_path) as img:
                resized = img.convert("RGB").resize((1024, 1024), Image.LANCZOS)
                buf = io.BytesIO()
                resized.save(buf, format="JPEG", quality=90)
                b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")

            prompt = (
                "Reimagine this artwork as an ultra-wide panoramic scene, seamlessly extending "
                "the visual world of the original to the left and right. Keep the exact same "
                "color palette, atmosphere, lighting, and mood. Create a cohesive, continuous "
                "cinematic composition that expands the scene naturally. "
                "Absolutely NO TEXT, NO WORDS, NO LETTERS, NO TYPOGRAPHY anywhere in the image."
            )
            url = "https://api.venice.ai/api/v1/image/edit"
            headers = {"Authorization": f"Bearer {VENICE_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "image": f"data:image/jpeg;base64,{b64_img}",
                "prompt": prompt,
                "aspect_ratio": "16:9"
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    data = resp.read()
                    if "image" in content_type or (len(data) > 8 and data[:8] == b'\x89PNG\r\n\x1a\n'):
                        raw_bytes = data
                    else:
                        try:
                            res_json = json.loads(data.decode("utf-8"))
                            if "data" in res_json and res_json["data"]:
                                b64 = res_json["data"][0].get("b64_json", "")
                                raw_bytes = base64.b64decode(b64)
                            else:
                                raw_bytes = data
                        except Exception:
                            raw_bytes = data

                    if raw_bytes and len(raw_bytes) > 1000:
                        banner_img = Image.open(io.BytesIO(raw_bytes))
                        w, h = banner_img.size
                        target_w, target_h = 1240, 400
                        target_ratio = target_w / target_h
                        new_h = int(w / target_ratio)
                        center_offset = int(h * 0.1)
                        top = (h - new_h) // 2 + center_offset
                        top = min(top, h - new_h)
                        cropped = banner_img.crop((0, max(0, top), w, min(h, top + new_h)))
                        final = cropped.resize((target_w, target_h), Image.LANCZOS)
                        out_buf = io.BytesIO()
                        final.save(out_buf, "PNG")
                        banner_bytes = out_buf.getvalue()
                        if state is not None:
                            add_cost(state, "waveform_banners", VENICE_IMAGE_EDIT_COST)
            except Exception as api_err:
                logger.warning(f"Venice waveform API edit error for {clean_name}: {api_err}. Using local high-res panoramic crop.")

        if not banner_bytes and os.path.exists(bg_image_path):
            try:
                with Image.open(bg_image_path) as img:
                    w, h = img.size
                    target_w, target_h = 1240, 400
                    target_ratio = target_w / target_h
                    new_h = int(w / target_ratio)
                    center_offset = int(h * 0.1)
                    top = (h - new_h) // 2 + center_offset
                    top = min(top, max(0, h - new_h))
                    cropped = img.crop((0, max(0, top), w, min(h, top + new_h)))
                    final = cropped.resize((target_w, target_h), Image.LANCZOS)
                    out_buf = io.BytesIO()
                    final.save(out_buf, "PNG")
                    banner_bytes = out_buf.getvalue()
                    logger.info(f"Generated clean local crop waveform banner for {clean_name}")
            except Exception as fe:
                logger.error(f"Local crop waveform failed for {clean_name}: {fe}")

        if banner_bytes:
            extra_dirs = []
            if album_slug:
                slug = album_slug.lower().replace(" ", "-").replace("_", "-")
                extra_dirs = [
                    os.path.join(music_root, "albums", slug, "artwork"),
                    os.path.join(music_root, "albums", slug, "artwork", "waveforms"),
                    os.path.join(music_root, "artwork", "albums", slug),
                    os.path.join(music_root, "artwork", "albums", slug, "waveforms"),
                    os.path.join(music_root, "artwork", "waveforms", slug),
                    os.path.join(music_root, "exports", slug, "waveforms"),
                    os.path.join(music_root, "releases", slug, "waveforms"),
                    os.path.join(music_root, "releases", slug, "covers"),
                ]
            target_dirs = set((out_dirs or []) + extra_dirs + [master_dir])
            saved_primary = None
            for d in target_dirs:
                if d:
                    os.makedirs(d, exist_ok=True)
                    dest = os.path.join(d, f"{clean_name}_waveform.png")
                    with open(dest, "wb") as f:
                        f.write(banner_bytes)
                    if not saved_primary:
                        saved_primary = dest
                    if track_num is not None:
                        num_dest = os.path.join(d, f"{int(track_num):02d}_{clean_name}_waveform.png")
                        with open(num_dest, "wb") as f:
                            f.write(banner_bytes)
                    elif album_slug and os.path.abspath(d) != os.path.abspath(master_dir):
                        alb_dest = os.path.join(d, "album_waveform.png")
                        with open(alb_dest, "wb") as f:
                            f.write(banner_bytes)
            logger.info(f"Successfully generated/saved clean waveform banner for {clean_name} across {len(target_dirs)} directories")
            return saved_primary or True
    except Exception as e:
        logger.error(f"Failed to generate waveform banner for {title_clean}: {e}")
    return False


def phase_4_album_cover(proposal, tracklist, state=None, dashboard=None):
    if dashboard:
        dashboard.set_phase(4)
    album_name = proposal.get('album', 'Unknown Album')
    visual = proposal.get('visual', '')
    subgenre = proposal.get('subgenre', '')
    brief = proposal.get('brief', '')

    art_dir = get_album_artwork_dir(album_name)
    os.makedirs(art_dir, exist_ok=True)
    cover_path = os.path.join(art_dir, "album_cover.png")
    cover_bg = os.path.join(art_dir, "album_cover_bg.png")

    force_regen = getattr(phase_4_album_cover, '_force_regen', False)
    phase_4_album_cover._force_regen = False

    if not os.path.exists(cover_bg) or not os.path.exists(cover_path) or force_regen:
        send_message(f"🎨 <b>Designing album cover for {html.escape(album_name)}...</b>\nUpsampling visual prompt with K3 AI...")

        core_concept = f"Album visual: {visual}. Musical brief: {brief}"
        upsampled_prompt = upsample_image_prompt_k3(album_name, core_concept, subgenre=subgenre, is_album=True)

        send_message("🖼️ <b>Synthesizing visual with Venice SOTA image engine (qwen-image-3-pro)...</b>")
        raw_path = generate_artwork_venice(upsampled_prompt, album_name, state=state)
        if not raw_path or not os.path.exists(raw_path):
            send_message("❌ Failed to generate album cover.")
            return "regen"

        shutil.copy2(raw_path, cover_bg)

    if os.path.exists(OVERLAY_TITLE_SCRIPT) and os.path.exists(cover_bg):
        styled_album = stylize_title(album_name)
        logger.info(f"Overlaying title '{styled_album}' stacked & justified onto bottom of cover preview...")
        subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                        "--image", cover_bg, "--title", styled_album, "--stacked", "--bottom", "--auto-color", "--opacity", "0.60", "--output", cover_path], capture_output=True)
    elif os.path.exists(cover_bg) and not os.path.exists(cover_path):
        shutil.copy2(cover_bg, cover_path)

    jpg_path = os.path.splitext(cover_path)[0] + '.jpg'
    try:
        from PIL import Image
        with Image.open(cover_path) as im:
            im.convert('RGB').save(jpg_path, 'JPEG', quality=95)
    except Exception as e:
        logger.warning(f"Could not convert cover to jpg: {e}")

    def _send_album_review_card():
        buttons = [
            [{"text": "✅ Approve Album Cover", "callback_data": "ap:albumcover:approve"}],
            [
                {"text": "🔄 Regenerate", "callback_data": "ap:albumcover:regen"},
                {"text": "✏️ Edit Cover", "callback_data": "ap:albumcover:edit"}
            ],
            [
                {"text": "🌑 Darker", "callback_data": "ap:albumcover:quickedit:darker"},
                {"text": "🌫️ Dense Mist", "callback_data": "ap:albumcover:quickedit:mist"},
                {"text": "🗡️ Add Katana", "callback_data": "ap:albumcover:quickedit:katana"}
            ],
            [
                {"text": "👤 Fedora Shadow", "callback_data": "ap:albumcover:quickedit:fedora"},
                {"text": "🌕 Moon Glint", "callback_data": "ap:albumcover:quickedit:moon"}
            ]
        ]
        moon_phase, _ = get_current_moon_phase()
        caption = (
            f"🎨 <b>Album Cover: {html.escape(album_name)}</b>\n"
            f"🌙 Phase: <i>{moon_phase}</i> | 📐 3000×3000 Master on Approval\n"
            f"<i>Review cover below — tap Approve, Regenerate, or Edit:</i>"
        )
        send_file = jpg_path if os.path.exists(jpg_path) else cover_path
        send_photo(send_file, caption=caption, reply_markup={"inline_keyboard": buttons})

    _send_album_review_card()

    while True:
        flag, content = poll_flags()
        if flag == "albumcover_approved":
            send_message("✅ Album cover approved! Upscaling clean master to 3000×3000 & generating panoramic waveform banner...")
            if os.path.exists(cover_bg):
                upscale_artwork_venice(cover_bg)
                if state:
                    add_cost(state, "cover_upscale", VENICE_UPSCALE_COST)
                if os.path.exists(OVERLAY_TITLE_SCRIPT):
                    styled_album = stylize_title(album_name)
                    subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                                    "--image", cover_bg, "--title", styled_album, "--stacked", "--bottom", "--auto-color", "--opacity", "0.60", "--output", cover_path], capture_output=True)
                else:
                    shutil.copy2(cover_bg, cover_path)
                try:
                    from PIL import Image
                    with Image.open(cover_path) as im:
                        im.convert('RGB').save(jpg_path, 'JPEG', quality=95)
                except Exception:
                    pass
            alb_bg = cover_bg if os.path.exists(cover_bg) else cover_path
            album_slug = album_name.lower().replace(' ', '-').replace('_', '-')
            wave_res = generate_waveform_banner(alb_bg, album_name, [art_dir, "/opt/data/music/artwork/waveforms"], track_num=None, album_slug=album_slug, force=True)
            if isinstance(wave_res, str) and os.path.exists(wave_res):
                send_photo(wave_res, caption=f"🌊 <b>Album Waveform Banner: {html.escape(album_name)}</b> (1240×400)")
            return "approved"
        elif flag == "albumcover_regen":
            send_message("🔄 <b>Regenerating album cover from scratch...</b>")
            phase_4_album_cover._force_regen = True
            if state:
                add_cost(state, "cover_regeneration", VENICE_IMAGE_GEN_COST)
                costs = init_cost_tracker(state)
                costs["cover_regen_count"] = costs.get("cover_regen_count", 0) + 1
                save_state(state)
            return phase_4_album_cover(proposal, tracklist, state=state, dashboard=dashboard)
        elif flag == "albumcover_edit":
            edit_directive = content if content else "darker, heavier contrast, dramatic lighting"
            send_message(f"✏️ <b>Modifying cover visual:</b> <i>{html.escape(edit_directive)}</i>\nRunning Venice AI vision edit inference...")

            if not os.path.exists(cover_bg) and os.path.exists(cover_path):
                shutil.copy2(cover_path, cover_bg)

            edit_artwork_venice(cover_bg, edit_directive, cover_bg, state=state)

            if os.path.exists(OVERLAY_TITLE_SCRIPT):
                styled_album = stylize_title(album_name)
                logger.info(f"Overlaying title '{styled_album}' stacked & justified onto bottom of 3000x3000 canvas...")
                subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                                "--image", cover_bg, "--title", styled_album, "--stacked", "--bottom", "--auto-color", "--opacity", "0.60", "--output", cover_path], capture_output=True)
            else:
                shutil.copy2(cover_bg, cover_path)

            jpg_path = os.path.splitext(cover_path)[0] + '.jpg'
            try:
                from PIL import Image
                with Image.open(cover_path) as im:
                    im.convert('RGB').save(jpg_path, 'JPEG', quality=95)
            except Exception as e:
                logger.warning(f"Could not convert cover to jpg: {e}")

            _send_album_review_card()


# ── Phase 5: Track Cover Art ───────────────────────────────────────────
def _extract_track_dna(track_item, proposal):
    title = track_item.get('title', 'Unknown Track')
    visual = proposal.get('visual', '')
    subgenre = proposal.get('subgenre', '')
    album = proposal.get('album', '')

    extra_stems = ""
    prod_dir = track_item.get('production_dir')
    if prod_dir and os.path.exists(os.path.join(prod_dir, 'production_plan.json')):
        try:
            with open(os.path.join(prod_dir, 'production_plan.json')) as f:
                plan = json.load(f)
            stems = plan.get('stems', {})
            main_p = stems.get('main', {}).get('prompt', '')
            tex_p = stems.get('texture', {}).get('prompt', '')
            energy = plan.get('energy', '')
            genre = plan.get('genre', subgenre)
            extra_stems = f"Sonic DNA: {main_p}. Texture: {tex_p}. Mood: {energy}."
        except Exception as e:
            logger.warning(f"Failed to read production_plan.json for {title}: {e}")

    direction = track_item.get('direction', track_item.get('genre', subgenre))
    return (
        f"Track Title: '{title}'. Album Universe: '{album}' ({visual}). Musical Style: {direction}. {extra_stems} "
        f"CRITICAL VISUAL DIRECTIVE: This track cover MUST depict a completely original, distinct sub-environment or focal subject within the '{album}' universe that directly interprets the title '{title}'. "
        f"Dramatically vary the focal point, camera distance, and composition so it does NOT look like the main album cover or other tracks."
    )


def phase_5_track_covers(proposal, tracklist, state=None, dashboard=None):
    if dashboard:
        dashboard.set_phase(5)
    album_name = proposal.get('album', 'Unknown Album')
    subgenre = proposal.get('subgenre', '')
    track_art_dir = get_album_artwork_dir(album_name)
    os.makedirs(track_art_dir, exist_ok=True)

    force_regen_all = getattr(phase_5_track_covers, '_force_regen', False)
    phase_5_track_covers._force_regen = False

    track_cover_paths = []

    for i, t in enumerate(tracklist):
        title = t.get('title', f'Track {i+1}')
        dna = _extract_track_dna(t, proposal)

        cover_path = os.path.join(track_art_dir, f"{title}_cover.png")
        bg_backup = os.path.join(track_art_dir, f"{title}_cover_bg.png")

        if not os.path.exists(bg_backup) or force_regen_all:
            send_message(f"🖌️ [{(i+1)}/{len(tracklist)}] Upsampling visual for <b>{html.escape(title)}</b> with K3...")
            upsampled = upsample_image_prompt_k3(title, dna, subgenre=subgenre, is_album=False)
            raw_path = generate_artwork_venice(upsampled, f"{album_name}/{title}", state=state)
            if raw_path and os.path.exists(raw_path):
                shutil.copy2(raw_path, bg_backup)

        if os.path.exists(bg_backup):
            if os.path.exists(OVERLAY_TITLE_SCRIPT):
                styled_title = stylize_title(title)
                subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                                "--image", bg_backup, "--title", styled_title, "--stacked", "--bottom", "--auto-color", "--opacity", "0.68", "--output", cover_path], capture_output=True)
            else:
                shutil.copy2(bg_backup, cover_path)

            jpg_cov = os.path.splitext(cover_path)[0] + '.jpg'
            try:
                from PIL import Image
                with Image.open(cover_path) as im:
                    im.convert('RGB').save(jpg_cov, 'JPEG', quality=95)
            except Exception:
                pass

            track_btn = [
                [
                    {"text": f"🔄 Regen {title}", "callback_data": f"ap:art:redo:{i+1}"},
                    {"text": f"✏️ Edit {title}", "callback_data": f"ap:art:edit:{i+1}"}
                ],
                [
                    {"text": "🌑 Darker", "callback_data": f"ap:art:quickedit:{i+1}:darker"},
                    {"text": "🌫️ Mist", "callback_data": f"ap:art:quickedit:{i+1}:mist"},
                    {"text": "🗡️ Katana", "callback_data": f"ap:art:quickedit:{i+1}:katana"}
                ]
            ]
            send_file = jpg_cov if os.path.exists(jpg_cov) else cover_path
            send_photo(send_file, caption=f"🎨 Track {i+1}: <b>{html.escape(title)}</b>", reply_markup={"inline_keyboard": track_btn})
            track_cover_paths.append(cover_path)

    buttons = [
        [{"text": "✅ Approve All Covers", "callback_data": "ap:trackcovers:approve"}],
        [{"text": "🔄 Regenerate All", "callback_data": "ap:trackcovers:regenall"}]
    ]
    send_message("👆 <b>Review all track covers above:</b>\nTap any track's button to edit or regenerate, or Approve All to finalize:", reply_markup={"inline_keyboard": buttons})

    while True:
        flag, content = poll_flags()
        if flag == "trackcovers_approved":
            album_slug = album_name.lower().replace(' ', '-').replace('_', '-')
            send_message(f"⬆️ <b>Upscaling all {len(track_cover_paths)} track covers to 3000×3000 & generating per-song waveform banners...</b>")
            for i, cp in enumerate(track_cover_paths):
                track_title = os.path.basename(cp).replace('_cover.png', '').replace('_cover.jpg', '')
                bg_path = os.path.join(track_art_dir, f"{track_title}_cover_bg.png")
                send_message(f"⚙️ [{(i+1)}/{len(track_cover_paths)}] Upscaling & generating waveform for <b>{html.escape(track_title)}</b>...")
                if os.path.exists(bg_path):
                    upscale_artwork_venice(bg_path)
                    # Generate clean panoramic waveform banner from un-captioned background
                    wave_res = generate_waveform_banner(bg_path, track_title, [track_art_dir, "/opt/data/music/artwork/waveforms"], track_num=i+1, album_slug=album_slug, force=True)
                    if os.path.exists(OVERLAY_TITLE_SCRIPT):
                        styled_title = stylize_title(track_title)
                        subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                                        "--image", bg_path, "--title", styled_title, "--stacked", "--bottom", "--auto-color", "--opacity", "0.68", "--output", cp], capture_output=True)
                else:
                    upscale_artwork_venice(cp)
                    wave_res = generate_waveform_banner(cp, track_title, [track_art_dir, "/opt/data/music/artwork/waveforms"], track_num=i+1, album_slug=album_slug, force=True)
                if isinstance(wave_res, str) and os.path.exists(wave_res):
                    send_photo(wave_res, caption=f"🌊 Track {i+1} Waveform: <b>{html.escape(track_title)}</b> (1240×400)")
                if state:
                    add_cost(state, "cover_upscale", VENICE_UPSCALE_COST)
                jpg_cp = os.path.splitext(cp)[0] + '.jpg'
                try:
                    from PIL import Image
                    with Image.open(cp) as im:
                        im.convert('RGB').save(jpg_cp, 'JPEG', quality=95)
                except Exception:
                    pass
            send_message("✅ <b>All track covers upscaled & per-song waveform banners generated!</b> Assembling final release package for your review & confirmation...")
            return "approved"
        elif flag == "trackcovers_regenall":
            send_message("🔄 <b>Regenerating all track covers...</b>")
            phase_5_track_covers._force_regen = True
            if state:
                add_cost(state, "cover_regeneration", VENICE_IMAGE_GEN_COST * len(tracklist))
                costs = init_cost_tracker(state)
                costs["cover_regen_count"] = costs.get("cover_regen_count", 0) + len(tracklist)
                save_state(state)
            return phase_5_track_covers(proposal, tracklist, state=state, dashboard=dashboard)
        elif flag and flag.startswith("art_redo_"):
            try:
                track_num = int(flag.split("_")[-1])
                idx = track_num - 1
                if 0 <= idx < len(tracklist):
                    t = tracklist[idx]
                    title = t.get('title', f'Track {track_num}')
                    send_message(f"🔄 <b>Regenerating cover for Track {track_num}: {html.escape(title)}...</b>")
                    dna = _extract_track_dna(t, proposal)
                    upsampled = upsample_image_prompt_k3(title, dna, subgenre=subgenre, is_album=False)
                    cover_path = os.path.join(track_art_dir, f"{title}_cover.png")
                    bg_path = os.path.join(track_art_dir, f"{title}_cover_bg.png")
                    raw = generate_artwork_venice(upsampled, f"{album_name}/{title}", state=state)
                    if raw and os.path.exists(raw):
                        shutil.copy2(raw, bg_path)
                        if os.path.exists(OVERLAY_TITLE_SCRIPT):
                            styled_title = stylize_title(title)
                            subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                                            "--image", bg_path, "--title", styled_title, "--stacked", "--bottom", "--auto-color", "--opacity", "0.68", "--output", cover_path], capture_output=True)
                        else:
                            shutil.copy2(bg_path, cover_path)
                        track_btn = [
                            [
                                {"text": f"🔄 Regen {title}", "callback_data": f"ap:art:redo:{track_num}"},
                                {"text": f"✏️ Edit {title}", "callback_data": f"ap:art:edit:{track_num}"}
                            ],
                            [
                                {"text": "🌑 Darker", "callback_data": f"ap:art:quickedit:{track_num}:darker"},
                                {"text": "🌫️ Mist", "callback_data": f"ap:art:quickedit:{track_num}:mist"},
                                {"text": "🗡️ Katana", "callback_data": f"ap:art:quickedit:{track_num}:katana"}
                            ]
                        ]
                        send_photo(cover_path, caption=f"🎨 Track {track_num}: <b>{html.escape(title)}</b> (Regenerated)", reply_markup={"inline_keyboard": track_btn})
            except Exception as e:
                logger.error(f"Error redoing track cover: {e}")
        elif flag and flag.startswith("art_edit_"):
            try:
                track_num = int(flag.split("_")[-1])
                idx = track_num - 1
                if 0 <= idx < len(tracklist):
                    t = tracklist[idx]
                    title = t.get('title', f'Track {track_num}')
                    edit_directive = content if content else "deepen shadows, cinematic chiaroscuro, moody atmosphere"
                    send_message(f"✏️ <b>Modifying Track {track_num} ({html.escape(title)}):</b> <i>{html.escape(edit_directive)}</i>\nRunning Venice AI vision edit inference...")
                    cover_path = os.path.join(track_art_dir, f"{title}_cover.png")
                    bg_path = os.path.join(track_art_dir, f"{title}_cover_bg.png")
                    if not os.path.exists(bg_path) and os.path.exists(cover_path):
                        shutil.copy2(cover_path, bg_path)

                    if os.path.exists(bg_path):
                        edit_artwork_venice(bg_path, edit_directive, bg_path, state=state)
                        if os.path.exists(OVERLAY_TITLE_SCRIPT):
                            styled_title = stylize_title(title)
                            subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                                            "--image", bg_path, "--title", styled_title, "--stacked", "--bottom", "--auto-color", "--opacity", "0.68", "--output", cover_path], capture_output=True)
                        else:
                            shutil.copy2(bg_path, cover_path)
                        track_btn = [
                            [
                                {"text": f"🔄 Regen {title}", "callback_data": f"ap:art:redo:{track_num}"},
                                {"text": f"✏️ Edit {title}", "callback_data": f"ap:art:edit:{track_num}"}
                            ],
                            [
                                {"text": "🌑 Darker", "callback_data": f"ap:art:quickedit:{track_num}:darker"},
                                {"text": "🌫️ Mist", "callback_data": f"ap:art:quickedit:{track_num}:mist"},
                                {"text": "🗡️ Katana", "callback_data": f"ap:art:quickedit:{track_num}:katana"}
                            ]
                        ]
                        send_photo(cover_path, caption=f"🎨 Track {track_num}: <b>{html.escape(title)}</b> (Edited: <i>{html.escape(edit_directive)}</i>)", reply_markup={"inline_keyboard": track_btn})
            except Exception as e:
                logger.error(f"Error editing track cover: {e}")


def assemble_release(proposal, tracklist, album_slug):
    """
    Assemble canonical release directory at /opt/data/music/releases/{album_slug}
    - Copies master FLAC files (no MP3 duplicates)
    - Exactly ONE cover per track + ONE album cover in covers/
    - Writes release.json, tracks_meta.json, and m3u8 playlist
    - Embeds artwork and tags directly into FLAC masters via tag_metadata.py
    """
    release_dir = os.path.join(RELEASES_BASE, album_slug)
    covers_dir = os.path.join(release_dir, "covers")
    os.makedirs(covers_dir, exist_ok=True)

    # 1. FLAC files
    flac_files = []
    tracks_meta = []
    tracks = []

    # Sanitize and guarantee clean, non-generic track titles
    prop_tracks = proposal.get("tracks", [])
    for idx, t in enumerate(tracklist):
        t_title = str(t.get("title", "")).strip()
        if not t_title or t_title.lower().startswith("track ") or t_title in ("?", "Unknown"):
            if idx < len(prop_tracks) and prop_tracks[idx] and not str(prop_tracks[idx]).lower().startswith("track "):
                t["title"] = str(prop_tracks[idx]).strip().upper()
            else:
                t["title"] = f"PHANTOM SEQUENCE {idx+1}"
            logger.info(f"Sanitized generic track title {idx+1} -> {t['title']}")

    for idx, t in enumerate(tracklist, 1):
        title = t.get("title", f"Track {idx}")
        clean_title = title.replace(" ", "_")
        prefix = f"{idx:02d}_{clean_title}_MASTER"
        pdir = t.get("production_dir")

        dest_flac = os.path.join(release_dir, f"{prefix}.flac")
        master_src = t.get("master_path")
        if master_src and os.path.exists(master_src):
            shutil.copy2(master_src, dest_flac)
            flac_files.append(os.path.basename(dest_flac))
        elif pdir and os.path.exists(pdir):
            cands = glob.glob(os.path.join(pdir, "master_*.flac")) or glob.glob(os.path.join(pdir, "*.flac"))
            if cands:
                shutil.copy2(cands[0], dest_flac)
                flac_files.append(os.path.basename(dest_flac))
        elif os.path.exists(dest_flac):
            flac_files.append(os.path.basename(dest_flac))

        tracks.append(title)
        tracks_meta.append({
            "title": title,
            "bpm": t.get("bpm", 120),
            "key": t.get("key", "Cm"),
            "genre": t.get("genre", proposal.get("subgenre", "Dark Nightride Trap"))
        })

    # 2. Cover art - exactly 1 image per song + 1 album cover (no extra loose files)
    art_dir = get_album_artwork_dir(proposal.get("album", album_slug))
    # Album cover
    alb_cov = None
    if os.path.exists(art_dir):
        for ext in [".jpg", ".png"]:
            c = os.path.join(art_dir, f"album_cover{ext}")
            if os.path.exists(c):
                alb_cov = c
                break
    if alb_cov:
        ext = os.path.splitext(alb_cov)[1]
        shutil.copy2(alb_cov, os.path.join(covers_dir, f"album_cover{ext}"))

    for idx, t in enumerate(tracklist, 1):
        title = t.get("title", f"Track {idx}")
        clean_title = title.replace(" ", "_")
        chosen = None
        if os.path.exists(art_dir):
            for ext in [".jpg", ".png"]:
                cands = [
                    os.path.join(art_dir, f"{title}_cover{ext}"),
                    os.path.join(art_dir, f"{clean_title}_cover{ext}"),
                    os.path.join(art_dir, f"Track {idx}_cover{ext}"),
                    os.path.join(art_dir, f"Track_{idx}_cover{ext}"),
                    os.path.join(art_dir, f"{title}{ext}"),
                    os.path.join(art_dir, f"{clean_title}{ext}"),
                ]
                for c in cands:
                    if os.path.exists(c):
                        chosen = c
                        break
                if chosen:
                    break
        if chosen:
            ext = os.path.splitext(chosen)[1]
            dest_cov = os.path.join(covers_dir, f"{idx:02d}_{clean_title}{ext}")
            shutil.copy2(chosen, dest_cov)
            if ("Track " in os.path.basename(chosen) or "Track_" in os.path.basename(chosen)) and os.path.exists(OVERLAY_TITLE_SCRIPT):
                try:
                    bg_cand = chosen.replace(f'_cover{ext}', f'_cover_bg{ext}')
                    bg_img = bg_cand if os.path.exists(bg_cand) else dest_cov
                    styled_title = stylize_title(title)
                    subprocess.run([
                        "/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                        "--image", bg_img, "--title", styled_title, "--stacked", "--bottom", "--auto-color", "--opacity", "0.68", "--output", dest_cov
                    ], capture_output=True, timeout=30)
                except Exception as oe:
                    logger.warning(f"Re-overlay title error on {dest_cov}: {oe}")

    # 2b. Waveform banners - ensure dedicated waveforms/ folder across all canonical directories
    music_root = "/opt/data/music" if os.path.exists("/opt/data/music") else "D:/music"
    master_waves_dir = os.path.join(music_root, "artwork", "waveforms")
    master_waves_sub = os.path.join(master_waves_dir, album_slug)
    art_waves_dir = os.path.join(art_dir, "waveforms")
    art_albums_dir = os.path.join(music_root, "artwork", "albums", album_slug)
    art_albums_waves_dir = os.path.join(art_albums_dir, "waveforms")
    export_dir = os.path.join(music_root, "exports", album_slug)
    export_waves_dir = os.path.join(export_dir, "waveforms")
    export_covers_dir = os.path.join(export_dir, "covers")
    release_waves_dir = os.path.join(release_dir, "waveforms")

    for d in [master_waves_dir, master_waves_sub, art_waves_dir, art_albums_dir, art_albums_waves_dir, export_dir, export_waves_dir, export_covers_dir, release_waves_dir]:
        os.makedirs(d, exist_ok=True)

    # Also sync covers to artwork/albums/{album_slug} and exports/{album_slug}/covers
    for cf in os.listdir(covers_dir):
        src_cf = os.path.join(covers_dir, cf)
        if os.path.isfile(src_cf):
            for dst_d in [art_albums_dir, export_covers_dir]:
                try:
                    shutil.copy2(src_cf, os.path.join(dst_d, cf))
                except Exception:
                    pass

    clean_alb_name = sanitize_filename(proposal.get("album", album_slug))
    alb_wave_found = None
    alb_wave_cands = [
        os.path.join(release_waves_dir, "album_waveform.png"),
        os.path.join(release_waves_dir, f"{clean_alb_name}_waveform.png"),
        os.path.join(covers_dir, "album_waveform.png"),
        os.path.join(covers_dir, f"{clean_alb_name}_waveform.png"),
        os.path.join(art_dir, "album_waveform.png"),
        os.path.join(art_dir, f"{clean_alb_name}_waveform.png"),
        os.path.join(art_waves_dir, f"{clean_alb_name}_waveform.png"),
        os.path.join(master_waves_dir, f"{clean_alb_name}_waveform.png"),
    ]
    for awc in alb_wave_cands:
        if os.path.exists(awc) and os.path.getsize(awc) > 1000:
            alb_wave_found = awc
            break

    if not alb_wave_found:
        alb_bg_cands = [
            os.path.join(art_dir, "album_cover_bg.png"),
            os.path.join(art_dir, f"{clean_alb_name}_bg.png"),
            os.path.join(art_dir, f"{album_slug}_bg.png"),
            os.path.join(covers_dir, "album_cover.png"),
            os.path.join(release_dir, "cover.png"),
            os.path.join(release_dir, "cover.jpg"),
        ]
        alb_bg = next((c for c in alb_bg_cands if os.path.exists(c)), None)
        if alb_bg:
            logger.info(f"Generating missing album waveform banner for {clean_alb_name}...")
            generate_waveform_banner(alb_bg, clean_alb_name, [release_waves_dir, covers_dir, master_waves_dir, art_dir], track_num=None, album_slug=album_slug)
            alb_wave_found = os.path.join(release_waves_dir, f"{clean_alb_name}_waveform.png")

    if alb_wave_found and os.path.exists(alb_wave_found):
        for dst_dir in [release_waves_dir, covers_dir, art_dir, art_waves_dir, art_albums_dir, art_albums_waves_dir, master_waves_sub, export_waves_dir]:
            for fn in ["album_waveform.png", f"{clean_alb_name}_waveform.png"]:
                dst = os.path.join(dst_dir, fn)
                if os.path.abspath(alb_wave_found) != os.path.abspath(dst):
                    try: shutil.copy2(alb_wave_found, dst)
                    except Exception: pass
        master_alb_dst = os.path.join(master_waves_dir, f"{clean_alb_name}_waveform.png")
        if os.path.abspath(alb_wave_found) != os.path.abspath(master_alb_dst):
            try: shutil.copy2(alb_wave_found, master_alb_dst)
            except Exception: pass

    for idx, t in enumerate(tracklist, 1):
        title = t.get("title", f"Track {idx}")
        clean_title = sanitize_filename(title)
        tr_wave_found = None
        tr_wave_cands = [
            os.path.join(release_waves_dir, f"{idx:02d}_{clean_title}_waveform.png"),
            os.path.join(release_waves_dir, f"{clean_title}_waveform.png"),
            os.path.join(covers_dir, f"{idx:02d}_{clean_title}_waveform.png"),
            os.path.join(covers_dir, f"{clean_title}_waveform.png"),
            os.path.join(art_dir, f"{idx:02d}_{clean_title}_waveform.png"),
            os.path.join(art_dir, f"{clean_title}_waveform.png"),
            os.path.join(art_waves_dir, f"{idx:02d}_{clean_title}_waveform.png"),
            os.path.join(art_waves_dir, f"{clean_title}_waveform.png"),
            os.path.join(master_waves_dir, f"{idx:02d}_{clean_title}_waveform.png"),
            os.path.join(master_waves_dir, f"{clean_title}_waveform.png"),
        ]
        for twc in tr_wave_cands:
            if os.path.exists(twc) and os.path.getsize(twc) > 1000:
                tr_wave_found = twc
                break

        if not tr_wave_found:
            tr_bg_cands = [
                os.path.join(art_dir, f"{title}_cover_bg.png"),
                os.path.join(art_dir, f"{clean_title}_cover_bg.png"),
                os.path.join(art_dir, f"OS_{idx:02d}_{title.lower().replace(' ', '_')}_bg.png"),
                os.path.join(art_dir, f"{clean_title}_bg.png"),
                os.path.join(covers_dir, f"{idx:02d}_{clean_title}_cover.png"),
                os.path.join(covers_dir, f"{idx:02d}_{clean_title}.png"),
                os.path.join(covers_dir, f"{idx:02d}_{clean_title}.jpg"),
            ]
            tr_bg = next((c for c in tr_bg_cands if os.path.exists(c)), None)
            if tr_bg:
                logger.info(f"Generating missing waveform banner for track {idx} ({title})...")
                generate_waveform_banner(tr_bg, clean_title, [release_waves_dir, covers_dir, master_waves_dir, art_dir], track_num=idx, album_slug=album_slug)
                tr_wave_found = os.path.join(release_waves_dir, f"{clean_title}_waveform.png")

        if tr_wave_found and os.path.exists(tr_wave_found):
            for dst_dir in [release_waves_dir, covers_dir, art_dir, art_waves_dir, art_albums_dir, art_albums_waves_dir, master_waves_sub, export_waves_dir, master_waves_dir]:
                for fn in [f"{idx:02d}_{clean_title}_waveform.png", f"{clean_title}_waveform.png"]:
                    dst = os.path.join(dst_dir, fn)
                    if os.path.abspath(tr_wave_found) != os.path.abspath(dst):
                        try: shutil.copy2(tr_wave_found, dst)
                        except Exception: pass

    # Clean any unwanted files from release_dir (ensure no MP3s and no loose images in root)
    for f in os.listdir(release_dir):
        fp = os.path.join(release_dir, f)
        if os.path.isfile(fp):
            if f.endswith(".mp3") or f.endswith(".jpg") or f.endswith(".png"):
                try: os.remove(fp)
                except Exception: pass

    # 3. Write release.json & tracks_meta.json
    release_manifest = {
        "album": proposal.get("album", album_slug.upper()).replace("-", " "),
        "promoted_from": album_slug,
        "promoted_at": datetime.now().isoformat(),
        "track_count": len(flac_files),
        "tracks": tracks,
        "status": "release-ready",
        "windows_path": f"D:\\music\\releases\\{album_slug}",
        "source": "master-producer",
        "genre": proposal.get("subgenre", "Dark Nightride Trap")
    }
    with open(os.path.join(release_dir, "release.json"), "w", encoding="utf-8") as f:
        json.dump(release_manifest, f, indent=2)

    with open(os.path.join(release_dir, "tracks_meta.json"), "w", encoding="utf-8") as f:
        json.dump(tracks_meta, f, indent=2)

    # 4. Write playlist in release_dir and sync FLACs + playlist to exports/{album_slug}
    album_display = proposal.get("album", album_slug.upper()).replace("-", " ")
    with open(os.path.join(release_dir, f"{album_slug}_playlist.m3u8"), "w", encoding="utf-8") as pf:
        pf.write("#EXTM3U\n")
        pf.write(f"#PLAYLIST:{album_display} (VØIDRIDE Studio Masters)\n")
        for idx, title in enumerate(tracks, 1):
            clean_title = title.replace(" ", "_")
            pf.write(f"#EXTINF:-1,VØIDRIDE - {title}\n")
            pf.write(f"D:\\music\\releases\\{album_slug}\\{idx:02d}_{clean_title}_MASTER.flac\n")

    # 5. Tag metadata & embed artwork directly into FLACs
    tag_script = "/opt/data/skills/delivery-receipt/scripts/tag_metadata.py"
    if os.path.exists(tag_script):
        try:
            logger.info(f"Tagging metadata & embedding artwork into FLACs for release: {album_slug}")
            subprocess.run(["/opt/hermes/.venv/bin/python3", tag_script, "--release", album_slug], capture_output=True, text=True, timeout=120)
        except Exception as e:
            logger.error(f"tag_metadata failed: {e}")

    # 5b. Sync tagged FLACs and playlist into /opt/data/music/exports/{album_slug}
    try:
        for fn in flac_files:
            src_f = os.path.join(release_dir, fn)
            dst_f = os.path.join(export_dir, fn)
            if os.path.exists(src_f):
                shutil.copy2(src_f, dst_f)
        with open(os.path.join(export_dir, f"{album_slug}_playlist.m3u8"), "w", encoding="utf-8") as epf:
            epf.write("#EXTM3U\n")
            epf.write(f"#PLAYLIST:{album_display} (VØIDRIDE Studio Masters)\n")
            for idx, title in enumerate(tracks, 1):
                clean_title = title.replace(" ", "_")
                epf.write(f"#EXTINF:-1,VØIDRIDE - {title}\n")
                epf.write(f"D:\\music\\exports\\{album_slug}\\{idx:02d}_{clean_title}_MASTER.flac\n")
    except Exception as se:
        logger.warning(f"Export sync warning: {se}")

    return release_dir


# ── Phase 6: Final Review Gate & Deliverables ───────────────────────────
def phase_6_final_review(proposal, tracklist=None, state=None, dashboard=None):
    if dashboard:
        dashboard.set_phase(6)
    album_name = proposal.get('album', 'release')
    album_slug = album_name.lower().replace(' ', '-')
    album_release_dir = f"/opt/data/music/releases/{album_slug}"

    already_packaged = bool(
        state and state.get("phase_6_package_sent")
        and os.path.exists(os.path.join(album_release_dir, "release.json"))
    )

    if not already_packaged:
        # 1. Canonical assembly: embed FLAC covers & keep strictly 1 image per song + album cover
        assemble_release(proposal, tracklist or [], album_slug)

        # 2. Generate Windows review playlist & receipt
        try:
            playlist_script = "/opt/data/skills/delivery-receipt/scripts/send_windows_playlist.py"
            receipt_script = "/opt/data/skills/delivery-receipt/scripts/deliver_receipt.py"
            if os.path.exists(playlist_script):
                subprocess.run(["/opt/hermes/.venv/bin/python3", playlist_script, "--release", album_slug], capture_output=True, text=True, timeout=120)
            if os.path.exists(receipt_script):
                subprocess.run(["/opt/hermes/.venv/bin/python3", receipt_script, "--release", album_slug], capture_output=True, text=True, timeout=120)
        except Exception as e:
            logger.error(f"Playlist/receipt generation error: {e}")

        # 3. Share album directory via Cloudflare tunnel & local service
        ext_link = None
        int_link = None
        win_release_folder = f"D:\\music\\releases\\{album_slug}"
        win_playlist_path = f"{win_release_folder}\\{album_slug}_playlist.m3u8"
        if os.path.exists(album_release_dir):
            try:
                share_res = subprocess.run(["/opt/hermes/.venv/bin/python3", SHARE_SCRIPT, "--path", album_release_dir], capture_output=True, text=True, timeout=180)
                for line in share_res.stdout.splitlines():
                    if "[EXTERNAL LINK]" in line:
                        ext_link = line.split("[EXTERNAL LINK]")[-1].strip()
                    elif "[INTERNAL LINK]" in line:
                        int_link = line.split("[INTERNAL LINK]")[-1].strip()
            except Exception as e:
                logger.error(f"Packaging error: {e}")

        # 3b. Deliver all reference masters together for inline preview if available
        for t in (tracklist or []):
            track_num = t.get('track', '?')
            title = t.get('title', f"Track {track_num}")
            bpm = t.get('bpm', proposal.get('bpm', '?') if proposal else '?')
            key = t.get('key', proposal.get('key', '?') if proposal else '?')
            mp3 = t.get('master_mp3') or t.get('mp3_path')
            if mp3 and os.path.exists(mp3):
                send_audio(mp3, caption=f"🎵 [{track_num}/{len(tracklist)}] {title} (Mastered · {bpm} BPM · {key})")

        # 4. Build prompt message with download links & interactive buttons
        final_buttons = [
            [{"text": "🚀 Confirm: Good to Proceed to SoundCloud", "callback_data": "ap:final:publish"}],
            [
                {"text": "🎵 Edit Songs", "callback_data": "ap:final:edit_songs"},
                {"text": "🎨 Edit Album Art", "callback_data": "ap:final:edit_album"}
            ],
            [
                {"text": "🖼️ Edit Track Covers", "callback_data": "ap:final:edit_covers"},
                {"text": "❌ Keep on Hold / Cancel", "callback_data": "ap:final:cancel"}
            ]
        ]

        msg = (
            f"📦 <b>{html.escape(album_name)} — Final Release Package Submitted!</b>\n\n"
            f"✨ Lossless 24-bit/48kHz FLAC studio masters (artwork embedded into files).\n"
            f"🖼️ Exactly 1 cover per track + album cover + per-song waveform banners.\n\n"
        )
        if ext_link:
            msg += f"🌐 <b>External Download (Cloudflare / Mobile):</b>\n🔗 <a href='{ext_link}'>{ext_link}</a>\n\n"
        if int_link:
            msg += f"🏠 <b>Internal Download (Tailscale / LAN):</b>\n🔗 <a href='{int_link}'>{int_link}</a>\n\n"
        msg += f"📁 <b>Windows Local Folder:</b>\n<code>{html.escape(win_release_folder)}</code>\n"
        msg += f"🎶 <b>Windows VLC Playlist:</b>\n<code>{html.escape(win_playlist_path)}</code>\n\n"
        msg += (
            "<b>Please review all reference masters and artwork above.</b>\n"
            "👉 <i>When you are ready, tap <b>Confirm: Good to Proceed to SoundCloud</b> to push live:</i>"
        )

        send_message(msg, reply_markup={"inline_keyboard": final_buttons})
        if state is not None:
            state["phase_6_package_sent"] = True
            save_state(state)
        logger.info("Sent final review package & publishing gate to Telegram. Polling for decisions...")
    else:
        logger.info(f"Phase 6 package already sent for {album_name}; skipping duplicate MP3/archive delivery.")

    # 5. Poll for user decision (or immediately execute if final_publish was already confirmed before a retry)
    auto_publish = bool(state and state.get("phase_6_publish_confirmed"))
    while True:
        if auto_publish:
            flag, content = "final_publish", "publish"
            auto_publish = False
        else:
            flag, content = poll_flags()
        if flag == "final_publish":
            if state is not None:
                state["phase_6_publish_confirmed"] = True
                save_state(state)
            logger.info("User confirmed publish. Pushing to SoundCloud...")
            send_message(f"🚀 <b>Publishing {html.escape(album_name)} to SoundCloud...</b>\n<i>Uploading 24-bit studio FLAC masters and synchronized covers. Live progress will be reported below.</i>")
            cmd = ["/opt/hermes/.venv/bin/python3", PUBLISH_SCRIPT, "--release", album_slug, "--confirm", "--force"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            if res.returncode == 0:
                logger.info(f"Published {album_name} to SoundCloud successfully.")
                send_agent_notification(f"Published {album_name} to SoundCloud")
                return "published"
            else:
                err_text = res.stderr or res.stdout or "Unknown publishing failure"
                send_message(f"❌ SoundCloud upload failed:\n<pre>{html.escape(err_text[:300])}</pre>")
                if logger_hub:
                    logger_hub.log_failure("PUBLISH_FAIL", err_text, album=album_name, phase=6)
                remediation_buttons = [
                    [{"text": "🔄 Retry Publish", "callback_data": "ap:final:publish"}],
                    [{"text": "🎵 Redo Songs", "callback_data": "ap:final:edit_songs"}],
                    [{"text": "❌ Cancel", "callback_data": "ap:final:cancel"}],
                ]
                send_message("SoundCloud publishing did not complete successfully. Please choose an option:",
                             reply_markup={"inline_keyboard": remediation_buttons})
                continue
        elif flag == "final_edit_songs":
            if state is not None:
                state["phase_6_package_sent"] = False
                state["phase_6_publish_confirmed"] = False
                save_state(state)
            return "edit_songs"
        elif flag == "final_edit_album":
            if state is not None:
                state["phase_6_package_sent"] = False
                state["phase_6_publish_confirmed"] = False
                save_state(state)
            return "edit_album"
        elif flag == "final_edit_covers":
            if state is not None:
                state["phase_6_package_sent"] = False
                state["phase_6_publish_confirmed"] = False
                save_state(state)
            return "edit_covers"
        elif flag == "final_cancel":
            return "cancelled"


def run_test_mode(proposal_index):
    print(f"--- PIPELINE TEST MODE (Proposal Index: {proposal_index}) ---")
    try:
        with open(PROPOSALS_FILE, 'r') as f:
            raw = json.load(f)
            proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
            if proposal_index >= len(proposals):
                print(f"❌ Invalid index {proposal_index}. Only {len(proposals)} proposals available.")
                return
            proposal = proposals[proposal_index]
            print(f"✅ Successfully loaded Proposal [{proposal_index}]: {proposal.get('album')}")
            print(f"   Subgenre: {proposal.get('subgenre')}")
            print(f"   BPM/Key: {proposal.get('bpm')} / {proposal.get('key')}")
            print("--- TEST PASSED: 0-based boundary verified cleanly ---")
    except Exception as e:
        print(f"❌ Test error: {e}")


def main():
    parser = argparse.ArgumentParser(description="VØIDRIDE Album Production Pipeline")
    parser.add_argument("--proposal-index", type=int, default=0, help="0-based index of proposal")
    parser.add_argument("--mode", default="full", choices=["full", "sample"])
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true", help="Force acquire lock by terminating any existing pipeline")
    parser.add_argument("--redo-tracks", default=None, help="Comma-separated 1-based track numbers to redo immediately (e.g. '1,5')")
    parser.add_argument("--redo-feedback", default=None, help="Feedback direction to apply when redoing tracks")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        run_test_mode(args.proposal_index)
        return

    clear_flags()
    state = load_state()
    mode = args.mode
    duration = args.duration if args.duration else (20 if mode == "sample" else 220)

    if args.resume and state.get("proposal"):
        proposal = state["proposal"]
        mode = state.get("mode", mode)
        duration = state.get("duration", duration)
        profile = {}
        if os.path.exists(PROFILE_FILE):
            try:
                with open(PROFILE_FILE) as pf:
                    profile = json.load(pf)
            except Exception: pass
        current_phase = state.get("phase", 1)
        tracklist = state.get("completed_tracks") or state.get("tracklist") or []
    else:
        # Starting a new album production — force lock acquisition and create clean fresh state
        args.force = True
        if not os.path.exists(PROPOSALS_FILE):
            logger.error(f"Proposals file not found: {PROPOSALS_FILE}")
            sys.exit(1)
        with open(PROPOSALS_FILE, 'r') as f:
            raw = json.load(f)
            proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
            if args.proposal_index >= len(proposals):
                logger.error(f"Proposal index {args.proposal_index} out of range (count: {len(proposals)})")
                send_message(f"❌ Error: Proposal index {args.proposal_index} out of range.")
                sys.exit(1)
            proposal = proposals[args.proposal_index]

        profile = {}
        if os.path.exists(PROFILE_FILE):
            try:
                with open(PROFILE_FILE) as pf:
                    profile = json.load(pf)
            except Exception: pass

        state = {
            "proposal": proposal,
            "mode": mode,
            "duration": duration,
            "phase": 1,
            "completed_tracks": [],
            "tracklist": [],
            "costs": {}
        }
        current_phase = 1
        tracklist = []
        if os.path.exists("/tmp/completed_tracks.json"):
            try: os.remove("/tmp/completed_tracks.json")
            except Exception: pass

    state["mode"] = mode
    state["duration"] = duration
    state["proposal"] = proposal

    redo_track, redo_feedback = None, None

    # ── Published Album Guard ──
    # If the album is already published on SoundCloud or in releases/, abort immediately,
    # clean up stale pipeline state, and do NOT send any messages or audio to Telegram.
    album_name = proposal.get("album", "")
    album_slug = album_name.lower().replace(" ", "-").replace("_", "-")
    release_candidates = [
        f"/opt/data/music/releases/{album_slug}/release.json",
        f"D:/music/releases/{album_slug}/release.json",
        f"/opt/data/music/albums/{album_slug}/release.json",
        f"D:/music/albums/{album_slug}/release.json"
    ]
    is_already_published = False
    for rpath in release_candidates:
        if os.path.exists(rpath):
            try:
                with open(rpath, "r", encoding="utf-8") as rf:
                    rj = json.load(rf)
                if rj.get("status") == "published" or rj.get("soundcloud", {}).get("track_ids"):
                    is_already_published = True
                    break
            except Exception:
                pass

    if is_already_published:
        logger.info(f"Album '{album_name}' is already published on SoundCloud ({album_slug}). Cleaning up stale pipeline state and exiting cleanly.")
        if os.path.exists(STATE_FILE):
            try:
                os.remove(STATE_FILE)
            except Exception:
                pass
        for st_f in ["/opt/data/music/pipeline_state.json", "D:/music/pipeline_state.json"]:
            if os.path.exists(st_f):
                try:
                    os.remove(st_f)
                except Exception:
                    pass
        clear_flags()
        sys.exit(0)

    acquire_lock(force=args.force)
    init_cost_tracker(state)

    # Auto-discover existing completed masters and artwork on disk only if state tracklist is incomplete
    if not (args.resume and len(tracklist) >= 5):
        disc_tracks, disc_phase, disc_art = discover_existing_album_production(proposal)
        if len(disc_tracks) >= 5:
            logger.info(f"Auto-discovery found {len(disc_tracks)} completed masters on disk for {proposal.get('album')}.")
            tracklist = disc_tracks
            state["completed_tracks"] = disc_tracks
            state["tracklist"] = disc_tracks
            if not (args.resume and state.get("phase")):
                current_phase = disc_phase
                state["phase"] = disc_phase
            else:
                current_phase = state.get("phase")
            logger.info(f"Pipeline phase set to [{current_phase}/6]")
            save_state(state)

    # Internal status tracker (dashboard messages disabled)
    dashboard = LiveStatusDashboard(
        album_name=proposal.get("album", "Unknown Album"),
        mode=mode,
        duration=duration,
        subgenre=proposal.get("subgenre", ""),
        total_tracks=5
    )

    # Immediate CLI multi-track redo before entering main loop
    if args.redo_tracks and tracklist:
        redo_nums = [int(x.strip()) for x in str(args.redo_tracks).split(",") if x.strip().isdigit()]
        if redo_nums:
            for rn in redo_nums:
                tracklist = phase_1_redo_single(
                    proposal, profile, tracklist, rn,
                    feedback=args.redo_feedback, duration=duration, dashboard=dashboard, state=state
                )
                state["tracklist"] = tracklist
                state["completed_tracks"] = tracklist
                save_state(state)
            current_phase = 2 if mode != "sample" else 3
            state["phase"] = current_phase
            save_state(state)

    try:
        while True:
            try:
                # Phase 1: Music Production
                if current_phase <= 1:
                    dashboard.set_phase(1)
                    state["phase"] = 1
                    save_state(state)
                    tracklist = phase_1_produce(proposal, profile, redo_track, redo_feedback, mode=mode, duration=duration, dashboard=dashboard, state=state)
                    state["tracklist"] = tracklist
                    state["phase"] = 2
                    save_state(state)
                    current_phase = 2

                # Phase 2: DAW Mastering (bypassed if mode == sample)
                if current_phase == 2:
                    if mode == "sample":
                        logger.info("Sample preview mode: bypassing DAW mastering.")
                        current_phase = 3
                    else:
                        dashboard.set_phase(2)
                        phase_2_daw_handoff(proposal, tracklist, mode=mode, dashboard=dashboard)
                        state["tracklist"] = tracklist
                        state["phase"] = 3
                        save_state(state)
                        current_phase = 3

                # Phase 3: Song Review
                if current_phase == 3:
                    dashboard.set_phase(3)
                    decision, payload = phase_3_song_review(tracklist, proposal=proposal, dashboard=dashboard)
                    if decision == "reject":
                        send_message(f"❌ Album remaking with direction: <i>{payload}</i>")
                        proposal['brief'] = proposal.get('brief', '') + f"\n[USER REVISION]: {payload}"
                        current_phase = 1
                        state["completed_tracks"] = []
                        save_state(state)
                        continue
                    elif decision == "redo_track":
                        t_num, fb = payload
                        tracklist = phase_1_redo_single(proposal, profile, tracklist, t_num, fb, duration=duration, dashboard=dashboard, state=state)
                        state["tracklist"] = tracklist
                        state["completed_tracks"] = tracklist
                        save_state(state)
                        current_phase = 2 if mode != "sample" else 3
                        continue
                    elif decision == "approved":
                        send_message("✅ All songs approved! Moving to album cover art.")
                        state["phase"] = 4
                        save_state(state)
                        current_phase = 4

                # Phase 4: Album Cover Art
                if current_phase == 4:
                    dashboard.set_phase(4)
                    art_decision = phase_4_album_cover(proposal, tracklist, state=state, dashboard=dashboard)
                    if art_decision == "approved":
                        state["phase"] = 5
                        save_state(state)
                        current_phase = 5
                    else:
                        continue

                # Phase 5: Track Cover Art
                if current_phase == 5:
                    dashboard.set_phase(5)
                    covers_decision = phase_5_track_covers(proposal, tracklist, state=state, dashboard=dashboard)
                    if covers_decision == "approved":
                        state["phase"] = 6
                        save_state(state)
                        current_phase = 6
                    else:
                        continue

                # Phase 6: Final Review & Publishing Gate
                if current_phase == 6:
                    dashboard.set_phase(6)
                    final_decision = phase_6_final_review(proposal, tracklist=tracklist, state=state, dashboard=dashboard)
                    if final_decision == "edit_songs":
                        send_message("🎵 <b>Returning to Phase 3: Song Review...</b>")
                        state["phase"] = 3
                        save_state(state)
                        current_phase = 3
                        continue
                    elif final_decision == "edit_album":
                        send_message("🎨 <b>Returning to Phase 4: Album Cover Art...</b>")
                        state["phase"] = 4
                        save_state(state)
                        current_phase = 4
                        continue
                    elif final_decision == "edit_covers":
                        send_message("🖼️ <b>Returning to Phase 5: Track Cover Art...</b>")
                        state["phase"] = 5
                        save_state(state)
                        current_phase = 5
                        continue
                    else:  # "published" or "cancelled"
                        cost_summary = format_cost_summary(state, proposal.get('album', 'Release'), proposal=proposal, tracklist=tracklist)
                        send_message(cost_summary)
                        if os.path.exists(STATE_FILE):
                            try: os.remove(STATE_FILE)
                            except Exception: pass
                        break
            except Exception as e:
                import traceback
                tb_str = traceback.format_exc()
                tb_frames = traceback.extract_tb(e.__traceback__)
                loc_str = ""
                if tb_frames:
                    last_f = tb_frames[-1]
                    loc_str = f" ({os.path.basename(last_f.filename)}:{last_f.lineno} in {last_f.name})"
                logger.error(f"Unhandled exception in pipeline phase {current_phase}: {e}\n{tb_str}")
                if logger_hub:
                    logger_hub.log_failure("UNHANDLED_EXCEPTION", f"{type(e).__name__}: {e}{loc_str}", traceback_str=tb_str, album=proposal.get('album', 'Unknown'), phase=current_phase)
                send_pipeline_error_card(
                    album_name=proposal.get('album', 'Unknown Album'),
                    phase_num=current_phase,
                    phase_name=dashboard.phase_names.get(current_phase, f"Phase {current_phase}"),
                    diag={
                        "category": "UNHANDLED_EXCEPTION",
                        "root_line": f"{type(e).__name__}: {e}{loc_str}",
                        "hint": "Unexpected Python exception in pipeline orchestrator. State saved for resume — tap Retry Now after fixing or to re-attempt.",
                    },
                    include_buttons=True,
                )
                recover_action = None
                while True:
                    flag, content = poll_flags(timeout_hours=6)
                    if flag in ("error:retry", "error_retry"):
                        if dashboard:
                            dashboard.clear_error()
                        recover_action = "retry"
                        break
                    elif flag in ("error:skip", "error_skip"):
                        if dashboard:
                            dashboard.clear_error()
                        recover_action = "skip"
                        break
                    elif flag in ("error:log", "error_log"):
                        send_message(f"📋 <b>Full Traceback ({html.escape(proposal.get('album', 'Album'))}):</b>\n<pre>{html.escape(tb_str[-1500:])}</pre>")
                        continue
                    elif flag in ("error:abort", "error_abort") or flag is None:
                        logger.info("Pipeline aborted or timed out at unhandled exception gate.")
                        recover_action = "abort"
                        break
                if recover_action == "retry":
                    continue
                elif recover_action == "skip" and current_phase < 6:
                    current_phase += 1
                    state["phase"] = current_phase
                    save_state(state)
                    continue
                else:
                    break
    finally:
        release_lock()
        clear_flags()

    logger.info("Pipeline execution complete.")


if __name__ == "__main__":
    main()
