#!/usr/bin/env python3
"""
SoundCloud API client — upload, update, list, status, batch operations.

Uses tokens stored by oauth_flow.py. Automatically refreshes expired tokens.

Usage:
    python3 soundcloud_api.py upload --file PATH --title TITLE [options]
    python3 soundcloud_api.py update --track-id ID [options]
    python3 soundcloud_api.py list [--limit N] [--json]
    python3 soundcloud_api.py status --track-id ID
    python3 soundcloud_api.py batch-upload --dir PATH [options]
"""

import argparse
import json
import os
import re
import sys
import time
import subprocess
from pathlib import Path

import requests

SOUNDCLOUD_API_BASE = "https://api.soundcloud.com"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(os.environ.get("HERMES_HOME", os.path.join(os.path.expanduser("~"), ".hermes")), "credentials", "soundcloud_tokens.json")
if not os.path.exists(TOKEN_FILE) and os.path.exists("/opt/data/home/.hermes/credentials/soundcloud_tokens.json"):
    TOKEN_FILE = "/opt/data/home/.hermes/credentials/soundcloud_tokens.json"

# Supported audio formats
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".aiff", ".aac", ".m4a"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Rate limit handling
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds, exponential backoff base


def log(msg):
    print(f"[soundcloud] {msg}", file=sys.stderr, flush=True)


def fail(msg):
    print(json.dumps({"success": False, "error": msg}))
    sys.exit(1)


def output_result(data):
    """Print result as JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def load_tokens():
    """Load tokens from disk."""
    if not os.path.exists(TOKEN_FILE):
        fail("No tokens found. Run: python3 ~/.hermes/skills/music/soundcloud/scripts/oauth_flow.py --auth")
    try:
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        fail(f"Corrupted token file: {e}")


def save_tokens(tokens):
    """Save tokens to disk."""
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return tokens


def is_token_expired(tokens):
    """Check if the access token is expired (60s buffer)."""
    if "expires_at" not in tokens:
        return True
    return time.time() > (tokens["expires_at"] - 60)


def refresh_access_token(tokens):
    """Refresh the access token. Returns new tokens dict or None."""
    client_id = tokens.get("client_id") or os.environ.get("SOUNDCLOUD_CLIENT_ID", "")
    client_secret = tokens.get("client_secret") or os.environ.get("SOUNDCLOUD_CLIENT_SECRET", "")
    refresh_token = tokens.get("refresh_token")

    if not refresh_token:
        log("No refresh token available")
        return None

    log("Refreshing access token...")
    # SoundCloud requires client credentials in POST body (NOT Basic auth header)
    resp = requests.post("https://api.soundcloud.com/oauth2/token", headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=30)

    if resp.status_code != 200:
        log(f"Token refresh failed: {resp.status_code} {resp.text[:200]}")
        return None

    new_data = resp.json()
    result = {
        "access_token": new_data["access_token"],
        "refresh_token": new_data.get("refresh_token", refresh_token),
        "expires_at": int(time.time()) + new_data.get("expires_in", 3600),
        "scope": new_data.get("scope", tokens.get("scope", "")),
        "client_id": client_id,
        "client_secret": client_secret,
    }
    save_tokens(result)
    log("Token refreshed successfully")
    return result


def get_auth_headers():
    """Get valid authorization headers, refreshing if needed."""
    tokens = load_tokens()

    if is_token_expired(tokens):
        new_tokens = refresh_access_token(tokens)
        if not new_tokens:
            fail("Access token expired and refresh failed. Re-authenticate with: "
                 "python3 ~/.hermes/skills/music/soundcloud/scripts/oauth_flow.py --auth")
        tokens = new_tokens

    return {"Authorization": f"OAuth {tokens['access_token']}"}


def api_request(method, endpoint, headers=None, params=None, json_data=None,
                files=None, data=None, retry_on_429=True):
    """
    Make a SoundCloud API request with automatic retry on 429.
    Returns (status_code, response_json_or_text).
    """
    url = f"{SOUNDCLOUD_API_BASE}{endpoint}"
    if headers is None:
        headers = get_auth_headers()

    attempt = 0
    while attempt < MAX_RETRIES:
        attempt += 1
        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
                data=data,
                files=files,
                timeout=120,
            )

            if resp.status_code == 429 and retry_on_429:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log(f"Rate limited (429), retrying in {delay}s... [attempt {attempt}/{MAX_RETRIES}]")
                time.sleep(delay)
                continue

            # Try to parse JSON
            try:
                body = resp.json()
            except Exception:
                body = resp.text

            return resp.status_code, body

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log(f"Request timed out, retrying in {delay}s... [attempt {attempt}/{MAX_RETRIES}]")
                time.sleep(delay)
                continue
            fail(f"Request timed out after {MAX_RETRIES} attempts")

        except requests.exceptions.ConnectionError as e:
            fail(f"Connection error: {e}")

    # Exhausted retries
    return resp.status_code, resp.text if hasattr(resp, 'text') else "Unknown error"


def validate_audio_file(filepath):
    """Validate that the audio file exists and has a supported extension."""
    path = Path(filepath)
    if not path.exists():
        fail(f"File not found: {filepath}")
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        fail(f"Unsupported audio format: {path.suffix}. Supported: {', '.join(sorted(AUDIO_EXTENSIONS))}")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 500:
        fail(f"File too large: {size_mb:.0f}MB. SoundCloud max is ~500MB.")
    return path


def validate_artwork(filepath):
    """Validate artwork file exists, format, and minimum dimensions."""
    if not filepath:
        return None
    path = Path(filepath)
    if not path.exists():
        fail(f"Artwork not found: {filepath}")
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        fail(f"Unsupported image format: {path.suffix}. Supported: JPG, PNG")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 10:
        fail(f"Artwork too large: {size_mb:.0f}MB. SoundCloud max is 10MB.")
    # Check dimensions via ffprobe
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            w, h = r.stdout.strip().split(",")
            w, h = int(w), int(h)
            if w < 800 or h < 800:
                fail(f"Artwork too small: {w}x{h}. Minimum 800x800 for SoundCloud.")
            log(f"Artwork validated: {w}x{h}")
        else:
            log("Could not verify artwork dimensions (ffprobe unavailable), proceeding anyway")
    except FileNotFoundError:
        log("ffprobe not found, skipping artwork dimension check")
    except Exception as e:
        log(f"Artwork dimension check skipped: {e}")
    return path


def resolve_track_id(track_id=None, track_url=None):
    """
    Resolve a track ID from either a direct ID or a SoundCloud URL.
    Returns integer track ID.
    """
    if track_id:
        return int(track_id)

    if track_url:
        # Try SoundCloud resolve endpoint
        headers = get_auth_headers()
        status, body = api_request("GET", "/resolve", headers=headers, params={"url": track_url})
        if status == 200 and isinstance(body, dict):
            if body.get("kind") == "track":
                return body["id"]
            fail(f"URL resolved to a '{body.get('kind', 'unknown')}', not a track")
        fail(f"Could not resolve URL: {track_url} (status {status})")

    fail("Must provide --track-id or --track-url")


# ──────────────────────────────────────────────
# COMMAND: upload
# ──────────────────────────────────────────────

def cmd_upload(args):
    """Upload a new track to SoundCloud."""
    audio_path = validate_audio_file(args.file)
    artwork_path = validate_artwork(args.artwork) if args.artwork else None

    title = args.title or audio_path.stem
    tags_list = [t.strip() for t in args.tags.split(",")] if args.tags else []

    log(f"Uploading: {audio_path.name} — {title}")

    # Build multipart form data
    headers = get_auth_headers()
    # Don't set Content-Type — requests handles multipart boundary

    track_metadata = {
        "track[title]": title,
        "track[sharing]": args.sharing or "public",
        "track[downloadable]": str(args.downloadable).lower() if args.downloadable else "false",
        "track[streamable]": "true",
    }

    if args.description:
        track_metadata["track[description]"] = args.description
    if args.genre:
        track_metadata["track[genre]"] = args.genre
    if tags_list:
        for i, tag in enumerate(tags_list):
            track_metadata[f"track[tag_list][{i}]"] = tag
    if args.release_date:
        track_metadata["track[release_date]"] = args.release_date
    if args.label:
        track_metadata["track[label_name]"] = args.label

    # Open files for upload
    files = {}
    audio_file = open(str(audio_path), "rb")
    files["track[asset_data]"] = (audio_path.name, audio_file, "application/octet-stream")

    artwork_file = None
    if artwork_path:
        artwork_file = open(str(artwork_path), "rb")
        mime = "image/png" if artwork_path.suffix.lower() == ".png" else "image/jpeg"
        files["track[artwork_data]"] = (artwork_path.name, artwork_file, mime)

    try:
        status, body = api_request("POST", "/tracks", headers=headers,
                                    data=track_metadata, files=files)
    finally:
        audio_file.close()
        if artwork_file:
            artwork_file.close()

    if status == 201 and isinstance(body, dict):
        track = body
        track_id = track.get("id")
        permalink = track.get("permalink_url", "N/A")
        state = track.get("state", "unknown")
        log(f"✅ Track uploaded! ID: {track_id}, State: {state}")
        output_result({
            "success": True,
            "track_id": track_id,
            "title": track.get("title"),
            "permalink_url": permalink,
            "state": state,
            "sharing": track.get("sharing"),
            "created_at": track.get("created_at"),
        })
    else:
        error_msg = body if isinstance(body, str) else body.get("errors", body) if isinstance(body, dict) else str(body)
        fail(f"Upload failed ({status}): {error_msg}")


# ──────────────────────────────────────────────
# COMMAND: update
# ──────────────────────────────────────────────

def cmd_update(args):
    """Update an existing track's metadata."""
    track_id = resolve_track_id(args.track_id, args.track_url)
    headers = get_auth_headers()

    # Build update payload — only send fields that were specified
    update_data = {}
    if args.title:
        update_data["track[title]"] = args.title
    if args.description is not None:
        update_data["track[description]"] = args.description
    if args.genre:
        update_data["track[genre]"] = args.genre
    if args.tags:
        tags_list = [t.strip() for t in args.tags.split(",")]
        for i, tag in enumerate(tags_list):
            update_data[f"track[tag_list][{i}]"] = tag
    if args.sharing:
        update_data["track[sharing]"] = args.sharing
    if args.downloadable is not None:
        update_data["track[downloadable]"] = str(args.downloadable).lower()
    if args.release_date:
        update_data["track[release_date]"] = args.release_date
    if args.label:
        update_data["track[label_name]"] = args.label

    # Handle artwork update
    files = None
    artwork_file = None
    artwork_path = validate_artwork(args.artwork) if args.artwork else None
    if artwork_path:
        files = {}
        artwork_file = open(str(artwork_path), "rb")
        files["track[artwork_data]"] = (artwork_path.name, artwork_file, "image/jpeg")

    if not update_data and not files:
        fail("Nothing to update. Specify at least one field to change.")

    log(f"Updating track {track_id}...")

    try:
        status, body = api_request("PUT", f"/tracks/{track_id}", headers=headers,
                                    data=update_data, files=files)
    finally:
        if artwork_file:
            artwork_file.close()

    if status == 200 and isinstance(body, dict):
        track = body
        log(f"✅ Track {track_id} updated")
        output_result({
            "success": True,
            "track_id": track_id,
            "title": track.get("title"),
            "description": track.get("description", ""),
            "genre": track.get("genre", ""),
            "sharing": track.get("sharing"),
            "downloadable": track.get("downloadable"),
            "permalink_url": track.get("permalink_url"),
        })
    else:
        error_msg = body if isinstance(body, str) else body.get("errors", body) if isinstance(body, dict) else str(body)
        fail(f"Update failed ({status}): {error_msg}")


# ──────────────────────────────────────────────
# COMMAND: list
# ──────────────────────────────────────────────

def cmd_list(args):
    """List the authenticated user's tracks."""
    headers = get_auth_headers()
    limit = args.limit or 10

    log(f"Fetching {limit} recent tracks...")

    status, body = api_request("GET", "/me/tracks", headers=headers,
                                params={"limit": limit, "linked_partitioning": 1})

    if status != 200:
        fail(f"Failed to list tracks ({status}): {body}")

    tracks = body if isinstance(body, list) else body.get("collection", [])

    if args.json_output:
        output_result({
            "success": True,
            "count": len(tracks),
            "tracks": [{
                "id": t.get("id"),
                "title": t.get("title"),
                "state": t.get("state"),
                "sharing": t.get("sharing"),
                "genre": t.get("genre", ""),
                "created_at": t.get("created_at"),
                "permalink_url": t.get("permalink_url"),
                "downloadable": t.get("downloadable"),
                "playback_count": t.get("playback_count", 0),
                "duration": t.get("duration", 0),
            } for t in tracks]
        })
    else:
        # Human-readable table
        lines = [f"Found {len(tracks)} tracks:\n"]
        for t in tracks:
            state_icon = "✅" if t.get("state") == "finished" else "⏳" if t.get("state") == "processing" else "❓"
            sharing_icon = "🌐" if t.get("sharing") == "public" else "🔒"
            duration_s = t.get("duration", 0) // 1000  # SoundCloud returns ms
            duration_str = f"{duration_s // 60}:{duration_s % 60:02d}" if duration_s else "?"
            lines.append(
                f"  {state_icon} {sharing_icon} {t.get('id','?'):>10} │ "
                f"{t.get('title', 'Untitled')[:50]:<50} │ "
                f"{duration_str:>6} │ {t.get('genre', '')[:20]}"
            )
        result_text = "\n".join(lines)
        output_result({"success": True, "count": len(tracks), "text": result_text})


# ──────────────────────────────────────────────
# COMMAND: status
# ──────────────────────────────────────────────

def cmd_status(args):
    """Get details and encoding status of a specific track."""
    track_id = resolve_track_id(args.track_id, args.track_url)
    headers = get_auth_headers()

    log(f"Checking status of track {track_id}...")

    status, body = api_request("GET", f"/tracks/{track_id}", headers=headers)

    if status != 200:
        fail(f"Track {track_id} not found or access denied ({status}): {body}")

    track = body
    state = track.get("state", "unknown")
    state_description = {
        "finished": "✅ Track is live and playable",
        "processing": "⏳ SoundCloud is encoding the audio — check back in a minute",
        "failed": "❌ Encoding failed — re-upload the track",
        "uploading": "📤 Upload still in progress",
    }.get(state, f"❓ Unknown state: {state}")

    duration_ms = track.get("duration", 0)
    duration_s = duration_ms // 1000 if duration_ms else 0

    output_result({
        "success": True,
        "track_id": track_id,
        "title": track.get("title"),
        "state": state,
        "state_description": state_description,
        "sharing": track.get("sharing"),
        "downloadable": track.get("downloadable"),
        "genre": track.get("genre", ""),
        "tag_list": track.get("tag_list", ""),
        "description": track.get("description", ""),
        "duration_seconds": duration_s,
        "duration_display": f"{duration_s // 60}:{duration_s % 60:02d}" if duration_s else "N/A",
        "permalink_url": track.get("permalink_url"),
        "artwork_url": track.get("artwork_url"),
        "playback_count": track.get("playback_count", 0),
        "download_count": track.get("download_count", 0),
        "favoritings_count": track.get("favoritings_count", 0),
        "created_at": track.get("created_at"),
        "last_modified": track.get("last_modified"),
        "user": {
            "id": track.get("user", {}).get("id"),
            "username": track.get("user", {}).get("username"),
        } if track.get("user") else None,
    })


# ──────────────────────────────────────────────
# COMMAND: batch-upload
# ──────────────────────────────────────────────

def cmd_batch_upload(args):
    """Upload all audio files from a directory."""
    directory = Path(args.dir)
    if not directory.is_dir():
        fail(f"Directory not found: {args.dir}")

    # Find audio files
    audio_files = sorted([
        f for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    ])

    # Deduplicate: when both FLAC and MP3 exist for the same track, keep only FLAC
    # (SoundCloud accepts FLAC natively and transcodes server-side)
    stems_seen = {}
    for f in audio_files:
        stem = f.stem.lower()
        if stem in stems_seen:
            existing = stems_seen[stem]
            # Prefer FLAC > WAV > AIFF > everything else > MP3
            lossless = {".flac", ".wav", ".aiff"}
            if f.suffix.lower() in lossless and existing.suffix.lower() not in lossless:
                stems_seen[stem] = f  # Replace lossy with lossless
            elif f.suffix.lower() == ".flac" and existing.suffix.lower() != ".flac":
                stems_seen[stem] = f  # FLAC beats WAV/AIFF for size
        else:
            stems_seen[stem] = f
    audio_files = sorted(stems_seen.values())

    if not audio_files:
        fail(f"No audio files found in {args.dir}")

    # Find artwork files
    artwork_dir = Path(args.artwork_dir) if args.artwork_dir else directory
    artwork_map = {}
    if args.artwork_dir or args.artwork_dir is None:
        for img in artwork_dir.iterdir():
            if img.suffix.lower() in IMAGE_EXTENSIONS:
                # Map by base name (without extension)
                artwork_map[img.stem.lower()] = img

    log(f"Found {len(audio_files)} audio files to upload")

    results = []
    for i, audio_path in enumerate(audio_files, 1):
        title = args.title_template or audio_path.stem
        # Replace {n} placeholder with track number
        title = title.replace("{n}", str(i)).replace("{N}", str(i).zfill(2))

        # Find matching artwork by base name
        artwork = None
        base = audio_path.stem.lower()
        for key in [base, base.replace(" ", "-"), base.replace("-", " ")]:
            if key in artwork_map:
                artwork = artwork_map[key]
                break

        # Also check for generic cover if no match
        if not artwork:
            for candidate_name in ["cover", "artwork", "folder", "album"]:
                if candidate_name in artwork_map:
                    artwork = artwork_map[candidate_name]
                    break

        log(f"[{i}/{len(audio_files)}] Uploading: {audio_path.name}")

        # Build metadata
        track_metadata = {
            "track[title]": title,
            "track[sharing]": args.sharing or "public",
            "track[downloadable]": str(args.downloadable).lower() if args.downloadable else "false",
            "track[streamable]": "true",
        }

        if args.description:
            desc = args.description.replace("{n}", str(i)).replace("{N}", str(i).zfill(2))
            track_metadata["track[description]"] = desc
        if args.genre:
            track_metadata["track[genre]"] = args.genre
        if args.tags:
            tags_list = [t.strip() for t in args.tags.split(",")]
            for j, tag in enumerate(tags_list):
                track_metadata[f"track[tag_list][{j}]"] = tag

        # Upload
        headers = get_auth_headers()
        files = {}
        audio_file = open(str(audio_path), "rb")
        files["track[asset_data]"] = (audio_path.name, audio_file, "application/octet-stream")

        artwork_file = None
        if artwork:
            artwork_file = open(str(artwork), "rb")
            content_type = "image/jpeg" if artwork.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            files["track[artwork_data]"] = (artwork.name, artwork_file, content_type)

        try:
            status, body = api_request("POST", "/tracks", headers=headers,
                                        data=track_metadata, files=files)
        finally:
            audio_file.close()
            if artwork_file:
                artwork_file.close()

        if status == 201 and isinstance(body, dict):
            track = body
            results.append({
                "success": True,
                "file": audio_path.name,
                "track_id": track.get("id"),
                "title": track.get("title"),
                "permalink_url": track.get("permalink_url"),
                "state": track.get("state"),
            })
            log(f"  ✅ Uploaded: {track.get('title')} (ID: {track.get('id')})")
        else:
            error_msg = body if isinstance(body, str) else body.get("errors", body) if isinstance(body, dict) else str(body)
            results.append({
                "success": False,
                "file": audio_path.name,
                "error": f"Upload failed ({status}): {error_msg}",
            })
            log(f"  ❌ Failed: {audio_path.name} — {error_msg}")

        # Small delay between uploads to avoid rate limits
        if i < len(audio_files):
            time.sleep(1)

    # Summary
    succeeded = sum(1 for r in results if r["success"])
    failed = len(results) - succeeded
    log(f"\nBatch upload complete: {succeeded} succeeded, {failed} failed")

    output_result({
        "success": failed == 0,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    })


# ──────────────────────────────────────────────
# COMMAND: create-playlist
# ──────────────────────────────────────────────

def cmd_create_playlist(args):
    """Create a new playlist."""
    headers = get_auth_headers()
    
    track_ids = [t.strip() for t in args.track_ids.split(",")] if args.track_ids else []
    
    playlist_data = {
        "playlist[title]": args.title,
        "playlist[sharing]": args.sharing,
    }
    
    if track_ids:
        playlist_data["playlist[tracks][][id]"] = track_ids

    if args.description:
        playlist_data["playlist[description]"] = args.description
    
    if args.tags:
        tags_list = [t.strip() for t in args.tags.split(",")]
        for i, tag in enumerate(tags_list):
            playlist_data[f"playlist[tag_list][{i}]"] = tag

    files = None
    artwork_file = None
    artwork_path = validate_artwork(args.artwork) if args.artwork else None
    if artwork_path:
        files = {}
        artwork_file = open(str(artwork_path), "rb")
        mime = "image/png" if artwork_path.suffix.lower() == ".png" else "image/jpeg"
        files["playlist[artwork_data]"] = (artwork_path.name, artwork_file, mime)

    log(f"Creating playlist: {args.title}")

    try:
        status, body = api_request("POST", "/playlists", headers=headers,
                                    data=playlist_data, files=files)
    finally:
        if artwork_file:
            artwork_file.close()

    if status == 201 and isinstance(body, dict):
        permalink = body.get("permalink_url", "N/A")
        log(f"✅ Playlist created! URL: {permalink}")
        output_result({
            "success": True,
            "playlist_id": body.get("id"),
            "permalink_url": permalink,
        })
    else:
        error_msg = body if isinstance(body, str) else body.get("errors", body) if isinstance(body, dict) else str(body)
        fail(f"Playlist creation failed ({status}): {error_msg}")


# ──────────────────────────────────────────────
# Main argument parser
# ──────────────────────────────────────────────


# COMMAND: update-playlist
def cmd_update_playlist(args):
    playlist_data = {}
    files = {}
    
    if args.title:
        playlist_data["playlist[title]"] = args.title
    if getattr(args, "track_ids", None):
        playlist_data["playlist[tracks][][id]"] = [t.strip() for t in args.track_ids.split(",")]
    if getattr(args, "artwork", None):
        import mimetypes
        from pathlib import Path
        artwork_path = Path(args.artwork)
        if not artwork_path.exists():
            fail(f"Artwork file not found: {args.artwork}")
        mime, _ = mimetypes.guess_type(artwork_path)
        mime = mime or "image/jpeg"
        artwork_file = open(artwork_path, "rb")
        files["playlist[artwork_data]"] = (artwork_path.name, artwork_file, mime)
    
    if not playlist_data and not files:
        fail("Nothing to update.")
        
    log(f"Updating playlist {args.playlist_id}...")
    headers = get_auth_headers()
    try:
        status, body = api_request("PUT", f"/playlists/{args.playlist_id}", headers=headers,
                                    data=playlist_data, files=files)
        if status in [200, 201]:
            log("✅ Playlist updated!")
            import json
            print(json.dumps({"status": "success"}))
        else:
            fail(f"Update failed ({status}): {body}")
    finally:
        for _, (name, f, mime) in files.items():
            f.close()

def main():
    parser = argparse.ArgumentParser(
        description="SoundCloud API client — upload, update, list, and manage tracks"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── upload ──
    upload_parser = subparsers.add_parser("upload", help="Upload a new track")
    upload_parser.add_argument("--file", required=True, help="Path to audio file")
    upload_parser.add_argument("--title", default=None, help="Track title (defaults to filename)")
    upload_parser.add_argument("--description", default=None, help="Track description")
    upload_parser.add_argument("--tags", default=None, help="Comma-separated tags")
    upload_parser.add_argument("--genre", default=None, help="Genre (e.g. 'Electronic')")
    upload_parser.add_argument("--artwork", default=None, help="Path to cover art (JPG/PNG, min 800x800)")
    upload_parser.add_argument("--sharing", choices=["public", "private"], default="public")
    upload_parser.add_argument("--downloadable", action="store_true", help="Allow downloads")
    upload_parser.add_argument("--release-date", default=None, help="Release date (ISO format)")
    upload_parser.add_argument("--label", default=None, help="Label name")

    # ── update ──
    update_parser = subparsers.add_parser("update", help="Update track metadata")
    update_parser.add_argument("--track-id", type=int, default=None, help="Track ID")
    update_parser.add_argument("--track-url", default=None, help="SoundCloud track URL")
    update_parser.add_argument("--title", default=None, help="New title")
    update_parser.add_argument("--description", default=None, help="New description")
    update_parser.add_argument("--tags", default=None, help="New comma-separated tags")
    update_parser.add_argument("--genre", default=None, help="New genre")
    update_parser.add_argument("--artwork", default=None, help="New cover art")
    update_parser.add_argument("--sharing", choices=["public", "private"], default=None)
    update_parser.add_argument("--downloadable", type=bool, default=None, help="true/false")
    update_parser.add_argument("--release-date", default=None, help="New release date")
    update_parser.add_argument("--label", default=None, help="New label name")

    # ── list ──
    list_parser = subparsers.add_parser("list", help="List your recent tracks")
    list_parser.add_argument("--limit", type=int, default=10, help="Number of tracks (default 10)")
    list_parser.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    # ── status ──
    status_parser = subparsers.add_parser("status", help="Check track status/details")
    status_parser.add_argument("--track-id", type=int, default=None, help="Track ID")
    status_parser.add_argument("--track-url", default=None, help="SoundCloud track URL")

    # ── batch-upload ──
    batch_parser = subparsers.add_parser("batch-upload", help="Upload all audio files from a directory")
    batch_parser.add_argument("--dir", required=True, help="Directory containing audio files")
    batch_parser.add_argument("--artwork-dir", default=None, help="Directory with cover art (matches by filename)")
    batch_parser.add_argument("--title-template", default=None,
                              help="Title template ({n}=track number, {N}=zero-padded)")
    batch_parser.add_argument("--description", default=None, help="Description template ({n}/{N} supported)")
    batch_parser.add_argument("--genre", default=None, help="Genre for all tracks")
    batch_parser.add_argument("--tags", default=None, help="Comma-separated tags for all tracks")
    batch_parser.add_argument("--sharing", choices=["public", "private"], default="public")
    batch_parser.add_argument("--downloadable", action="store_true", help="Allow downloads")


    # ── update-playlist ──
    upd_playlist_parser = subparsers.add_parser("update-playlist", help="Update a playlist")
    upd_playlist_parser.add_argument("--playlist-id", required=True)
    upd_playlist_parser.add_argument("--title", default=None)
    upd_playlist_parser.add_argument("--artwork", default=None)
    upd_playlist_parser.add_argument("--track-ids", default=None)

    # ── create-playlist ──
    playlist_parser = subparsers.add_parser("create-playlist", help="Create a playlist from uploaded track IDs")
    playlist_parser.add_argument("--title", required=True, help="Playlist title")
    playlist_parser.add_argument("--track-ids", required=True, help="Comma-separated SoundCloud track IDs")
    playlist_parser.add_argument("--artwork", default=None, help="Path to playlist cover art (JPG/PNG)")
    playlist_parser.add_argument("--description", default=None, help="Playlist description")
    playlist_parser.add_argument("--tags", default=None, help="Comma-separated tags")
    playlist_parser.add_argument("--sharing", choices=["public", "private"], default="public")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "upload": cmd_upload,
        "update": cmd_update,
        "list": cmd_list,
        "status": cmd_status,
        "batch-upload": cmd_batch_upload,
        "create-playlist": cmd_create_playlist,
        "update-playlist": cmd_update_playlist,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()

