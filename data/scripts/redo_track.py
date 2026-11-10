#!/usr/bin/env python3
"""
redo_track.py — Deterministic, single-command track redo orchestrator.

Eliminates title drift, duration truncation, and unmastered audio drops by:
  1. Locking the canonical track title from release.json (no K3 renaming).
  2. Enforcing the exact album duration (260s / 4:20 default, never falling back to 150s/60s).
  3. Generating stems via master-producer with locked parameters.
  4. Packaging masters and re-tagging FLAC/MP3 with proper track artwork.

Usage:
  python3 redo_track.py --release overpass-sodium --track 3 --feedback "Harder 808 drop, darker pads"
  python3 redo_track.py --release overpass-sodium --track 3 --duration 260
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Paths
BASE_DIR = Path("/opt/data" if sys.platform != "win32" else r"D:\sp2\data")
RELEASES_DIR = Path(os.environ.get("RELEASES_DIR", "/opt/data/music/releases" if sys.platform != "win32" else r"D:\music\releases"))
PROFILES_DIR = Path(os.environ.get("PROFILES_DIR", "/opt/data/music/profiles" if sys.platform != "win32" else r"D:\sp2\data\music\profiles"))
PRODUCTIONS_DIR = Path(os.environ.get("PRODUCTIONS_DIR", "/opt/data/music/productions" if sys.platform != "win32" else r"D:\music\productions"))
MASTER_PRODUCER = Path("/opt/data/skills/master-producer/master-producer/scripts/master-producer.py" if sys.platform != "win32" else r"D:\sp2\data\skills\master-producer\master-producer\scripts\master-producer.py")
TAG_SCRIPT = Path("/opt/data/skills/delivery-receipt/scripts/tag_metadata.py" if sys.platform != "win32" else r"D:\sp2\data\skills\delivery-receipt\scripts\tag_metadata.py")


def log(msg):
    print(f"[redo] {msg}", flush=True)


def load_release_info(release_slug):
    release_dir = RELEASES_DIR / release_slug
    if not release_dir.exists():
        log(f"Error: Release directory not found: {release_dir}")
        sys.exit(1)

    rel_json = release_dir / "release.json"
    manifest = {}
    if rel_json.exists():
        try:
            with open(rel_json, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            log(f"Warning: could not read release.json: {e}")

    meta_json = release_dir / "tracks_meta.json"
    tracks_meta = []
    if meta_json.exists():
        try:
            with open(meta_json, "r", encoding="utf-8") as f:
                tracks_meta = json.load(f)
        except Exception as e:
            log(f"Warning: could not read tracks_meta.json: {e}")

    return release_dir, manifest, tracks_meta


def redo_track(release_slug, track_num, feedback=None, duration=None, dry_run=False):
    release_dir, manifest, tracks_meta = load_release_info(release_slug)

    # 1. Identify Track Title
    track_title = None
    tracks_list = manifest.get("tracks", [])
    if 1 <= track_num <= len(tracks_list):
        track_title = tracks_list[track_num - 1]
    elif 1 <= track_num <= len(tracks_meta):
        track_title = tracks_meta[track_num - 1].get("title")

    if not track_title:
        log(f"Error: Could not determine title for Track {track_num} in release {release_slug}")
        sys.exit(1)

    track_title = track_title.strip().upper()
    log(f"Target Track: [{track_num}/{len(tracks_list) or len(tracks_meta)}] '{track_title}'")

    # 2. Determine Duration
    # Strict hierarchy: CLI override > release.json > 260s default
    target_duration = duration or manifest.get("duration") or 260
    log(f"Locked Duration: {target_duration}s (4:{target_duration%60:02d})")

    # 3. Load Sonic Identity & Brief
    album_name = manifest.get("album", release_slug.replace("-", " ").title())
    genre = manifest.get("genre", "Hyperspeed Cyber-Samurai Drift Phonk / West Coast Bass")

    profile_path = PROFILES_DIR / "vidride" / "profile.json"
    profile_prefix = ""
    if profile_path.exists():
        try:
            with open(profile_path, "r", encoding="utf-8") as pf:
                prof = json.load(pf)
                profile_prefix = prof.get("prompt_prefix", "")
        except Exception:
            pass

    brief = f"{album_name} — {genre}. Track {track_num}: {track_title}."
    if feedback:
        brief += f" [USER REVISION]: {feedback}."
    if profile_prefix:
        brief += f"\nSONIC SIGNATURE:\n{profile_prefix}"

    # 4. Context File
    ctx = {
        "track_number": track_num,
        "total_tracks": len(tracks_list) or 5,
        "album_name": album_name,
        "album_theme": genre,
        "track_title": track_title,
        "brief": brief,
        "variation_rules": [f"User redo directive: {feedback}"] if feedback else []
    }
    ctx_path = Path("/tmp" if sys.platform != "win32" else os.environ.get("TEMP", "/tmp")) / f"album_ctx_redo_{track_num}.json"
    with open(ctx_path, "w", encoding="utf-8") as f:
        json.dump(ctx, f, indent=2)

    # 5. Build Execution Command
    python_bin = sys.executable
    cmd = [
        str(python_bin), str(MASTER_PRODUCER),
        "--prompt", brief,
        "--duration", str(target_duration),
        "--quality", "standard",
        "--director",
        "--title", track_title,
        "--no-deliver"
    ]

    log(f"Executing: {' '.join(cmd[:6])} --title '{track_title}' ...")

    if dry_run:
        log("DRY RUN — exiting without generating.")
        return True

    env = os.environ.copy()
    env["ALBUM_CONTEXT_FILE"] = str(ctx_path)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)

    if proc.returncode != 0:
        log(f"❌ Track generation failed:\n{proc.stderr[-500:]}")
        return False

    # 6. Parse Output for Generated Files
    generated_mp3 = None
    generated_flac = None
    try:
        last_line = proc.stdout.strip().split("\n")[-1]
        rj = json.loads(last_line)
        files = rj.get("files", {})
        generated_mp3 = files.get("mp3")
        generated_flac = files.get("flac")
    except Exception:
        # Fallback to inspecting recent productions directory
        log("Inspecting recent productions directory...")
        recent_dirs = sorted(PRODUCTIONS_DIR.glob(f"*{release_slug}*"), key=os.path.getmtime)
        if recent_dirs:
            latest = recent_dirs[-1]
            flacs = list(latest.glob("*.flac"))
            mp3s = list(latest.glob("*.mp3"))
            if flacs:
                generated_flac = str(flacs[0])
            if mp3s:
                generated_mp3 = str(mp3s[0])

    if not generated_flac or not os.path.exists(generated_flac):
        log("❌ Could not locate generated FLAC master.")
        return False

    # 7. Copy to Release Directory
    target_flac_name = f"{track_title.lower().replace(' ', '_')}_MASTER.flac"
    dest_flac = release_dir / target_flac_name
    shutil.copy2(generated_flac, dest_flac)
    log(f"  ✓ Copied FLAC: {dest_flac.name} ({os.path.getsize(dest_flac)/1024/1024:.1f} MB)")

    if generated_mp3 and os.path.exists(generated_mp3):
        target_mp3_name = f"{track_title.lower().replace(' ', '_')}_MASTER.mp3"
        dest_mp3 = release_dir / target_mp3_name
        shutil.copy2(generated_mp3, dest_mp3)
        log(f"  ✓ Copied MP3: {dest_mp3.name}")

    # 8. Re-tag Release Metadata & Artwork
    log("Re-tagging release metadata and embedding artwork...")
    tag_cmd = [str(python_bin), str(TAG_SCRIPT), "--release", release_slug]
    tag_proc = subprocess.run(tag_cmd, capture_output=True, text=True)
    if tag_proc.returncode == 0:
        log("  ✓ Metadata tagging complete.")
    else:
        log(f"  ⚠️ Tagging warning:\n{tag_proc.stderr[-300:]}")

    log(f"✅ Track {track_num} ({track_title}) successfully remade and synchronized with {release_slug}!")
    return True


def main():
    parser = argparse.ArgumentParser(description="Deterministic single-track redo orchestrator")
    parser.add_argument("--release", required=True, help="Album release slug (e.g. overpass-sodium)")
    parser.add_argument("--track", type=int, required=True, help="Track number (1-indexed)")
    parser.add_argument("--feedback", help="Feedback / sonic directive for the revision")
    parser.add_argument("--duration", type=int, help="Target duration in seconds (default: locked from release or 260s)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without running generation")
    args = parser.parse_args()

    success = redo_track(
        release_slug=args.release,
        track_num=args.track,
        feedback=args.feedback,
        duration=args.duration,
        dry_run=args.dry_run
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
