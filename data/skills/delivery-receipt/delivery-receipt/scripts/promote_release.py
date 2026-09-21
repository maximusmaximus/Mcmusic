#!/usr/bin/env python3
"""
promote_release.py — Promote an export session to the canonical releases directory.

The releases directory is the SINGLE SOURCE OF TRUTH for publish-ready tracks.
hermes-music should ONLY publish from /opt/data/music/releases/.

Usage:
  python3 promote_release.py --from mars-descent-v3 --as mars-descent
  python3 promote_release.py --from mars-descent-v3 --as mars-descent --cleanup
  python3 promote_release.py --list
"""
import argparse
import json
import os
import shutil
from pathlib import Path
from datetime import datetime

EXPORTS_DIR = Path(os.environ.get("LOCAL_EXPORTS", "/opt/data/music/exports"))
RELEASES_DIR = Path(os.environ.get("RELEASES_DIR", "/opt/data/music/releases"))
WIN_ROOT = os.environ.get("WIN_MUSIC_ROOT", r"D:\music")


def to_windows(path):
    s = str(path)
    if s.startswith("/opt/data/music/"):
        return os.path.join(WIN_ROOT, s[len("/opt/data/music/"):]).replace("/", "\\")
    return s


def list_releases():
    """List all current releases."""
    if not RELEASES_DIR.exists():
        print(json.dumps({"releases": []}))
        return

    releases = []
    for d in sorted(RELEASES_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest = d / "release.json"
        info = {"name": d.name, "windows_path": to_windows(d)}
        if manifest.exists():
            info.update(json.load(open(manifest)))
        flacs = list(d.glob("*.flac"))
        info["track_count"] = len(flacs)
        info["total_mb"] = round(sum(f.stat().st_size for f in flacs) / (1024*1024), 1)
        releases.append(info)

    print(json.dumps({"releases": releases}, indent=2))


def promote(from_session, as_name, artwork_dir="/opt/data/music/artwork/covers/", cleanup=False):
    """Promote an export session to the releases directory."""
    src = EXPORTS_DIR / from_session
    if not src.exists():
        print(f"ERROR: Export session '{from_session}' not found")
        return False

    dst = RELEASES_DIR / as_name
    dst.mkdir(parents=True, exist_ok=True)

    # Clean existing release
    for f in dst.iterdir():
        if f.is_file():
            f.unlink()

    # Copy all FLAC, MP3, and playlist files
    copied = {"flac": 0, "mp3": 0, "other": 0}
    tracks = []
    for f in sorted(src.iterdir()):
        if not f.is_file():
            continue
        if f.suffix in (".flac", ".mp3", ".m3u8", ".json"):
            shutil.copy2(str(f), str(dst / f.name))
            if f.suffix == ".flac":
                copied["flac"] += 1
                tracks.append(f.stem.replace("_MASTER", "").replace("_", " "))
            elif f.suffix == ".mp3":
                copied["mp3"] += 1
            else:
                copied["other"] += 1

    # Look for artwork covers
    artwork_path = Path(artwork_dir)
    covers_found = []
    if artwork_path.exists():
        candidates = set()
        matched_subdir = None
        name_variants = [as_name, as_name.replace("-", "_")]
        
        # 1. Check artwork dir for a subdirectory matching the release name
        for d in artwork_path.iterdir():
            if d.is_dir() and any(v in d.name for v in name_variants):
                matched_subdir = d
                break
                
        if matched_subdir:
            # 2. If found, copy all PNGs from that subdir
            for f in matched_subdir.glob("*.png"):
                candidates.add(f)
        else:
            # 3. If not found, search the artwork dir root for PNGs containing the release name
            for f in artwork_path.glob("*.png"):
                if any(v in f.name for v in name_variants):
                    candidates.add(f)
                    
        # 4. Always look for *_album_* or *_playlist_* files as the album cover (in root)
        for f in artwork_path.glob("*.png"):
            if ("_album_" in f.name or "_playlist_" in f.name) and any(v in f.name for v in name_variants):
                candidates.add(f)

        for c in sorted(candidates):
            shutil.copy2(str(c), str(dst / c.name))
            covers_found.append(c.name)

    # Create release manifest
    release_manifest = {
        "album": as_name.upper().replace("-", " "),
        "promoted_from": from_session,
        "promoted_at": datetime.now().isoformat(),
        "track_count": copied["flac"],
        "tracks": tracks,
        "covers": covers_found,
        "status": "release-ready",
        "windows_path": to_windows(dst),
        "source": "dawagent-mix-mastered",
    }
    with open(dst / "release.json", "w") as f:
        json.dump(release_manifest, f, indent=2)

    # Update playlist paths to point to releases dir
    for pl in dst.glob("*.m3u8"):
        content = pl.read_text(encoding="utf-8")
        content = content.replace(
            f"exports\\{from_session}\\",
            f"releases\\{as_name}\\"
        ).replace(
            f"exports/{from_session}/",
            f"releases/{as_name}/"
        )
        pl.write_text(content, encoding="utf-8")
        # Rename playlist to match release name
        new_name = dst / f"{as_name}_playlist.m3u8"
        if pl.name != new_name.name:
            pl.rename(new_name)

    print(f"✅ Promoted {from_session} → releases/{as_name}")
    print(f"   {copied['flac']} FLACs, {copied['mp3']} MP3s")
    print(f"   Windows: {to_windows(dst)}")

    # ── Tag all audio files with metadata + cover art ──
    tag_script = Path(os.environ.get("HERMES_HOME", "/opt/data")) / \
        "skills/delivery-receipt/delivery-receipt/scripts/tag_metadata.py"
    if tag_script.exists():
        print(f"   Tagging metadata...")
        import subprocess
        result = subprocess.run(
            ["python3", str(tag_script), "--release", as_name],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            # Count tagged lines from output
            tagged_lines = [l for l in result.stdout.splitlines() if "✓" in l]
            print(f"   🏷️ Tagged {len(tagged_lines)} files with metadata + cover art")
        else:
            print(f"   ⚠️ Tagging failed: {result.stderr[-200:]}")

    # Cleanup old export versions if requested
    if cleanup:
        cleaned = 0
        for d in EXPORTS_DIR.iterdir():
            if d.is_dir() and d.name.startswith(as_name):
                shutil.rmtree(str(d))
                print(f"   🗑️ Removed exports/{d.name}")
                cleaned += 1
        if cleaned:
            print(f"   Cleaned {cleaned} old export version(s)")

    return True


def main():
    parser = argparse.ArgumentParser(description="Promote exports to canonical releases")
    parser.add_argument("--list", action="store_true", help="List all releases")
    parser.add_argument("--from", dest="from_session", help="Source export session")
    parser.add_argument("--as", dest="as_name", help="Release name (canonical album name)")
    parser.add_argument("--cleanup", action="store_true", help="Remove old export versions after promoting")
    parser.add_argument("--artwork-dir", default="/opt/data/music/artwork/covers/", help="Directory containing artwork covers")
    args = parser.parse_args()

    if args.list:
        list_releases()
    elif args.from_session and args.as_name:
        promote(args.from_session, args.as_name, artwork_dir=args.artwork_dir, cleanup=args.cleanup)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
