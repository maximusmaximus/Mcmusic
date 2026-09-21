# Batch Playlist Generation for Legacy Sessions

When a user asks for playlists across all (or many) existing FLAC exports, the target is usually sessions that were produced before the delivery-receipt pipeline script was in place. Here's the pattern:

## Scan and Identify

```python
import os

exports_dir = "/opt/data/music/exports"
missing = []

for entry in os.listdir(exports_dir):
    dir_path = os.path.join(exports_dir, entry)
    if not os.path.isdir(dir_path):
        continue
    flacs = [f for f in os.listdir(dir_path) if f.endswith('.flac')]
    if not flacs:
        continue
    playlists = [f for f in os.listdir(dir_path) if f.endswith('.m3u8')]
    if not playlists:
        print(f"MISSING: {entry} ({len(flacs)} FLACs)")
        missing.append(entry)

print(f"\n{len(missing)} sessions without playlists")
```

## Generate Playlist for a Single-Track Directory

Single-track playlists follow this format:

```
#EXTM3U
#PLAYLIST:SESSION NAME (DAWAGENT Mastered)
#EXTINF:260,1. session-name
D:\music\exports\dir-name\session-name_MASTER.flac
```

The Windows path uses `D:\music\exports\` prefix (maps to `/mnt/d/music/exports/` on WSL).

## Multi-Track Directories

For albums with multiple FLACs in one directory, use numbered entries (01_, 02_, etc.) and descriptive titles derived from the filenames:

```
#EXTM3U
#PLAYLIST:ALBUM NAME (DAWAGENT Mastered)
#EXTINF:260,1. TRACK TITLE
D:\music\exports\album-dir\01_TRACK_TITLE_MASTER.flac
#EXTINF:260,2. TRACK TITLE 2
D:\music\exports\album-dir\02_TRACK_TITLE_2_MASTER.flac
```

## Naming Convention

Playlist file: `{dirname}_playlist.m3u8`
- Kept inside the same directory as the FLACs
- Lowercase dirname, underscores for spaces in dir names
- The `_playlist.m3u8` suffix distinguishes it from other files

## Working with Promoted Albums

When an album has been **promoted** (via `promote_release.py`), the individual per-track FLACs live in `/opt/data/music/releases/<album>/`, not in exports. The exports directory may only contain a combined album FLAC (`album_MASTER.flac`).

If the user asks for "a playlist of all the tracks for the last album," check the `releases/` directory first — that's where the numbered individual track FLACs are stored with their Windows paths pointing to `D:\music\releases\`:

```
#EXTM3U
#PLAYLIST:ALBUM NAME (DAWAGENT Mastered)
#EXTINF:260,1. TRACK TITLE
D:\music\releases\album-slug\TRACK_TITLE_MASTER.flac
```

## When to Use This vs. deliver_receipt.py

| Situation | Tool |
|-----------|------|
| Single new production | `deliver_receipt.py --session NAME` |
| Batch backfill for legacy sessions | Manual generation (this pattern) |
| User asks "send me playlists for everything" | Scan + generate for all missing |
| Playlist for a promoted album | Generate pointing to `D:\music\releases\<album>\` paths |

## Filtering Out Test/Timestamp Versions

Export directories with timestamps (e.g., `abyss-throttle-master-20260907-182125`) are often intermediate test versions that were superseded by the final album in `releases/`. When batch-generating, skip or flag these — the user likely wants the canonical release, not every draft.
