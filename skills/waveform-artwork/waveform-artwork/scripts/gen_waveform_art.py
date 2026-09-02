#!/usr/bin/env python3
"""
gen_waveform_art.py — Generate panoramic scene-extension artwork banners (1240x400)
from SoundCloud cover art using Venice AI image editing.

Pipeline:
  1. Fetch the track's cover art URL from SoundCloud
  2. Send to Venice /api/v1/image/edit with the cover as input
  3. Venice remixes/extends the cover into a wide panoramic scene (16:9)
  4. Crop/resize result to exactly 1240x400
  5. Save to output directory

Usage:
  python3 gen_waveform_art.py --playlist-id 2287519329 --output-dir /app/music/artwork/waveforms
  python3 gen_waveform_art.py --playlist-id 2287519329 --playlist-id 2285528526 --output-dir /app/music/artwork/waveforms
  python3 gen_waveform_art.py --track-id 2386286106 --output-dir /app/music/artwork/waveforms
"""

import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

import requests

# ── Configuration ──────────────────────────────────────────────
VENICE_API_KEY = os.environ.get("VENICE_API_KEY", "")
VENICE_EDIT_URL = "https://api.venice.ai/api/v1/image/edit"

# SoundCloud auth
SC_TOKEN_PATHS = [
    os.path.expanduser("~/.hermes/credentials/soundcloud_tokens.json"),
    "/opt/data/home/.hermes/credentials/soundcloud_tokens.json",
    "/opt/data/.soundcloud_auth/soundcloud_tokens.json",
]

# Defaults
DEFAULT_OUTPUT_DIR = "/app/music/artwork/waveforms"
TARGET_WIDTH = 1240
TARGET_HEIGHT = 400

# Scene extension prompt — no "waveform" language, just panoramic scene expansion
SCENE_PROMPT = (
    "Reimagine this artwork as an ultra-wide panoramic scene, seamlessly extending "
    "the visual world of the original to the left and right. Keep the exact same "
    "color palette, atmosphere, lighting, and mood. Create a cohesive, continuous "
    "cinematic composition that expands the scene naturally. "
    "Absolutely NO TEXT, NO WORDS, NO LETTERS, NO TYPOGRAPHY anywhere in the image."
)


def log(msg):
    print(f"[waveform-art] {msg}", file=sys.stderr, flush=True)


def fail(msg):
    print(json.dumps({"success": False, "error": msg}))
    sys.exit(1)


def output_result(data):
    print(json.dumps(data, indent=2, default=str))


# ── SoundCloud helpers ──────────────────────────────────────────
def load_sc_tokens():
    """Load SoundCloud tokens from disk, trying multiple paths."""
    for path in SC_TOKEN_PATHS:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    tokens = json.load(f)
                if tokens.get("access_token"):
                    return tokens
            except (json.JSONDecodeError, IOError):
                continue
    return None


def refresh_sc_token(tokens):
    """Refresh the SoundCloud access token."""
    resp = requests.post("https://secure.soundcloud.com/oauth/token", data={
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": tokens["client_id"],
        "client_secret": tokens["client_secret"],
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)

    if resp.status_code != 200:
        return None

    new_data = resp.json()
    result = {
        "access_token": new_data["access_token"],
        "refresh_token": new_data.get("refresh_token", tokens["refresh_token"]),
        "expires_at": int(time.time()) + new_data.get("expires_in", 3600),
        "scope": new_data.get("scope", ""),
        "client_id": tokens["client_id"],
        "client_secret": tokens["client_secret"],
    }

    for path in SC_TOKEN_PATHS:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(result, f, indent=2)
        except OSError:
            pass

    return result


def get_sc_headers():
    """Get valid SoundCloud auth headers, refreshing if needed."""
    tokens = load_sc_tokens()
    if not tokens:
        fail("No SoundCloud tokens found. Run OAuth flow first.")

    if time.time() > tokens.get("expires_at", 0) - 60:
        log("SoundCloud token expired, refreshing...")
        tokens = refresh_sc_token(tokens)
        if not tokens:
            fail("SoundCloud token refresh failed. Re-authenticate.")
        log("Token refreshed successfully.")

    return {"Authorization": f"OAuth {tokens['access_token']}", "Accept": "application/json"}


def get_playlist_tracks(playlist_id):
    """Fetch tracks from a SoundCloud playlist."""
    headers = get_sc_headers()
    resp = requests.get(
        f"https://api.soundcloud.com/playlists/{playlist_id}",
        headers=headers, timeout=30
    )
    if resp.status_code != 200:
        fail(f"Failed to fetch playlist {playlist_id}: {resp.status_code}")

    data = resp.json()
    tracks = []
    for t in data.get("tracks", []):
        artwork = t.get("artwork_url")
        if artwork:
            artwork = artwork.replace("-large", "-t500x500")
        tracks.append({
            "id": t["id"],
            "title": t["title"],
            "artwork_url": artwork,
        })
    return data.get("title", "Unknown"), tracks


def get_single_track(track_id):
    """Fetch a single track's metadata."""
    headers = get_sc_headers()
    resp = requests.get(
        f"https://api.soundcloud.com/tracks/{track_id}",
        headers=headers, timeout=30
    )
    if resp.status_code != 200:
        fail(f"Failed to fetch track {track_id}: {resp.status_code}")

    t = resp.json()
    artwork = t.get("artwork_url")
    if artwork:
        artwork = artwork.replace("-large", "-t500x500")
    return {
        "id": t["id"],
        "title": t["title"],
        "artwork_url": artwork,
    }


# ── Venice AI scene extension ──────────────────────────────────
def extend_scene(artwork_source, prompt=SCENE_PROMPT):
    """
    Use Venice image edit endpoint to extend a cover into a wide panoramic scene.
    Accepts a local file path or a public URL.
    NO fallback text-to-image is performed if image is missing.
    """
    if not artwork_source:
        raise ValueError("Artwork source is missing. Fallback generation is disabled.")

    if os.path.exists(str(artwork_source)):
        with open(artwork_source, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode("utf-8")
        image_data = f"data:image/png;base64,{b64_img}"
    elif str(artwork_source).startswith("http://") or str(artwork_source).startswith("https://"):
        image_data = str(artwork_source)
    else:
        raise FileNotFoundError(f"Artwork source not found: {artwork_source}")

    resp = requests.post(VENICE_EDIT_URL, headers={
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json",
    }, json={
        "prompt": prompt,
        "image": image_data,
        "aspect_ratio": "16:9",
        "output_format": "png",
    }, timeout=180)

    if resp.status_code != 200:
        error_text = resp.text[:300]
        raise RuntimeError(f"Venice edit failed ({resp.status_code}): {error_text}")

    content_type = resp.headers.get("Content-Type", "")
    if "image" in content_type:
        return resp.content
    else:
        # May return JSON with b64
        try:
            data = resp.json()
            if "data" in data and data["data"]:
                b64 = data["data"][0].get("b64_json", "")
                return base64.b64decode(b64)
        except Exception:
            pass
        # Fall back to raw content
        return resp.content


def crop_to_banner(image_bytes, target_w=TARGET_WIDTH, target_h=TARGET_HEIGHT):
    """Crop and resize the panoramic scene to exact banner dimensions."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    orig_w, orig_h = img.size

    target_ratio = target_w / target_h  # ~3.1:1
    current_ratio = orig_w / orig_h     # ~1.78:1 for 16:9

    if current_ratio > target_ratio:
        # Wider than needed — crop width from center
        new_w = int(orig_h * target_ratio)
        left = (orig_w - new_w) // 2
        crop_box = (left, 0, left + new_w, orig_h)
    else:
        # Taller than needed — take a horizontal band from center-bottom
        # (more interesting area, like the ground/foreground)
        new_h = int(orig_w / target_ratio)
        # Position slightly below center for more interesting content
        center_offset = int(orig_h * 0.1)
        top = (orig_h - new_h) // 2 + center_offset
        top = min(top, orig_h - new_h)  # Clamp
        crop_box = (0, top, orig_w, top + new_h)

    cropped = img.crop(crop_box)
    resized = cropped.resize((target_w, target_h), Image.LANCZOS)

    buf = io.BytesIO()
    resized.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def sanitize_filename(title):
    """Clean title for use as filename."""
    clean = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    return clean.strip().replace(" ", "_").upper()


# ── Main pipeline ──────────────────────────────────────────────
def generate_for_track(track, output_dir, prompt, force=False):
    """Generate a scene-extension banner for a single track."""
    track_id = track["id"]
    title = track["title"]
    artwork_url = track.get("artwork_url")

    filename = f"{sanitize_filename(title)}_waveform.png"
    output_path = Path(output_dir) / filename

    if output_path.exists() and not force:
        log(f"  ⏭️  Already exists: {filename}")
        return {"title": title, "track_id": track_id, "file": str(output_path), "status": "skipped"}

    if not artwork_url:
        log(f"  ⚠️  No artwork for {title} — skipping (scene extension requires cover art)")
        return {"title": title, "track_id": track_id, "status": "error", "error": "No cover art"}

    # Scene extension via Venice edit
    log(f"  🎨 Extending scene from cover art (16:9)...")
    try:
        raw_image = extend_scene(artwork_url, prompt)
    except RuntimeError as e:
        log(f"  ❌ Scene extension failed: {e}")
        return {"title": title, "track_id": track_id, "status": "error", "error": str(e)}

    # Crop to banner dimensions
    log(f"  ✂️  Cropping to {TARGET_WIDTH}x{TARGET_HEIGHT}...")
    banner_image = crop_to_banner(raw_image)

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(banner_image)
    log(f"  ✅ Saved: {output_path} ({len(banner_image)} bytes)")

    return {
        "title": title,
        "track_id": track_id,
        "file": str(output_path),
        "status": "ok",
        "size_bytes": len(banner_image),
    }


def run(args):
    """Main execution."""
    output_dir = args.output_dir
    prompt = args.prompt or SCENE_PROMPT
    force = args.force

    tracks = []

    if args.playlist_id:
        for pid in args.playlist_id:
            log(f"Fetching playlist {pid}...")
            playlist_title, playlist_tracks = get_playlist_tracks(pid)
            log(f"  Album: {playlist_title} ({len(playlist_tracks)} tracks)")
            tracks.extend(playlist_tracks)

    if args.track_id:
        for tid in args.track_id:
            log(f"Fetching track {tid}...")
            track = get_single_track(tid)
            tracks.append(track)

    if args.image:
        title = args.title or Path(args.image).stem.replace("_bg", "").replace("_cover", "")
        tracks.append({
            "id": 0,
            "title": title,
            "artwork_url": args.image,
        })

    if not tracks:
        fail("No tracks to process. Specify --image, --playlist-id, or --track-id.")

    log(f"\n{'='*60}")
    log(f"Scene extension for {len(tracks)} tracks")
    log(f"  Method: Venice image edit (direct cover remix)")
    log(f"  Output: {output_dir}")
    log(f"  Size: {TARGET_WIDTH}x{TARGET_HEIGHT}")
    log(f"{'='*60}\n")

    results = []
    for i, track in enumerate(tracks, 1):
        log(f"[{i}/{len(tracks)}] {track['title']}")
        result = generate_for_track(track, output_dir, prompt, force)
        results.append(result)

        if i < len(tracks):
            time.sleep(1)

    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    errors = sum(1 for r in results if r["status"] == "error")

    log(f"\n{'='*60}")
    log(f"Done! {ok} generated, {skipped} skipped, {errors} errors")
    for r in results:
        icon = {"ok": "✅", "skipped": "⏭️", "error": "❌"}.get(r["status"], "?")
        log(f"  {icon} {r['title']}")
    log(f"{'='*60}")

    output_result({
        "success": errors == 0,
        "total": len(results),
        "generated": ok,
        "skipped": skipped,
        "errors": errors,
        "output_dir": output_dir,
        "results": results,
    })


def main():
    parser = argparse.ArgumentParser(
        description="Generate panoramic scene-extension banners from SoundCloud cover art"
    )
    parser.add_argument(
        "--image", "--image-path", default=None,
        help="Direct local path or URL to clean background / cover image"
    )
    parser.add_argument(
        "--title", default=None,
        help="Track title (used for output filename when --image is provided)"
    )
    parser.add_argument(
        "--playlist-id", type=int, action="append", default=None,
        help="SoundCloud playlist/album ID (can specify multiple)"
    )
    parser.add_argument(
        "--track-id", type=int, action="append", default=None,
        help="SoundCloud track ID (can specify multiple)"
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "--prompt", default=None,
        help="Custom scene extension prompt (default: built-in panoramic extension prompt)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Regenerate even if output file already exists"
    )
    args = parser.parse_args()

    if not args.image and not args.playlist_id and not args.track_id:
        parser.print_help()
        sys.exit(1)

    if not VENICE_API_KEY:
        fail("VENICE_API_KEY not set in environment")

    run(args)


if __name__ == "__main__":
    main()
