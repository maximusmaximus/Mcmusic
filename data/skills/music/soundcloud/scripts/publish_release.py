#!/usr/bin/env python3
"""
publish_release.py — Gated, button-driven SoundCloud publishing.

Replaces the agent's ad-hoc publish workflow with a single script that:
  1. REVIEW GATE — Sends release summary + inline buttons to Telegram
  2. PUBLISH  — Uploads tracks (FLAC), creates playlist, artwork, tags, label
  3. DONE     — Sends compact confirmation with SoundCloud link

Usage:
  python3 publish_release.py --release mars-descent             # Full gated publish
  python3 publish_release.py --release mars-descent --preview    # Send audio for review first
  python3 publish_release.py --release mars-descent --confirm    # Skip review gate (auto-publish)
  python3 publish_release.py --release mars-descent --dry-run    # Preview what would be sent
  python3 publish_release.py --list                              # List release-ready albums
"""

import argparse
import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths ──
if sys.platform == "win32":
    RELEASES_DIR = Path(os.environ.get("RELEASES_DIR", r"D:\music\releases"))
    ARTWORK_DIR = Path(os.environ.get("ARTWORK_DIR", r"D:\music\artwork\covers"))
    SC_SCRIPT = Path(os.environ.get("SC_SCRIPT", r"D:\sp2\data\skills\music\soundcloud\scripts\soundcloud_api.py"))
else:
    RELEASES_DIR = Path(os.environ.get("RELEASES_DIR", "/opt/data/music/releases"))
    ARTWORK_DIR = Path(os.environ.get("ARTWORK_DIR", "/opt/data/music/artwork/covers"))
    SC_SCRIPT = Path(os.environ.get("SC_SCRIPT", "/opt/data/skills/music/soundcloud/scripts/soundcloud_api.py"))
def get_env_var(name, default=None):
    val = os.environ.get(name)
    if not val:
        try:
            env = open("/proc/1/environ").read().split(chr(0))
            for e in env:
                if e.startswith(f"{name}="):
                    val = e.split("=", 1)[1]
                    break
        except: pass
    if not val:
        try:
            import yaml
            cfg = yaml.safe_load(open("/opt/data/config.yaml"))
            val = cfg.get(name, cfg.get(name.lower()))
        except: pass
    return val or default

TELEGRAM_BOT_TOKEN = get_env_var("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = get_env_var("TELEGRAM_CHAT_ID", "8293122782")

# Default metadata
DEFAULT_LABEL = "VØIDRIDE"
DEFAULT_GENRE = "Electronic"
STYLIZE_SCRIPT = Path(r"D:\sp2\data\scripts\stylize_title.py") if sys.platform == "win32" else Path("/opt/data/scripts/stylize_title.py")


def stylize_title(title):
    """Convert plain title to VØIDRIDE Unicode aesthetic."""
    if STYLIZE_SCRIPT.exists():
        try:
            res = subprocess.run(
                [sys.executable, str(STYLIZE_SCRIPT), title],
                capture_output=True, text=True, timeout=10
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip().split('-> ')[-1]
        except Exception:
            pass
    return title.upper() if title else ""


def get_canonical_track_title(i, flac, manifest=None, tracks_meta=None):
    """Return uppercase canonical track title from manifest or metadata, falling back to clean flac stem."""
    if manifest and manifest.get("tracks") and i < len(manifest["tracks"]):
        return str(manifest["tracks"][i]).strip().upper()
    if tracks_meta and i < len(tracks_meta) and tracks_meta[i].get("title"):
        return str(tracks_meta[i]["title"]).strip().upper()
    import re
    clean = re.sub(r'^\d+[\s_\-]*', '', flac.stem.replace("_MASTER", "").replace("_", " "))
    return clean.strip().upper()


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[publish {ts}] {msg}", flush=True)


def send_telegram(text, buttons=None, parse_mode="HTML"):
    """Send a Telegram message, optionally with inline keyboard buttons."""
    if not TELEGRAM_BOT_TOKEN:
        log("No TELEGRAM_BOT_TOKEN — printing locally")
        print(text)
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    data = json.dumps(payload).encode()
    import urllib.request
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                return result.get("result", {}).get("message_id")
    except Exception as e:
        log(f"Telegram error: {e}")
    return None


def send_audio_file(filepath, title):
    """Send audio file via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(filepath):
        return False
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    if size_mb > 49:
        log(f"  File too large ({size_mb:.1f} MB), skipping")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        r = subprocess.run([
            "curl", "-s", "-X", "POST", url,
            "-F", f"chat_id={CHAT_ID}",
            "-F", f"document=@{filepath}",
            "-F", f"caption=🎵 {title}",
        ], capture_output=True, text=True, timeout=180)
        return '"ok":true' in r.stdout
    except Exception as e:
        log(f"Send error: {e}")
        return False


def load_release(release_name):
    """Load release manifest and track metadata."""
    release_dir = RELEASES_DIR / release_name
    if not release_dir.is_dir():
        return None, None, None

    manifest = {}
    manifest_path = release_dir / "release.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)

    tracks_meta = []
    meta_path = release_dir / "tracks_meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            tracks_meta = json.load(f)

    # Find FLAC masters
    flacs = sorted(release_dir.glob("*_MASTER.flac"))
    if not flacs:
        flacs = sorted(release_dir.glob("*.flac"))

    return manifest, tracks_meta, flacs


def find_artwork(release_name, track_title=None):
    """Find cover art for a release or specific track. Prefers JPG (smaller) over PNG."""
    slug = release_name.replace("-", "_")

    # Also check the release's own covers/ directory
    release_covers = RELEASES_DIR / release_name / "covers"
    search_dirs = []
    if release_covers.exists():
        search_dirs.append(release_covers)
    if ARTWORK_DIR.exists():
        search_dirs.append(ARTWORK_DIR)

    if track_title:
        title_slug = track_title.replace(" ", "_").lower()
        # Prefer JPG (under 10MB) over PNG (often 10-12MB, exceeds SC limit)
        for ext in ["*.jpg", "*.png"]:
            for search_dir in search_dirs:
                for f in search_dir.rglob(ext):
                    if title_slug in f.name.lower():
                        return f
        return None

    # Album/playlist artwork — prefer JPG
    for search_dir in search_dirs:
        for pattern in ["*album_cover*.jpg", "*album_cover*.png", "*album*.jpg", "*album*.png"]:
            for f in sorted(search_dir.rglob(pattern)):
                return f

    # Fallback: any image in a matching subdirectory
    if ARTWORK_DIR.exists():
        for d in ARTWORK_DIR.iterdir():
            if d.is_dir() and (slug in d.name or release_name in d.name):
                for f in sorted(d.glob("*.jpg")):
                    return f
                for f in sorted(d.glob("*.png")):
                    return f

    return None


def build_tags(track_meta, manifest):
    """Build 8-10 discoverable tags for a track."""
    tags = set()
    genre = track_meta.get("genre", manifest.get("genre", ""))
    if genre:
        for part in genre.replace("/", ",").replace("·", ",").split(","):
            part = part.strip().lower()
            if part and len(part) < 30:
                tags.add(part)

    bpm = track_meta.get("bpm")
    if bpm:
        tags.add(f"{bpm}bpm")
    key = track_meta.get("key")
    if key:
        tags.add(key.lower())

    tags.update(["electronic", "dark", "instrumental"])
    return list(tags)[:10]


def ensure_uploadable_artwork(artwork_path):
    """Ensure artwork is <= 9.5MB for SoundCloud/Telegram upload. Auto-converts large PNG to high-quality JPG."""
    if not artwork_path or not Path(artwork_path).exists():
        return None
    p = Path(artwork_path)
    # Check if a sibling .jpg already exists under 9.5MB
    sibling_jpg = p.with_suffix(".jpg")
    if sibling_jpg.exists() and sibling_jpg.stat().st_size < 9.5 * 1024 * 1024:
        return sibling_jpg
    if p.stat().st_size < 9.5 * 1024 * 1024 and p.suffix.lower() in [".jpg", ".jpeg"]:
        return p
    # Convert/compress to JPG
    try:
        from PIL import Image
        out_jpg = p.with_suffix(".jpg")
        im = Image.open(p).convert("RGB")
        im.save(out_jpg, "JPEG", quality=95, optimize=True)
        if out_jpg.stat().st_size < 9.5 * 1024 * 1024:
            return out_jpg
    except Exception as e:
        log(f"Warning: could not auto-compress artwork {p}: {e}")
    if p.stat().st_size < 10 * 1024 * 1024:
        return p
    return None


def ensure_release_waveforms(release_name, manifest=None, flacs=None):
    """Ensure release_dir/waveforms exists and contains waveform banners for all tracks and album."""
    release_dir = RELEASES_DIR / release_name
    if not release_dir.is_dir():
        return False

    waves_dir = release_dir / "waveforms"
    covers_dir = release_dir / "covers"
    waves_dir.mkdir(parents=True, exist_ok=True)
    covers_dir.mkdir(parents=True, exist_ok=True)

    master_waves_dir = Path("/opt/data/music/artwork/waveforms")
    if not master_waves_dir.exists() and Path("D:/music/artwork/waveforms").exists():
        master_waves_dir = Path("D:/music/artwork/waveforms")
    master_waves_dir.mkdir(parents=True, exist_ok=True)

    # Album waveform
    clean_alb = release_name.replace("-", "_").upper()
    alb_wave = waves_dir / "album_waveform.png"
    if not alb_wave.exists() or alb_wave.stat().st_size < 1000:
        cand = next((p for p in [
            covers_dir / "album_waveform.png",
            covers_dir / f"{clean_alb}_waveform.png",
            master_waves_dir / f"{clean_alb}_waveform.png",
            master_waves_dir / "album_waveform.png",
        ] if p.exists() and p.stat().st_size > 1000), None)
        if cand:
            import shutil
            shutil.copy2(cand, alb_wave)
            shutil.copy2(cand, waves_dir / f"{clean_alb}_waveform.png")
            shutil.copy2(cand, covers_dir / "album_waveform.png")
        else:
            alb_art = find_artwork(release_name)
            if alb_art:
                log(f"Auto-generating missing album waveform banner for {release_name}...")
                _gen_waveform_banner(alb_art, clean_alb, [waves_dir, covers_dir, master_waves_dir])

    # Track waveforms
    if flacs:
        for idx, flac in enumerate(flacs, 1):
            title = get_canonical_track_title(idx - 1, flac, manifest)
            clean_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip().replace(" ", "_").upper()
            tw = waves_dir / f"{idx:02d}_{clean_title}_waveform.png"
            if not tw.exists() or tw.stat().st_size < 1000:
                cand = next((p for p in [
                    covers_dir / f"{idx:02d}_{clean_title}_waveform.png",
                    covers_dir / f"{clean_title}_waveform.png",
                    master_waves_dir / f"{idx:02d}_{clean_title}_waveform.png",
                    master_waves_dir / f"{clean_title}_waveform.png",
                ] if p.exists() and p.stat().st_size > 1000), None)
                if cand:
                    import shutil
                    shutil.copy2(cand, tw)
                    shutil.copy2(cand, waves_dir / f"{clean_title}_waveform.png")
                    shutil.copy2(cand, covers_dir / f"{idx:02d}_{clean_title}_waveform.png")
                else:
                    tr_art = find_artwork(release_name, title)
                    if tr_art:
                        log(f"Auto-generating missing waveform banner for Track {idx} ({title})...")
                        _gen_waveform_banner(tr_art, f"{idx:02d}_{clean_title}", [waves_dir, covers_dir, master_waves_dir])
    return True


def _gen_waveform_banner(src_img, title, out_dirs):
    """Generate 1240x400 waveform banner using gen_waveform_art or fallback crop."""
    src_p = Path(src_img)
    if not src_p.exists():
        return False
    wave_script = Path("/opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py")
    if not wave_script.exists():
        for cand in [
            Path("D:/sp2/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py"),
            Path("D:/hermes-music/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py"),
        ]:
            if cand.exists():
                wave_script = cand
                break
    generated = False
    if wave_script.exists():
        try:
            r = subprocess.run([
                sys.executable, str(wave_script),
                "--image", str(src_p), "--title", title,
                "--output-dir", str(out_dirs[0])
            ], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                generated = True
        except Exception as e:
            log(f"Waveform generator error: {e}")

    # Fallback to PIL crop if script failed
    if not generated:
        try:
            from PIL import Image
            import io
            with Image.open(src_p) as img:
                w, h = img.size
                target_w, target_h = 1240, 400
                target_ratio = target_w / target_h
                new_h = int(w / target_ratio)
                center_offset = int(h * 0.1)
                top = (h - new_h) // 2 + center_offset
                top = min(top, max(0, h - new_h))
                cropped = img.crop((0, max(0, top), w, min(h, top + new_h)))
                final = cropped.resize((target_w, target_h), Image.LANCZOS)
                for od in out_dirs:
                    od.mkdir(parents=True, exist_ok=True)
                    final.save(od / f"{title}_waveform.png", "PNG")
                return True
        except Exception as fe:
            log(f"Fallback crop error: {fe}")
            return False

    src_res = out_dirs[0] / f"{title}_waveform.png"
    if src_res.exists():
        import shutil
        for od in out_dirs[1:]:
            od.mkdir(parents=True, exist_ok=True)
            try: shutil.copy2(src_res, od / f"{title}_waveform.png")
            except Exception: pass
        return True
    return False


def sc_upload(flac_path, title, tags, genre, artwork=None, label=DEFAULT_LABEL):
    """Upload a single track to SoundCloud. Returns dict {"track_id": id, "url": permalink_url, "title": title} or None."""
    cmd = [
        sys.executable, str(SC_SCRIPT), "upload",
        "--file", str(flac_path),
        "--title", title,
        "--genre", genre or DEFAULT_GENRE,
        "--tags", ",".join(tags),
        "--sharing", "public",
        "--downloadable",
        "--label", label,
    ]
    valid_art = ensure_uploadable_artwork(artwork)
    if valid_art:
        cmd.extend(["--artwork", str(valid_art)])

    log(f"  Uploading: {title}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        err_detail = (r.stdout.strip() + " " + r.stderr.strip()).strip()[-300:]
        log(f"  ✗ Upload failed: {err_detail}")
        return None
    try:
        result = json.loads(r.stdout)
        if result.get("success"):
            track_id = result["track_id"]
            permalink = result.get("permalink_url") or result.get("permalink", "")
            log(f"  ✓ Uploaded: {title} → ID {track_id} ({permalink})")
            return {"track_id": track_id, "url": permalink, "title": title}
    except json.JSONDecodeError:
        log(f"  ✗ Bad response: {r.stdout[:200]}")
    return None


def sc_create_playlist(title, track_ids, artwork=None, description="", label=DEFAULT_LABEL):
    """Create a SoundCloud playlist via soundcloud_api.py (supports artwork upload)."""
    cmd = [
        sys.executable, str(SC_SCRIPT), "create-playlist",
        "--title", title,
        "--track-ids", ",".join(str(tid) for tid in track_ids),
        "--sharing", "public",
    ]
    if description:
        cmd.extend(["--description", description])
    valid_art = ensure_uploadable_artwork(artwork)
    if valid_art:
        cmd.extend(["--artwork", str(valid_art)])

    log(f"  Creating playlist: {title} ({len(track_ids)} tracks)")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        err_detail = (r.stdout.strip() + " " + r.stderr.strip()).strip()[-300:]
        log(f"  ✗ Playlist creation failed: {err_detail}")
        return None, None
    try:
        result = json.loads(r.stdout)
        if result.get("success"):
            playlist_id = result.get("playlist_id")
            permalink = result.get("permalink_url") or result.get("permalink", "")
            if not permalink and playlist_id:
                slug = title.lower().replace(" ", "-")
                permalink = f"https://soundcloud.com/ridethevoid/sets/{slug}"
            log(f"  ✓ Playlist created: {title} → {permalink}")
            return playlist_id, permalink
    except json.JSONDecodeError:
        log(f"  ✗ Bad response: {r.stdout[:200]}")
    return None, None


def list_releases():
    """List all release-ready albums."""
    if not RELEASES_DIR.exists():
        print(json.dumps({"releases": []}))
        return

    releases = []
    for d in sorted(RELEASES_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest_path = d / "release.json"
        flacs = list(d.glob("*.flac"))
        if not flacs:
            continue

        info = {"name": d.name, "track_count": len(flacs)}
        if manifest_path.exists():
            manifest = json.load(open(manifest_path))
            info["album"] = manifest.get("album", d.name.upper())
            info["status"] = manifest.get("status", "unknown")
            info["tracks"] = manifest.get("tracks", [])
        artwork = find_artwork(d.name)
        info["has_artwork"] = artwork is not None
        releases.append(info)

    print(json.dumps({"releases": releases}, indent=2))


def review_gate(release_name, manifest, tracks_meta, flacs, dry_run=False):
    """Send release summary with action buttons."""
    album = manifest.get("album", release_name.upper()).replace("-", " ")
    track_count = len(flacs)

    track_lines = []
    for i, flac in enumerate(flacs):
        title = get_canonical_track_title(i, flac, manifest, tracks_meta)
        meta = tracks_meta[i] if i < len(tracks_meta) else {}
        bpm = meta.get("bpm", "?")
        key = meta.get("key", "?")
        track_lines.append(f"  {i+1}. {html.escape(title)} ({bpm} BPM, {key})")

    tags_sample = []
    if tracks_meta:
        tags_sample = build_tags(tracks_meta[0], manifest)[:5]

    artwork = find_artwork(release_name)
    art_status = "✅ Found" if artwork else "⚠️ Missing"

    ensure_release_waveforms(release_name, manifest, flacs)
    waves_dir = RELEASES_DIR / release_name / "waveforms"
    waves_count = len(list(waves_dir.glob("*_waveform.png"))) if waves_dir.exists() else 0
    wave_status = f"✅ {waves_count} banners ready" if waves_count else "⚠️ Missing"

    msg = (
        f"📦 <b>Ready to publish: {html.escape(album)}</b>\n\n"
        f"🎵 <b>{track_count} tracks:</b>\n"
        + "\n".join(track_lines) + "\n\n"
        f"🏷️ <b>Tags:</b> {html.escape(', '.join(tags_sample[:5]))}...\n"
        f"🎨 <b>Cover art:</b> {art_status}\n"
        f"🌊 <b>Waveforms:</b> {wave_status}\n"
        f"🔒 <b>Sharing:</b> public\n"
        f"📛 <b>Label:</b> {html.escape(DEFAULT_LABEL)}"
    )

    buttons = [
        [{"text": "🚀 Publish to SoundCloud", "callback_data": f"pub:{release_name}:go"}],
        [{"text": "👀 Preview audio first", "callback_data": f"pub:{release_name}:preview"}],
        [{"text": "✏️ Edit tags/title", "callback_data": f"pub:{release_name}:edit"}],
        [{"text": "❌ Cancel", "callback_data": f"pub:{release_name}:cancel"}],
    ]

    if dry_run:
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", errors="replace").decode("ascii"))
        print(f"\nButtons: {json.dumps(buttons, indent=2)}")
        return True

    msg_id = send_telegram(msg, buttons=buttons)
    return msg_id is not None


def preview_gate(release_name, flacs):
    """Send audio files for user review with proceed/reject buttons."""
    log(f"Sending {len(flacs)} tracks for preview...")
    for flac in flacs:
        import re
        title = re.sub(r'^\d+[\s_\-]*', '', flac.stem.replace("_MASTER", "").replace("_", " "))
        ok = send_audio_file(str(flac), title)
        log(f"  {'✓' if ok else '✗'} {title}")
        time.sleep(2)

    buttons = [
        [{"text": "✅ Sounds good — publish", "callback_data": f"pub:{release_name}:go"}],
        [{"text": "🔄 Regenerate", "callback_data": f"pub:{release_name}:regen"}],
        [{"text": "⏭️ Skip publishing", "callback_data": f"pub:{release_name}:cancel"}],
    ]

    send_telegram(
        f"👆 <b>Review the {len(flacs)} tracks above</b>\n\nReady to publish to SoundCloud?",
        buttons=buttons
    )


def cleanup_pipeline_state(release_name):
    """Purge pipeline state if it matches this published album to avoid rogue watchdog resume loops."""
    rel_clean = str(release_name).lower().replace(" ", "-").replace("_", "-")
    for sp in ["/opt/data/music/pipeline_state.json", "D:/music/pipeline_state.json"]:
        if os.path.exists(sp):
            try:
                with open(sp, "r", encoding="utf-8") as sf:
                    sdata = json.load(sf)
                st_album = sdata.get("proposal", {}).get("album", "").lower().replace(" ", "-").replace("_", "-")
                if not st_album or st_album == rel_clean:
                    os.remove(sp)
                    log(f"Cleaned up pipeline state at {sp} for published release {release_name}")
            except Exception as e:
                log(f"Warning checking/cleaning pipeline state at {sp}: {e}")


def _fetch_existing_sc_tracks():
    """Fetch recent tracks on SoundCloud so retries reuse already-uploaded tracks instead of duplicating."""
    existing = {}
    try:
        r = subprocess.run(
            [sys.executable, "-c",
             f"import sys, json; sys.path.insert(0, '{SC_SCRIPT.parent}'); import soundcloud_api as sc; s, tr = sc.api_request('GET', '/me/tracks?limit=30'); print(json.dumps(tr if isinstance(tr, list) else []))"],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode == 0 and r.stdout.strip():
            for t in json.loads(r.stdout.strip()):
                t_title = (t.get("title") or "").strip().upper()
                if t_title and t.get("id") and t_title not in existing:
                    existing[t_title] = {
                        "track_id": t["id"],
                        "url": t.get("permalink_url") or t.get("permalink", ""),
                        "title": t.get("title") or t_title,
                    }
    except Exception as e:
        log(f"  Warning checking existing SC tracks: {e}")
    return existing


def publish(release_name, manifest, tracks_meta, flacs, force=False):
    """Execute the full publish: tag files, upload tracks, create playlist, add artwork."""
    album_plain = manifest.get("album", release_name.upper()).replace("-", " ")
    album = album_plain.upper()

    # ── Duplicate guard ──
    if not force and manifest.get("status") == "published" and manifest.get("soundcloud", {}).get("track_ids"):
        sc = manifest["soundcloud"]
        log(f"⚠ {album_plain} is already published (playlist {sc.get('playlist_id')}) — use --force to re-publish")
        send_telegram(f"⚠ <b>{html.escape(album_plain)}</b> is already published on SoundCloud.")
        cleanup_pipeline_state(release_name)
        return False

    log(f"Publishing {album} ({len(flacs)} tracks)...")

    send_telegram(
        f"🚀 <b>Publishing to SoundCloud: {html.escape(album)}</b>\n"
        f"• Tracks: {len(flacs)} studio masters (24-bit / 48 kHz)\n"
        f"• Tagging metadata & synchronizing cover art..."
    )

    # 0. Ensure waveform banners are ready
    ensure_release_waveforms(release_name, manifest, flacs)

    # 0b. Ensure all files are tagged with metadata + cover art
    tag_script = Path("/opt/data/skills/delivery-receipt/delivery-receipt/scripts/tag_metadata.py")
    if tag_script.exists():
        log("Tagging metadata + cover art...")
        result = subprocess.run(
            [sys.executable, str(tag_script), "--release", release_name],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            tagged = sum(1 for l in result.stdout.splitlines() if "✓" in l)
            log(f"  Tagged {tagged} files")
        else:
            log(f"  ⚠ Tagging failed (non-fatal): {result.stderr[-100:]}")

    # 1. Upload all tracks (reusing any already-uploaded track from a prior attempt)
    existing_sc_tracks = _fetch_existing_sc_tracks()
    uploaded_tracks = []
    for i, flac in enumerate(flacs):
        title = get_canonical_track_title(i, flac, manifest, tracks_meta)
        meta = tracks_meta[i] if i < len(tracks_meta) else {}
        tags = build_tags(meta, manifest)
        genre = meta.get("genre", DEFAULT_GENRE).split("/")[0].strip()
        artwork = find_artwork(release_name, title)

        if title.upper() in existing_sc_tracks:
            track_res = existing_sc_tracks[title.upper()]
            log(f"  ✓ Reusing already-uploaded track: {title} → ID {track_res['track_id']}")
            uploaded_tracks.append(track_res)
            send_telegram(f"✅ <i>[{i+1}/{len(flacs)}]</i> <b>{html.escape(title)}</b> verified on SoundCloud!")
            continue

        send_telegram(f"📤 <i>[{i+1}/{len(flacs)}]</i> Uploading <b>{html.escape(title)}</b> (24-bit studio FLAC)...")

        track_res = sc_upload(flac, title, tags, genre, artwork)
        if track_res:
            uploaded_tracks.append(track_res)
            send_telegram(f"✅ <i>[{i+1}/{len(flacs)}]</i> <b>{html.escape(title)}</b> uploaded!")
        else:
            send_telegram(f"⚠️ <i>[{i+1}/{len(flacs)}]</i> Upload failed for <b>{html.escape(title)}</b>")
        time.sleep(1)

    track_ids = [t["track_id"] for t in uploaded_tracks]
    if not track_ids:
        send_telegram(f"❌ <b>{html.escape(album)}</b> — All uploads failed.")
        return False

    # ── Strict upload verification: ALL tracks must succeed ──
    failed_count = len(flacs) - len(track_ids)
    if failed_count > 0:
        log(f"❌ {failed_count}/{len(flacs)} tracks failed to upload — halting publication")
        send_telegram(f"❌ <b>Publication halted for {html.escape(album)}</b>: {failed_count} of {len(flacs)} tracks failed initial upload. All tracks must succeed.")
        return False

    # 2. Wait for encoding & active Content ID verification
    log("Waiting for SoundCloud encoding & verifying tracks...")
    send_telegram("⏳ <i>SoundCloud is transcoding audio masters into high-bitrate streaming formats...</i>")
    max_wait = 180  # max 3 minutes
    poll_interval = 10
    waited = 0
    flagged_tracks = []
    while waited < max_wait:
        time.sleep(poll_interval)
        waited += poll_interval
        all_ready = True
        flagged_tracks = []
        for tid in track_ids:
            r = subprocess.run(
                [sys.executable, str(SC_SCRIPT), "status", "--track-id", str(tid)],
                capture_output=True, text=True, timeout=15
            )
            try:
                status = json.loads(r.stdout)
                st_val = status.get("state")
                dur_sec = status.get("duration_seconds") or 0
                if not status.get("success", True) or "404" in str(status.get("error", "")):
                    flagged_tracks.append((tid, "404 Not Found / Content ID Removal"))
                    all_ready = False
                elif st_val == "failed":
                    flagged_tracks.append((tid, "Transcode Failed"))
                    all_ready = False
                elif st_val == "finished" or (st_val == "unknown" and dur_sec > 0):
                    pass
                else:
                    all_ready = False
            except (json.JSONDecodeError, KeyError):
                all_ready = False
        if flagged_tracks:
            break
        if all_ready:
            log(f"  ✓ All tracks encoded and verified ({waited}s)")
            break

    if flagged_tracks:
        err_msg = ", ".join(f"Track ID {tid} ({reason})" for tid, reason in flagged_tracks)
        log(f"❌ Track verification failed: {err_msg}")
        send_telegram(
            f"❌ <b>Publication halted for {html.escape(album)}</b>:\n"
            f"{html.escape(err_msg)}\n\n"
            f"<i>One or more tracks were removed by SoundCloud Content ID or failed transcoding. Use track remediation to regenerate and replace flagged tracks before publishing.</i>"
        )
        return False

    send_telegram("✅ <i>Audio transcoding complete! Assembling SoundCloud playlist...</i>")

    # 3. Create playlist
    album_artwork = find_artwork(release_name)
    playlist_id, permalink = sc_create_playlist(
        title=album,
        track_ids=track_ids,
        artwork=album_artwork,
        description=f"{album} — {DEFAULT_LABEL}",
    )
    if not playlist_id:
        send_telegram(f"❌ Failed to create SoundCloud playlist for <b>{html.escape(album)}</b>")
        return False

    # STRICT PLAYLIST AUDIT: Ensure playlist actually contains all expected tracks
    log(f"Auditing playlist {playlist_id} for all {len(flacs)} tracks...")
    verified_count = 0
    try:
        r_pl = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, '{SC_SCRIPT.parent}'); import soundcloud_api as sc; s, p = sc.api_request('GET', '/playlists/{playlist_id}'); import json; print(len(p.get('tracks', [])) if isinstance(p, dict) and s == 200 else -1)"],
            capture_output=True, text=True, timeout=20
        )
        if r_pl.returncode == 0:
            verified_count = int(r_pl.stdout.strip())
    except Exception as e:
        log(f"Playlist check error: {e}")

    if verified_count != len(flacs):
        log(f"❌ Playlist verification failed: Expected {len(flacs)} tracks, but playlist has {verified_count}")
        send_telegram(
            f"❌ <b>{html.escape(album)}</b>: Playlist verification failed!\n"
            f"Expected {len(flacs)} tracks, but SoundCloud playlist only contains {verified_count} tracks.\n"
            f"<i>Release is NOT marked as published.</i>"
        )
        return False

    # 4. Tag update pass (tags sometimes don't stick on first upload)
    log("Running tag update pass...")
    tag_failures = 0
    for i, track_id in enumerate(track_ids):
        meta = tracks_meta[i] if i < len(tracks_meta) else {}
        tags = build_tags(meta, manifest)
        cmd = [
            sys.executable, str(SC_SCRIPT), "update",
            "--track-id", str(track_id),
            "--tags", ",".join(tags),
            "--label", DEFAULT_LABEL,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        if r.returncode != 0:
            tag_failures += 1
            log(f"  ⚠ Tag update failed for track {track_id}")
        time.sleep(0.5)
    if tag_failures:
        log(f"  ⚠ {tag_failures} tag updates failed")

    # 5. Update release.json with SC metadata
    manifest["soundcloud"] = {
        "track_ids": track_ids,
        "playlist_id": playlist_id,
        "permalink": permalink,
        "published_at": datetime.now().isoformat(),
        "tracks": uploaded_tracks,
    }
    manifest["status"] = "published"
    manifest_path = RELEASES_DIR / release_name / "release.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    cleanup_pipeline_state(release_name)

    # 6. Comprehensive, clear publication receipt
    uploaded = len(uploaded_tracks)

    result_lines = [
        "🎉 <b>SOUNDCLOUD RELEASE PUBLISHED</b>\n",
        f"💿 <b>Album:</b> {html.escape(album)}",
        f"🏷️ <b>Label:</b> {html.escape(DEFAULT_LABEL)}",
        "🎚️ <b>Format:</b> 24-bit / 48 kHz Studio FLAC Masters",
        "🖼️ <b>Artwork:</b> Embedded FLAC Picture Blocks + Hi-Res Covers\n",
    ]
    if permalink:
        result_lines.append(f"📋 <b>Playlist:</b>\n🔗 <a href=\"{permalink}\">{html.escape(album)} (Full Playlist)</a>\n")

    result_lines.append(f"🎵 <b>Tracklist & Direct Links ({uploaded} tracks):</b>")
    for idx, t in enumerate(uploaded_tracks, 1):
        t_title = t.get("title", f"Track {idx}")
        t_url = t.get("url")
        meta = tracks_meta[idx-1] if idx-1 < len(tracks_meta) else {}
        bpm = meta.get("bpm")
        key = meta.get("key")
        extra = f" ({bpm} BPM, {key})" if bpm and key else ""
        if t_url:
            result_lines.append(f"{idx}. <a href=\"{t_url}\">{html.escape(t_title)}</a>{extra}")
        else:
            result_lines.append(f"{idx}. {html.escape(t_title)}{extra}")

    buttons = []
    if permalink:
        buttons.append([{"text": "🔗 Listen to Playlist", "url": permalink}])
    if uploaded_tracks and uploaded_tracks[0].get("url"):
        buttons.append([{"text": f"🎵 Play {uploaded_tracks[0]['title'][:25]}", "url": uploaded_tracks[0]["url"]}])

    send_telegram("\n".join(result_lines), buttons=buttons)
    log(f"✓ Published {album}: {uploaded} tracks, playlist {playlist_id}")
    return True


def repair_track(release_name, manifest, tracks_meta, flacs, track_idx):
    """Repair/re-upload a single track, update existing playlist and release.json."""
    album_plain = manifest.get("album", release_name.upper()).replace("-", " ")
    album = stylize_title(album_plain)
    if track_idx < 1 or track_idx > len(flacs):
        log(f"Invalid track index {track_idx}, must be 1..{len(flacs)}")
        return False

    i = track_idx - 1
    flac = flacs[i]
    title = get_canonical_track_title(i, flac, manifest, tracks_meta)
    meta = tracks_meta[i] if i < len(tracks_meta) else {}
    tags = build_tags(meta, manifest)
    genre = meta.get("genre", DEFAULT_GENRE).split("/")[0].strip()
    artwork = find_artwork(release_name, title)

    send_telegram(f"🔧 <b>Repairing Track {track_idx}/{len(flacs)}:</b> Uploading <b>{html.escape(title)}</b> (24-bit studio FLAC)...")
    track_res = sc_upload(flac, title, tags, genre, artwork)
    if not track_res:
        send_telegram(f"❌ Upload failed for <b>{html.escape(title)}</b>")
        return False

    new_track_id = track_res["track_id"]
    send_telegram(f"⏳ <i>SoundCloud is transcoding & scanning {html.escape(title)} (ID: {new_track_id})...</i>")

    time.sleep(15)
    flagged = False
    for _ in range(12):
        time.sleep(5)
        r = subprocess.run([sys.executable, str(SC_SCRIPT), "status", "--track-id", str(new_track_id)],
                           capture_output=True, text=True, timeout=15)
        try:
            status = json.loads(r.stdout)
            if not status.get("success", True) or "404" in str(status.get("error", "")):
                flagged = True
                break
            if status.get("state") == "finished":
                break
        except Exception:
            pass

    if flagged:
        send_telegram(f"❌ Track {new_track_id} was removed by SoundCloud (Content ID flag / transcode failure)!")
        return False

    # Update playlist
    sc_info = manifest.get("soundcloud", {})
    playlist_id = sc_info.get("playlist_id")
    track_ids = list(sc_info.get("track_ids", []))
    if len(track_ids) == len(flacs):
        track_ids[i] = new_track_id
    else:
        existing_tracks = sc_info.get("tracks", [])
        track_ids = []
        for idx in range(len(flacs)):
            if idx == i:
                track_ids.append(new_track_id)
            elif idx < len(existing_tracks):
                track_ids.append(existing_tracks[idx].get("track_id"))

    if playlist_id:
        log(f"Updating playlist {playlist_id} with repaired track list: {track_ids}")
        res_pl = subprocess.run([
            sys.executable, str(SC_SCRIPT), "update-playlist",
            "--playlist-id", str(playlist_id),
            "--track-ids", ",".join(str(t) for t in track_ids)
        ], capture_output=True, text=True, timeout=30)
        if res_pl.returncode != 0:
            send_telegram(f"❌ Failed to update playlist {playlist_id}")
            return False

    # Update manifest
    manifest_tracks = sc_info.get("tracks", [])
    while len(manifest_tracks) <= i:
        manifest_tracks.append({})
    manifest_tracks[i] = track_res
    sc_info["track_ids"] = track_ids
    sc_info["tracks"] = manifest_tracks
    manifest["soundcloud"] = sc_info
    manifest["status"] = "published"

    manifest_path = RELEASES_DIR / release_name / "release.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    cleanup_pipeline_state(release_name)

    send_telegram(f"✅ <b>Track {track_idx} ({html.escape(title)}) successfully repaired and synced to playlist!</b>")
    return True


def main():
    parser = argparse.ArgumentParser(description="Gated SoundCloud publishing")
    parser.add_argument("--release", help="Release directory name (e.g., mars-descent)")
    parser.add_argument("--preview", action="store_true", help="Send audio for review before publishing")
    parser.add_argument("--confirm", action="store_true", help="Skip review gate, publish immediately")
    parser.add_argument("--force", action="store_true", help="Force re-publish even if already published")
    parser.add_argument("--repair-track", type=int, default=None, help="Repair/replace a single track by 1-based index")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without sending")
    parser.add_argument("--list", action="store_true", help="List release-ready albums")
    args = parser.parse_args()

    if args.list:
        list_releases()
        return

    if not args.release:
        parser.print_help()
        sys.exit(1)

    manifest, tracks_meta, flacs = load_release(args.release)
    if manifest is None or not flacs:
        log(f"Release '{args.release}' not found or empty")
        sys.exit(1)

    log(f"Loaded release: {args.release} ({len(flacs)} tracks)")

    if args.repair_track is not None:
        ok = repair_track(args.release, manifest, tracks_meta, flacs, args.repair_track)
        if not ok:
            sys.exit(1)
        return

    if args.confirm:
        ok = publish(args.release, manifest, tracks_meta, flacs, force=args.force)
        if not ok:
            sys.exit(1)
    elif args.preview:
        preview_gate(args.release, flacs)
    else:
        review_gate(args.release, manifest, tracks_meta, flacs, dry_run=args.dry_run)

    if args.dry_run:
        log("Dry run complete — nothing was sent")


if __name__ == "__main__":
    main()




