# Release Directory Structure

When tracks have been produced, DAWAGENT-processed, and promoted to release-ready state,
they live in `/opt/data/music/releases/<album-slug>/` with structured metadata.

## Directory Layout

```
/opt/data/music/releases/mars-descent/
├── IGNITION_VEIL_MASTER.flac      # Lossless master (for archival / quality upload)
├── IGNITION_VEIL_MASTER.mp3       # 320kbps MP3 (for fast SoundCloud upload)
├── APOGEE_DRIFT_MASTER.flac
├── APOGEE_DRIFT_MASTER.mp3
├── PLASMA_SHEAR_MASTER.flac
├── PLASMA_SHEAR_MASTER.mp3
├── GRAVITY_LOCK_MASTER.flac
├ence GRAVITY_LOCK_MASTER.mp3
├── RED_REQUIEM_MASTER.flac
├── RED_REQUIEM_MASTER.mp3
├── release.json                   # Album-level metadata
├── tracks_meta.json               # Per-track BPM, key, genre
└── mars-descent_playlist.m3u8     # Playback order
```

## release.json Format

Two formats exist depending on whether the album was published via the pipeline or prepared manually.

### Pre-Publish Format (manual / promote workflow)

```json
{
  "album": "MARS DESCENT",
  "promoted_from": "mars-descent-v3",
  "promoted_at": "2026-08-27T23:00:49.753998",
  "track_count": 5,
  "tracks": [
    "IGNITION VEIL",
    "APOGEE DRIFT",
    "PLASMA SHEAR",
    "GRAVITY LOCK",
    "RED REQUIEM"
  ],
  "status": "release-ready",
  "windows_path": "D:\\\\music\\\\releases\\\\mars-descent",
  "source": "dawagent-mix-mastered"
}
```

### Published Format (album_pipeline.py — after SoundCloud upload)

```json
{
  "title": "ASHFALL CORRIDOR",
  "genre": "cinematic nightride phonk / volcanic trap noir",
  "label": "VØIDRIDE",
  "release_date": "2026-09-05",
  "description": "...",
  "soundcloud": {
    "track_ids": [2394856722, 2394856749, 2394856815, 2394856839],
    "playlist_id": 2294366724,
    "permalink": "",
    "published_at": "2026-09-05T05:05:07.007924"
  },
  "status": "published"
}
```

Key fields (pre-publish):
- `status`: `"release-ready"` means files are mastered, tagged, and ready for upload
- `source`: `"dawagent-mix-mastered"` means DAWAGENT processing was applied (preferred over raw Venice output)
- `promoted_from`: the working version that was promoted to release
- `tracks`: ordered list matching playlist order

Key fields (published):
- `soundcloud.track_ids`: ordered array of SC track IDs matching track order
- `soundcloud.playlist_id`: the SC playlist ID
- `status`: `"published"` means it's live on SoundCloud
- `description`: album description used as SC playlist description

## tracks_meta.json Format

```json
[
  {"title": "IGNITION VEIL", "bpm": 155, "key": "Cm", "genre": "Dark Nightride Trap / Aggressive Witch House"},
  {"title": "APOGEE DRIFT", "bpm": 125, "key": "Fm", "genre": "Dark Nightride Trap / Weightless Melodic Witch House"},
  ...
]
```

Use this to populate SoundCloud tags and descriptions during upload.

## Cover Art Location

```
/opt/data/music/artwork/covers/
├── mars_descent_1_IGNITION_VEIL.png      # Per-track cover (3000×3000)
├── mars_descent_1_IGNITION_VEIL.jpg
├── mars_descent_1_bg.png                 # Background only (no title overlay)
├── mars_descent_1_raw.webp               # Original Venice API output
├── mars_descent_2_APOGEE_DRIFT.png
├── mars_descent_album_playlist.png        # Album/playlist cover (3000×3000)
├── mars_descent_album_playlist.jpg
├── mars_descent_album_bg.png
└── mars_descent_album_raw.webp
```

Naming pattern: `{album_slug}_{track_number}_{TRACK_NAME}.png` for tracks,
`{album_slug}_album_playlist.png` for the playlist cover.

Scale covers to 800×800 minimum before SoundCloud upload:
```bash
ffmpeg -y -i cover.png -vf "scale=800:800:force_original_aspect_ratio=decrease,pad=800:800:(ow-iw)/2:(oh-ih)/2" cover_800.png
```

## Release Directory Cover Art

Covers can live inside the release directory alongside the tracks (preferred for new albums) or in the shared artwork directory. Both patterns work:

**Pattern A — Inside release directory** (preferred for new albums):
```
/opt/data/music/releases/cherenkov-horizon/
├── 01_BLUE_RADIATION.flac
├── 01_BLUE_RADIATION_cover.png      # 3000×3000 PNG
├── 01_BLUE_RADIATION_cover.jpg      # 1500×1500 JPG (Telegram delivery)
├── 02_GRAPHITE_CORE.flac
├── 02_GRAPHITE_CORE_cover.png
├── 02_GRAPHITE_CORE_cover.jpg
├── ...
├── album_cover.png                   # Album/playlist cover
├── album_cover.jpg
├── release.json
├── tracks_meta.json
└── cherenkov-horizon_playlist.m3u8
```

**Pattern B — Shared artwork directory** (legacy):
```
/opt/data/music/artwork/covers/cherenkov-horizon/
├── 01_BLUE_RADIATION_cover.png
├── 01_BLUE_RADIATION_cover.jpg
├── ...
└── album_cover.png
```

When setting up a new release, copy covers into the release directory so `publish_release.py` can auto-discover them.

**⚠️ Sync both directions when re-generating covers post-promotion:**
If covers are re-generated after promotion (e.g. title overlay applied, different scene, fixes), the new titled versions live in the release directory's `covers/` subdirectory. But `publish_release.py`'s `find_artwork()` searches `/opt/data/music/artwork/covers/` — so you MUST sync back:
```bash
cp /opt/data/music/releases/<album>/covers/*_cover.png /opt/data/music/artwork/covers/
cp /opt/data/music/releases/<album>/covers/album_cover.png /opt/data/music/artwork/covers/
```

## Upload Workflow with Release Directory

1. Read `release.json` to get track order and album name
2. Read `tracks_meta.json` to get per-track BPM, key, genre for tags
3. Upload from `_MASTER.mp3` files (5x faster than FLAC, SoundCloud re-encodes anyway)
4. Use per-track covers from `/opt/data/music/artwork/covers/`
5. After upload: tag update pass, description enrichment, playlist creation, playlist artwork