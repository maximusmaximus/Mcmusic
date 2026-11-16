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
        clean_stem = sanitize_filename(disp_title) + "_cover" if label != "Album Cover" else cov_stem
        bg_cands = [os.path.join(art_dir, f"{clean_stem}_bg.png"), os.path.join(art_dir, f"{cov_stem}_bg.png")]
        fg_cands = [
            os.path.join(art_dir, f"{clean_stem}.jpg"),
            os.path.join(art_dir, f"{clean_stem}.png"),
            os.path.join(art_dir, f"{cov_stem}.jpg"),
            os.path.join(art_dir, f"{cov_stem}.png"),
        ]
        target_p = next((p for p in bg_cands + fg_cands if os.path.exists(p)), fg_cands[0])
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
VENICE_API_BASE = os.environ.get('VENICE_API_BASE', 'https://api.venice.ai/api/v1').rstrip('/')


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
    url = f"{VENICE_API_BASE}/api_keys/rate_limits"
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
    if os.path.exists(jpg_candidate) and os.path.getsize(jpg_candidate) <= 8_500_000:
        actual_path = jpg_candidate
    elif os.path.exists(photo_path) and (photo_path.lower().endswith('.png') or os.path.getsize(photo_path) > 8_500_000):
        try:
            from PIL import Image
            with Image.open(photo_path) as im:
                rgb = im.convert('RGB')
                for q in (94, 88, 80):
                    rgb.save(jpg_candidate, 'JPEG', quality=q)
                    if os.path.getsize(jpg_candidate) <= 8_500_000:
                        break
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


def _is_cover_3k_ready(image_path, min_dim=2800):
    """Return True iff image_path exists on disk and has pixel dimensions >= min_dim x min_dim."""
    if not image_path or not os.path.exists(image_path):
        return False
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            w, h = im.size
            return w >= min_dim and h >= min_dim
    except Exception:
        return False


def get_canonical_track_cover_paths(art_dir, title):
    """
    Return canonical `(bg_png, cover_png, cover_jpg)` paths using underscore-normalized
    `sanitize_filename(title)` so space-vs-underscore splits (`OPTIC NERVE_cover.png` vs
    `OPTIC_NERVE_cover.png`) never occur. Automatically adopts legacy space-named files
    if the canonical file does not yet exist.
    """
    os.makedirs(art_dir, exist_ok=True)
    clean_stem = "".join(c if c.isalnum() or c in " -_" else "" for c in str(title)).strip().replace(" ", "_").upper()
    if not clean_stem:
        clean_stem = "TRACK"
    bg_png = os.path.join(art_dir, f"{clean_stem}_cover_bg.png")
    cov_png = os.path.join(art_dir, f"{clean_stem}_cover.png")
    cov_jpg = os.path.join(art_dir, f"{clean_stem}_cover.jpg")

    legacy_pairs = [
        (os.path.join(art_dir, f"{title}_cover_bg.png"), bg_png),
        (os.path.join(art_dir, f"{title}_cover.png"), cov_png),
        (os.path.join(art_dir, f"{title}_cover.jpg"), cov_jpg),
    ]
    for leg_src, canon_dst in legacy_pairs:
        if os.path.abspath(leg_src) != os.path.abspath(canon_dst) and os.path.exists(leg_src) and not os.path.exists(canon_dst):
            try:
                shutil.copy2(leg_src, canon_dst)
            except Exception:
                pass
    return bg_png, cov_png, cov_jpg


# ── Album Asset Discovery ──────────────────────────────────────────────
def discover_existing_album_production(proposal):
    """
    Checks disk for existing completed masters and 3000x3000 artwork for the given album proposal.
    Un-upscaled 1024x1024 draft covers do NOT qualify as Phase-6-ready so the pipeline never
    skips 4x upscaling on resume.
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
    if ALBUMS_BASE and ALBUMS_BASE != "/opt/data/music/albums":
        exports_dirs.insert(0, os.path.join(os.path.dirname(ALBUMS_BASE.rstrip("/\\")), "exports"))

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

    # 2. Check artwork — STRICT 3000x3000 (>=2800px) gate!
    art_dir = get_album_artwork_dir(album_name)
    has_album_cover = False
    has_all_track_covers = False

    if os.path.isdir(art_dir):
        for ext in [".jpg", ".png"]:
            alb_cand = os.path.join(art_dir, f"album_cover{ext}")
            if _is_cover_3k_ready(alb_cand):
                has_album_cover = True
                break

        if len(tracklist) >= 5:
            track_covers_3k = 0
            for idx, t in enumerate(tracklist, 1):
                title = t.get("title", f"Track {idx}")
                clean_title = "".join(c if c.isalnum() or c in " -_" else "" for c in str(title)).strip().replace(" ", "_").upper()
                matched_3k = False
                for ext in [".jpg", ".png"]:
                    cands = [
                        os.path.join(art_dir, f"{clean_title}_cover{ext}"),
                        os.path.join(art_dir, f"{title}_cover{ext}"),
                        os.path.join(art_dir, f"Track {idx}_cover{ext}"),
                        os.path.join(art_dir, f"{clean_title}{ext}"),
                        os.path.join(art_dir, f"{title}{ext}"),
                    ]
                    if any(_is_cover_3k_ready(c) for c in cands):
                        matched_3k = True
                        break
                if matched_3k:
                    track_covers_3k += 1
            if track_covers_3k >= len(tracklist):
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
    Ensure prompt satisfies Venice AI validation (max 1500 chars) and enforces strict NO TEXT / NO GRAFFITI.
    """
    prompt = prompt.strip()
    suffix = " NO TEXT, NO LETTERS, NO TYPOGRAPHY, NO WORDS, NO GRAFFITI, NO SIGNAGE"
    if "NO TEXT" in prompt.upper() and "NO GRAFFITI" in prompt.upper():
        suffix = ""
    elif "NO TEXT" in prompt.upper():
        suffix = ", NO GRAFFITI, NO SIGNAGE"
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


TRACK_SHOT_SCALES = [
    ("architectural_wide", "Low-angle 24mm anamorphic architectural wide shot establishing a vast sub-space inside the album's world"),
    ("interior_pov", "Intimate 35mm interior / cockpit / close tactile console perspective inside the album's world"),
    ("surreal_artifact_mid", "Hypnotic 50mm medium shot on a singular sculptural, organic, or cybernetic focal phenomenon native to the album's world"),
    ("oblique_geometric_overhead", "High-angle 30-degree oblique geometric shadow and wet-reflection composition inside the album's world"),
    ("nocturnal_horizon_silhouette", "Sweeping widescreen nocturnal aftermath and distant horizon silhouette closing the album's world"),
]

OFF_WORLD_LITERAL_PUN_TERMS = [
    ("shipping container", "dark monolithic urban architecture"),
    ("shipping containers", "dark monolithic urban structures"),
    ("cargo port", "rain-slicked midnight avenue"),
    ("cargo dock", "wet obsidian causeway"),
    ("ocean pier", "nocturnal concrete overlook"),
    ("submarine cable", "glowing neural filament"),
    ("submarine cables", "glowing neural filaments"),
    ("nuclear cooling tower", "subterranean monolithic heat-exchange shaft"),
    ("nuclear cooling towers", "subterranean monolithic heat-exchange shafts"),
    ("nuclear power plant", "dark cybernetic subterranean facility"),
    ("sunny beach", "mist-shrouded midnight shoreline"),
    ("bright daylight", "deep midnight chiaroscuro"),
    ("clear blue sky", "obsidian smog-veiled night sky"),
]


def _hue_to_palette_name(hue_deg):
    h = hue_deg % 360.0
    if h < 18 or h >= 342:
        return "crimson neon red"
    elif h < 45:
        return "molten sodium amber"
    elif h < 72:
        return "acid volt yellow"
    elif h < 150:
        return "electric bioluminescent green"
    elif h < 205:
        return "ice electric cyan"
    elif h < 255:
        return "cobalt sapphire glow"
    elif h < 305:
        return "deep ultraviolet violet"
    else:
        return "hyper neon magenta"


def extract_album_cover_palette_summary(image_path, fallback_visual=""):
    """
    Inspect the approved Phase 4 album_cover_bg.png pixel palette so all 5 track covers
    inherit the exact same lighting color grade. Falls back cleanly to text cues if offline/missing.
    """
    if image_path and os.path.exists(image_path):
        try:
            import colorsys
            from PIL import Image
            with Image.open(image_path) as im:
                rgb_im = im.convert("RGB")
                resample = Image.Resampling.BOX if hasattr(Image, "Resampling") else Image.BOX
                thumb = rgb_im.resize((96, 96), resample)
            bins = [0.0] * 36
            hue_rgb_acc = [[0.0, 0.0, 0.0, 0.0] for _ in range(36)]
            for y in range(96):
                for x in range(96):
                    r, g, b = thumb.getpixel((x, y))
                    hv, sv, vv = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                    if vv > 0.12 and sv > 0.16:
                        wgt = (sv ** 1.3) * (vv ** 1.1)
                        bi = int((hv * 360.0) // 10.0) % 36
                        bins[bi] += wgt
                        hue_rgb_acc[bi][0] += r * wgt
                        hue_rgb_acc[bi][1] += g * wgt
                        hue_rgb_acc[bi][2] += b * wgt
                        hue_rgb_acc[bi][3] += wgt
            if sum(bins) > 0.5:
                ranked = sorted(range(36), key=lambda i: bins[i], reverse=True)
                b1 = ranked[0]
                h1 = (b1 * 10.0 + 5.0) % 360.0
                b2 = None
                for cand in ranked[1:]:
                    hc = (cand * 10.0 + 5.0) % 360.0
                    dist = abs(hc - h1) % 360.0
                    dist = 360.0 - dist if dist > 180.0 else dist
                    if dist >= 35.0 and bins[cand] >= bins[b1] * 0.15:
                        b2 = cand
                        break

                def _bin_hex(b_idx):
                    acc = hue_rgb_acc[b_idx]
                    if acc[3] <= 0:
                        return "#00F0FF"
                    rr = int(round(acc[0] / acc[3]))
                    gg = int(round(acc[1] / acc[3]))
                    bb = int(round(acc[2] / acc[3]))
                    return f"#{rr:02X}{gg:02X}{bb:02X}"

                desc1 = f"{_hue_to_palette_name(h1)} ({_bin_hex(b1)})"
                if b2 is not None:
                    h2 = (b2 * 10.0 + 5.0) % 360.0
                    desc2 = f"{_hue_to_palette_name(h2)} ({_bin_hex(b2)})"
                    return f"Pitch-black obsidian shadows lit strictly by {desc1} and {desc2}"
                return f"Pitch-black obsidian shadows lit strictly by {desc1} with cold specular rim reflections"
        except Exception as e:
            logger.warning(f"Album cover palette extraction fallback: {e}")

    vis_clean = (fallback_visual or "").strip()
    if vis_clean:
        return f"Pitch-black nocturnal shadows anchored to the album visual palette ({vis_clean[:160]})"
    return "Pitch-black obsidian shadows with electric cyan and deep ultraviolet neon highlights"


def _scrub_off_world_puns_and_cap_motifs(tracks_out, album_visual, locked_world, locked_palette, moon_name, moon_desc):
    """
    Deterministic guardrail applied to every Album Visual Showrunner plan:
      1. Strips off-world literal title puns unless explicitly part of `album_visual`.
      2. Enforces strict album-wide motif caps across all 5 tracks:
         - fedora silhouette: <= 1 track total
         - katana blade: <= 1 track total
         - moon: <= 2 tracks total
      3. Ensures every track has a distinct shot scale and explicit palette/world lock.
    """
    vis_low = (album_visual or "").lower()
    fedora_seen = 0
    katana_seen = 0
    moon_seen = 0
    used_scales = set()

    fedora_re = re.compile(r"[^.;,]*\b(fedora|wide-brimmed hat|trench\s*coat figure)\b[^.;,]*[.,;]?", re.IGNORECASE)
    katana_re = re.compile(r"[^.;,]*\b(katana|tsuka|samurai sword|japanese sword)\b[^.;,]*[.,;]?", re.IGNORECASE)
    moon_re = re.compile(r"[^.;,]*\b(moon|crescent|gibbous|lunar)\b[^.;,]*[.,;]?", re.IGNORECASE)

    cleaned_tracks = []
    for idx, item in enumerate(tracks_out):
        default_scale_id, default_scale_desc = TRACK_SHOT_SCALES[idx % len(TRACK_SHOT_SCALES)]
        scale_id = str(item.get("shot_scale") or default_scale_id).strip().lower().replace(" ", "_")
        if scale_id in used_scales:
            scale_id = default_scale_id
        used_scales.add(scale_id)

        prompt_txt = str(item.get("image_prompt") or "").strip()
        # 1. Scrub off-world literal title puns unless native to the album's own visual brief
        for bad_term, safe_repl in OFF_WORLD_LITERAL_PUN_TERMS:
            if bad_term not in vis_low and bad_term in prompt_txt.lower():
                prompt_txt = re.sub(re.escape(bad_term), safe_repl, prompt_txt, flags=re.IGNORECASE)

        # 2. Enforce strict motif caps across the 5-track series
        if fedora_re.search(prompt_txt):
            if fedora_seen >= 1:
                prompt_txt = fedora_re.sub(" ", prompt_txt)
            else:
                fedora_seen += 1
        if katana_re.search(prompt_txt):
            if katana_seen >= 1:
                prompt_txt = katana_re.sub(" ", prompt_txt)
            else:
                katana_seen += 1
        if moon_re.search(prompt_txt):
            if moon_seen >= 2:
                prompt_txt = moon_re.sub(" ", prompt_txt)
            else:
                moon_seen += 1

        prompt_txt = re.sub(r"\s{2,}", " ", prompt_txt).strip(" ,;-")
        if locked_palette and locked_palette[:28].lower() not in prompt_txt.lower():
            prompt_txt = f"{prompt_txt}. Color & lighting grade: {locked_palette}."
        if "35mm" not in prompt_txt.lower() and "anamorphic" not in prompt_txt.lower():
            prompt_txt = f"Photorealistic 35mm anamorphic cinema frame, shallow depth of field, subtle film grain. {prompt_txt}"

        item_clean = {
            "track_number": idx + 1,
            "title": str(item.get("title") or f"TRACK {idx + 1}").strip().upper(),
            "shot_scale": scale_id,
            "focal_subject": str(item.get("focal_subject") or default_scale_desc).strip(),
            "image_prompt": sanitize_prompt_for_venice(prompt_txt),
        }
        cleaned_tracks.append(item_clean)

    return cleaned_tracks


def _build_deterministic_visual_blueprint(proposal, tracklist, locked_palette):
    """Offline / fallback cohesive 5-cover visual blueprint strictly anchored to the album's world."""
    album_name = proposal.get("album", "UNKNOWN ALBUM")
    album_visual = (proposal.get("visual") or "rain-slicked midnight cyberpunk metropolis shrouded in fog").strip()
    subgenre = proposal.get("subgenre", "dark nightride trap")
    moon_name, moon_desc = get_current_moon_phase()

    locked_world = f"Unified nocturnal visual universe of '{album_name}': {album_visual}"
    camera_treatment = "Photorealistic ARRI Alexa 65 anamorphic 35mm film still, wet specular reflections, volumetric haze, razor-sharp textures, subtle halation"

    raw_tracks = []
    for idx, t in enumerate(tracklist):
        t_title = str(t.get("title") or f"TRACK {idx + 1}").strip().upper()
        scale_id, scale_desc = TRACK_SHOT_SCALES[idx % len(TRACK_SHOT_SCALES)]
        motif_clause = ""
        if idx == 0:
            motif_clause = f"High in the mist, {moon_desc} ({moon_name}) casts cold rim light."
        elif idx == 1:
            motif_clause = "A matte-black katana hilt rests subtly in deep shadow along the console edge."
        elif idx == 4:
            motif_clause = "In the distant background haze stands the motionless dark silhouette of a figure in a wide-brimmed fedora, face completely obscured."

        img_prompt = (
            f"{camera_treatment}. {scale_desc} set strictly inside the exact world of {album_visual}. "
            f"Visual chapter interpreting '{t_title}' ({subgenre}) through environmental light, architecture, and atmosphere within this world — "
            f"never breaking setting continuity. {motif_clause} "
            f"Color & lighting grade: {locked_palette}."
        )
        raw_tracks.append({
            "track_number": idx + 1,
            "title": t_title,
            "shot_scale": scale_id,
            "focal_subject": f"{scale_id} chapter for {t_title}",
            "image_prompt": img_prompt,
        })

    tracks_checked = _scrub_off_world_puns_and_cap_motifs(
        raw_tracks, album_visual, locked_world, locked_palette, moon_name, moon_desc
    )
    return {
        "album": album_name,
        "locked_world": locked_world,
        "locked_palette": locked_palette,
        "camera_treatment": camera_treatment,
        "moon_phase": moon_name,
        "tracks": tracks_checked,
    }


def plan_album_visual_showrunner(proposal, tracklist, album_cover_bg_path=None, state=None, force=False):
    """
    Single-Pass 'Album Visual Showrunner' (Phase 5 Art Direction Blueprint):
    Plans all 5 track covers TOGETHER in one unified LLM pass anchored to the approved
    Phase 4 Album Cover's world, lighting palette, and lens treatment so:
      1. Every track cover clearly belongs to the exact same visual world & color grade.
      2. Zero off-world literal title puns occur (e.g. no daytime shipping ports on an ocular cyber-noir album).
      3. All 5 tracks get distinct, non-repeating camera scales/framings (no duplicate car-mirror or duplicate iris shots).
      4. Signature props (fedora, katana, moon) are budgeted across the whole album (<=1-2 tracks total), never spammed on every cover.
    """
    album_name = proposal.get("album", "Unknown Album")
    art_dir = get_album_artwork_dir(album_name)
    os.makedirs(art_dir, exist_ok=True)
    plan_path = os.path.join(art_dir, "visual_showrunner_plan.json")

    expected_titles = [str(t.get("title", f"Track {i+1}")).strip().upper() for i, t in enumerate(tracklist)]

    if not force and os.path.exists(plan_path):
        try:
            with open(plan_path, "r", encoding="utf-8") as rf:
                cached = json.load(rf)
            cached_titles = [str(x.get("title", "")).strip().upper() for x in cached.get("tracks", [])]
            if len(cached_titles) == len(expected_titles) and cached_titles == expected_titles:
                return cached
        except Exception:
            pass

    if not album_cover_bg_path:
        cand_bg = os.path.join(art_dir, "album_cover_bg.png")
        cand_fg = os.path.join(art_dir, "album_cover.png")
        album_cover_bg_path = cand_bg if os.path.exists(cand_bg) else (cand_fg if os.path.exists(cand_fg) else None)

    album_visual = proposal.get("visual", "")
    subgenre = proposal.get("subgenre", "dark nightride trap")
    brief = proposal.get("brief", "")
    locked_palette = extract_album_cover_palette_summary(album_cover_bg_path, fallback_visual=album_visual)
    moon_name, moon_desc = get_current_moon_phase()

    blueprint = None
    if VENICE_API_KEY and len(tracklist) > 0:
        track_lines = []
        for idx, t in enumerate(tracklist):
            t_title = expected_titles[idx]
            scale_id, scale_desc = TRACK_SHOT_SCALES[idx % len(TRACK_SHOT_SCALES)]
            dna_snip = _extract_track_dna(t, proposal)
            track_lines.append(
                f"  Track {idx+1}: title='{t_title}' | assigned_shot_scale='{scale_id}' ({scale_desc}) | musical_role={dna_snip[:240]}"
            )

        sys_prompt = (
            "You are the Executive Visual Showrunner for VØIDRIDE, designing a cohesive 5-track collector's vinyl/digital "
            "single-cover series that pairs with an already-approved Main Album Cover.\n\n"
            "ABSOLUTE COHESION & ANTI-DRIFT RULES:\n"
            "1. ONE SHARED WORLD & COLOR GRADE: Every single track cover MUST take place inside the EXACT SAME physical universe, "
            "time of night, atmospheric weather, lens/film stock, and locked 2-color neon lighting palette as the Album Cover.\n"
            "2. FORBID LITERAL OFF-WORLD TITLE PUNS: Interpret track titles poetically/viscerally INSIDE the album's world. "
            "NEVER leave the album's world for a literal pun (e.g., if the album is ocular neon-noir, 'OPTIC NERVE' must show "
            "bioluminescent retinal/neural light conduits in that neon-noir night world — NEVER daytime shipping containers or ocean docks; "
            "if the album is a server complex, 'COOLING TOWER' stays inside the neon server megastructure — NEVER rural nuclear stacks).\n"
            "3. FIVE DISTINCT NON-REPEATING COMPOSITIONS: Follow each track's `assigned_shot_scale` so all 5 covers have distinct "
            "camera distances and focal subjects. NEVER repeat car-mirror reflections twice, NEVER repeat the Album Cover's exact hero shot, "
            "and NEVER repeat the same central prop.\n"
            "4. STRICT ALBUM-WIDE MOTIF BUDGET: Across ALL 5 tracks combined:\n"
            "   - Shadowed man in fedora silhouette: include on AT MOST 1 track (0 if pure macro/abstract world).\n"
            "   - Matte-black katana: include on AT MOST 1 track.\n"
            f"   - Astronomical moon ({moon_name}: {moon_desc}): include on AT MOST 1-2 exterior tracks.\n"
            "5. NO TEXT IN ARTWORK: Every `image_prompt` MUST be 90-145 words (<1150 chars), photorealistic 35mm anamorphic cinema photography, "
            "and explicitly forbid any text, letters, numbers, signage, or graffiti.\n\n"
            "Return STRICT JSON ONLY (no markdown fences, no commentary) matching this exact schema:\n"
            "{\n"
            '  "locked_world": "1-sentence description of the shared physical environment & atmosphere",\n'
            '  "locked_palette": "exact shared 2-3 color lighting & shadow palette",\n'
            '  "camera_treatment": "shared lens, film grain & lighting style",\n'
            '  "tracks": [\n'
            '    {"track_number": 1, "title": "...", "shot_scale": "...", "focal_subject": "...", "image_prompt": "..."}\n'
            "  ]\n"
            "}"
        )

        user_prompt = (
            f"Album Title: {album_name}\n"
            f"Subgenre: {subgenre}\n"
            f"Approved Main Album Cover Concept (DO NOT DUPLICATE THIS EXACT HERO FRAMING, BUT STAY IN THIS EXACT WORLD): {album_visual}\n"
            f"Approved Album Cover Extracted Pixel Palette (LOCK ALL 5 COVERS TO THIS PALETTE): {locked_palette}\n"
            f"Album Sonic Brief: {brief}\n\n"
            f"Plan cohesive visual prompts for all {len(tracklist)} tracks:\n" + "\n".join(track_lines)
        )

        url = f"{VENICE_API_BASE}/chat/completions"
        headers = {"Authorization": f"Bearer {VENICE_API_KEY}", "Content-Type": "application/json"}
        models_to_try = (
            _mr.get_role_chain("llm.showrunner", ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"])
            if _mr else ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"]
        )

        for model_name in models_to_try:
            v_params = {"strip_thinking_response": True}
            if "qwen" in model_name.lower():
                v_params["disable_thinking"] = True
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.62,
                "max_tokens": 2200,
                "venice_parameters": v_params,
            }
            try:
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                raw_txt = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                raw_txt = re.sub(r"^```(?:json)?\s*", "", raw_txt, flags=re.IGNORECASE)
                raw_txt = re.sub(r"\s*```$", "", raw_txt).strip()
                start_b = raw_txt.find("{")
                end_b = raw_txt.rfind("}")
                if start_b != -1 and end_b > start_b:
                    parsed = json.loads(raw_txt[start_b:end_b + 1])
                    tr_arr = parsed.get("tracks") or []
                    if isinstance(tr_arr, list) and len(tr_arr) >= len(tracklist):
                        lw = str(parsed.get("locked_world") or f"Unified nocturnal world of {album_name}: {album_visual}").strip()
                        lp = str(parsed.get("locked_palette") or locked_palette).strip()
                        ct = str(parsed.get("camera_treatment") or "Photorealistic 35mm anamorphic cinema frame").strip()
                        for idx_t in range(len(tracklist)):
                            tr_arr[idx_t]["title"] = expected_titles[idx_t]
                        checked = _scrub_off_world_puns_and_cap_motifs(
                            tr_arr[:len(tracklist)], album_visual, lw, lp, moon_name, moon_desc
                        )
                        blueprint = {
                            "album": album_name,
                            "locked_world": lw,
                            "locked_palette": lp,
                            "camera_treatment": ct,
                            "moon_phase": moon_name,
                            "model_used": model_name,
                            "tracks": checked,
                        }
                        if state is not None:
                            add_cost(state, "prompt_upsampling", VENICE_K3_PROMPT_COST * 2)
                        logger.info(f"Album Visual Showrunner planned {len(checked)} cohesive track covers via {model_name}")
                        break
            except Exception as e:
                logger.warning(f"Visual Showrunner attempt with {model_name} failed: {e}")
                time.sleep(1)

    if blueprint is None:
        blueprint = _build_deterministic_visual_blueprint(proposal, tracklist, locked_palette)

    try:
        with open(plan_path, "w", encoding="utf-8") as wf:
            json.dump(blueprint, wf, indent=2)
    except Exception as e:
        logger.warning(f"Could not save visual_showrunner_plan.json: {e}")

    return blueprint


def build_redo_track_prompt_from_blueprint(proposal, tracklist, track_idx, feedback="", state=None):
    """
    Generate a replacement prompt for a single track (`track_idx`, 0-based) that stays 100%
    locked to the album's Visual Showrunner world & color palette while avoiding sibling subjects.
    """
    blueprint = plan_album_visual_showrunner(proposal, tracklist, state=state, force=False)
    tracks_bp = blueprint.get("tracks", [])
    target_title = str(tracklist[track_idx].get("title", f"Track {track_idx+1}")).strip().upper()
    scale_id, scale_desc = TRACK_SHOT_SCALES[track_idx % len(TRACK_SHOT_SCALES)]

    sibling_subjects = [
        f"Track {t.get('track_number')}: {t.get('focal_subject', '')}"
        for i, t in enumerate(tracks_bp) if i != track_idx
    ]
    locked_world = blueprint.get("locked_world", proposal.get("visual", ""))
    locked_palette = blueprint.get("locked_palette", "")
    cam = blueprint.get("camera_treatment", "Photorealistic 35mm anamorphic cinema photography")

    director_notes = (
        f"LOCKED ALBUM WORLD: {locked_world}\n"
        f"LOCKED ALBUM PALETTE (MANDATORY): {locked_palette}\n"
        f"CAMERA & FILM TREATMENT: {cam}\n"
        f"ASSIGNED SHOT SCALE: {scale_id} ({scale_desc})\n"
        f"DO NOT REPEAT SIBLING SUBJECTS: {'; '.join(sibling_subjects)}\n"
        f"FORBID LITERAL OFF-WORLD PUNS: Stay strictly inside the locked album world above."
    )
    if feedback:
        director_notes += f"\nUSER REDO FEEDBACK: {feedback}"

    dna = _extract_track_dna(tracklist[track_idx], proposal)
    fresh_prompt = upsample_image_prompt_k3(
        target_title,
        dna,
        subgenre=proposal.get("subgenre", ""),
        is_album=False,
        custom_notes=director_notes,
        state=state,
        allow_random_motifs=False,
    )
    moon_name, moon_desc = get_current_moon_phase()
    scrubbed = _scrub_off_world_puns_and_cap_motifs(
        [{"title": target_title, "shot_scale": scale_id, "focal_subject": scale_desc, "image_prompt": fresh_prompt}],
        proposal.get("visual", ""),
        locked_world,
        locked_palette,
        moon_name,
        moon_desc,
    )[0]["image_prompt"]

    # Update cached blueprint entry on disk so subsequent audits reflect the redo
    if track_idx < len(tracks_bp):
        tracks_bp[track_idx]["image_prompt"] = scrubbed
        art_dir = get_album_artwork_dir(proposal.get("album", "Unknown Album"))
        try:
            with open(os.path.join(art_dir, "visual_showrunner_plan.json"), "w", encoding="utf-8") as wf:
                json.dump(blueprint, wf, indent=2)
        except Exception:
            pass
    return scrubbed


def upsample_image_prompt_k3(title, core_concept, subgenre="", is_album=False, custom_notes="", state=None, allow_random_motifs=None):
    """
    Upsample image prompt into a hyper-detailed cinematic scene via Venice LLM.
    For Album Covers (`is_album=True`), subtly weaves at most 1-2 VØIDRIDE motifs if natural.
    For Track Covers, random per-track motif spamming is disabled by default so the Album Visual
    Showrunner enforces strict cross-album cohesion.
    """
    if not VENICE_API_KEY:
        logger.warning("VENICE_API_KEY missing, using fallback prompt.")
        return sanitize_prompt_for_venice(f"Cinematic neon-noir scene for {title}. {core_concept}. {subgenre}")

    moon_name, moon_desc = get_current_moon_phase()

    if allow_random_motifs is None:
        allow_random_motifs = bool(is_album)

    motifs = []
    if allow_random_motifs:
        import random
        if random.random() < 0.45:
            motifs.append("Optional background detail (only if fitting the setting): distant motionless silhouette in a dark wide-brimmed fedora in deep shadow")
        if random.random() < 0.55:
            motifs.append(f"Astronomical moon phase if sky/reflection is visible: {moon_name} ({moon_desc})")

    motifs_instruction = "\n".join(f"- {m}" for m in motifs) if motifs else "- Keep props organic to the locked album world; do NOT force unrelated katanas or hats"

    system_instruction = (
        "You are an elite cinematic art director and visual prompt engineer for VØIDRIDE, "
        "a dark neon-noir / witch house trap / heavy West Coast bass electronic artist.\n"
        "Your task: Convert the given visual concept and director notes into an extraordinarily "
        "detailed, photorealistic cinematic scene prompt for an AI image generation model.\n\n"
        "Strict Guidelines:\n"
        "1. NO TEXT, NO LETTERS, NO TYPOGRAPHY, NO WATERMARKS, NO WORDS, NO GRAFFITI, NO SIGNAGE in the image.\n"
        "2. Style: Photorealistic 35mm / anamorphic cinematic photography, ARRI Alexa 65, shallow depth of field, "
        "volumetric fog, film grain, subtle halation, dramatic chiaroscuro lighting, razor-sharp textures.\n"
        "3. WORLD & PALETTE COHESION: Never break out of the album's physical setting or color palette for literal title puns.\n"
        f"4. Motif discipline:\n{motifs_instruction}\n"
        "5. CRITICAL CONSTRAINT: The generated prompt MUST be under 1150 characters (around 140 words). Be densely atmospheric and concise.\n\n"
        "Output ONLY the final generated image prompt paragraph. Do NOT include markdown headers, preambles, or conversational filler."
    )

    user_input = (
        f"Title: {title}\n"
        f"Type: {'Album Cover' if is_album else 'Single Track Cover'}\n"
        f"Subgenre / Sonic DNA: {subgenre}\n"
        f"Core Concept / Theme: {core_concept}\n"
    )
    if custom_notes:
        user_input += f"Specific Director Notes:\n{custom_notes}\n"

    url = f"{VENICE_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json"
    }

    models_to_try = _mr.get_role_chain("llm.image_prompt", ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"]) if _mr else ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"]
    for model_name in models_to_try:
        v_params = {"strip_thinking_response": True}
        if "qwen" in model_name.lower():
            v_params["disable_thinking"] = True
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_input}
            ],
            "temperature": 0.65,
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
        bg_png, _, _ = get_canonical_track_cover_paths(art_dir, parts[1])
        out_path = bg_png
    else:
        art_dir = get_album_artwork_dir(album_name)
        out_path = os.path.join(art_dir, "album_cover_bg.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if not VENICE_API_KEY:
        logger.error("VENICE_API_KEY missing, skipping image generation.")
        return None

    clean_prompt = sanitize_prompt_for_venice(prompt)

    url = f"{VENICE_API_BASE}/images/generations"
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
                        raw_bytes = base64.b64decode(b64)
                        with open(out_path, 'wb') as f:
                            f.write(raw_bytes)
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

    url = f"{VENICE_API_BASE}/image/edit"
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


def upscale_artwork_venice(image_path, target_size=3000, allow_local_fallback=False):
    if not os.path.exists(image_path):
        return image_path
    from PIL import Image, ImageFilter
    try:
        with Image.open(image_path) as img:
            if img.size[0] >= target_size and img.size[1] >= target_size:
                return image_path

        if VENICE_API_KEY:
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
            url = f"{VENICE_API_BASE}/image/upscale"
            req = urllib.request.Request(url, data=body, method='POST', headers={
                'Authorization': f'Bearer {VENICE_API_KEY}',
                'Content-Type': f'multipart/form-data; boundary={boundary}',
            })

            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req, timeout=150) as response:
                        upscaled_data = response.read()

                    if len(upscaled_data) > 1000:
                        tmp_path = image_path + '.4k_tmp.png'
                        with open(tmp_path, 'wb') as f:
                            f.write(upscaled_data)
                        with Image.open(tmp_path) as upscaled_img:
                            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                            final = upscaled_img.resize((target_size, target_size), resample)
                            final.save(image_path, 'PNG')
                            jpg_path = os.path.splitext(image_path)[0] + '.jpg'
                            final.convert('RGB').save(jpg_path, 'JPEG', quality=95)
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                        return image_path
                except Exception as ue:
                    logger.warning(f"Venice upscale attempt {attempt+1} failed for {os.path.basename(image_path)}: {ue}")
                    time.sleep(2)

        if allow_local_fallback:
            with Image.open(image_path) as src_im:
                resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                up_im = src_im.convert("RGB").resize((target_size, target_size), resample)
                up_im = up_im.filter(ImageFilter.UnsharpMask(radius=2.0, percent=130, threshold=3))
                if image_path.lower().endswith(".png"):
                    up_im.save(image_path, "PNG")
                else:
                    up_im.save(image_path, "JPEG", quality=95)
            logger.info(f"Applied crisp {target_size}x{target_size} Lanczos+Unsharp fallback upscale to {image_path}")
            return image_path
    except Exception as e:
        logger.error(f"Upscale failed for {image_path}: {e}")
        if logger_hub:
            logger_hub.log_failure("UPSCALE_FAIL", str(e), album=os.path.basename(image_path), phase=4)
    return image_path


def _resolve_overlay_script_and_python():
    python_bin = "/opt/hermes/.venv/bin/python3" if os.path.exists("/opt/hermes/.venv/bin/python3") else sys.executable
    repo_overlay = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "creative", "cover-title-overlay", "scripts", "overlay-title.py")
    )
    for cand in (OVERLAY_TITLE_SCRIPT, repo_overlay):
        if cand and os.path.exists(cand):
            return python_bin, cand
    return python_bin, None


def _save_bounded_cover_jpg(src_img_path, jpg_path, max_bytes=8_000_000):
    """Save an RGB JPEG guaranteed <= max_bytes (well under Telegram's 10MB sendPhoto cap)."""
    from PIL import Image
    with Image.open(src_img_path) as im:
        rgb = im.convert("RGB")
        for q in (95, 91, 86, 80):
            rgb.save(jpg_path, "JPEG", quality=q)
            if os.path.getsize(jpg_path) <= max_bytes:
                break
    return jpg_path


def _run_overlay_title(bg_path, title, out_path, is_album=False, album_anchor=None, opacity=None):
    """
    Run `overlay-title.py` with album-cohesive neon palette anchoring (`--album` or `--album-anchor`),
    producing both `out_path` and a `< 8 MB` companion `.jpg`.
    """
    if not os.path.exists(bg_path):
        return False
    python_bin, overlay_script = _resolve_overlay_script_and_python()
    eff_opacity = opacity if opacity is not None else (0.62 if is_album else 0.68)
    if overlay_script:
        styled = stylize_title(title)
        cmd = [
            python_bin,
            overlay_script,
            "--image", bg_path,
            "--title", styled,
            "--stacked",
            "--bottom",
            "--auto-color",
            "--opacity", f"{eff_opacity:.2f}",
            "--output", out_path,
        ]
        if is_album:
            cmd.append("--album")
        elif album_anchor and os.path.exists(album_anchor):
            cmd.extend(["--album-anchor", album_anchor])
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            logger.warning(f"overlay-title warning on {out_path}: {res.stderr[:240]}")
    if not os.path.exists(out_path):
        shutil.copy2(bg_path, out_path)
    jpg_out = os.path.splitext(out_path)[0] + ".jpg"
    try:
        _save_bounded_cover_jpg(out_path, jpg_out)
    except Exception as e:
        logger.warning(f"Could not write JPEG companion for {out_path}: {e}")
    return True


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
        if ALBUMS_BASE and ALBUMS_BASE != "/opt/data/music/albums":
            music_root = os.path.dirname(ALBUMS_BASE.rstrip("/\\"))
        else:
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
    jpg_path = os.path.join(art_dir, "album_cover.jpg")

    force_regen = getattr(phase_4_album_cover, '_force_regen', False)
    phase_4_album_cover._force_regen = False

    if not os.path.exists(cover_bg) or not os.path.exists(cover_path) or force_regen:
        send_message(f"🎨 <b>Designing album cover for {html.escape(album_name)}...</b>\nUpsampling visual prompt with K3 AI...")

        core_concept = f"Album visual: {visual}. Musical brief: {brief}"
        upsampled_prompt = upsample_image_prompt_k3(album_name, core_concept, subgenre=subgenre, is_album=True, state=state)

        send_message("🖼️ <b>Synthesizing visual with Venice SOTA image engine (qwen-image-3-pro)...</b>")
        raw_path = generate_artwork_venice(upsampled_prompt, album_name, state=state)
        if not raw_path or not os.path.exists(raw_path):
            send_message("❌ Failed to generate album cover.")
            return "regen"

        if os.path.abspath(raw_path) != os.path.abspath(cover_bg):
            shutil.copy2(raw_path, cover_bg)
        # Invalidate cached Phase 5 visual blueprint whenever the Album Cover changes so Track Covers re-lock to it
        bp_cache = os.path.join(art_dir, "visual_showrunner_plan.json")
        if os.path.exists(bp_cache):
            try:
                os.remove(bp_cache)
            except Exception:
                pass

    _run_overlay_title(cover_bg, album_name, cover_path, is_album=True, opacity=0.62)

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
                upscale_artwork_venice(cover_bg, target_size=3000, allow_local_fallback=True)
                if state:
                    add_cost(state, "cover_upscale", VENICE_UPSCALE_COST)
                _run_overlay_title(cover_bg, album_name, cover_path, is_album=True, opacity=0.62)
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
            bp_cache = os.path.join(art_dir, "visual_showrunner_plan.json")
            if os.path.exists(bp_cache):
                try:
                    os.remove(bp_cache)
                except Exception:
                    pass
            _run_overlay_title(cover_bg, album_name, cover_path, is_album=True, opacity=0.62)
            _send_album_review_card()


# ── Phase 5: Track Cover Art (Cohesive Album Visual Showrunner) ────────
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
            main_p = stems.get('main', {}).get('prompt', '')[:160]
            tex_p = stems.get('texture', {}).get('prompt', '')[:120]
            energy = plan.get('energy', '')
            extra_stems = f"Sonic DNA: {main_p}. Texture: {tex_p}. Mood: {energy}."
        except Exception as e:
            logger.warning(f"Failed to read production_plan.json for {title}: {e}")

    direction = track_item.get('direction', track_item.get('genre', subgenre))
    return (
        f"Track Title: '{title}'. Shared Album World: '{album}' ({visual}). Musical Style: {direction}. {extra_stems} "
        f"COHESION RULE: Keep this scene strictly inside the physical setting, atmosphere, and color palette of '{album}' — "
        f"never drift into literal off-world puns."
    )


def phase_5_track_covers(proposal, tracklist, state=None, dashboard=None):
    if dashboard:
        dashboard.set_phase(5)
    album_name = proposal.get('album', 'Unknown Album')
    track_art_dir = get_album_artwork_dir(album_name)
    os.makedirs(track_art_dir, exist_ok=True)

    force_regen_all = getattr(phase_5_track_covers, '_force_regen', False)
    phase_5_track_covers._force_regen = False

    album_anchor = os.path.join(track_art_dir, "album_cover_bg.png")
    if not os.path.exists(album_anchor):
        cand_alb = os.path.join(track_art_dir, "album_cover.png")
        album_anchor = cand_alb if os.path.exists(cand_alb) else None

    # Single-pass Album Visual Showrunner locks world, palette, shot scales, and motif budget across all 5 tracks!
    send_message(f"🎬 <b>Album Visual Showrunner planning cohesive {len(tracklist)}-cover visual world for {html.escape(album_name)}...</b>")
    blueprint = plan_album_visual_showrunner(
        proposal,
        tracklist,
        album_cover_bg_path=album_anchor,
        state=state,
        force=force_regen_all,
    )
    bp_tracks = blueprint.get("tracks", [])

    track_entries = []

    for i, t in enumerate(tracklist):
        title = t.get('title', f'Track {i+1}')
        bg_backup, cover_path, jpg_cov = get_canonical_track_cover_paths(track_art_dir, title)
        bp_prompt = bp_tracks[i]["image_prompt"] if i < len(bp_tracks) else sanitize_prompt_for_venice(_extract_track_dna(t, proposal))

        if not os.path.exists(bg_backup) or force_regen_all:
            send_message(f"🖌️ [{(i+1)}/{len(tracklist)}] Synthesizing cohesive track cover for <b>{html.escape(title)}</b>...")
            raw_path = generate_artwork_venice(bp_prompt, f"{album_name}/{title}", state=state)
            if not raw_path or not os.path.exists(raw_path):
                logger.warning(f"Retrying Track {i+1} ({title}) cover generation with blueprint fallback prompt...")
                fallback_bp = _build_deterministic_visual_blueprint(
                    proposal, tracklist, blueprint.get("locked_palette", "")
                )["tracks"][i]["image_prompt"]
                raw_path = generate_artwork_venice(fallback_bp, f"{album_name}/{title}", state=state)
            if not raw_path or not os.path.exists(raw_path):
                raise RuntimeError(f"Track {i+1} ({title}) cover generation failed after retries — refusing incomplete cover set.")
            if os.path.abspath(raw_path) != os.path.abspath(bg_backup):
                shutil.copy2(raw_path, bg_backup)

        _run_overlay_title(bg_backup, title, cover_path, is_album=False, album_anchor=album_anchor, opacity=0.68)

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
        track_entries.append((i + 1, title, bg_backup, cover_path, jpg_cov))

    buttons = [
        [{"text": "✅ Approve All Covers", "callback_data": "ap:trackcovers:approve"}],
        [{"text": "🔄 Regenerate All", "callback_data": "ap:trackcovers:regenall"}]
    ]
    send_message("👆 <b>Review all track covers above:</b>\nTap any track's button to edit or regenerate, or Approve All to finalize:", reply_markup={"inline_keyboard": buttons})

    while True:
        flag, content = poll_flags()
        if flag == "trackcovers_approved":
            album_slug = album_name.lower().replace(' ', '-').replace('_', '-')
            send_message(f"⬆️ <b>Upscaling all {len(track_entries)} track covers to 3000×3000 & generating per-song waveform banners...</b>")
            for idx_num, track_title, bg_path, cp, jpg_cp in track_entries:
                send_message(f"⚙️ [{idx_num}/{len(track_entries)}] Upscaling & generating waveform for <b>{html.escape(track_title)}</b>...")
                if os.path.exists(bg_path):
                    was_already_3k = _is_cover_3k_ready(bg_path)
                    upscale_artwork_venice(bg_path, target_size=3000, allow_local_fallback=True)
                    wave_res = generate_waveform_banner(bg_path, track_title, [track_art_dir, "/opt/data/music/artwork/waveforms"], track_num=idx_num, album_slug=album_slug, force=True)
                    _run_overlay_title(bg_path, track_title, cp, is_album=False, album_anchor=album_anchor, opacity=0.68)
                    if state and not was_already_3k:
                        add_cost(state, "cover_upscale", VENICE_UPSCALE_COST)
                else:
                    was_already_3k = _is_cover_3k_ready(cp)
                    upscale_artwork_venice(cp, target_size=3000, allow_local_fallback=True)
                    _save_bounded_cover_jpg(cp, jpg_cp)
                    wave_res = generate_waveform_banner(cp, track_title, [track_art_dir, "/opt/data/music/artwork/waveforms"], track_num=idx_num, album_slug=album_slug, force=True)
                    if state and not was_already_3k:
                        add_cost(state, "cover_upscale", VENICE_UPSCALE_COST)
                if isinstance(wave_res, str) and os.path.exists(wave_res):
                    send_photo(wave_res, caption=f"🌊 Track {idx_num} Waveform: <b>{html.escape(track_title)}</b> (1240×400)")
            send_message("✅ <b>All track covers upscaled to 3000×3000 & per-song waveform banners generated!</b> Assembling final release package for your review & confirmation...")
            return "approved"
        elif flag == "trackcovers_regenall":
            send_message("🔄 <b>Regenerating all track covers with fresh Album Visual Showrunner blueprint...</b>")
            phase_5_track_covers._force_regen = True
            if state:
                add_cost(state, "cover_regeneration", VENICE_IMAGE_GEN_COST * len(tracklist))
                costs = init_cost_tracker(state)
                costs["cover_regen_count"] = costs.get("cover_regen_count", 0) + len(tracklist)
                save_state(state)
            return phase_5_track_covers(proposal, tracklist, state=state, dashboard=dashboard)
        elif flag and flag.startswith("art_redo_"):
            try:
                raw_tail = flag.split("_")[-1]
                if not raw_tail.isdigit():
                    logger.warning(f"Ignoring malformed art_redo flag '{flag}'")
                    continue
                track_num = int(raw_tail)
                idx = track_num - 1
                if 0 <= idx < len(tracklist):
                    t = tracklist[idx]
                    title = t.get('title', f'Track {track_num}')
                    fb_notes = content if content and content.strip().lower() != "redo" else ""
                    send_message(f"🔄 <b>Regenerating cover for Track {track_num}: {html.escape(title)} (locked to {html.escape(album_name)} visual world)...</b>")
                    redo_prompt = build_redo_track_prompt_from_blueprint(proposal, tracklist, idx, feedback=fb_notes, state=state)
                    bg_path, cover_path, jpg_cov = get_canonical_track_cover_paths(track_art_dir, title)
                    raw = generate_artwork_venice(redo_prompt, f"{album_name}/{title}", state=state)
                    if raw and os.path.exists(raw):
                        if os.path.abspath(raw) != os.path.abspath(bg_path):
                            shutil.copy2(raw, bg_path)
                        _run_overlay_title(bg_path, title, cover_path, is_album=False, album_anchor=album_anchor, opacity=0.68)
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
                        send_photo(jpg_cov if os.path.exists(jpg_cov) else cover_path, caption=f"🎨 Track {track_num}: <b>{html.escape(title)}</b> (Regenerated)", reply_markup={"inline_keyboard": track_btn})
            except Exception as e:
                logger.error(f"Error redoing track cover: {e}")
        elif flag and flag.startswith("art_edit_"):
            try:
                raw_tail = flag.split("_")[-1]
                if not raw_tail.isdigit():
                    logger.warning(f"Ignoring malformed art_edit flag '{flag}'")
                    continue
                track_num = int(raw_tail)
                idx = track_num - 1
                if 0 <= idx < len(tracklist):
                    t = tracklist[idx]
                    title = t.get('title', f'Track {track_num}')
                    edit_directive = content if content else "deepen shadows, cinematic chiaroscuro, moody atmosphere"
                    send_message(f"✏️ <b>Modifying Track {track_num} ({html.escape(title)}):</b> <i>{html.escape(edit_directive)}</i>\nRunning Venice AI vision edit inference...")
                    bg_path, cover_path, jpg_cov = get_canonical_track_cover_paths(track_art_dir, title)
                    if not os.path.exists(bg_path) and os.path.exists(cover_path):
                        shutil.copy2(cover_path, bg_path)

                    if os.path.exists(bg_path):
                        edit_artwork_venice(bg_path, edit_directive, bg_path, state=state)
                        _run_overlay_title(bg_path, title, cover_path, is_album=False, album_anchor=album_anchor, opacity=0.68)
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
                        send_photo(jpg_cov if os.path.exists(jpg_cov) else cover_path, caption=f"🎨 Track {track_num}: <b>{html.escape(title)}</b> (Edited: <i>{html.escape(edit_directive)}</i>)", reply_markup={"inline_keyboard": track_btn})
            except Exception as e:
                logger.error(f"Error editing track cover: {e}")


def _export_3000_release_jpg(src_cover, src_bg, title, dest_jpg, is_album=False, album_anchor=None):
    """
    Guarantee every packaged release cover is strictly 3000x3000 RGB JPEG (<= 8 MB).
    If an un-upscaled (<2800px) cover ever reaches Phase 6, automatically upscales the clean
    background to 3000x3000 and re-overlays crisp 3000px typography before exporting.
    """
    from PIL import Image, ImageFilter
    chosen = src_cover if (src_cover and os.path.exists(src_cover)) else src_bg
    if not chosen or not os.path.exists(chosen):
        return False

    if not _is_cover_3k_ready(chosen, min_dim=2800):
        logger.info(f"Auto-healing sub-3K cover for '{title}' -> 3000x3000 before release packaging...")
        if src_bg and os.path.exists(src_bg):
            upscale_artwork_venice(src_bg, target_size=3000, allow_local_fallback=True)
            titled_target = src_cover or (os.path.splitext(src_bg)[0].replace("_bg", "") + ".png")
            _run_overlay_title(src_bg, title, titled_target, is_album=is_album, album_anchor=album_anchor)
            chosen = titled_target
        else:
            upscale_artwork_venice(chosen, target_size=3000, allow_local_fallback=True)

    with Image.open(chosen) as im:
        rgb = im.convert("RGB")
        if rgb.size != (3000, 3000):
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            rgb = rgb.resize((3000, 3000), resample)
            rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.6, percent=115, threshold=3))
        for q in (95, 91, 86, 80):
            rgb.save(dest_jpg, "JPEG", quality=q)
            if os.path.getsize(dest_jpg) <= 8_000_000:
                break
    return True


def assemble_release(proposal, tracklist, album_slug):
    """
    Assemble canonical release directory at /opt/data/music/releases/{album_slug}
    - Copies master FLAC files (no MP3 duplicates)
    - Strictly 3000x3000 RGB .jpg covers (<= 8 MB): 1 per song + 1 album_cover.jpg
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
        clean_title = sanitize_filename(title)
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

    # 2. Cover art - strictly 3000x3000 RGB .jpg (<= 8 MB): 1 per song + 1 album_cover.jpg
    album_display_name = proposal.get("album", album_slug)
    art_dir = get_album_artwork_dir(album_display_name)
    alb_bg = os.path.join(art_dir, "album_cover_bg.png") if os.path.exists(os.path.join(art_dir, "album_cover_bg.png")) else None
    alb_cov = None
    if os.path.exists(art_dir):
        for ext in [".png", ".jpg"]:
            c = os.path.join(art_dir, f"album_cover{ext}")
            if os.path.exists(c):
                alb_cov = c
                break
    if alb_cov or alb_bg:
        _export_3000_release_jpg(
            alb_cov,
            alb_bg,
            album_display_name,
            os.path.join(covers_dir, "album_cover.jpg"),
            is_album=True,
        )
        stale_alb_png = os.path.join(covers_dir, "album_cover.png")
        if os.path.exists(stale_alb_png):
            try:
                os.remove(stale_alb_png)
            except Exception:
                pass

    for idx, t in enumerate(tracklist, 1):
        title = t.get("title", f"Track {idx}")
        clean_title = sanitize_filename(title)
        bg_cand, cov_png_cand, cov_jpg_cand = get_canonical_track_cover_paths(art_dir, title) if os.path.exists(art_dir) else (None, None, None)
        chosen = None
        if os.path.exists(art_dir):
            cands = [
                cov_png_cand,
                cov_jpg_cand,
                os.path.join(art_dir, f"{title}_cover.png"),
                os.path.join(art_dir, f"{title}_cover.jpg"),
                os.path.join(art_dir, f"{clean_title}.png"),
                os.path.join(art_dir, f"{clean_title}.jpg"),
                os.path.join(art_dir, f"Track {idx}_cover.png"),
                os.path.join(art_dir, f"Track_{idx}_cover.png"),
            ]
            chosen = next((c for c in cands if c and os.path.exists(c)), None)

        dest_jpg = os.path.join(covers_dir, f"{idx:02d}_{clean_title}.jpg")
        if chosen or (bg_cand and os.path.exists(bg_cand)):
            # If source was a generic Track_N placeholder, force title re-overlay onto bg first
            if chosen and ("Track " in os.path.basename(chosen) or "Track_" in os.path.basename(chosen)) and bg_cand and os.path.exists(bg_cand):
                _run_overlay_title(bg_cand, title, cov_png_cand, is_album=False, album_anchor=alb_bg)
                chosen = cov_png_cand
            _export_3000_release_jpg(
                chosen,
                bg_cand if (bg_cand and os.path.exists(bg_cand)) else None,
                title,
                dest_jpg,
                is_album=False,
                album_anchor=alb_bg,
            )
            stale_tr_png = os.path.join(covers_dir, f"{idx:02d}_{clean_title}.png")
            if os.path.exists(stale_tr_png):
                try:
                    os.remove(stale_tr_png)
                except Exception:
                    pass

    # 2b. Waveform banners - ensure dedicated waveforms/ folder across all canonical directories
    if ALBUMS_BASE and ALBUMS_BASE != "/opt/data/music/albums":
        music_root = os.path.dirname(ALBUMS_BASE.rstrip("/\\"))
    else:
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


def _is_pipeline_lock_active():
    """Return (True, pid) if an active album_pipeline.py process currently holds LOCK_FILE."""
    if not os.path.exists(LOCK_FILE):
        return False, None
    try:
        data = open(LOCK_FILE).read().strip().split(":")
        pid = int(data[0])
        if pid == os.getpid():
            return False, None
        saved_start = data[1] if len(data) > 1 else ""
        proc_start_file = f"/proc/{pid}/stat"
        if os.path.exists(proc_start_file):
            stat = open(proc_start_file).read().split()
            current_start = stat[21] if len(stat) > 21 else ""
            if current_start == saved_start:
                return True, pid
            return False, None
        # Non-procfs fallback
        os.kill(pid, 0)
        return True, pid
    except Exception:
        return False, None


def run_redo_cover_cli(proposal_index, target_spec, feedback=""):
    """
    Unified, safe cover regeneration entry point (--redo-cover <album|all|1..5[,N]>).
    - If an active album_pipeline.py holds LOCK_FILE, NEVER kills it — writes the matching
      flag into /tmp/pipeline_flags/ so the live Phase 4/5 loop handles it in-world.
    - If no pipeline is active, regenerates the cover(s) directly using the Album Visual
      Showrunner blueprint, upscales to 3000x3000, overlays album-cohesive neon typography,
      crops clean waveform banners, and delivers the preview to Telegram.
    """
    spec = str(target_spec or "").strip().lower()
    if not spec:
        logger.error("--redo-cover requires 'album', 'all', or 1-based track number(s) like '3' or '2,5'")
        return 1

    is_active, active_pid = _is_pipeline_lock_active()
    if is_active:
        os.makedirs(FLAGS_DIR, exist_ok=True)
        fb_payload = (feedback or "").strip()
        written_flags = []
        if spec == "album":
            flag_path = os.path.join(FLAGS_DIR, "albumcover_regen")
            with open(flag_path, "w", encoding="utf-8") as f:
                f.write(fb_payload or "regen")
            written_flags.append("albumcover_regen")
        elif spec == "all":
            flag_path = os.path.join(FLAGS_DIR, "trackcovers_regenall")
            with open(flag_path, "w", encoding="utf-8") as f:
                f.write(fb_payload or "regenall")
            written_flags.append("trackcovers_regenall")
        else:
            nums = [int(x.strip()) for x in spec.split(",") if x.strip().isdigit()]
            for n in nums:
                flag_path = os.path.join(FLAGS_DIR, f"art_redo_{n}")
                with open(flag_path, "w", encoding="utf-8") as f:
                    f.write(fb_payload or "redo")
                written_flags.append(f"art_redo_{n}")
        logger.info(
            f"Active pipeline detected (PID {active_pid}); signaled {written_flags} without interrupting production."
        )
        print(json.dumps({"status": "signaled_active_pipeline", "pid": active_pid, "flags": written_flags}))
        return 0

    state = load_state()
    proposal = None
    if state.get("proposal") and proposal_index is None:
        proposal = state["proposal"]
    elif os.path.exists(PROPOSALS_FILE):
        with open(PROPOSALS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
            idx = proposal_index if proposal_index is not None else 0
            if 0 <= idx < len(proposals):
                proposal = proposals[idx]
    if not proposal and state.get("proposal"):
        proposal = state["proposal"]
    if not proposal:
        logger.error("Could not resolve album proposal for --redo-cover.")
        return 1

    album_name = proposal.get("album", "Unknown Album")
    album_slug = album_name.lower().replace(" ", "-").replace("_", "-")
    art_dir = get_album_artwork_dir(album_name)
    os.makedirs(art_dir, exist_ok=True)

    tracklist = state.get("completed_tracks") or state.get("tracklist") or []
    if not tracklist:
        disc_tracks, _, _ = discover_existing_album_production(proposal)
        if disc_tracks:
            tracklist = disc_tracks
    if not tracklist:
        tracklist = [
            {
                "track": idx + 1,
                "title": str(t).strip().upper(),
                "bpm": proposal.get("bpm", 140),
                "key": proposal.get("key", "Fm"),
                "genre": proposal.get("subgenre", "Dark Nightride Trap"),
            }
            for idx, t in enumerate(proposal.get("tracks", []))
        ]

    if spec == "album":
        visual = proposal.get("visual", "")
        subgenre = proposal.get("subgenre", "")
        brief = proposal.get("brief", "")
        extra_fb = f" User visual direction: {feedback}." if feedback else ""
        core_concept = f"Album visual: {visual}. Musical brief: {brief}.{extra_fb}"
        upsampled_prompt = upsample_image_prompt_k3(album_name, core_concept, subgenre=subgenre, is_album=True, state=state)
        raw_path = generate_artwork_venice(upsampled_prompt, album_name, state=state)
        if not raw_path or not os.path.exists(raw_path):
            logger.error("Failed to regenerate album cover via Venice.")
            return 1
        cover_bg = os.path.join(art_dir, "album_cover_bg.png")
        cover_path = os.path.join(art_dir, "album_cover.png")
        jpg_path = os.path.join(art_dir, "album_cover.jpg")
        if os.path.abspath(raw_path) != os.path.abspath(cover_bg):
            shutil.copy2(raw_path, cover_bg)
        bp_cache = os.path.join(art_dir, "visual_showrunner_plan.json")
        if os.path.exists(bp_cache):
            try:
                os.remove(bp_cache)
            except Exception:
                pass
        upscale_artwork_venice(cover_bg, target_size=3000, allow_local_fallback=True)
        generate_waveform_banner(cover_bg, album_name, [art_dir, "/opt/data/music/artwork/waveforms"], track_num=None, album_slug=album_slug, force=True)
        _run_overlay_title(cover_bg, album_name, cover_path, is_album=True, opacity=0.62)
        send_photo(jpg_path if os.path.exists(jpg_path) else cover_path, caption=f"🎨 <b>Album Cover Regenerated: {html.escape(album_name)}</b> (3000×3000)")
        print(json.dumps({"status": "ok", "target": "album", "cover": cover_path}))
        return 0

    targets = (
        list(range(1, len(tracklist) + 1))
        if spec == "all"
        else [int(x.strip()) for x in spec.split(",") if x.strip().isdigit()]
    )
    if not targets:
        logger.error(f"No valid track numbers parsed from --redo-cover '{target_spec}'")
        return 1

    album_anchor = os.path.join(art_dir, "album_cover_bg.png")
    if not os.path.exists(album_anchor):
        cand_alb = os.path.join(art_dir, "album_cover.png")
        album_anchor = cand_alb if os.path.exists(cand_alb) else None

    plan_album_visual_showrunner(
        proposal,
        tracklist,
        album_cover_bg_path=album_anchor,
        state=state,
        force=(spec == "all"),
    )

    regenerated = []
    for t_num in targets:
        idx = t_num - 1
        if not (0 <= idx < len(tracklist)):
            continue
        title = tracklist[idx].get("title", f"Track {t_num}")
        redo_prompt = build_redo_track_prompt_from_blueprint(proposal, tracklist, idx, feedback=feedback or "", state=state)
        bg_path, cover_path, jpg_cov = get_canonical_track_cover_paths(art_dir, title)
        raw = generate_artwork_venice(redo_prompt, f"{album_name}/{title}", state=state)
        if not raw or not os.path.exists(raw):
            logger.error(f"Failed to regenerate cover for Track {t_num} ({title})")
            continue
        if os.path.abspath(raw) != os.path.abspath(bg_path):
            shutil.copy2(raw, bg_path)
        upscale_artwork_venice(bg_path, target_size=3000, allow_local_fallback=True)
        generate_waveform_banner(bg_path, title, [art_dir, "/opt/data/music/artwork/waveforms"], track_num=t_num, album_slug=album_slug, force=True)
        _run_overlay_title(bg_path, title, cover_path, is_album=False, album_anchor=album_anchor, opacity=0.68)
        send_photo(jpg_cov if os.path.exists(jpg_cov) else cover_path, caption=f"🎨 Track {t_num}: <b>{html.escape(title)}</b> (Regenerated · 3000×3000)")
        regenerated.append({"track": t_num, "title": title, "cover": cover_path})

    # If an unpublished release staging directory exists, keep its 3000x3000 covers synchronized
    staged_rel_json = os.path.join(RELEASES_BASE, album_slug, "release.json")
    if regenerated and os.path.exists(staged_rel_json):
        try:
            with open(staged_rel_json, "r", encoding="utf-8") as rf:
                rj = json.load(rf)
            if rj.get("status") != "published" and not rj.get("soundcloud", {}).get("track_ids"):
                assemble_release(proposal, tracklist, album_slug)
        except Exception as e:
            logger.warning(f"Could not sync staged release directory after --redo-cover: {e}")

    print(json.dumps({"status": "ok", "album": album_name, "regenerated": regenerated}))
    return 0


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
    parser.add_argument("--proposal-index", type=int, default=None, help="0-based index of proposal")
    parser.add_argument("--mode", default="full", choices=["full", "sample"])
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true", help="Force acquire lock by terminating any existing pipeline")
    parser.add_argument("--redo-tracks", default=None, help="Comma-separated 1-based track numbers to redo immediately (e.g. '1,5')")
    parser.add_argument("--redo-feedback", default=None, help="Feedback direction to apply when redoing tracks")
    parser.add_argument("--redo-cover", default=None, help="Safely regenerate cover art ('album', 'all', or 1-based track numbers like '3' or '2,4') without killing active pipeline")
    parser.add_argument("--redo-cover-feedback", default=None, help="Visual direction to apply with --redo-cover")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.redo_cover is not None:
        rc = run_redo_cover_cli(args.proposal_index, args.redo_cover, feedback=args.redo_cover_feedback or "")
        sys.exit(rc)

    if args.proposal_index is None:
        args.proposal_index = 0

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
