# Remove a Track from an Existing Published Album

When a track in a published SoundCloud album needs to be removed (bad audio, content ID flag, user request), the process requires updating BOTH the SoundCloud playlist AND the local release metadata.

## Workflow

### Step 1: Find the Track and Playlist

Use the raw SoundCloud API to list the user's playlists and find the target album:

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

# Get user info
req = urllib.request.Request('https://api.soundcloud.com/me')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Accept', 'application/json; charset=utf-8')
resp = urllib.request.urlopen(req)
user = json.loads(resp.read().decode())

# List all playlists
req = urllib.request.Request(f'https://api.soundcloud.com/users/{user["id"]}/playlists')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Accept', 'application/json; charset=utf-8')
resp = urllib.request.urlopen(req)
playlists = json.loads(resp.read().decode())
for pl in playlists:
    print(f'Playlist: {pl["title"]} (ID: {pl["id"]}) - {pl.get("track_count", "?")} tracks')
```

Or use the CLI list command to find track IDs first:

```bash
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py list --limit 100 --json
```

### Step 2: Delete the Track from SoundCloud

SC has no `delete` CLI command — use the raw DELETE API:

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

TRACK_ID = 123456789  # Replace with actual track ID
req = urllib.request.Request(f'https://api.soundcloud.com/tracks/{TRACK_ID}', method='DELETE')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Accept', 'application/json; charset=utf-8')
resp = urllib.request.urlopen(req)
# Status 200 = success, irreversible
```

### Step 3: Update the Playlist (Remove the Track)

Use `update-playlist` CLI command with the remaining track IDs (PUT replaces the entire track list):

```bash
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py \
  update-playlist \
  --playlist-id PLAYLIST_ID \
  --track-ids "id1,id2,id3,id4"
```

Important: Include ALL remaining track IDs, not just the ones being removed. PUT replaces the full list.

### Step 4: Update Local Metadata

After removing from SoundCloud, update the local `release.json` in the album's release directory:

```bash
/opt/data/music/releases/<album-slug>/release.json
```

Remove the deleted track's ID from `soundcloud.track_ids` array.

### Step 5 (Optional): Replace the Track

If replacing the removed track with a new one:

1. **Produce the replacement**: Use `master-producer.py` for a single track (NOT `produce-album.py`)
   - Use the **same model** as the original track (check the production plan for the removed track)
   - Match the album's genre, BPM range, and sonic DNA
   - Use `--research --compose --director --skip-master` flags

2. **Get user approval**: Send the raw mix for listening first

3. **Process through DAWAGENT**: Run Demucs stems → create session → handoff

4. **Upload to SoundCloud**:
   ```bash
   python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py \
     upload --file /path/to/master.flac \
     --artwork /path/to/cover.png \
     --title "TRACK TITLE" \
     --genre "Electronic" \
     --label "VØIDRIDE" \
     --sharing public --downloadable
   ```

5. **Add to playlist**: Use `update-playlist` with ALL track IDs (old remaining + new)

6. **Update `release.json`**: Add the new track's ID to `soundcloud.track_ids` and update `tracks_meta.json` with the new track's metadata

## Pitfalls

- **Track IDs must be strings** in playlist JSON payloads, not integers
- **Release.json must be kept in sync** — the local metadata is the source of truth for re-publishing
- **Cover art** for the replacement track may need to be generated if the original track's cover was unique to it
- **Encoding delay**: After uploading the replacement, wait for `state: finished` before updating the playlist to include it
