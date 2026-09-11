# Publishing a Full Album — Proven Pattern

This documents the working pattern for end-to-end album publishing that was used
for CHERENKOV-HORIZON and subsequent releases.

## When to Use This vs publish_release.py

- **publish_release.py** — preferred when a release directory with `release.json` and `tracks_meta.json` already exists and is correctly structured. Handles upload, playlist, tags, and artwork in one command.
- **Custom Python script** — use when you need per-track artwork paths, custom descriptions, or fine-grained control over tag/label passes. Write the script to a file in `/tmp/` and run via `terminal(background=True)`.

## Proven Upload Script Pattern

```python
#!/usr/bin/env python3
"""Album upload script — run via terminal, not execute_code."""
import subprocess, json, time

SC = "/opt/data/skills/music/soundcloud/scripts/soundcloud_api.py"
RELEASE = "/opt/data/music/releases/ALBUM_SLUG"

TRACKS = [
    {
        "file": f"{RELEASE}/01_TRACK.flac",
        "artwork": f"{RELEASE}/01_TRACK_cover.png",
        "title": "TRACK TITLE",          # ALL CAPS per user rule
        "description": "Genre. BPM, key.",
        "tags": "witch house,dark trap,bpm,key,album_slug",
        "genre": "Electronic",
    },
    # ... more tracks
]

track_ids = []

# Step 1: Upload all tracks
for i, track in enumerate(TRACKS):
    cmd = [
        "python3", SC, "upload",
        "--file", track["file"],
        "--artwork", track["artwork"],
        "--title", track["title"],
        "--description", track["description"],
        "--tags", track["tags"],
        "--genre", track["genre"],
        "--label", "VØIDRIDE",
        "--sharing", "public",
        "--downloadable",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    # Parse track_id from JSON response
    # ...
    time.sleep(3)  # Rate limit

# Step 2: Tag update pass (tags often fail on initial upload)
for i, (tid, track) in enumerate(zip(track_ids, TRACKS)):
    cmd = ["python3", SC, "update", "--track-id", str(tid), "--tags", track["tags"]]
    subprocess.run(cmd, ...)
    time.sleep(2)

# Step 3: Label pass
for tid in track_ids:
    cmd = ["python3", SC, "update", "--track-id", str(tid), "--label", "VØIDRIDE"]
    subprocess.run(cmd, ...)
    time.sleep(2)

# Step 4: Create playlist with album artwork
ids_str = ",".join(str(tid) for tid in track_ids)
cmd = [
    "python3", SC, "create-playlist",
    "--title", "₩ₜł₮lø-Tł†ⱠɆ",  # Unicode title
    "--track-ids", ids_str,
    "--artwork", f"{RELEASE}/album_cover.png",
    "--description", "Album description.",
    "--tags", "witch house,album,bpm",
    "--sharing", "public",
]
subprocess.run(cmd, ...)
```

## Key Points

1. **FLAC upload** — user rule: FLAC ONLY, never MP3
2. **Track titles: ALL CAPS** — "BLUE RADIATION" not "Blue Radiation"
3. **Per-track artwork** — use the `_cover.png` (3000x3000) files
4. **3-second delays** between uploads to avoid rate limiting
5. **Tag + label passes AFTER upload** — tags often don't stick on initial upload during encoding
6. **Playlist title can use Unicode** — but don't mix Unicode + plain ASCII
7. **Track IDs must be STRINGS** in playlist JSON (soundcloud_api.py handles this)
8. **`--label "VØIDRIDE"`** — no `--artist` flag exists
9. **Content ID false positives** — AI-generated tracks can get flagged. If a track disappears (404), must regenerate with different prompt

## Release Directory Setup

Before publishing, set up the release directory:

```bash
/opt/data/music/releases/<album-slug>/
├── release.json          # Album metadata
├── tracks_meta.json      # Per-track BPM, key, genre
├── 01_TRACK.flac         # FLAC masters
├── 01_TRACK_cover.png    # Per-track artwork (3000x3000)
├── 01_TRACK_cover.jpg    # Per-track artwork (1500x1500 for Telegram)
├── album_cover.png       # Album/playlist artwork
├── album_cover.jpg       # Album artwork (Telegram)
└── album_playlist.m3u8   # VLC playback playlist
```