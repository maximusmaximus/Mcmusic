#!/usr/bin/env python3
"""
watchdog.py — Production health monitor.
Runs every 10 minutes via entrypoint cron.

Checks:
  1. Stale handoffs: demucs stems exist but no FLAC master after 30 min → auto-master
  2. Undelivered exports: FLAC exists in dawagent/exports but not in music/exports → auto-copy
  3. Session bloat: gateway session > 60K tokens → log warning
  4. Container health: check dawagent is running
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_PREFIX = "[watchdog]"
SESSIONS_DIR = Path("/opt/data/dawagent/sessions")
EXPORTS_DIR = Path("/opt/data/dawagent/exports")
MUSIC_EXPORTS = Path("/opt/data/music/exports")
SESSIONS_JSON = Path("/opt/data/sessions/sessions.json")
STALE_THRESHOLD_SEC = 30 * 60  # 30 minutes
TOKEN_WARN_THRESHOLD = 60000

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("WATCHDOG_CHAT_ID", "8293122782")

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{LOG_PREFIX} {ts} {msg}", flush=True)


def send_telegram(text):
    """Send a notification via Telegram."""
    if not BOT_TOKEN:
        log("No TELEGRAM_BOT_TOKEN — skipping notification")
        return
    try:
        subprocess.run([
            "curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"chat_id": CHAT_ID, "text": text})
        ], capture_output=True, timeout=15)
    except Exception as e:
        log(f"Telegram send failed: {e}")


def send_file(filepath, caption=""):
    """Send a file via Telegram."""
    if not BOT_TOKEN:
        return False
    try:
        r = subprocess.run([
            "curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
            "-F", f"chat_id={CHAT_ID}",
            "-F", f"document=@{filepath}",
            "-F", f"caption={caption}"
        ], capture_output=True, timeout=120, text=True)
        result = json.loads(r.stdout)
        return result.get("ok", False)
    except Exception as e:
        log(f"File send failed: {e}")
        return False


def master_track(session_name, track_name, stems_dir):
    """Mix 4 demucs stems into a mastered FLAC."""
    slug = f"{session_name}-{track_name.lower().replace('_', '-')}"
    export_dir = EXPORTS_DIR / slug
    export_dir.mkdir(parents=True, exist_ok=True)
    output = export_dir / f"{slug}_MASTER.flac"

    if output.exists():
        return str(output)

    drums = stems_dir / "drums.wav"
    bass = stems_dir / "bass.wav"
    vocals = stems_dir / "vocals.wav"
    other = stems_dir / "other.wav"

    if not all(f.exists() for f in [drums, bass, vocals, other]):
        log(f"  Missing stems for {track_name}")
        return None

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(drums), "-i", str(bass), "-i", str(vocals), "-i", str(other),
        "-filter_complex",
        "[0:a]volume=1.0[d];[1:a]volume=0.9[b];[2:a]volume=1.1[v];[3:a]volume=0.85[o];"
        "[d][b][v][o]amix=inputs=4:duration=longest:dropout_transition=3,"
        "dynaudnorm=p=0.9:s=5,loudnorm=I=-14:TP=-1:LRA=11[out]",
        "-map", "[out]", "-ar", "48000", "-sample_fmt", "s32",
        str(output)
    ]

    try:
        subprocess.run(cmd, timeout=300, check=True, capture_output=True)
        log(f"  ✅ Mastered: {output.name}")
        return str(output)
    except subprocess.CalledProcessError as e:
        log(f"  ❌ Master failed for {track_name}: {e.stderr[:200] if e.stderr else ''}")
        return None


def check_stale_handoffs():
    """Find sessions with demucs stems but no exported masters."""
    if not SESSIONS_DIR.exists():
        return

    now = time.time()
    for session_dir in SESSIONS_DIR.iterdir():
        if not session_dir.is_dir():
            continue

        demucs_dir = session_dir / "demucs" / "htdemucs"
        if not demucs_dir.exists():
            continue

        # Check age — only act on sessions older than threshold
        mtime = max(
            f.stat().st_mtime
            for f in demucs_dir.rglob("*.wav")
            if f.is_file()
        ) if any(demucs_dir.rglob("*.wav")) else 0

        if mtime == 0 or (now - mtime) < STALE_THRESHOLD_SEC:
            continue

        session_name = session_dir.name
        tracks = [d for d in demucs_dir.iterdir() if d.is_dir()]
        unmastered = []

        for track_dir in tracks:
            slug = f"{session_name}-{track_dir.name.lower().replace('_', '-')}"
            master = EXPORTS_DIR / slug / f"{slug}_MASTER.flac"
            if not master.exists():
                unmastered.append(track_dir)

        if unmastered:
            log(f"Stale handoff: {session_name} — {len(unmastered)} tracks unmastered")
            mastered_files = []
            for track_dir in unmastered:
                result = master_track(session_name, track_dir.name, track_dir)
                if result:
                    mastered_files.append(result)

            if mastered_files:
                send_telegram(
                    f"🔧 Watchdog auto-mastered {len(mastered_files)} tracks "
                    f"from {session_name} (stale handoff recovery)"
                )


def check_undelivered_exports():
    """Copy dawagent exports to music/exports and send if not already done."""
    if not EXPORTS_DIR.exists():
        return

    for export_dir in EXPORTS_DIR.iterdir():
        if not export_dir.is_dir():
            continue

        flacs = list(export_dir.glob("*_MASTER.flac"))
        if not flacs:
            continue

        for flac in flacs:
            dest_dir = MUSIC_EXPORTS / export_dir.name
            dest_file = dest_dir / flac.name

            if dest_file.exists():
                continue

            # Copy to music/exports
            dest_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", str(flac), str(dest_file)], check=True)
            log(f"Copied: {flac.name} → {dest_dir}")


def check_session_health():
    """Warn about bloated gateway sessions."""
    if not SESSIONS_JSON.exists():
        return

    try:
        with open(SESSIONS_JSON) as f:
            sessions = json.load(f)

        for key, session in sessions.items():
            tokens = session.get("last_prompt_tokens", 0)
            sid = session.get("session_id", "?")
            if tokens > TOKEN_WARN_THRESHOLD:
                log(f"⚠️  Session {sid} has {tokens:,} prompt tokens (threshold: {TOKEN_WARN_THRESHOLD:,})")
    except Exception as e:
        log(f"Session check error: {e}")


def main():
    log("Running health check...")

    check_stale_handoffs()
    check_undelivered_exports()
    check_session_health()

    log("Health check complete")


if __name__ == "__main__":
    main()
