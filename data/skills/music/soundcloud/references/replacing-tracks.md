# Replacing Tracks in a Published Album

When a user wants to remove and replace a track on a published SoundCloud album:

## Step 1: Identify the Track

1. Find the playlist via SC API (`/users/{id}/playlists`)
2. Match track position to ID using `release.json` `soundcloud.track_ids` array (0-indexed)
3. The playlist directory is at `/opt/data/music/releases/<album>/`
4. `release.json` has `soundcloud.playlist_id` and `soundcloud.track_ids`
5. `tracks_meta.json` has title/BPM/key/genre in order (same index as track_ids)

## Step 2: Delete Old Track + Update Playlist

```python
# Delete track
req = urllib.request.Request(f'https://api.soundcloud.com/tracks/{TRACK_ID}', method='DELETE')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Accept', 'application/json; charset=utf-8')
urllib.request.urlopen(req)  # 200 = success

# Update playlist (PUT replaces entire track list — include ALL desired track IDs)
payload = json.dumps({
    "playlist": {
        "tracks": [{"id": str(t)} for t in remaining_ids]
    }
}).encode('utf-8')
req = urllib.request.Request(f'https://api.soundcloud.com/playlists/{PLAYLIST_ID}',
    data=payload, method='PUT')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Content-Type', 'application/json; charset=utf-8')
req.add_header('Accept', 'application/json; charset=utf-8')
urllib.request.urlopen(req)
```

## Step 3: Update release.json

```python
release['soundcloud']['track_ids'] = remaining_ids
with open(release_path, 'w') as f:
    json.dump(release, f, indent=2)
```

## Step 4: Produce Replacement Track

- **Use the SAME main model** as the original track — check `production_plan.json` in the original production directory for `stems.main.model`
- Same duration, same BPM +/- 5, same key, same energy arc
- Use `master-producer.py` for a single track (NOT `produce-album.py`)
- Include `--research --compose --director --skip-master` flags
- Enrich the prompt based on the original track's production plan

## Step 5: DAWAGENT Handoff

1. Run Demucs stem separation on the mix
2. Create DAW session (`dawctl_local.py session create`)
3. Add 4 tracks (Drums, Bass, Vocals, Other)
4. Hand off via `handoff.py write` with per-stem processing plan
5. Tell user to message @DAWAGENT_bot: `process <session>`

## Step 6: Cover Art

1. Copy/rename the original album cover (if per-track artwork exists) or generate new background
2. Upscale to 3000×3000 if needed
3. Overlay Unicode-styled title using `cover-title-overlay` skill's overlay-title.py
   - Track covers: `--bottom` position
   - Use a neon color matching the album's volcanic/cinematic palette

## Step 7: Upload Replacement to SoundCloud

1. After user approves (DAWAGENT-processed master + cover), upload via `soundcloud_api.py upload`
2. Update the playlist to add the new track ID: `soundcloud_api.py update-playlist --playlist-id ID --track-ids "id1,id2,id3"`
3. Update `release.json` with the new track ID
