# Replacing a Track in a Published Album

Workflow for removing a bad track from a published SoundCloud album and replacing it with a new production.

## Discovery Flow

1. The user says "remove track N from [album]" — identify whether N is:
   - A **track name** ("remove Emberhollow") → it's a track title
   - A **track number** ("remove track 3") → check `tracks_meta.json` for track ordering
2. Find the album's release directory at `/opt/data/music/releases/<album-slug>/`
3. Read `release.json` to get:
   - The `soundcloud.track_ids` array (ordered list matching track order)
   - The `soundcloud.playlist_id`
   - The album title (may have Unicode styling)
4. Read `tracks_meta.json` for per-track BPM/key/genre — track order = index in the array
5. Index into `track_ids` array to find the SoundCloud ID of the target track (0-indexed)

## Step 1: Delete Track from SoundCloud

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

TRACK_ID = 2394856782  # Replace with actual track ID

req = urllib.request.Request(f'https://api.soundcloud.com/tracks/{TRACK_ID}', method='DELETE')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Accept', 'application/json; charset=utf-8')
resp = urllib.request.urlopen(req)
# Status 200 = success, irreversible
```

**⚠️ Track deletion is irreversible** — all plays, comments, and stats are lost.

## Step 2: Update Playlist (Remove Track)

Use `update-playlist` with `--track-ids` to set the **full list of remaining tracks** (PUT replaces the entire track list):

```bash
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py \
  update-playlist \
  --playlist-id 2294366724 \
  --track-ids "2394856722,2394856749,2394856815,2394856839"
```

**Important:** Pass ALL remaining track IDs, not just the ones being removed. PUT replaces the list entirely.

## Step 3: Update release.json

After deleting and updating the playlist, sync the local `release.json`:

```python
import json
release_path = '/opt/data/music/releases/ashfall-corridor/release.json'
with open(release_path) as f:
    release = json.load(f)

# Remove the deleted track ID from the array
release['soundcloud']['track_ids'].remove(TRACK_ID)

with open(release_path, 'w') as f:
    json.dump(release, f, indent=2)
```

## Step 4: Produce Replacement Track

Use `master-producer.py` for a single replacement track (NOT `produce-album.py`):

```bash
python3 /opt/data/skills/master-producer/master-producer/scripts/master-producer.py \
  --research --compose --director --skip-master \
  --prompt "ENRICHED_PROMPT matching album style" \
  --quality standard \
  --duration 260 \
  --chat-id CHAT_ID
```

**Critical:** Match the original track's:
- **Model** (check `production_plan.json` from the album session — was it `elevenlabs-music`?)
- **BPM range** (the replacement should fit the album's flow)
- **Key** (check tracks_meta.json for the album's key palette)
- **Sonic DNA** (VØIDRIDE style: 808 dominant, no house, smooth buildups, etc.)

## Step 5: Send for Review

Convert the raw mix to MP3 for preview:

```bash
ffmpeg -y -i "mix_20260905_063158.wav" -c:a libmp3lame -b:a 320k /tmp/TRACKNAME_preview.mp3
```

Send `MEDIA:/tmp/TRACKNAME_preview.mp3` to the user for approval.

## Step 6: Post-Approval Publishing

Once approved, the full publishing flow:
1. Demucs stem separation
2. DAWAGENT processing (mastering chain)
3. Copy mastered FLAC to release directory
4. Update `tracks_meta.json` with new track info
5. Upload via `publish_release.py` with `--confirm` (skip review since user already approved)
6. Regenerate waveform art for the album

## Pipeline-Active Warning

If `[pipeline]` notifications are arriving, `album_pipeline.py` is running and handles everything autonomously. **Do NOT interfere** — only answer user questions. The pipeline handles production, review gates, artwork, and publishing.

## Release.json Format (Pipeline Style)

Published albums use this format (from `album_pipeline.py`):

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

Compare with the pre-publish format (which has `album`, `tracks` array, no `soundcloud` section).
