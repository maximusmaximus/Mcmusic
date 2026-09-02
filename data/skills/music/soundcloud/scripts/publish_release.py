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
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths ──
RELEASES_DIR = Path(os.environ.get("RELEASES_DIR", "/opt/data/music/releases"))
ARTWORK_DIR = Path(os.environ.get("ARTWORK_DIR", "/opt/data/music/artwork/covers"))
SC_SCRIPT = Path(os.environ.get("SC_SCRIPT",
    "/opt/data/skills/music/soundcloud/scripts/soundcloud_api.py"))
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")

# Default metadata
DEFAULT_LABEL = "VØIDRIDE"
DEFAULT_GENRE = "Electronic"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[publish {ts}] {msg}", flush=True)


def send_telegram(text, buttons=None, parse_mode="Markdown"):
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
        manifest = json.load(open(manifest_path))

    tracks_meta = []
    meta_path = release_dir / "tracks_meta.json"
    if meta_path.exists():
        tracks_meta = json.load(open(meta_path))

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


def sc_upload(flac_path, title, tags, genre, artwork=None, label=DEFAULT_LABEL):
    """Upload a single track to SoundCloud. Returns track_id or None."""
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
    if artwork and artwork.exists():
        cmd.extend(["--artwork", str(artwork)])

    log(f"  Uploading: {title}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        log(f"  ✗ Upload failed: {r.stderr[-200:]}")
        return None
    try:
        result = json.loads(r.stdout)
        if result.get("success"):
            track_id = result["track_id"]
            log(f"  ✓ Uploaded: {title} → ID {track_id}")
            return track_id
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
    if artwork and artwork.exists() and artwork.stat().st_size < 10 * 1024 * 1024:
        cmd.extend(["--artwork", str(artwork)])

    log(f"  Creating playlist: {title} ({len(track_ids)} tracks)")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        log(f"  ✗ Playlist creation failed: {r.stderr[-200:]}")
        return None, None
    try:
        result = json.loads(r.stdout)
        if result.get("success"):
            playlist_id = result.get("playlist_id")
            permalink = result.get("permalink", "")
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
    album = manifest.get("album", release_name.upper().replace("-", " "))
    track_count = len(flacs)

    track_lines = []
    for i, flac in enumerate(flacs):
        import re
        title = re.sub(r'^\d+[\s_]*', '', flac.stem.replace("_MASTER", "").replace("_", " "))
        meta = tracks_meta[i] if i < len(tracks_meta) else {}
        bpm = meta.get("bpm", "?")
        key = meta.get("key", "?")
        track_lines.append(f"  {i+1}. {title} ({bpm} BPM, {key})")

    tags_sample = []
    if tracks_meta:
        tags_sample = build_tags(tracks_meta[0], manifest)[:5]

    artwork = find_artwork(release_name)
    art_status = "✅ Found" if artwork else "⚠️ Missing"

    msg = (
        f"📦 *Ready to publish: {album}*\n\n"
        f"🎵 {track_count} tracks:\n"
        + "\n".join(track_lines) + "\n\n"
        f"🏷️ Tags: {', '.join(tags_sample[:5])}...\n"
        f"🎨 Cover art: {art_status}\n"
        f"🔒 Sharing: public\n"
        f"📛 Label: {DEFAULT_LABEL}"
    )

    buttons = [
        [{"text": "🚀 Publish to SoundCloud", "callback_data": f"pub:{release_name}:go"}],
        [{"text": "👀 Preview audio first", "callback_data": f"pub:{release_name}:preview"}],
        [{"text": "✏️ Edit tags/title", "callback_data": f"pub:{release_name}:edit"}],
        [{"text": "❌ Cancel", "callback_data": f"pub:{release_name}:cancel"}],
    ]

    if dry_run:
        print(msg)
        print(f"\nButtons: {json.dumps(buttons, indent=2)}")
        return True

    msg_id = send_telegram(msg, buttons=buttons)
    return msg_id is not None


def preview_gate(release_name, flacs):
    """Send audio files for user review with proceed/reject buttons."""
    log(f"Sending {len(flacs)} tracks for preview...")
    for flac in flacs:
        import re
        title = re.sub(r'^\d+[\s_]*', '', flac.stem.replace("_MASTER", "").replace("_", " "))
        ok = send_audio_file(str(flac), title)
        log(f"  {'✓' if ok else '✗'} {title}")
        time.sleep(2)

    buttons = [
        [{"text": "✅ Sounds good — publish", "callback_data": f"pub:{release_name}:go"}],
        [{"text": "🔄 Regenerate", "callback_data": f"pub:{release_name}:regen"}],
        [{"text": "⏭️ Skip publishing", "callback_data": f"pub:{release_name}:cancel"}],
    ]

    send_telegram(
        f"👆 *Review the {len(flacs)} tracks above*\n\nReady to publish to SoundCloud?",
        buttons=buttons
    )


def publish(release_name, manifest, tracks_meta, flacs, force=False):
    """Execute the full publish: tag files, upload tracks, create playlist, add artwork."""
    album = manifest.get("album", release_name.upper().replace("-", " "))

    # ── Duplicate guard ──
    if not force and manifest.get("status") == "published" and manifest.get("soundcloud", {}).get("track_ids"):
        sc = manifest["soundcloud"]
        log(f"⚠ {album} is already published (playlist {sc.get('playlist_id')}) — use --force to re-publish")
        send_telegram(f"⚠ *{album}* is already published on SoundCloud\\.")
        return False

    log(f"Publishing {album} ({len(flacs)} tracks)...")

    send_telegram(f"⏳ Publishing *{album}* to SoundCloud...")

    # 0. Ensure all files are tagged with metadata + cover art
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

    # 1. Upload all tracks
    track_ids = []
    for i, flac in enumerate(flacs):
        import re
        title = re.sub(r'^\d+[\s_]*', '', flac.stem.replace("_MASTER", "").replace("_", " "))
        meta = tracks_meta[i] if i < len(tracks_meta) else {}
        tags = build_tags(meta, manifest)
        genre = meta.get("genre", DEFAULT_GENRE).split("/")[0].strip()
        artwork = find_artwork(release_name, title)

        track_id = sc_upload(flac, title, tags, genre, artwork)
        if track_id:
            track_ids.append(track_id)
        time.sleep(1)

    if not track_ids:
        send_telegram(f"❌ *{album}* — All uploads failed")
        return False

    # ── Partial upload warning ──
    failed_count = len(flacs) - len(track_ids)
    if failed_count > 0:
        log(f"⚠ {failed_count}/{len(flacs)} tracks failed to upload")
        send_telegram(f"⚠ *{album}*: {failed_count} of {len(flacs)} tracks failed to upload")

    # 2. Wait for encoding
    log("Waiting 30s for SoundCloud encoding...")
    time.sleep(30)

    # 3. Create playlist
    album_artwork = find_artwork(release_name)
    playlist_id, permalink = sc_create_playlist(
        title=album,
        track_ids=track_ids,
        artwork=album_artwork,
        description=f"{album} — {DEFAULT_LABEL}",
    )

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
    }
    manifest["status"] = "published"
    manifest_path = RELEASES_DIR / release_name / "release.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # 6. Done notification
    uploaded = len(track_ids)

    result_lines = [
        f"✅ *{album}* published!",
        f"🎵 {uploaded} tracks" + (f" ({failed_count} failed)" if failed_count else ""),
    ]
    if playlist_id:
        result_lines.append(f"📋 Playlist created")

    buttons = []
    if permalink:
        buttons.append([{"text": "🔗 View on SoundCloud", "url": permalink}])

    send_telegram("\n".join(result_lines), buttons=buttons)
    log(f"✓ Published {album}: {uploaded} tracks, playlist {playlist_id}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Gated SoundCloud publishing")
    parser.add_argument("--release", help="Release directory name (e.g., mars-descent)")
    parser.add_argument("--preview", action="store_true", help="Send audio for review before publishing")
    parser.add_argument("--confirm", action="store_true", help="Skip review gate, publish immediately")
    parser.add_argument("--force", action="store_true", help="Force re-publish even if already published")
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

    if args.confirm:
        publish(args.release, manifest, tracks_meta, flacs, force=args.force)
    elif args.preview:
        preview_gate(args.release, flacs)
    else:
        review_gate(args.release, manifest, tracks_meta, flacs, dry_run=args.dry_run)

    if args.dry_run:
        log("Dry run complete — nothing was sent")


if __name__ == "__main__":
    main()




