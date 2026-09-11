# SoundCloud Playlist API Reference

Creating and managing playlists (sets) via the SoundCloud API v2.

## Key Discovery: Track Format for Playlists

**The SoundCloud API requires `id` fields as STRINGS, not integers, when creating or updating playlists with tracks.** Multipart form data does NOT work for attaching tracks. Only JSON with the correct `Accept` and `Content-Type` headers works.

### Creating a Playlist with Tracks

```
POST https://api.soundcloud.com/playlists
Content-Type: application/json; charset=utf-8
Accept: application/json; charset=utf-8
Authorization: OAuth {access_token}

{
  "playlist": {
    "title": "Album Title",
    "description": "Album description",
    "sharing": "public",
    "tracks": [
      {"id": "2377094696"},
      {"id": "2377094729"},
      {"id": "2377094777"}
    ]
  }
}
```

**Critical:** Track IDs must be **strings** (`"2377094696"`), NOT integers (`2377094696`). Integer IDs are accepted but tracks silently don't attach — the playlist is created with 0 tracks.

**Critical:** Both `Content-Type: application/json; charset=utf-8` AND `Accept: application/json; charset=utf-8` headers must be present. Without the `Accept` header, the API returns 422 "Could not parse JSON request body."

### Adding Tracks to an Existing Playlist

```
PUT https://api.soundcloud.com/playlists/{playlist_id}
Content-Type: application/json; charset=utf-8
Accept: application/json; charset=utf-8
Authorization: OAuth {access_token}

{
  "playlist": {
    "tracks": [
      {"id": "2377094696"},
      {"id": "2377094729"}
    ]
  }
}
```

This replaces the entire track list — include ALL tracks, not just new ones.

### Deleting a Playlist

```
DELETE https://api.soundcloud.com/playlists/{playlist_id}
Authorization: OAuth {access_token}
```

Response: 200 OK on success. Immediate and irreversible.

### Listing User Playlists

```
GET https://api.soundcloud.com/me/playlists?limit=50
Authorization: OAuth {access_token}
```

Returns a flat array (not a collection object like tracks).

**Pre-refresh the token first.** The `access_token` read from the token JSON file may be expired. Before any raw API call, run `soundcloud_api.py list --limit 1 --json` to trigger the script's auto-refresh, which writes a fresh `access_token` to the file. Then read the updated token for your raw call. Skipping this causes a `401 Unauthorized`.

### Playlist Object Fields

- `id` — playlist ID
- `title` — display title
- `description` — markdown description
- `sharing` — "public" or "private"
- `track_count` — number of tracks
- `tracks` — array of track objects (may be empty on creation)
- `permalink_url` — SoundCloud URL
- `artwork_url` — cover art (set separately)
- `genre` — genre field
- `tag_list` — space-separated tags
- `label_name` — label field

### Adding Cover Art to a Playlist

**IMPORTANT:** Use `playlist[artwork_data]` (NOT `track[artwork_data]`). The `soundcloud_api.py update --artwork` command uses `track[artwork_data]` which returns 500 on playlists. You must use a direct Python request:

```python
import json, urllib.request

boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

with open('/path/to/cover.png', 'rb') as f:
    img_data = f.read()

body = (
    f"--{boundary}\r\n"
    f"Content-Disposition: form-data; name=\"playlist[artwork_data]\"; filename=\"cover.png\"\r\n"
    f"Content-Type: image/png\r\n\r\n"
).encode() + img_data + f"\r\n--{boundary}--\r\n".encode()

req = urllib.request.Request(
    f"https://api.soundcloud.com/playlists/{PLAYLIST_ID}",
    data=body, method='PUT'
)
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
resp = urllib.request.urlopen(req)
result = json.loads(resp.read().decode())
print(f"Artwork: {result.get('artwork_url')}")
```

Cover image must be square, minimum 800×800, JPEG or PNG (not WebP). Convert Venice WebP output first: `ffmpeg -i cover.webp -q:v 2 cover.png`.

## What Does NOT Work

These approaches were all tested and **fail silently** (create playlist with 0 tracks):
- Multipart form data with `playlist[track_ids][]=ID`
- Multipart form data with `playlist[track_ids][0]=ID`
- URL-encoded form data with `track_ids[]=ID`
- JSON with integer IDs: `{"id": 2377094696}`
- JSON without `Accept: application/json; charset=utf-8` header
- PUT to `/playlists/{id}/tracks/{track_id}`
- POST to `/playlists/{id}/tracks` with track data
- The `/me/playlist_additions` endpoint (returns 405)

The `track_ids` field (as a space-separated string) is accepted on creation but also does NOT attach tracks.

## Workflow: Create Album Sets

```python
import json, urllib.request

# After creating playlist with tracks:
# 1. POST to /playlists with JSON body (string IDs!)
# 2. Verify track_count matches expected
# 3. Optionally add artwork and description via PUT
```

Track order in the `tracks` array determines playlist order (first = top).

### Unicode in Playlist Titles

SoundCloud **preserves Unicode characters** in playlist display titles. Use Unicode-styled titles for album/EP playlists (e.g., `ꐃ₦₮ɄɌꐃɄƦɌɆ₦ᵾɆ`). The permalink is auto-generated as ASCII regardless (e.g., `ridethevoid/sets/qv0hy2qdsehm`). Always include `charset=utf-8` in both Content-Type and Accept headers to ensure Unicode is transmitted correctly.

**Track titles on SoundCloud must be plain ASCII** — Unicode causes permalink and display issues. The Unicode-styled title belongs on the cover art and playlist title only.