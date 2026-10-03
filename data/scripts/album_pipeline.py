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

# Import logger_hub if available
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import logger_hub
except ImportError:
    logger_hub = None

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

# Cost constants
VENICE_IMAGE_GEN_COST = 0.04
VENICE_IMAGE_EDIT_COST = 0.04
VENICE_UPSCALE_COST = 0.02


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
            "cover_generation": 0.0,
            "cover_regeneration": 0.0,
            "cover_edits": 0.0,
            "cover_upscale": 0.0,
            "mastering": 0.0,
            "redo_count": 0,
            "cover_regen_count": 0,
            "cover_edit_count": 0,
        }
    return state["costs"]


def add_cost(state, category, amount):
    costs = init_cost_tracker(state)
    costs[category] = costs.get(category, 0) + amount
    save_state(state)


def get_total_cost(state):
    costs = state.get("costs", {})
    return sum(v for k, v in costs.items() if isinstance(v, (int, float)) and k not in ("redo_count", "cover_regen_count", "cover_edit_count"))


def format_cost_summary(state, album_name):
    costs = state.get("costs", {})
    total = get_total_cost(state)
    track_count = len(state.get("tracklist", []))
    lines = [
        f"💰 <b>{album_name}</b> — Production Cost Summary",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"🎵 Track Production:    ${costs.get('track_production', 0):.2f}  ({track_count} tracks)",
    ]
    if costs.get("track_redos", 0) > 0:
        lines.append(f"🔄 Track Redos:         ${costs.get('track_redos', 0):.2f}  ({costs.get('redo_count', 0)} redos)")
    lines.extend([
        f"🎨 Cover Generation:    ${costs.get('cover_generation', 0):.2f}",
    ])
    if costs.get("cover_regeneration", 0) > 0:
        lines.append(f"🔄 Cover Regeneration:  ${costs.get('cover_regeneration', 0):.2f}  ({costs.get('cover_regen_count', 0)} regens)")
    if costs.get("cover_edits", 0) > 0:
        lines.append(f"✏️ Cover Edits:         ${costs.get('cover_edits', 0):.2f}  ({costs.get('cover_edit_count', 0)} edits)")
    lines.extend([
        f"⬆️ Cover Upscale:       ${costs.get('cover_upscale', 0):.2f}",
        f"🎛️ DAWAGENT Mastering:  $0.00  (local)",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>Total: ${total:.2f}</b>  (${total/max(track_count,1):.2f}/track)",
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
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _send_tg_request("sendMessage", payload)


def edit_message(message_id, text, reply_markup=None):
    if not message_id:
        return None
    payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _send_tg_request("editMessageText", payload)


def send_agent_notification(text):
    return send_message(f"[pipeline] {text}")


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


def stylize_title(title):
    try:
        res = subprocess.run(["/opt/hermes/.venv/bin/python3", STYLIZE_SCRIPT, title], capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            styled = res.stdout.strip()
            if '->' in styled:
                styled = styled.split('->')[-1].strip()
            return styled
    except Exception:
        pass
    return title


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

    sorted_sessions = sorted(
        found_sessions.values(),
        key=lambda x: (x.get("processed_at") or "", x.get("mtime", 0))
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

    prop_tracks = proposal.get("tracks", [])
    cover_visual = proposal.get("visual", "")
    album_theme = f"{subgenre}. {proposal.get('brief', '')}".strip()
    cmd = [
        "/opt/hermes/.venv/bin/python3", PRODUCE_SCRIPT,
        "--brief", brief,
        "--tracks", "5",
        "--duration", str(duration),
        "--mode", mode,
        "--quality", "standard",
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
    stderr_lines = []

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
                        dashboard.update_track(cur_num, f"Track {cur_num}", "generating", progress_pct=prog.get("elapsed_sec", 10) % 100, sub_phase=prog.get("phase_name"))
                        dashboard.live_cost = prog.get("total_cost", dashboard.live_cost)
                except Exception:
                    pass
            time.sleep(0.5)
            continue

        logger.info(f"Produce output: {line}")

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
                t_cost = data.get("cost", "2.29")
                tracklist.append(data)
                if dashboard:
                    dashboard.update_track(t_num, t_title, "complete", bpm=t_bpm, cost=t_cost)
                    dashboard.live_cost += float(t_cost)
                if state:
                    state["completed_tracks"] = tracklist
                    save_state(state)
                continue
        except (ValueError, json.JSONDecodeError):
            pass

        # Text format regex: "[produce-album]     ✅ EYEWALL | 160 BPM | $3.85"
        import re
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
                state["completed_tracks"] = tracklist
                save_state(state)
            if logger_hub:
                logger_hub.log_event("TRACK_COMPLETE", track_entry, album=album_name, phase=1, track_num=track_num)

    process.wait()

    if process.returncode != 0:
        err_out = process.stderr.read()
        logger.error(f"Produce album failed with code {process.returncode}: {err_out[-300:]}")
        if logger_hub:
            logger_hub.log_failure("PRODUCE_SCRIPT_FAIL", f"Exit {process.returncode}: {err_out[-200:]}", traceback_str=err_out, album=album_name, phase=1)
        if dashboard:
            dashboard.set_error(f"Production script failed (exit {process.returncode}): {err_out[-150:]}", track_num=track_num+1)
            # Interactive Error Recovery Gate
            send_message(f"⚠️ <b>Production halted on Track {track_num+1}</b>\nTap Retry to re-attempt or Skip to continue.")
            while True:
                flag, content = poll_flags(timeout_hours=1)
                if flag == "error:retry":
                    dashboard.clear_error()
                    return phase_1_produce(proposal, profile, mode=mode, duration=duration, dashboard=dashboard, state=state)
                elif flag == "error:skip":
                    dashboard.clear_error()
                    break
                elif flag == "error:log":
                    send_message(f"📋 <b>Error Log:</b>\n<pre>{err_out[-800:]}</pre>")
                    continue

    # Locate actual MP3 and FLAC files
    album_slug = proposal.get('album', '').lower().replace(' ', '-').replace('_', '-')
    prod_dirs = sorted(glob.glob(f"/opt/data/music/productions/*{album_slug}*"))
    for i, t in enumerate(tracklist):
        if i < len(prod_dirs):
            d = prod_dirs[i]
            mp3s = sorted(glob.glob(os.path.join(d, "*.mp3")))
            flacs = sorted(glob.glob(os.path.join(d, "*.flac")))
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
        if dashboard:
            dashboard.set_error("Production failed: 0 tracks produced", track_num=1)
        send_message(f"🚨 <b>Production failed:</b> No audio tracks were produced for <b>{album_name}</b>. Halting pipeline.")
        sys.exit(1)

    if logger_hub:
        logger_hub.log_event("PHASE_COMPLETE", {"tracks_count": len(tracklist)}, album=album_name, phase=1)

    return tracklist


# ── Single Track Redo ───────────────────────────────────────────────────
def phase_1_redo_single(proposal, profile, tracklist, track_num, feedback=None, duration=260, dashboard=None):
    album_name = proposal.get('album', 'Unknown Album')
    subgenre = proposal.get('subgenre', 'dark nightride trap')

    original = next((t for t in tracklist if t.get('track') == track_num), None)
    if not original:
        send_message(f"❌ Track {track_num} not found in tracklist")
        return tracklist

    title = original.get('title', f'Track {track_num}')
    bpm = original.get('bpm', '130')
    key = original.get('key', 'Cm')

    cover_visual = proposal.get("visual", "")
    brief = f"{album_name} - {subgenre}. Track {track_num}: {title}. {proposal.get('brief', '')} {bpm} BPM, {key}. "
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
    if feedback:
        brief += f"\n[REDO FEEDBACK]: {feedback}\n"

    if dashboard:
        dashboard.update_track(track_num, title, "generating", progress_pct=30, sub_phase=f"Redoing: {feedback[:30] if feedback else 'tweak'}")

    send_message(f"🔄 Redoing Track {track_num}: <b>{title}</b>...")

    ctx = {
        "track_number": track_num,
        "total_tracks": len(tracklist),
        "album_name": album_name,
        "album_theme": f"{subgenre}. {proposal.get('brief', '')}",
        "cover_visual": cover_visual,
        "track_title": title,
        "brief": brief,
        "variation_rules": [f"Redo with feedback: {feedback}"] if feedback else []
    }
    ctx_file = f"/tmp/album_ctx_redo_{track_num}.json"
    with open(ctx_file, "w") as f:
        json.dump(ctx, f)

    cmd = [
        "/opt/hermes/.venv/bin/python3", MASTER_PRODUCER_SCRIPT,
        "--prompt", brief,
        "--duration", str(duration),
        "--quality", "standard",
        "--director",
        "--title", title,
        "--no-deliver"
    ]
    env = os.environ.copy()
    env["ALBUM_CONTEXT_FILE"] = ctx_file
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)

    if proc.returncode != 0:
        send_message(f"❌ Track {track_num} redo failed: {proc.stderr[:100]}")
        if logger_hub:
            logger_hub.log_failure("REDO_FAIL", proc.stderr, album=album_name, phase=1, track_num=track_num)
        return tracklist

    # Update track files
    album_slug = album_name.lower().replace(' ', '-').replace('_', '-')
    prod_dirs = sorted(glob.glob(f"/opt/data/music/productions/*{album_slug}*"))
    if prod_dirs:
        latest_dir = prod_dirs[-1]
        mp3s = sorted(glob.glob(os.path.join(latest_dir, "*.mp3")))
        flacs = sorted(glob.glob(os.path.join(latest_dir, "*.flac")))
        if mp3s:
            original["mp3_path"] = mp3s[-1]
        if flacs:
            original["flac_path"] = flacs[-1]
        original["production_dir"] = latest_dir

    if dashboard:
        dashboard.update_track(track_num, title, "complete")

    send_message(f"✅ Track {track_num}: <b>{title}</b> redone successfully!")
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
        elif any(k in s_lower for k in ["texture", "pad", "atmosphere", "accent", "sfx"]):
            plan_parts.append(
                f"{s_name}: x42 High-Pass Filter (cut < 220Hz) + Dragonfly Hall Reverb (cavernous 3.5s) + "
                f"Calf Stereo Tools (140% stereo width)"
            )
        elif any(k in s_lower for k in ["no_drum", "instrument", "main"]):
            plan_parts.append(
                f"{s_name}: Calf 8-Band EQ (sculpt mids 1.5-4kHz) + LSP Compressor (musical glue 3:1) + Dragonfly Room"
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

        # Check for demucs stems
        demucs_dirs = glob.glob(os.path.join(prod_dir, "stems", "demucs", "htdemucs", "*"))
        if demucs_dirs and os.path.isdir(demucs_dirs[0]):
            d_dir = demucs_dirs[0]
            d_drums = os.path.join(d_dir, "drums.wav")
            d_nodrums = os.path.join(d_dir, "no_drums.wav")
            if os.path.exists(d_drums) and os.path.exists(d_nodrums):
                stems_to_use = [d_drums, d_nodrums]
                stem_names = ["Drums", "Instrumentation"]

        # If no demucs stems, check for main/texture stems
        if not stems_to_use:
            raw_stems = sorted(glob.glob(os.path.join(prod_dir, "stems", "*.wav")) + glob.glob(os.path.join(prod_dir, "stems", "*.mp3")))
            valid_stems = [s for s in raw_stems if not s.endswith("_fx.wav")]
            if len(valid_stems) >= 2:
                stems_to_use = valid_stems
                stem_names = [Path(s).stem.replace('_', ' ').title() for s in valid_stems]

        # Fallback to pre-mixed wav/flac if stems unavailable
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
            "--bpm", str(t_bpm if str(t_bpm).isdigit() else 120),
            "--stems", ",".join(stems_to_use),
            "--stem-names", ",".join(stem_names),
            "--plan", dsp_plan,
            "--source", "album_pipeline",
            "--notes", f"{album_name} Track {i}: {title_plain} ({subgenre}, {t_key})"
        ]
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
        import tempfile
        album_name = proposal.get("album", "ALBUM").replace(" ", "-")
        pack_dir = os.path.join(tempfile.gettempdir(), f"flac-{album_name}")
        os.makedirs(pack_dir, exist_ok=True)

        flac_files = []
        for idx, t in enumerate(tracklist):
            flac = t.get("master_path") or t.get("flac_path")
            if flac and os.path.exists(flac):
                title = t.get("title", f"Track_{idx+1}")
                dest_name = f"{(idx+1):02d}-{title.replace(' ', '-')}.flac"
                dest = os.path.join(pack_dir, dest_name)
                shutil.copy2(flac, dest)
                flac_files.append(dest_name)
            elif t.get("mp3_path") and os.path.exists(t["mp3_path"]):
                dest_name = f"{(idx+1):02d}-{t.get('title', f'Track_{idx+1}').replace(' ', '-')}.mp3"
                dest = os.path.join(pack_dir, dest_name)
                shutil.copy2(t["mp3_path"], dest)
                flac_files.append(dest_name)

        if not flac_files:
            send_message(f"⚠️ No completed audio tracks found for <b>{album_name}</b> yet. Production is currently in progress.")
            shutil.rmtree(pack_dir, ignore_errors=True)
            return

        # M3U8 playlist - ONLY when all tracks are present
        total_expected = len(tracklist) if tracklist else 5
        has_playlist = len(flac_files) >= total_expected and total_expected > 1
        if has_playlist:
            playlist_path = os.path.join(pack_dir, f"{album_name}.m3u8")
            with open(playlist_path, "w", encoding="utf-8") as pf:
                pf.write("#EXTM3U\n")
                for fname in flac_files:
                    title_clean = os.path.splitext(fname)[0].split("-", 1)[-1].replace("-", " ")
                    pf.write(f"#EXTINF:-1,{title_clean}\nD:\\music\\exports\\{album_name}\\{fname}\n")

        # Tag metadata
        tag_script = "/opt/data/skills/delivery-receipt/scripts/tag_metadata.py"
        if os.path.exists(tag_script):
            subprocess.run(["/opt/hermes/.venv/bin/python3", tag_script, "--dir", pack_dir], capture_output=True, timeout=60)

        # Share via Cloudflare tunnel & local service
        res = subprocess.run(["/opt/hermes/.venv/bin/python3", SHARE_SCRIPT, "--path", pack_dir], capture_output=True, text=True, timeout=120)
        external_link = None
        internal_link = None
        local_path = None
        for line in res.stdout.splitlines():
            if "[EXTERNAL LINK]" in line:
                external_link = line.split("[EXTERNAL LINK]")[-1].strip()
            elif "[INTERNAL LINK]" in line:
                internal_link = line.split("[INTERNAL LINK]")[-1].strip()
            elif "[SUCCESS] Packaged successfully:" in line:
                linux_path = line.split("[SUCCESS] Packaged successfully:")[-1].strip()
                if linux_path.startswith("/opt/data/music/"):
                    local_path = linux_path.replace("/opt/data/music/", "D:\\music\\").replace("/", "\\")
                else:
                    local_path = linux_path

        pl_suffix = " + VLC playlist" if has_playlist else ""
        msg = (
            f"📦 <b>{html.escape(album_name)} — Full Master Archive</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎵 {len(flac_files)} Tracks (48kHz/32-bit Studio FLACs{pl_suffix})\n\n"
        )
        if external_link:
            msg += f"🌐 <b>External Download (Cloudflare / Mobile):</b>\n🔗 <a href='{external_link}'>{external_link}</a>\n\n"
        if internal_link:
            msg += f"🏠 <b>Internal Download (Tailscale / LAN):</b>\n🔗 <a href='{internal_link}'>{internal_link}</a>\n\n"
        if local_path:
            msg += f"📁 <b>Windows Local File:</b>\n<code>{html.escape(local_path)}</code>\n"

        send_message(msg)
        shutil.rmtree(pack_dir, ignore_errors=True)
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


def upsample_image_prompt_k3(title, core_concept, subgenre="", is_album=False, custom_notes=""):
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
        "5. CRITICAL CONSTRAINT: The generated prompt MUST be under 1200 characters (around 150 words). Be densely atmospheric and concise.\n\n"
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

    models_to_try = ["kimi-k3", "qwen-3-7-plus"]
    for model_name in models_to_try:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_input}
            ],
            "temperature": 0.7,
            "max_tokens": 1800
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
    models = ["qwen-image-3-pro", "grok-imagine-image-quality"]

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

        send_message("⬆️ Upscaling clean background artwork to 3000×3000...")
        upscale_artwork_venice(cover_bg)
        if state:
            add_cost(state, "cover_upscale", VENICE_UPSCALE_COST)

    if os.path.exists(OVERLAY_TITLE_SCRIPT) and os.path.exists(cover_bg):
        styled_album = stylize_title(album_name)
        logger.info(f"Overlaying title '{styled_album}' with chromatic opposite color onto 3000x3000 canvas...")
        subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                        "--image", cover_bg, "--title", styled_album, "--auto-color", "--output", cover_path], capture_output=True)
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
            f"🌙 Phase: <i>{moon_phase}</i> | 📐 3000×3000 Ultra-HD\n"
            f"<i>Review cover below — tap Approve, Regenerate, or Edit:</i>"
        )
        send_file = jpg_path if os.path.exists(jpg_path) else cover_path
        send_photo(send_file, caption=caption, reply_markup={"inline_keyboard": buttons})

    _send_album_review_card()

    while True:
        flag, content = poll_flags()
        if flag == "albumcover_approved":
            send_message("✅ Album cover approved!")
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

            send_message("⬆️ Upscaling edited background to 3000×3000...")
            upscale_artwork_venice(cover_bg)
            if state:
                add_cost(state, "cover_upscale", VENICE_UPSCALE_COST)

            if os.path.exists(OVERLAY_TITLE_SCRIPT):
                styled_album = stylize_title(album_name)
                logger.info(f"Overlaying title '{styled_album}' with chromatic opposite color onto 3000x3000 canvas...")
                subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                                "--image", cover_bg, "--title", styled_album, "--auto-color", "--output", cover_path], capture_output=True)
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
            return (
                f"Track title: {title}. Subgenre: {genre}. Energy & mood: {energy}. "
                f"Main sonic DNA: {main_p}. Texture elements: {tex_p}. Album atmosphere: {visual}"
            )
        except Exception as e:
            logger.warning(f"Failed to read production_plan.json for {title}: {e}")

    direction = track_item.get('direction', track_item.get('genre', subgenre))
    return f"Track title: {title}. Style: {direction}. Album visual concept: {visual}"


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
                                "--image", bg_backup, "--title", styled_title, "--bottom", "--auto-color", "--output", cover_path], capture_output=True)
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
            send_message(f"⬆️ <b>Upscaling all {len(track_cover_paths)} track covers to 3000×3000 with crisp inverted typography...</b>")
            for i, cp in enumerate(track_cover_paths):
                track_title = os.path.basename(cp).replace('_cover.png', '').replace('_cover.jpg', '')
                bg_path = os.path.join(track_art_dir, f"{track_title}_cover_bg.png")
                send_message(f"⚙️ [{(i+1)}/{len(track_cover_paths)}] Upscaling clean background for <b>{html.escape(track_title)}</b>...")
                if os.path.exists(bg_path):
                    upscale_artwork_venice(bg_path)
                    if os.path.exists(OVERLAY_TITLE_SCRIPT):
                        styled_title = stylize_title(track_title)
                        subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                                        "--image", bg_path, "--title", styled_title, "--bottom", "--auto-color", "--output", cp], capture_output=True)
                else:
                    upscale_artwork_venice(cp)
                if state:
                    add_cost(state, "cover_upscale", VENICE_UPSCALE_COST)
                jpg_cp = os.path.splitext(cp)[0] + '.jpg'
                try:
                    from PIL import Image
                    with Image.open(cp) as im:
                        im.convert('RGB').save(jpg_cp, 'JPEG', quality=95)
                except Exception:
                    pass
            send_message("✅ <b>All track covers upscaled to 3000×3000!</b> Assembling final release package for your review & confirmation...")
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
                                            "--image", bg_path, "--title", styled_title, "--bottom", "--auto-color", "--output", cover_path], capture_output=True)
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
                                            "--image", bg_path, "--title", styled_title, "--bottom", "--auto-color", "--output", cover_path], capture_output=True)
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
                        "--image", bg_img, "--title", styled_title, "--bottom", "--auto-color", "--output", dest_cov
                    ], capture_output=True, timeout=30)
                except Exception as oe:
                    logger.warning(f"Re-overlay title error on {dest_cov}: {oe}")

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

    # 4. Write playlist
    with open(os.path.join(release_dir, f"{album_slug}_playlist.m3u8"), "w", encoding="utf-8") as pf:
        pf.write("#EXTM3U\n")
        for idx, title in enumerate(tracks, 1):
            clean_title = title.replace(" ", "_")
            pf.write(f"#EXTINF:-1,VØIDRIDE - {title}\n")
            pf.write(f"{idx:02d}_{clean_title}_MASTER.flac\n")

    # 5. Tag metadata & embed artwork directly into FLACs
    tag_script = "/opt/data/skills/delivery-receipt/scripts/tag_metadata.py"
    if os.path.exists(tag_script):
        try:
            logger.info(f"Tagging metadata & embedding artwork into FLACs for release: {album_slug}")
            subprocess.run(["/opt/hermes/.venv/bin/python3", tag_script, "--release", album_slug], capture_output=True, text=True, timeout=120)
        except Exception as e:
            logger.error(f"tag_metadata failed: {e}")

    return release_dir


# ── Phase 6: Final Review Gate & Deliverables ───────────────────────────
def phase_6_final_review(proposal, tracklist=None, state=None, dashboard=None):
    if dashboard:
        dashboard.set_phase(6)
    album_name = proposal.get('album', 'release')
    album_slug = album_name.lower().replace(' ', '-')

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
    album_release_dir = f"/opt/data/music/releases/{album_slug}"
    ext_link = None
    int_link = None
    local_path = None
    if os.path.exists(album_release_dir):
        try:
            share_res = subprocess.run(["/opt/hermes/.venv/bin/python3", SHARE_SCRIPT, "--path", album_release_dir], capture_output=True, text=True, timeout=180)
            for line in share_res.stdout.splitlines():
                if "[EXTERNAL LINK]" in line:
                    ext_link = line.split("[EXTERNAL LINK]")[-1].strip()
                elif "[INTERNAL LINK]" in line:
                    int_link = line.split("[INTERNAL LINK]")[-1].strip()
                elif "[SUCCESS] Packaged successfully:" in line:
                    lp = line.split("[SUCCESS] Packaged successfully:")[-1].strip()
                    if lp.startswith("/opt/data/music/"):
                        local_path = lp.replace("/opt/data/music/", "D:\\music\\").replace("/", "\\")
                    else:
                        local_path = lp
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
        f"🖼️ Exactly 1 cover per track + album cover (styled with opposite key color).\n\n"
    )
    if ext_link:
        msg += f"🌐 <b>External Download (Cloudflare / Mobile):</b>\n🔗 <a href='{ext_link}'>{ext_link}</a>\n\n"
    if int_link:
        msg += f"🏠 <b>Internal Download (Tailscale / LAN):</b>\n🔗 <a href='{int_link}'>{int_link}</a>\n\n"
    if local_path:
        msg += f"📁 <b>Windows Local File:</b>\n<code>{html.escape(local_path)}</code>\n\n"
    msg += (
        "<b>Please review all reference masters and artwork above.</b>\n"
        "👉 <i>When you are ready, tap <b>Confirm: Good to Proceed to SoundCloud</b> to push live:</i>"
    )

    send_message(msg, reply_markup={"inline_keyboard": final_buttons})
    logger.info("Sent final review package & publishing gate to Telegram. Polling for decisions...")

    # 5. Poll for user decision
    while True:
        flag, content = poll_flags()
        if flag == "final_publish":
            logger.info("User confirmed publish. Pushing to SoundCloud...")
            send_message(f"🚀 <b>Publishing {html.escape(album_name)} to SoundCloud...</b>\n<i>Uploading 24-bit studio FLAC masters and synchronized covers. Live progress will be reported below.</i>")
            cmd = ["/opt/hermes/.venv/bin/python3", PUBLISH_SCRIPT, "--release", album_slug, "--confirm", "--force"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                logger.info(f"Published {album_name} to SoundCloud successfully.")
                send_agent_notification(f"Published {album_name} to SoundCloud")
            else:
                send_message(f"❌ SoundCloud upload failed:\n<pre>{html.escape(res.stderr[:300])}</pre>")
                if logger_hub:
                    logger_hub.log_failure("PUBLISH_FAIL", res.stderr, album=album_name, phase=6)
            return "published"
        elif flag == "final_edit_songs":
            return "edit_songs"
        elif flag == "final_edit_album":
            return "edit_album"
        elif flag == "final_edit_covers":
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
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        run_test_mode(args.proposal_index)
        return

    clear_flags()
    state = load_state()
    mode = args.mode
    duration = args.duration if args.duration else (20 if mode == "sample" else 260)

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

    acquire_lock(force=args.force)
    init_cost_tracker(state)

    # Auto-discover existing completed masters and artwork on disk
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

    try:
        while True:
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
                    tracklist = phase_1_redo_single(proposal, profile, tracklist, t_num, fb, duration=duration, dashboard=dashboard)
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
                    cost_summary = format_cost_summary(state, proposal.get('album', 'Release'))
                    send_message(cost_summary)
                    if os.path.exists(STATE_FILE):
                        try: os.remove(STATE_FILE)
                        except Exception: pass
                    break
    finally:
        release_lock()
        clear_flags()

    logger.info("Pipeline execution complete.")


if __name__ == "__main__":
    main()
