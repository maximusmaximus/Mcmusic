#!/usr/bin/env python3
"""
tag_metadata.py — Tag FLAC/MP3 files with production metadata + embedded cover art.

Embeds: artist (VØIDRIDE), album, clean title, track number, genre, description/comment,
BPM, key, copyright, publisher.
Embeds track cover or album cover directly into FLAC (METADATA_BLOCK_PICTURE) and MP3 (APIC).

Usage:
  python3 tag_metadata.py --release saltflat-armory
  python3 tag_metadata.py --session saltflat-armory
  python3 tag_metadata.py --dir /opt/data/music/exports/saltflat-armory
"""

import argparse
import json
import os
import re
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    EXPORTS_DIR = Path(os.environ.get("LOCAL_EXPORTS", r"D:\music\exports"))
    RELEASES_DIR = Path(os.environ.get("RELEASES_DIR", r"D:\music\releases"))
    ARTWORK_DIR = Path(os.environ.get("ARTWORK_DIR", r"D:\music\artwork\covers"))
    ALBUMS_DIR = Path(os.environ.get("ALBUMS_DIR", r"D:\music\albums"))
else:
    EXPORTS_DIR = Path(os.environ.get("LOCAL_EXPORTS", "/opt/data/music/exports"))
    RELEASES_DIR = Path(os.environ.get("RELEASES_DIR", "/opt/data/music/releases"))
    ARTWORK_DIR = Path(os.environ.get("ARTWORK_DIR", "/opt/data/music/artwork/covers"))
    ALBUMS_DIR = Path(os.environ.get("ALBUMS_DIR", "/opt/data/music/albums"))

PROFILES = {
    "vidride": {
        "artist": "VØIDRIDE",
        "artist_sort": "VOIDRIDE",
        "publisher": "VØIDRIDE",
        "copyright_holder": "Max Infeld",
        "genre_default": "Dark Nightride Trap / Phonk",
    },
}
DEFAULT_PROFILE = "vidride"

def log(msg):
    print(f"[tag] {msg}", flush=True)

def clean_track_title(raw_stem):
    """Strip file prefixes like '1_', '01_', '01 - ' and master suffixes."""
    s = raw_stem.replace("_MASTER", "").replace(".MASTER", "").strip()
    s = re.sub(r'^\d+[\s._-]+', '', s).strip()
    return s.replace("_", " ")

def find_cover_for_track(target_dir, release_name, track_title, track_num=None):
    """Search for per-track or album cover across target dir, canonical album dir, and artwork dir."""
    title_clean = clean_track_title(track_title).upper()
    title_slug = title_clean.replace(" ", "_")
    slug_hyphen = release_name.replace("_", "-").lower() if release_name else ""
    slug_under = release_name.replace("-", "_").lower() if release_name else ""

    search_dirs = []
    if target_dir:
        td = Path(target_dir)
        search_dirs.append(td)
        if (td / "artwork").exists():
            search_dirs.append(td / "artwork")
    
    if release_name:
        alb_art = ALBUMS_DIR / slug_hyphen / "artwork"
        if alb_art.exists():
            search_dirs.append(alb_art)
        art_sub = ARTWORK_DIR / slug_hyphen
        if art_sub.exists():
            search_dirs.append(art_sub)
        art_sub_u = ARTWORK_DIR / slug_under
        if art_sub_u.exists():
            search_dirs.append(art_sub_u)

    if ARTWORK_DIR.exists():
        search_dirs.append(ARTWORK_DIR)

    # 1. Per-track cover search
    for sdir in search_dirs:
        if not sdir.exists():
            continue
        is_generic_root = (sdir == ARTWORK_DIR)
        for ext in ["*.png", "*.jpg", "*.jpeg"]:
            for f in sdir.glob(ext):
                fn_up = f.name.upper()
                fn_low = f.name.lower()
                # If searching in generic root, must belong to this album or match exact track title
                if is_generic_root and slug_hyphen and (slug_hyphen not in fn_low and slug_under not in fn_low):
                    if len(title_clean) >= 5 and title_clean in fn_up:
                        return f
                    continue
                if (title_slug and title_slug in fn_up) or (title_clean and title_clean in fn_up):
                    return f
                if track_num is not None and not is_generic_root:
                    if f"{track_num:02d}_" in f.name or f"{track_num}_" in f.name:
                        return f

    # 2. Album cover fallback
    for sdir in search_dirs:
        if not sdir.exists():
            continue
        is_generic_root = (sdir == ARTWORK_DIR)
        if is_generic_root and slug_hyphen:
            patterns = [f"*{slug_hyphen}*", f"*{slug_under}*"]
        else:
            patterns = ["*album_cover*", "*album*", "*cover*", "*playlist*"]

        for pattern in patterns:
            for ext in [".png", ".jpg", ".jpeg"]:
                matches = list(sdir.glob(f"{pattern}{ext}"))
                if matches:
                    return sorted(matches)[0]

    return None

def tag_file_ffmpeg(filepath, metadata, cover_path=None):
    """Tag audio file using ffmpeg with Vorbis (FLAC) or ID3v2 (MP3) tags and attach cover."""
    fp = Path(filepath)
    if not fp.exists():
        return False

    inputs = ["-i", str(fp)]
    maps = ["-map", "0:a"]
    meta_args = []

    for key, val in metadata.items():
        if val is not None and str(val).strip():
            meta_args.extend(["-metadata", f"{key}={val}"])

    has_cover = False
    if cover_path and Path(cover_path).exists():
        inputs.extend(["-i", str(cover_path)])
        maps.extend(["-map", "1:v"])
        meta_args.extend([
            "-metadata:s:v", "title=Album cover",
            "-metadata:s:v", "comment=Cover (front)",
            "-disposition:v", "attached_pic"
        ])
        has_cover = True

    tmp = tempfile.NamedTemporaryFile(suffix=fp.suffix, delete=False, dir=str(fp.parent))
    tmp.close()

    try:
        cmd = ["ffmpeg", "-y"]
        cmd.extend(inputs)
        cmd.extend(maps)
        cmd.extend(meta_args)
        cmd.extend(["-c:a", "copy"])
        if has_cover:
            cmd.extend(["-c:v", "copy"])

        if fp.suffix.lower() == ".mp3":
            cmd.extend(["-id3v2_version", "3"])

        cmd.append(tmp.name)

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and os.path.exists(tmp.name) and os.path.getsize(tmp.name) > 0:
            shutil.move(tmp.name, str(fp))
            return True
        else:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
            log(f"  ✗ {fp.name}: {res.stderr[-200:]}")
            return False
    except Exception as e:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        log(f"  ✗ {fp.name}: {e}")
        return False

def tag_directory(target_dir, artist=None, album=None, genre=None,
                  year=None, tracks_meta=None, release_name=None, embed_art=True):
    """Tag all FLAC and MP3 files in a directory with full metadata and cover art."""
    target_dir = Path(target_dir)
    if not target_dir.exists():
        log(f"Directory not found: {target_dir}")
        return False

    prof = PROFILES[DEFAULT_PROFILE]
    artist = artist or prof["artist"]
    publisher = prof.get("publisher", artist)
    copyright_holder = prof.get("copyright_holder", artist)
    genre_default = genre or prof.get("genre_default", "Dark Nightride Trap / Phonk")
    year = str(year or datetime.now().year)
    copyright_text = f"© {year} {copyright_holder}"

    if not album:
        name_source = release_name or target_dir.name
        album = clean_track_title(name_source).upper()

    flacs = sorted(target_dir.glob("*_MASTER.flac")) or sorted(target_dir.glob("*.flac"))
    total_tracks = len(flacs)

    meta_lookup = {}
    if tracks_meta:
        for t in tracks_meta:
            title_key = clean_track_title(t.get("title", "")).upper()
            if title_key:
                meta_lookup[title_key] = t

    log(f"Tagging {total_tracks} tracks: {artist} — {album}")
    tagged = 0

    for i, flac in enumerate(flacs, 1):
        clean_title = clean_track_title(flac.stem).upper()
        
        track_info = {}
        for k, v in meta_lookup.items():
            if k == clean_title or k in clean_title or clean_title in k:
                track_info = v
                break
        if not track_info and tracks_meta and (i - 1 < len(tracks_meta)):
            track_info = tracks_meta[i - 1]

        final_title = clean_track_title(track_info.get("title", clean_title)).upper()
        track_genre = track_info.get("genre") or genre_default
        track_bpm = str(track_info.get("bpm", "")).strip() if track_info.get("bpm") else ""
        track_key_sig = str(track_info.get("key", "")).strip()
        track_desc = track_info.get("description") or track_info.get("direction") or f"{artist} — {album} — {track_genre}"

        metadata = {
            "title": final_title,
            "TITLE": final_title,
            "artist": artist,
            "ARTIST": artist,
            "album_artist": artist,
            "ALBUMARTIST": artist,
            "album": album,
            "ALBUM": album,
            "track": f"{i}/{total_tracks}",
            "tracknumber": str(i),
            "totaltracks": str(total_tracks),
            "genre": track_genre,
            "GENRE": track_genre,
            "date": year,
            "year": year,
            "DATE": year,
            "copyright": copyright_text,
            "COPYRIGHT": copyright_text,
            "publisher": publisher,
            "organization": publisher,
            "description": track_desc,
            "DESCRIPTION": track_desc,
            "comment": track_desc,
            "COMMENT": track_desc,
        }
        if track_bpm:
            metadata["BPM"] = track_bpm
            metadata["TBPM"] = track_bpm
        if track_key_sig:
            metadata["TKEY"] = track_key_sig
            metadata["initialkey"] = track_key_sig

        cover = None
        if embed_art:
            cover = find_cover_for_track(target_dir, release_name or album, final_title, track_num=i)

        if tag_file_ffmpeg(flac, metadata, cover_path=cover):
            tagged += 1
            art_info = f" [Cover Attached: {cover.name}]" if cover else " [No Cover]"
            log(f"  ✓ {i}/{total_tracks} {final_title}{art_info}")

        # Tag matching MP3 if present
        mp3 = flac.with_suffix(".mp3")
        if not mp3.exists():
            mp3 = target_dir / (flac.stem + ".mp3")
        if mp3.exists():
            tag_file_ffmpeg(mp3, metadata, cover_path=cover)

    log(f"Tagged {tagged}/{total_tracks} tracks successfully.")
    return tagged > 0

def main():
    parser = argparse.ArgumentParser(description="Tag FLAC/MP3 files with complete metadata and embedded cover art")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--release", help="Release name (from releases/)")
    group.add_argument("--session", help="Export session name (from exports/)")
    group.add_argument("--dir", help="Arbitrary directory containing FLAC/MP3 files")
    parser.add_argument("--artist", help="Override artist name (default: VØIDRIDE)")
    parser.add_argument("--album", help="Override album name")
    parser.add_argument("--genre", help="Override genre")
    parser.add_argument("--year", help="Release year")
    parser.add_argument("--tracks-json", help="JSON file with per-track metadata")
    parser.add_argument("--no-art", action="store_true", help="Skip cover art embedding")
    args = parser.parse_args()

    tracks_meta = None
    if args.tracks_json and os.path.exists(args.tracks_json):
        try:
            with open(args.tracks_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                tracks_meta = data if isinstance(data, list) else data.get("tracklist", data.get("tracks", []))
        except Exception:
            pass

    if args.release:
        target = RELEASES_DIR / args.release
        release_name = args.release
        meta_p = target / "tracks_meta.json"
        if not tracks_meta and meta_p.exists():
            try:
                tracks_meta = json.load(open(meta_p, encoding="utf-8"))
            except Exception:
                pass
        rel_p = target / "release.json"
        if not args.album and rel_p.exists():
            try:
                args.album = json.load(open(rel_p, encoding="utf-8")).get("album")
            except Exception:
                pass
    elif args.session:
        target = EXPORTS_DIR / args.session
        release_name = args.session
        meta_p = target / "tracks_meta.json"
        if not tracks_meta and meta_p.exists():
            try:
                tracks_meta = json.load(open(meta_p, encoding="utf-8"))
            except Exception:
                pass
    else:
        target = Path(args.dir)
        release_name = target.name
        meta_p = target / "tracks_meta.json"
        if not tracks_meta and meta_p.exists():
            try:
                tracks_meta = json.load(open(meta_p, encoding="utf-8"))
            except Exception:
                pass

    tag_directory(
        target,
        artist=args.artist,
        album=args.album,
        genre=args.genre,
        year=args.year,
        tracks_meta=tracks_meta,
        release_name=release_name,
        embed_art=not args.no_art,
    )

if __name__ == "__main__":
    main()
