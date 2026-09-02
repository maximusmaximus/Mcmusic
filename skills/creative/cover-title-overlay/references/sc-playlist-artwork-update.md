# SoundCloud Playlist Artwork Update

Updating playlist artwork requires a raw multipart PUT request to the SoundCloud API.
The `soundcloud_api.py` tool does not have a dedicated `update-artwork` command for playlists,
so use urllib directly.

## Workflow

1. **Find the playlist ID** — list playlists via the API or `soundcloud_api.py list`
2. **Upload the cover** — multipart PUT with the PNG file

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

PLAYLIST_ID = 1234567890  # from listing
COVER_PATH = '/path/to/album_cover.png'

with open(COVER_PATH, 'rb') as f:
    img_data = f.read()

boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
body = (
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="playlist[artwork_data]"; filename="cover.png"\r\n'
    f'Content-Type: image/png\r\n\r\n'
).encode() + img_data + f'\r\n--{boundary}--\r\n'.encode()

req = urllib.request.Request(
    f'https://api.soundcloud.com/playlists/{PLAYLIST_ID}',
    data=body,
    method='PUT',
    headers={
        'Authorization': f'OAuth {tokens["access_token"]}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Accept': 'application/json; charset=utf-8',
    }
)

with urllib.request.urlopen(req, timeout=120) as resp:
    result = json.loads(resp.read().decode('utf-8'))
    print(f'Updated: {result.get("title", "?")}')
    print(f'Artwork: {result.get("artwork_url", "?")}')
```

## Key Points

- **Use PNG, not JPG** — SoundCloud accepts both but PNG preserves quality
- **Max 10MB** — 3000×3000 PNG covers are typically 5-8MB, well under the limit
- **Token refresh** — If you get 401, run `soundcloud_api.py list` first to refresh the token, then retry
- **PLAYLIST_ID** — found by listing all playlists and matching by title

## Finding Playlist ID

```python
req = urllib.request.Request('https://api.soundcloud.com/me/playlists?limit=50', headers={
    'Authorization': f'OAuth {tokens["access_token"]}',
    'Accept': 'application/json; charset=utf-8',
})
with urllib.request.urlopen(req, timeout=30) as resp:
    playlists = json.loads(resp.read().decode('utf-8'))
for p in playlists:
    print(f'{p["id"]} | {p["title"]}')
```

Match by title (Unicode titles work) to get the playlist ID.