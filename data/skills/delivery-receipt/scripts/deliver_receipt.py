#!/usr/bin/env python3
"""
deliver_receipt.py — Generates production receipts with local FLAC links
and VLC playlists for Windows review.

Copies mastered files from DAWAGENT exports (Podman volume) to the shared
music directory (D:\music\exports\ on Windows), creates .m3u8 playlists,
and sends everything via Telegram.

Path mapping:
  Container: /opt/data/music/exports/  →  WSL: /mnt/d/music/exports/  →  Windows: D:\music\exports\

Usage:
  python3 deliver_receipt.py --session spatial-ship --send-telegram
  python3 deliver_receipt.py --session spatial-ship --no-send  (generate only)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path


# ─── Path Configuration ──────────────────────────────────────────────────
# Container paths (inside hermes-music)
DAWAGENT_EXPORTS = Path(os.environ.get("DAWAGENT_EXPORTS", "/opt/data/dawagent/exports"))
DAWAGENT_SESSIONS = Path(os.environ.get("DAWAGENT_SESSIONS", "/opt/data/dawagent/sessions"))
LOCAL_EXPORTS = Path(os.environ.get("LOCAL_EXPORTS", "/opt/data/music/exports"))

# Windows path root — /opt/data/music/ maps to D:\music\ via WSL mount
WIN_MUSIC_ROOT = os.environ.get("WIN_MUSIC_ROOT", r"D:\music")

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[delivery-receipt {ts}] {msg}", flush=True)


def to_windows_path(container_path):
    """Convert container path to Windows path.
    /opt/data/music/exports/spatial-ship/file.flac
    → D:\\music\\exports\\spatial-ship\\file.flac
    """
    container_path = str(container_path)
    if container_path.startswith("/opt/data/music/"):
        relative = container_path[len("/opt/data/music/"):]
        return os.path.join(WIN_MUSIC_ROOT, relative).replace("/", "\\")
    return container_path


def send_telegram(text):
    """Send a text message via Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        log("No bot token — skipping Telegram")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        log(f"Telegram error: {e}")
        return False


def send_document(filepath, caption=""):
    """Send a file via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(filepath):
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        r = subprocess.run([
            "curl", "-s", "-X", "POST", url,
            "-F", f"chat_id={CHAT_ID}",
            "-F", f"document=@{filepath}",
            "-F", f"caption={caption}",
        ], capture_output=True, text=True, timeout=120)
        resp = json.loads(r.stdout)
        return resp.get("ok", False)
    except Exception as e:
        log(f"Document send error: {e}")
        return False


def get_audio_stats(filepath):
    """Get audio stats via ffprobe."""
    stats = {"size_mb": 0, "duration": "?", "duration_s": 0}
    try:
        stats["size_mb"] = round(os.path.getsize(filepath) / (1024 * 1024), 1)
    except:
        pass
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", filepath],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            fmt = json.loads(r.stdout).get("format", {})
            dur = float(fmt.get("duration", 0))
            stats["duration_s"] = round(dur, 1)
            stats["duration"] = f"{int(dur // 60)}:{int(dur % 60):02d}"
    except:
        pass
    return stats


def convert_to_flac(wav_path, flac_path):
    """Convert WAV to FLAC 48kHz/24-bit."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_path), "-c:a", "flac", "-sample_fmt", "s32", str(flac_path)],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode == 0 and os.path.exists(flac_path)


def generate_receipt(session_name, send_telegram_flag=True):
    """Generate receipt, playlist, copy FLACs, and optionally send via Telegram."""

    export_src = DAWAGENT_EXPORTS / session_name
    session_src = DAWAGENT_SESSIONS / session_name
    local_dir = LOCAL_EXPORTS / session_name

    if not export_src.exists():
        log(f"Export directory not found: {export_src}")
        return None

    # Create local exports directory
    local_dir.mkdir(parents=True, exist_ok=True)

    # Read handoff for metadata
    handoff = {}
    handoff_path = session_src / "handoff.json"
    if handoff_path.exists():
        with open(handoff_path) as f:
            handoff = json.load(f)

    # Find all master WAVs
    master_wavs = sorted(export_src.glob("*_MASTER.wav"))
    if not master_wavs:
        # Fallback: look for any WAV files
        master_wavs = sorted(export_src.glob("*.wav"))

    log(f"Found {len(master_wavs)} master files for {session_name}")

    # Convert to FLAC and copy to local exports
    tracks = []
    for wav in master_wavs:
        track_name = wav.stem.replace("_MASTER", "")
        flac_name = f"{track_name}_MASTER.flac"
        flac_src = export_src / flac_name
        flac_dst = local_dir / flac_name

        # Convert WAV → FLAC if needed
        if not flac_src.exists():
            log(f"  Converting {wav.name} → FLAC...")
            if not convert_to_flac(wav, flac_src):
                log(f"  ✗ FLAC conversion failed for {wav.name}")
                continue

        # Copy FLAC to local exports
        if not flac_dst.exists() or flac_dst.stat().st_size != flac_src.stat().st_size:
            shutil.copy2(str(flac_src), str(flac_dst))
            log(f"  Copied: {flac_name}")

        # Also copy MP3 if it exists
        mp3_src = export_src / f"{track_name}_MASTER.mp3"
        mp3_dst = local_dir / f"{track_name}_MASTER.mp3"
        if mp3_src.exists() and (not mp3_dst.exists() or mp3_dst.stat().st_size != mp3_src.stat().st_size):
            shutil.copy2(str(mp3_src), str(mp3_dst))

        # Get stats
        stats = get_audio_stats(str(flac_dst))
        win_path = to_windows_path(flac_dst)

        tracks.append({
            "name": track_name.replace("_", " "),
            "flac_local": str(flac_dst),
            "flac_windows": win_path,
            "mp3_local": str(mp3_dst) if mp3_dst.exists() else None,
            "duration": stats["duration"],
            "duration_s": stats["duration_s"],
            "size_mb": stats["size_mb"],
        })

    if not tracks:
        log("No tracks to deliver")
        return None

    # ─── Tag Metadata & Embed Covers ─────────────────────────────────────
    tag_candidates = [
        Path(__file__).resolve().parent / "tag_metadata.py",
        Path("/opt/data/skills/delivery-receipt/delivery-receipt/scripts/tag_metadata.py"),
        Path("/opt/data/skills/delivery-receipt/scripts/tag_metadata.py"),
    ]
    tag_script = next((p for p in tag_candidates if p.exists()), None)
    if tag_script:
        log(f"Stamping metadata & embedding cover art in {local_dir}...")
        try:
            subprocess.run([sys.executable, str(tag_script), "--dir", str(local_dir)], capture_output=True, timeout=60)
        except Exception as e:
            log(f"Tagging error: {e}")

    # ─── Create VLC Playlist (.m3u8) ─────────────────────────────────────
    playlist_name = f"{session_name}_playlist.m3u8"
    playlist_path = local_dir / playlist_name
    album_name = session_name.replace("-", " ").replace("_", " ").upper()

    with open(playlist_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write(f"#PLAYLIST:{album_name} (DAWAGENT Mastered)\n")
        for i, track in enumerate(tracks, 1):
            dur_s = int(track["duration_s"])
            title = f"{i}. {track['name']}"
            f.write(f"#EXTINF:{dur_s},{title}\n")
            f.write(f"{track['flac_windows']}\n")

    log(f"Playlist created: {playlist_path}")

    # ─── Build receipt text ──────────────────────────────────────────────
    total_dur = sum(t["duration_s"] for t in tracks)
    total_size = sum(t["size_mb"] for t in tracks)
    bpm = handoff.get("bpm", "?")

    lines = []
    lines.append(f"📀 {album_name} — DAWAGENT Mastered")
    lines.append(f"{'═' * 40}")
    lines.append(f"🎵 {len(tracks)} tracks | {int(total_dur // 60)}:{int(total_dur % 60):02d} total | {total_size:.0f} MB")
    lines.append(f"📁 FLAC 48kHz/24-bit lossless")
    lines.append("")

    win_dir = to_windows_path(local_dir)
    lines.append(f"📂 Folder: {win_dir}")
    lines.append(f"🎶 Playlist: {win_dir}\\{playlist_name}")
    lines.append("")

    for i, track in enumerate(tracks, 1):
        lines.append(f"━━━ {i}. {track['name']} ━━━")
        lines.append(f"  ⏱ {track['duration']} | 💾 {track['size_mb']} MB")
        lines.append(f"  📄 {track['flac_windows']}")
        lines.append("")

    lines.append("▶️ Open the .m3u8 playlist in VLC to review all tracks")

    receipt_text = "\n".join(lines)

    # Save receipt
    receipt_path = local_dir / f"{session_name}_receipt.txt"
    with open(receipt_path, "w", encoding="utf-8") as f:
        f.write(receipt_text)

    # Save receipt JSON
    receipt_json = {
        "session": session_name,
        "album": album_name,
        "created_at": datetime.now().isoformat(),
        "tracks": tracks,
        "playlist": str(playlist_path),
        "playlist_windows": to_windows_path(playlist_path),
        "folder_windows": win_dir,
        "total_tracks": len(tracks),
        "total_duration": f"{int(total_dur // 60)}:{int(total_dur % 60):02d}",
        "total_size_mb": round(total_size, 1),
        "bpm": bpm,
    }
    json_path = local_dir / f"{session_name}_receipt.json"
    with open(json_path, "w") as f:
        json.dump(receipt_json, f, indent=2)

    log(f"Receipt saved: {receipt_path}")

    # ─── Send via Telegram ───────────────────────────────────────────────
    if send_telegram_flag:
        # Send receipt text
        ok = send_telegram(receipt_text)
        log(f"Receipt text sent: {ok}")

        # Send playlist file
        time.sleep(1)
        ok = send_document(str(playlist_path), f"🎶 {album_name} — VLC Playlist (.m3u8)\nOpen in VLC to play all tracks")
        log(f"Playlist file sent: {ok}")

    return receipt_json


def main():
    parser = argparse.ArgumentParser(description="Generate delivery receipt with FLAC links and VLC playlist")
    parser.add_argument("--session", required=True, help="Session name (e.g., spatial-ship)")
    parser.add_argument("--send-telegram", action="store_true", default=True, help="Send via Telegram (default: true)")
    parser.add_argument("--no-send", action="store_true", help="Don't send via Telegram (generate only)")
    args = parser.parse_args()

    result = generate_receipt(args.session, send_telegram_flag=not args.no_send)
    if result:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({"success": False, "error": "No tracks found"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
