# Remove a Track from a Published SoundCloud Album

When you need to delete a track from a published album/playlist, three operations are required:

## Step 1: Identify the Track

Find the album's release directory under `/opt/data/music/releases/<album>/`.

- `release.json` contains `soundcloud.track_ids` (ordered array) and `soundcloud.playlist_id`
- `tracks_meta.json` contains the track metadata in order (index 0 = track 1, index N = track N+1)
- Each `track_id` maps to the SoundCloud track in the playlist

## Step 2: Delete the Track from SoundCloud

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

TRACK_ID = <SC_TRACK_ID>  # e.g. 2394856782

req = urllib.request.Request(f'https://api.soundcloud.com/tracks/{TRACK_ID}', method='DELETE')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Accept', 'application/json; charset=utf-8')
resp = urllib.request.urlopen(req)
# Status 200 = success, irreversible
```

## Step 3: Update the Playlist (Remove the Track)

The playlist PUT **replaces** the entire track list — you must include ALL remaining tracks, not just omit the removed one.

```python
remaining_ids = [2394856722, 2394856749, 2394856815, 2394856839]  # All EXCEPT the deleted track

payload = json.dumps({
    "playlist": {
        "tracks": [{"id": str(t)} for t in remaining_ids]  # MUST be STRING IDs, not ints!
    }
}).encode('utf-8')

req = urllib.request.Request(
    f'https://api.soundcloud.com/playlists/{PLAYLIST_ID}',
    data=payload, method='PUT'
)
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Content-Type', 'application/json; charset=utf-8')
req.add_header('Accept', 'application/json; charset=utf-8')
resp = urllib.request.urlopen(req)
```

## Step 4: Update release.json

```python
import json

release_path = '/opt/data/music/releases/<album>/release.json'
with open(release_path) as f:
    release = json.load(f)

release['soundcloud']['track_ids'] = remaining_ids  # same array as Step 3

with open(release_path, 'w') as f:
    json.dump(release, f, indent=2)
```

## Key Pitfalls

- **Track IDs must be strings in JSON** — integer IDs silently create empty playlists
- **Both `Content-Type` and `Accept` headers required** with `application/json; charset=utf-8`
- **Track deletion is irreversible** — plays/comments are lost; no undelete API
- **No audio replacement API** exists — to fix audio: upload new track → copy metadata → delete old track
- **Tags on the deleted track are also lost** — if you re-upload, re-apply tags separately
- **Update playlist artwork** if the track was the first/featured track and you want new artwork
