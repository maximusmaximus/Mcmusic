#!/usr/bin/env python3
"""
send_windows_playlist.py — Handles "send the windows playlist link to review"

Finds the latest (or specified) production export, ensures the Windows VLC .m3u8 playlist exists,
packages the release via secure-share for a live Cloudflare download link,
and delivers both the Windows playlist and package link to Telegram.
"""

import argparse
import json
import os
import sys
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

# Path resolution for both container and Windows host
if sys.platform == "win32":
    EXPORTS_DIR = Path(r"D:\music\exports")
    WIN_MUSIC_ROOT = r"D:\music"
else:
    EXPORTS_DIR = Path(os.environ.get("LOCAL_EXPORTS", "/opt/data/music/exports"))
    WIN_MUSIC_ROOT = os.environ.get("WIN_MUSIC_ROOT", r"D:\music")

CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")

def get_bot_token():
    for candidate in [
        Path("D:/sp2/data/config.yaml"),
        Path("/opt/data/config.yaml"),
        Path("D:/hermes-music/data/config.yaml"),
        Path("/mnt/d/sp2/data/config.yaml"),
        Path("D:/sp2/.env"),
        Path("/opt/data/.env"),
    ]:
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    if "bot_token:" in line:
                        token = line.split(":", 1)[1].strip().strip('\"').strip('\x27')
                        if token:
                            return token
                    elif "TELEGRAM_BOT_TOKEN=" in line:
                        token = line.split("=", 1)[1].strip().strip('\"').strip('\x27')
                        if token:
                            return token
            except Exception:
                pass
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")

def find_target_session(requested_session=None):
    if requested_session:
        session_path = EXPORTS_DIR / requested_session
        if session_path.exists():
            return session_path
        # Also check releases
        releases_dir = EXPORTS_DIR.parent / "releases" / requested_session
        if releases_dir.exists():
            return releases_dir

    if not EXPORTS_DIR.exists():
        return None

    # Find the most recently modified subdirectory in exports
    subdirs = [p for p in EXPORTS_DIR.iterdir() if p.is_dir()]
    if not subdirs:
        return None
    subdirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return subdirs[0]

def ensure_windows_playlist(session_dir):
    session_name = session_dir.name
    # Check for existing playlist
    playlists = list(session_dir.glob("*.m3u8")) + list(session_dir.glob("*.m3u"))
    if playlists:
        return playlists[0]

    # Look for audio files
    audio_files = []
    for ext in ["*.flac", "*.mp3", "*.wav"]:
        audio_files.extend(list(session_dir.glob(ext)))
    
    if not audio_files:
        return None

    # Sort audio files by name
    audio_files.sort(key=lambda p: p.name)

    playlist_path = session_dir / f"{session_name}_playlist.m3u8"
    win_session_path = f"{WIN_MUSIC_ROOT}\\exports\\{session_name}"
    album_title = session_name.replace("-", " ").replace("_", " ").upper()

    with open(playlist_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write(f"#PLAYLIST:{album_title} (Windows Local Review)\n")
        for i, audio in enumerate(audio_files, 1):
            f.write(f"#EXTINF:-1,{i}. {audio.stem}\n")
            f.write(f"{win_session_path}\\{audio.name}\n")

    print(f"[PLAYLIST] Generated Windows playlist: {playlist_path}")
    return playlist_path

def package_and_get_link(session_dir):
    # Locate deliver_release.py or share.py
    candidate_scripts = [
        Path("/opt/data/skills/secure-share/scripts/deliver_release.py"),
        Path(__file__).resolve().parent.parent.parent / "secure-share" / "scripts" / "deliver_release.py",
        Path("D:/sp2/data/skills/secure-share/scripts/deliver_release.py"),
        Path("C:/Users/maxin/.gemini/antigravity/skills/secure-share/scripts/deliver_release.py"),
        Path("/opt/data/skills/secure-share/scripts/share.py"),
        Path("D:/sp2/data/skills/secure-share/scripts/share.py"),
        Path("C:/Users/maxin/.gemini/antigravity/skills/secure-share/scripts/share.py"),
    ]

    script = None
    for c in candidate_scripts:
        if c.exists():
            script = c
            break

    if not script:
        return None

    cmd = [sys.executable, str(script), "--path", str(session_dir)]
    print(f"[PACKAGE] Executing: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)

    import re
    for line in proc.stdout.splitlines():
        if "[EXTERNAL LINK]" in line or "trycloudflare.com" in line:
            m = re.search(r'(https?://[^\s]+)', line)
            if m:
                return m.group(1)
    return None

def send_telegram_doc(token, chat_id, filepath, caption=""):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    cmd = [
        "curl", "-s", "-X", "POST", url,
        "-F", f"chat_id={chat_id}",
        "-F", f"document=@{filepath}",
        "-F", f"caption={caption}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout).get("ok", False)
    except Exception as e:
        print(f"Error sending document: {e}")
        return False

def send_telegram_msg(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Send Windows playlist and review package to Telegram")
    parser.add_argument("--session", default=None, help="Session name (defaults to most recent export)")
    parser.add_argument("--chat_id", default=CHAT_ID, help="Telegram chat ID")
    args = parser.parse_args()

    token = get_bot_token()
    if not token:
        print("Error: No bot token found.")
        sys.exit(1)

    session_dir = find_target_session(args.session)
    if not session_dir:
        print("Error: No export session found.")
        sys.exit(1)

    session_name = session_dir.name
    print(f"[SESSION] Target session: {session_name} ({session_dir})")

    # 0. Ensure all tracks are tagged with VØIDRIDE metadata & embedded artwork
    tag_candidates = [
        Path(__file__).resolve().parent / "tag_metadata.py",
        Path("/opt/data/skills/delivery-receipt/delivery-receipt/scripts/tag_metadata.py"),
        Path("/opt/data/skills/delivery-receipt/scripts/tag_metadata.py"),
        Path(r"D:\sp2\data\skills\delivery-receipt\delivery-receipt\scripts\tag_metadata.py"),
    ]
    tag_script = next((p for p in tag_candidates if p.exists()), None)
    if tag_script:
        print(f"[METADATA] Stamping metadata & embedding artwork for {session_name}...")
        try:
            subprocess.run([sys.executable, str(tag_script), "--dir", str(session_dir)], capture_output=True, timeout=60)
        except Exception as e:
            print(f"[METADATA] Tagging warning: {e}")

    # 1. Ensure Windows Playlist exists
    playlist_path = ensure_windows_playlist(session_dir)

    # 2. Package release and get Cloudflare link
    external_link = package_and_get_link(session_dir)

    # 3. Format paths
    win_playlist = f"{WIN_MUSIC_ROOT}\\exports\\{session_name}\\{playlist_path.name}" if playlist_path else "N/A"
    album_title = session_name.replace("-", " ").replace("_", " ").upper()

    # 4. Send Playlist file to Telegram
    if playlist_path and playlist_path.exists():
        caption = f"🎶 <b>{album_title}</b> — Windows VLC Playlist (.m3u8)"
        print(f"[TELEGRAM] Sending playlist document: {playlist_path.name}")
        send_telegram_doc(token, args.chat_id, str(playlist_path), caption)

    # 5. Send Summary & Cloudflare Download Link
    msg_lines = [
        f"📀 <b>{album_title} — Windows Review Package</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📂 <b>Local Win Path:</b> <code>{WIN_MUSIC_ROOT}\\exports\\{session_name}</code>",
        f"🎶 <b>VLC Playlist:</b> <code>{win_playlist}</code>",
        "",
    ]

    if external_link:
        msg_lines.extend([
            f"🔗 <b>Download ZIP Archive:</b> <a href=\"{external_link}\">{session_name}.zip</a>",
            "<i>(Includes all FLAC masters + Windows VLC playlist for remote/mobile download)</i>",
            "",
        ])
    else:
        msg_lines.append("⚠️ <i>External Cloudflare link could not be generated.</i>")

    msg_lines.append("▶️ <i>Open the attached .m3u8 in VLC on Windows to review all tracks with full metadata.</i>")

    full_text = "\n".join(msg_lines)
    print("[TELEGRAM] Sending review message...")
    ok = send_telegram_msg(token, args.chat_id, full_text)
    print(f"[RESULT] Telegram notification sent: {ok}")

if __name__ == "__main__":
    main()
