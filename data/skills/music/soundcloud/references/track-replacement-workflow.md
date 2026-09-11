# Single-Track Replacement in a Published SoundCloud Playlist

When a user says "remove track N" or "replace track N" from an existing SC playlist that's already part of a local release, follow this workflow.

## Prerequisites

- You know the release directory (e.g. `/opt/data/music/releases/ashfall-corridor/`)
- You know the playlist ID and track IDs from `release.json`
- Token may need refreshing: run `soundcloud_api.py list --limit 1` first

## Step 1: Remove Old Track

```python
# Delete the track from SoundCloud
req = urllib.request.Request(f'https://api.soundcloud.com/tracks/{TRACK_ID}', method='DELETE')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
urllib.request.urlopen(req)
```

## Step 2: Update Playlist (Remove)

Use PUT to replace the entire track list with the remaining tracks:

```python
payload = json.dumps({
    "playlist": {
        "tracks": [{"id": str(id)} for id in remaining_ids]
    }
}).encode('utf-8')

req = urllib.request.Request(
    f'https://api.soundcloud.com/playlists/{PLAYLIST_ID}',
    data=payload, method='PUT'
)
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Content-Type', 'application/json; charset=utf-8')
req.add_header('Accept', 'application/json; charset=utf-8')
```

## Step 3: Produce Replacement Track

- Use `master-producer.py` (NOT `produce-album.py` — that's for full albums)
- Match the original track's model, BPM, key, and duration from `production_plan.json`
- Same 3-stem setup (elevenlabs-music main + stable-audio-25 texture + SFX accent)
- `--skip-master` → hand off to DAWAGENT via `dawctl_local.py` + `handoff.py`

## Step 4: DAWAGENT Processing

```bash
# Copy mix to session dir
mkdir -p /opt/data/dawagent/sessions/<name>/demucs
cp mix.wav /opt/data/dawagent/sessions/<name>/<name>_mix.wav

# Run Demucs (use venv Python — system python3 doesn't have demucs)
/opt/hermes/.venv/bin/python3 -m demucs -n htdemucs \
  --out "/opt/data/dawagent/sessions/<name>/demucs" \
  "/opt/data/dawagent/sessions/<name>/<name>_mix.wav"

# Create session (delete old dir first if it exists from a failed create)
rm -rf /opt/data/dawagent/sessions/<name>
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  session create --name "<name>" --sr 48000 --bpm <BPM>

# Add tracks
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  track add --session "<name>" --name "Drums" --type audio
# ... repeat for Bass, Vocals, Other

# Hand off
python3 /opt/data/skills/dawagent/dawagent/scripts/handoff.py write \
  --session "<name>" --bpm <BPM> \
  --stems "drums,bass,vocals,other" \
  --stem-names "Drums,Bass,Vocals,Other" \
  --plan "per-stem processing chain" \
  --notes "context notes"
```

Wait for DAWAGENT to process (check exports). The mastered FLAC+MP3 appear in `/opt/data/dawagent/exports/<name>/`.

## Step 5: Upload New Track

Upload manually (not via `publish_release.py` — that's for full album releases):

```python
boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
body = b''
# Track file
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="track[asset_data]"; filename="<file>.flac"\r\n'
body += b'Content-Type: audio/flac\r\n\r\n'
body += track_data + b'\r\n'

# Title (PLAIN ASCII, ALL CAPS)
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="track[title]"\r\n\r\n'
body += b'PYREDRIFT\r\n'

# Sharing
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="track[sharing]"\r\n\r\n'
body += b'public\r\n'

# Genre
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="track[genre]"\r\n\r\n'
body += b'Electronic\r\n'

# Downloadable
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="track[downloadable]"\r\n\r\n'
body += b'true\r\n'

# Label (handles Unicode)
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="track[label_name]"\r\n\r\n'
body += 'VØIDRIDE\r\n'.encode('utf-8')

# Artwork (PNG binary)
body += f'--{boundary}\r\n'.encode()
body += b'Content-Disposition: form-data; name="track[artwork_data]"; filename="cover.png"\r\n'
body += b'Content-Type: image/png\r\n\r\n'
body += cover_data + b'\r\n'

body += f'--{boundary}--\r\n'.encode()
```

## Step 6: Insert into Playlist at Correct Position

Get current playlist tracks, then PUT with the new track inserted at the right index:

```python
# Get current tracks
req = urllib.request.Request(f'https://api.soundcloud.com/playlists/{PLAYLIST_ID}')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Accept', 'application/json; charset=utf-8')
resp = urllib.request.urlopen(req)
playlist = json.loads(resp.read().decode())
existing_ids = [str(t['id']) for t in playlist['tracks']]

# Build new order with inserted track
new_order = existing_ids.copy()
new_order.insert(2, str(new_track_id))  # insert at position 3 (index 2)

payload = json.dumps({
    "playlist": {"tracks": [{"id": id} for id in new_order]}
}).encode('utf-8')
```

## Step 7: Update Local Files

- `release.json` — update `soundcloud.track_ids` list with new order
- `tracks_meta.json` — insert new track metadata at correct position, remove old track
- Remove old audio file (e.g. `03-EMBERHOLLOW.flac`)

## Step 8: Apply Tags (after encoding completes)

Tags fail during encoding. Wait for `state: "finished"`, then:

```bash
python3 soundcloud_api.py update --track-id <ID> --tags "tag1 tag2 tag3"
```

If state is "unknown" instead of "finished", the track may still be processing. Check again after 1-2 minutes.

## Pitfalls

- **Token expiry**: Always run `soundcloud_api.py list --limit 1` first to refresh the token before using raw API calls
- **playlist PUT replaces the entire track list**: You must include ALL track IDs, not just the new one
- **Track IDs must be strings in JSON**: Integer IDs silently create empty playlists
- **Label with Unicode**: Use `.encode('utf-8')` for the label name since `Ø` isn't ASCII
- **State "unknown" is normal**: After upload, state may show "unknown" while encoding. The track is still public and playable; tags just can't be applied yet
- **Demucs in venv**: Use `/opt/hermes/.venv/bin/python3 -m demucs` NOT system `python3 -m demucs`
- **Session create fails if directory exists**: The `session create` command fails if the `/opt/data/dawagent/sessions/<name>/` directory already exists from a prior `mkdir`. Either don't pre-create the directory, or `rm -rf` it first
- **BPM for new track**: Match the removed track's BPM from `production_plan.json`. For album continuity, keep it in the same range as adjacent tracks
