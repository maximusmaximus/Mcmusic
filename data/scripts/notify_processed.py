#!/usr/bin/env python3
"""
notify_processed.py — Watches dawagent exports for completed sessions.
Runs inside hermes-music. Picks up notification.json files and sends
detailed production receipts back to the user via Telegram.

The receipt includes:
- Per-stem processing chains (what EQ/comp/reverb was applied)
- Audio stats per track (duration, file size, LUFS estimate)
- Master bus chain details
- Overall session summary

Usage:
  python3 notify_processed.py &
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

EXPORTS_DIR = Path(os.environ.get("DAWAGENT_EXPORTS", "/opt/data/dawagent/exports"))
MUSIC_EXPORTS = Path(os.environ.get("MUSIC_EXPORTS", "/opt/data/music/exports"))
SESSIONS_DIR = Path(os.environ.get("DAWAGENT_SESSIONS", "/opt/data/dawagent/sessions"))
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")
CHECK_INTERVAL = 30
SENT_MARKER = ".notified"
RECEIPT_FILE = "production_receipt.json"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[notify-processed {ts}] {msg}", flush=True)


def send_telegram(text, chat_id=None, parse_mode=None):
    """Send a message via Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        log("No TELEGRAM_BOT_TOKEN — skipping send")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id or CHAT_ID,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        log(f"Telegram send error: {e}")
        return False


def send_audio(filepath, session, title, performer="DAWAGENT", chat_id=None):
    """Send audio file via Telegram as playable audio."""
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(filepath):
        return False

    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    if size_mb > 49:
        log(f"  File too large for Telegram ({size_mb:.1f} MB), skipping: {filepath}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio"
    try:
        result = subprocess.run([
            "curl", "-s", "-X", "POST", url,
            "-F", f"chat_id={chat_id or CHAT_ID}",
            "-F", f"audio=@{filepath}",
            "-F", f"title={title}",
            "-F", f"performer={performer}",
            "-F", f"caption=🎛️ Mastered by DAWAGENT"
        ], capture_output=True, text=True, timeout=180)
        resp = json.loads(result.stdout)
        return resp.get("ok", False)
    except Exception as e:
        log(f"Audio send error: {e}")
        return False


def send_document(filepath, session, title, performer="DAWAGENT", chat_id=None):
    """Send a FLAC or other file via Telegram sendDocument (lossless delivery)."""
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(filepath):
        return False

    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    if size_mb > 49:
        log(f"  File too large for Telegram ({size_mb:.1f} MB), skipping: {filepath}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    caption = f"🎵 {title} — {performer}" if title else f"🎛️ Mastered by {performer}"
    try:
        result = subprocess.run([
            "curl", "-s", "-X", "POST", url,
            "-F", f"chat_id={chat_id or CHAT_ID}",
            "-F", f"document=@{filepath}",
            "-F", f"caption={caption}"
        ], capture_output=True, text=True, timeout=180)
        resp = json.loads(result.stdout)
        return resp.get("ok", False)
    except Exception as e:
        log(f"Document send error: {e}")
        return False


def get_audio_stats(filepath):
    """Get audio file stats using ffprobe."""
    stats = {"file": os.path.basename(filepath)}
    try:
        size = os.path.getsize(filepath)
        stats["size_mb"] = round(size / (1024 * 1024), 1)
    except Exception:
        stats["size_mb"] = 0

    try:
        # Duration + sample rate + channels
        r = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", filepath
        ], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            info = json.loads(r.stdout)
            fmt = info.get("format", {})
            stats["duration_s"] = round(float(fmt.get("duration", 0)), 1)
            stats["duration"] = format_duration(float(fmt.get("duration", 0)))
            stats["bitrate_kbps"] = round(int(fmt.get("bit_rate", 0)) / 1000)
            for stream in info.get("streams", []):
                if stream.get("codec_type") == "audio":
                    stats["sample_rate"] = int(stream.get("sample_rate", 0))
                    stats["channels"] = int(stream.get("channels", 0))
                    stats["codec"] = stream.get("codec_name", "?")
                    stats["bit_depth"] = stream.get("bits_per_raw_sample", "?")
                    break
    except Exception as e:
        log(f"  ffprobe error for {filepath}: {e}")

    # Try loudnorm analysis for LUFS
    try:
        r = subprocess.run([
            "ffmpeg", "-i", filepath, "-af",
            "loudnorm=print_format=json:I=-14:TP=-1:LRA=11",
            "-f", "null", "-"
        ], capture_output=True, text=True, timeout=60)
        # Parse loudnorm JSON from stderr
        stderr = r.stderr
        json_start = stderr.rfind("{")
        json_end = stderr.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            lufs_data = json.loads(stderr[json_start:json_end])
            stats["integrated_lufs"] = float(lufs_data.get("input_i", 0))
            stats["true_peak_db"] = float(lufs_data.get("input_tp", 0))
            stats["lra"] = float(lufs_data.get("input_lra", 0))
    except Exception as e:
        log(f"  LUFS analysis error for {filepath}: {e}")

    return stats


def format_duration(seconds):
    """Format seconds as M:SS."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def read_handoff(session_name):
    """Read the handoff manifest for processing details."""
    manifest_path = SESSIONS_DIR / session_name / "handoff.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            return json.load(f)
    return None


def build_receipt(session_name, notif, handoff):
    """Build a detailed production receipt."""
    receipt = {
        "session": session_name,
        "processed_at": notif.get("processed_at", datetime.now().isoformat()),
        "source": notif.get("source", "?"),
        "pipeline": "hermes-music → DAWAGENT (ffmpeg auto-processor)",
        "tracks": [],
        "summary": {},
    }

    export_dir = Path(notif.get("export_dir", str(EXPORTS_DIR / session_name)))
    processing_plan = handoff.get("processing_plan", {}) if handoff else {}
    stems_info = handoff.get("stems", []) if handoff else []

    # Group stems by track (e.g., Ignition_Vector_Drums → Ignition_Vector)
    track_stems = {}
    for stem in stems_info:
        name = stem.get("name", "")
        # Split off the stem type suffix
        for suffix in ("_Drums", "_Bass", "_Vocals", "_Other", "_drums", "_bass", "_vocals", "_other"):
            if name.endswith(suffix):
                track_name = name[:-len(suffix)]
                stem_type = suffix.lstrip("_")
                if track_name not in track_stems:
                    track_stems[track_name] = []
                chain = processing_plan.get(name, [])
                chain_str = " → ".join(chain) if isinstance(chain, list) and chain else "auto-detected"
                track_stems[track_name].append({
                    "stem": stem_type,
                    "chain": chain_str,
                    "source_file": os.path.basename(stem.get("file", "")),
                })
                break
        else:
            # Single-stem track (no suffix match)
            if name not in track_stems:
                track_stems[name] = []
            chain = processing_plan.get(name, [])
            chain_str = " → ".join(chain) if isinstance(chain, list) and chain else "auto-detected"
            track_stems[name].append({
                "stem": "full",
                "chain": chain_str,
                "source_file": os.path.basename(stem.get("file", "")),
            })

    # Analyze each master file
    total_duration = 0
    total_size_mb = 0
    track_names = notif.get("tracks", list(track_stems.keys()))

    for track_name in track_names:
        track_info = {"name": track_name.replace("_", " "), "stems": []}

        # Get stem processing details
        if track_name in track_stems:
            track_info["stems"] = track_stems[track_name]

        # Analyze master WAV
        master_wav = export_dir / f"{track_name}_MASTER.wav"
        master_mp3 = export_dir / f"{track_name}_MASTER.mp3"
        analysis_file = master_wav if master_wav.exists() else master_mp3

        if analysis_file.exists():
            stats = get_audio_stats(str(analysis_file))
            track_info["stats"] = stats
            total_duration += stats.get("duration_s", 0)
            total_size_mb += stats.get("size_mb", 0)

        # Check for processed stems
        processed_stems = sorted(export_dir.glob(f"{track_name}_*_processed.wav"))
        track_info["processed_stem_count"] = len(processed_stems)

        receipt["tracks"].append(track_info)

    receipt["summary"] = {
        "total_tracks": len(track_names),
        "total_stems_processed": notif.get("stem_count", len(stems_info)),
        "total_duration": format_duration(total_duration),
        "total_duration_s": round(total_duration, 1),
        "total_size_mb": round(total_size_mb, 1),
        "bpm": notif.get("bpm", handoff.get("bpm", "?") if handoff else "?"),
        "master_bus_chain": "Compressor 2:1 (glue, 30ms attack) → Limiter -1dB TP → Loudness -14 LUFS",
        "sample_rate": "48000 Hz",
        "bit_depth": "24-bit",
        "format": "WAV (PCM s24le) + MP3 320kbps",
    }

    return receipt


def format_receipt_telegram(receipt):
    """Format receipt as a compact Telegram message with action buttons."""
    session = receipt["session"].replace("_", " ").replace("-", " ").upper()
    summary = receipt["summary"]

    # Compact track list
    track_list = []
    for i, track in enumerate(receipt["tracks"], 1):
        name = track["name"]
        stats = track.get("stats", {})
        dur = stats.get("duration", "?")
        track_list.append(f"  {i}. {name} ({dur})")

    lines = [
        f"🎛️ *{session}* — mastered",
        f"🎵 {summary['total_tracks']} tracks · {summary['total_duration']} · {summary['total_size_mb']} MB",
        "",
    ]
    lines.extend(track_list)
    lines.append("")
    lines.append(f"📁 FLAC 48kHz/24-bit · {summary.get('bpm', '?')} BPM")

    return "\n".join(lines)


def build_receipt_buttons(session):
    """Build inline keyboard buttons for post-mastering actions."""
    slug = session.replace("_", "-")
    return [
        [{"text": "🚀 Publish to SoundCloud", "callback_data": f"pub:{slug}:go"}],
        [{"text": "👀 Preview audio first", "callback_data": f"pub:{slug}:preview"}],
        [{"text": "🔄 Regenerate", "callback_data": f"pub:{slug}:regen"}],
        [{"text": "⏭️ Skip", "callback_data": f"pub:{slug}:skip"}],
    ]


def check_notifications():
    """Scan exports for new notification.json files."""
    if not EXPORTS_DIR.exists():
        return

    for session_dir in sorted(EXPORTS_DIR.iterdir()):
        if not session_dir.is_dir():
            continue

        notif_path = session_dir / "notification.json"
        sent_path = session_dir / SENT_MARKER

        if notif_path.exists() and not sent_path.exists():
            try:
                with open(notif_path) as f:
                    notif = json.load(f)

                session = notif.get("session", session_dir.name)
                log(f"New notification: {session}")

                # Read the handoff manifest for processing details
                handoff = read_handoff(session)

                # Build detailed receipt
                receipt = build_receipt(session, notif, handoff)
                receipt_text = format_receipt_telegram(receipt)

                # Save receipt JSON
                receipt_path = session_dir / RECEIPT_FILE
                with open(receipt_path, "w") as f:
                    json.dump(receipt, f, indent=2)
                log(f"  Receipt saved: {receipt_path}")

                # Send compact receipt with action buttons via Telegram
                buttons = build_receipt_buttons(session)
                payload = {
                    "chat_id": CHAT_ID,
                    "text": receipt_text,
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": buttons},
                }
                if TELEGRAM_BOT_TOKEN:
                    import urllib.request as _ur
                    _req = _ur.Request(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"})
                    try:
                        _ur.urlopen(_req, timeout=15)
                        log("  ✓ Receipt + buttons sent")
                    except Exception as _e:
                        log(f"  ⚠ Receipt send failed: {_e}")
                        # Fallback: send without buttons
                        send_telegram(receipt_text)

                # ── GAP 4: Copy FLAC + MP3 to music/exports/ ──
                music_exports = Path("/opt/data/music/exports") / session
                music_exports.mkdir(parents=True, exist_ok=True)
                copied_count = 0
                for ext in ("*.flac", "*.mp3"):
                    for f in sorted(session_dir.glob(ext)):
                        dst = music_exports / f.name
                        if not dst.exists():
                            import shutil
                            shutil.copy2(str(f), str(dst))
                            copied_count += 1
                if copied_count:
                    log(f"  ✓ Copied {copied_count} files to {music_exports}")

                # ── Tag all audio files with metadata + cover art ──
                tag_script = os.path.join(
                    os.environ.get("HERMES_HOME", "/opt/data"),
                    "skills/delivery-receipt/delivery-receipt/scripts/tag_metadata.py")
                if os.path.exists(tag_script):
                    try:
                        tag_result = subprocess.run(
                            ["python3", tag_script, "--session", session],
                            capture_output=True, text=True, timeout=300)
                        if tag_result.returncode == 0:
                            tagged = sum(1 for l in tag_result.stdout.splitlines() if "✓" in l)
                            log(f"  ✓ Tagged {tagged} files with metadata")
                        else:
                            log(f"  ⚠ Tagging failed: {tag_result.stderr[-100:]}")
                    except Exception as tag_err:
                        log(f"  ⚠ Tagging error: {tag_err}")

                # Send master FLACs via Telegram (prefer lossless; fall back to MP3)
                flacs = sorted(music_exports.glob("*_MASTER.flac"))
                if flacs:
                    for flac in flacs:
                        title = flac.stem.replace("_MASTER", "").replace("_", " ")
                        if send_document(str(flac), session, title):
                            log(f"  ✓ Sent FLAC: {title}")
                        else:
                            log(f"  ✗ Failed: {title}")
                        time.sleep(2)  # Rate limit
                else:
                    # Fallback to MP3 if no FLACs
                    for mp3 in sorted(music_exports.glob("*_MASTER.mp3")):
                        title = mp3.stem.replace("_MASTER", "").replace("_", " ")
                        if send_audio(str(mp3), session, title):
                            log(f"  ✓ Sent MP3: {title}")
                        else:
                            log(f"  ✗ Failed: {title}")
                        time.sleep(2)  # Rate limit

                # Also copy WAV masters if FLAC doesn't exist yet
                for f in sorted(session_dir.glob("*_MASTER.wav")):
                    dst_flac = music_exports / f.name.replace(".wav", ".flac")
                    dst_mp3 = music_exports / f.name.replace(".wav", ".mp3")
                    if not dst_flac.exists():
                        import shutil
                        shutil.copy2(str(f), music_exports / f.name)

                # ── GAP 5: Auto-tag metadata ──
                try:
                    tag_script = os.path.join(
                        os.environ.get("HERMES_HOME", "/opt/data"),
                        "skills", "delivery-receipt", "delivery-receipt",
                        "scripts", "tag_metadata.py"
                    )
                    # Read metadata from both notification and handoff manifest
                    manifest_path = SESSIONS_DIR / session / "handoff.json"
                    tracks_json = None
                    profile = None
                    album_name = None
                    genre = notif.get("genre", "")
                    artist_name = None
                    if manifest_path.exists():
                        manifest = json.load(open(manifest_path))
                        album_name = manifest.get("album", "")
                        profile = manifest.get("profile", "")
                        if not genre:
                            genre = manifest.get("genre", "")
                    # Also check notification for album/profile (now forwarded from manifest)
                    if not album_name:
                        album_name = notif.get("album", "")
                    if not profile:
                        profile = notif.get("profile", "")
                    # Fallback: parse album from session name (e.g. "kinetic-overdrive-nitro-surge")
                    if not album_name:
                        # If session has 3+ hyphenated parts, first 2 are likely the album
                        parts = session.split("-")
                        if len(parts) >= 3:
                            album_name = " ".join(parts[:2]).upper()
                        else:
                            album_name = session.replace("_", " ").replace("-", " ").upper()
                    # Use profile as artist, fall back to default
                    if profile:
                        artist_name = profile
                    else:
                        artist_name = "VØIDRIDE"

                    # Look for tracks_meta.json in exports
                    meta_path = music_exports / "tracks_meta.json"
                    if not meta_path.exists():
                        # Try the dawagent export dir
                        alt_meta = session_dir / "tracks_meta.json"
                        if alt_meta.exists():
                            import shutil
                            shutil.copy2(str(alt_meta), str(meta_path))

                    # Build a tracks_meta.json from notification if none exists
                    # This ensures BPM, key, and genre reach tag_metadata.py per-track
                    if not meta_path.exists():
                        bpm = notif.get("bpm", "")
                        key = notif.get("key", "")
                        title = notif.get("title", session.replace("_", " ").replace("-", " ").title())
                        tracks_meta_data = [{
                            "title": title,
                            "bpm": bpm,
                            "key": key,
                            "genre": genre,
                        }]
                        with open(meta_path, "w") as mf:
                            json.dump(tracks_meta_data, mf, indent=2)
                        log(f"  Created tracks_meta.json from notification data")

                    if os.path.isfile(tag_script):
                        tag_cmd = [sys.executable, tag_script,
                                   "--session", session]
                        if artist_name:
                            tag_cmd.extend(["--artist", artist_name])
                        if album_name:
                            tag_cmd.extend(["--album", album_name])
                        if genre:
                            tag_cmd.extend(["--genre", genre])
                        if meta_path.exists():
                            tag_cmd.extend(["--tracks-json", str(meta_path)])

                        import subprocess as _sp
                        tr = _sp.run(tag_cmd, capture_output=True, text=True, timeout=120)
                        if tr.returncode == 0:
                            log(f"  ✓ Metadata tagged")
                        else:
                            log(f"  ⚠ Tagging failed: {tr.stderr[-200:]}")
                    else:
                        log(f"  ⚠ tag_metadata.py not found")
                except Exception as e:
                    log(f"  ⚠ Tagging error: {e}")

                # ── GAP 7: Create VLC playlist with Windows FLAC paths ──
                try:
                    flacs = sorted(music_exports.glob("*.flac"))
                    if flacs:
                        playlist_path = music_exports / f"{session}_playlist.m3u8"
                        win_dir = f"D:\\music\\exports\\{session}"
                        with open(playlist_path, "w", encoding="utf-8") as pl:
                            pl.write("#EXTM3U\n")
                            for f in flacs:
                                title = f.stem.replace("_MASTER", "").replace("_", " ")
                                pl.write(f"#EXTINF:-1,{title}\n")
                                pl.write(f"{win_dir}\\{f.name}\n")
                        log(f"  ✓ Playlist created: {playlist_path}")

                        # Send playlist as document via Telegram
                        if TELEGRAM_BOT_TOKEN:
                            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
                            try:
                                result = subprocess.run([
                                    "curl", "-s", "-X", "POST", url,
                                    "-F", f"chat_id={CHAT_ID}",
                                    "-F", f"document=@{playlist_path}",
                                    "-F", f"caption=🎧 VLC Playlist: {session} ({len(flacs)} FLAC tracks)\nOpen in VLC on Windows",
                                ], capture_output=True, text=True, timeout=30)
                                if '"ok":true' in result.stdout:
                                    log(f"  ✓ Playlist sent via Telegram")
                                else:
                                    log(f"  ⚠ Playlist send failed")
                            except Exception as e:
                                log(f"  ⚠ Playlist send error: {e}")
                except Exception as e:
                    log(f"  ⚠ Playlist creation error: {e}")

                # Generate local FLAC copies + VLC playlist via delivery-receipt skill
                try:
                    deliver_script = os.path.join(
                        os.environ.get("HERMES_HOME", "/opt/data"),
                        "skills", "delivery-receipt", "delivery-receipt",
                        "scripts", "deliver_receipt.py"
                    )
                    if os.path.isfile(deliver_script):
                        import subprocess as _sp
                        dr = _sp.run(
                            [sys.executable, deliver_script,
                             "--session", session, "--send-telegram"],
                            capture_output=True, text=True, timeout=300,
                        )
                        if dr.returncode == 0:
                            log(f"  ✓ Delivery receipt + VLC playlist sent")
                        else:
                            log(f"  ⚠ Delivery receipt failed: {dr.stderr[-200:]}")
                    else:
                        log(f"  ⚠ deliver_receipt.py not found at {deliver_script}")
                except Exception as e:
                    log(f"  ⚠ Delivery receipt error: {e}")

                # Mark as sent
                sent_path.write_text(datetime.now().isoformat())
                log(f"✓ Receipt + audio + playlist sent for {session}")

                # ── Combined album playlist: detect sibling sessions ──
                try:
                    parts = session.split("-")
                    if len(parts) >= 3:
                        album_prefix = "-".join(parts[:2])  # e.g. "kinetic-overdrive"
                        album_label = " ".join(parts[:2]).upper()
                    else:
                        album_prefix = session
                        album_label = session.upper()

                    # Find all sibling sessions (same album prefix)
                    sibling_dirs = sorted([
                        d for d in MUSIC_EXPORTS.iterdir()
                        if d.is_dir() and d.name.startswith(album_prefix + "-") and d.name != album_prefix
                    ])

                    # Check if ALL siblings have been delivered
                    if len(sibling_dirs) >= 2:
                        all_sent = all((d / ".notified").exists() for d in sibling_dirs)
                        combined_playlist = MUSIC_EXPORTS / f"{album_prefix.upper().replace('-', '_')}_playlist.m3u8"

                        if all_sent and not combined_playlist.exists():
                            log(f"  All {len(sibling_dirs)} tracks for {album_label} delivered — creating combined playlist")
                            with open(combined_playlist, "w", encoding="utf-8") as pl:
                                pl.write("#EXTM3U\n")
                                pl.write(f"#PLAYLIST:{album_label} — VØIDRIDE\n")
                                for sd in sibling_dirs:
                                    flacs = sorted(sd.glob("*.flac"))
                                    for flac in flacs:
                                        title = flac.stem.replace("_MASTER", "").replace("_", " ")
                                        # Remove album prefix from title
                                        title_clean = title.replace(album_prefix.replace("-", " "), "").strip().upper()
                                        if not title_clean:
                                            title_clean = title.upper()
                                        win_path = f"D:\\music\\exports\\{sd.name}\\{flac.name}"
                                        pl.write(f"#EXTINF:-1,{title_clean}\n")
                                        pl.write(f"{win_path}\n")

                            log(f"  ✓ Combined playlist: {combined_playlist}")

                            # Send combined playlist to Telegram
                            if TELEGRAM_BOT_TOKEN:
                                try:
                                    result = subprocess.run([
                                        "curl", "-s", "-X", "POST",
                                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                                        "-F", f"chat_id={CHAT_ID}",
                                        "-F", f"document=@{combined_playlist}",
                                        "-F", f"caption=🎧 {album_label} — Full Album Playlist ({len(sibling_dirs)} tracks)\nOpen in VLC: D:\\music\\exports\\{combined_playlist.name}",
                                    ], capture_output=True, text=True, timeout=30)
                                    if '"ok":true' in result.stdout:
                                        log(f"  ✓ Combined playlist sent via Telegram")
                                    else:
                                        log(f"  ⚠ Combined playlist send failed")
                                except Exception as e:
                                    log(f"  ⚠ Combined playlist send error: {e}")
                except Exception as e:
                    log(f"  ⚠ Combined playlist error: {e}")

            except Exception as e:
                log(f"Error processing notification {notif_path}: {e}")
                import traceback
                traceback.print_exc()


def main():
    log("Starting notification watcher (with receipts)")
    log(f"Watching: {EXPORTS_DIR}")
    log(f"Sessions: {SESSIONS_DIR}")

    while True:
        try:
            check_notifications()
        except Exception as e:
            log(f"Error: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
