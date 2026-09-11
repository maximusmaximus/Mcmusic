# Manual Publish Fallback Workflow

When `publish_release.py` fails silently with `✗ Upload failed: ` (empty error after the colon), **and** your artwork is already under 10MB, the issue may be something else in the script's internals. Rather than debugging the script, **fall back to manual upload** — it's faster and more reliable.

## Symptoms

```
[publish HH:MM:SS] Publishing ALBUM (5 tracks)...
[publish HH:MM:SS] Tagging metadata + cover art...
[publish HH:MM:SS]   Tagged 5 files
[publish HH:MM:SS]   Uploading: TRACK1
[publish HH:MM:SS]   ✗ Upload failed: 
[publish HH:MM:SS]   Uploading: TRACK2
[publish HH:MM:SS]   ✗ Upload failed: 
```

Empty error after "Upload failed:" = the script returned None early (non-zero return code from `soundcloud_api.py` or JSON parse failure).

## Step 1: Verify artwork size

Covers from Venice upscale are 4096×4096 at ~17-18MB → resize to 2000×2000 before uploading:

```bash
for f in /opt/data/music/releases/<album>/covers/*.png; do
  base=$(basename "$f")
  ffmpeg -y -i "$f" -vf "scale=2000:2000:flags=lanczos" -compression_level 6 "${f%.png}_2k.png"
  mv "${f%.png}_2k.png" "$f"
done
# Sync back to artwork/covers/ (publish_release.py searches there)
cp /opt/data/music/releases/<album>/covers/*.png /opt/data/music/artwork/covers/
```

## Step 2: Upload each track individually

If `publish_release.py` still fails after resizing, upload manually:

```bash
TRACK_IDS=()

# Upload track 1
RESULT=$(python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py upload \
  --file "/opt/data/music/releases/<album>/TRACK1_MASTER.flac" \
  --title "TRACK1" \
  --genre "Electronic" \
  --tags "tag1,tag2,tag3" \
  --sharing public --downloadable \
  --label "VØIDRIDE" \
  --artwork "/opt/data/music/artwork/covers/TRACK1.png")
TRACK_ID=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['track_id'])")
TRACK_IDS+=("$TRACK_ID")

# Repeat for each track in the album
```

## Step 3: Create the playlist

```bash
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py create-playlist \
  --title "ALBUM NAME (Unicode)" \
  --track-ids "$(IFS=,; echo "${TRACK_IDS[*]}")" \
  --sharing public \
  --artwork "/opt/data/music/artwork/covers/album_cover.png"
```

The response includes `playlist_id` and `permalink_url`.

## Step 4: Apply tags via raw API

The CLI `update` command often returns 200 OK but `tag_list` stays empty when tracks are in "unknown" state. The raw API PUT always works:

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

for tid in TRACK_IDS:
    payload = json.dumps({
        'track': {
            'tag_list': 'electronic dark instrumental 120bpm space',
            'label_name': 'VØIDRIDE'
        }
    }).encode()
    req = urllib.request.Request(
        f'https://api.soundcloud.com/tracks/{tid}',
        data=payload, method='PUT',
        headers={
            'Authorization': f'OAuth {tokens["access_token"]}',
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json; charset=utf-8',
        }
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    print(f'Track {tid}: tag_list="{result.get("tag_list","?")}"')
```

## Step 5: Update release.json

```json
{
  "status": "published",
  "soundcloud": {
    "track_ids": [ID1, ID2, ID3, ID4, ID5],
    "playlist_id": PLAYLIST_ID,
    "permalink": "https://soundcloud.com/ridethevoid/sets/permalink",
    "published_at": "2026-09-11T18:32:00"
  }
}
```

## Root Causes of publish_release.py Failure Beyond Artwork Size

| Cause | Symptom | Fix |
|-------|---------|-----|
| Cover > 10MB | Empty error after "Upload failed:" | Resize to 2000×2000, re-sync to artwork/covers/ |
| Token expired (script uses cached token) | Non-zero return code from sc_upload | First run `soundcloud_api.py list` to refresh token |
| Tags pass corrupts file before upload | Tagging succeeds but all uploads fail | Skip tag_metadata.py step: comment it out in publish() or upload files that were already pre-tagged |
| JSON response parse failure | sc_upload returns None despite upload working | Upload individually as fallback |
