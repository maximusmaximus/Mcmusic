#!/usr/bin/env python3
"""
recall_exports.py — Find and list/send past production exports.

Used by hermes-music to answer "send me the FLACs" / "where are my files" requests.
Lists all available exports, finds MP3s for Telegram delivery, and provides
Windows-accessible paths for local FLAC access.

Usage:
  python3 recall_exports.py --list                    # List all available exports
  python3 recall_exports.py --session mars-descent-v2  # Details for a session
  python3 recall_exports.py --session mars-descent-v2 --send  # Send MP3s + receipt via TG
  python3 recall_exports.py --search "mars"           # Search by name
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

EXPORTS_DIR = Path(os.environ.get("LOCAL_EXPORTS", "/opt/data/music/exports"))
WIN_ROOT = os.environ.get("WIN_MUSIC_ROOT", r"D:\music")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")


def to_windows(path):
    s = str(path)
    if s.startswith("/opt/data/music/"):
        return os.path.join(WIN_ROOT, s[len("/opt/data/music/"):]).replace("/", "\\")
    return s


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except:
        return False


def list_exports():
    """List all available export sessions."""
    if not EXPORTS_DIR.exists():
        print(json.dumps({"exports": [], "error": "No exports directory"}))
        return

    sessions = []
    for d in sorted(EXPORTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        flacs = list(d.glob("*.flac"))
        mp3s = list(d.glob("*.mp3"))
        playlist = d / f"{d.name}_playlist.m3u8"
        receipt = d / f"{d.name}_receipt.json"

        sessions.append({
            "name": d.name,
            "flac_count": len(flacs),
            "mp3_count": len(mp3s),
            "has_playlist": playlist.exists(),
            "has_receipt": receipt.exists(),
            "windows_path": to_windows(d),
            "total_size_mb": round(sum(f.stat().st_size for f in flacs) / (1024*1024), 1) if flacs else 0,
        })

    print(json.dumps({"exports": sessions}, indent=2))


def session_details(session_name):
    """Get details for a specific session."""
    session_dir = EXPORTS_DIR / session_name
    if not session_dir.exists():
        # Try fuzzy match
        matches = [d.name for d in EXPORTS_DIR.iterdir() if session_name.lower() in d.name.lower()]
        if matches:
            print(json.dumps({"error": f"Session '{session_name}' not found", "did_you_mean": matches}))
        else:
            print(json.dumps({"error": f"Session '{session_name}' not found", "available": [d.name for d in EXPORTS_DIR.iterdir() if d.is_dir()]}))
        return

    tracks = []
    for flac in sorted(session_dir.glob("*_MASTER.flac")):
        name = flac.stem.replace("_MASTER", "").replace("_", " ")
        mp3 = flac.with_suffix("").with_name(flac.stem + ".mp3")
        if not mp3.exists():
            mp3 = session_dir / (flac.stem.replace(".flac", "") + ".mp3")

        tracks.append({
            "name": name,
            "flac": str(flac),
            "flac_windows": to_windows(flac),
            "flac_size_mb": round(flac.stat().st_size / (1024*1024), 1),
            "mp3": str(mp3) if mp3.exists() else None,
            "mp3_size_mb": round(mp3.stat().st_size / (1024*1024), 1) if mp3.exists() else 0,
        })

    playlist = session_dir / f"{session_name}_playlist.m3u8"

    result = {
        "session": session_name,
        "tracks": tracks,
        "track_count": len(tracks),
        "windows_folder": to_windows(session_dir),
        "playlist": to_windows(playlist) if playlist.exists() else None,
        "playlist_exists": playlist.exists(),
        "total_flac_mb": round(sum(t["flac_size_mb"] for t in tracks), 1),
        "total_mp3_mb": round(sum(t["mp3_size_mb"] for t in tracks), 1),
        "telegram_sendable": all(t["mp3"] for t in tracks),
    }
    print(json.dumps(result, indent=2))


def send_session(session_name):
    """Send MP3s + receipt for a session via Telegram."""
    session_dir = EXPORTS_DIR / session_name
    if not session_dir.exists():
        print(json.dumps({"error": f"Session '{session_name}' not found"}))
        return

    mp3s = sorted(session_dir.glob("*_MASTER.mp3"))
    if not mp3s:
        print(json.dumps({"error": "No MP3 files found — run deliver_receipt.py first"}))
        return

    # Send info message first
    lines = [f"📂 {session_name.upper().replace('-', ' ')} — File Recall"]
    lines.append(f"📁 Windows: {to_windows(session_dir)}")
    playlist = session_dir / f"{session_name}_playlist.m3u8"
    if playlist.exists():
        lines.append(f"🎶 Playlist: {to_windows(playlist)}")
    lines.append(f"\n🎵 Sending {len(mp3s)} MP3s (320kbps)...")
    lines.append(f"💿 FLACs available locally at the Windows path above")
    send_telegram("\n".join(lines))

    # Send MP3s
    sent = 0
    for i, mp3 in enumerate(mp3s, 1):
        name = mp3.stem.replace("_MASTER", "").replace("_", " ")
        try:
            r = subprocess.run([
                "curl", "-s", "-X", "POST",
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio",
                "-F", f"chat_id={CHAT_ID}",
                "-F", f"audio=@{mp3}",
                "-F", f"title={i}. {name}",
                "-F", f"performer={session_name.upper().replace('-', ' ')}",
            ], capture_output=True, text=True, timeout=120)
            if json.loads(r.stdout).get("ok"):
                sent += 1
                print(f"  ✓ {name}")
            time.sleep(2)
        except Exception as e:
            print(f"  ✗ {name}: {e}")

    # Send playlist
    if playlist.exists():
        time.sleep(1)
        subprocess.run([
            "curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
            "-F", f"chat_id={CHAT_ID}",
            "-F", f"document=@{playlist}",
            "-F", f"caption=🎶 VLC Playlist — open to play all tracks",
        ], capture_output=True, text=True, timeout=60)

    print(json.dumps({"sent": sent, "total": len(mp3s), "session": session_name}))


def search_exports(query):
    """Search exports by name."""
    if not EXPORTS_DIR.exists():
        print(json.dumps({"results": []}))
        return

    results = []
    for d in sorted(EXPORTS_DIR.iterdir()):
        if d.is_dir() and query.lower() in d.name.lower():
            flacs = list(d.glob("*.flac"))
            results.append({
                "name": d.name,
                "tracks": len(flacs),
                "windows_path": to_windows(d),
            })
    print(json.dumps({"query": query, "results": results}, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Recall past production exports")
    parser.add_argument("--list", action="store_true", help="List all exports")
    parser.add_argument("--session", help="Session name to get details for")
    parser.add_argument("--send", action="store_true", help="Send MP3s via Telegram")
    parser.add_argument("--search", help="Search exports by name")
    args = parser.parse_args()

    if args.search:
        search_exports(args.search)
    elif args.session and args.send:
        send_session(args.session)
    elif args.session:
        session_details(args.session)
    elif args.list:
        list_exports()
    else:
        list_exports()


if __name__ == "__main__":
    main()
