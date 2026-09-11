# Playlist Artwork Update Workflow

Update a SoundCloud playlist's cover image when covers are regenerated or redesigned.

## Why This Exists

`soundcloud_api.py` has no `playlist-artwork` command. Playlist artwork must be updated via a raw multipart PUT request to the SoundCloud API. Track artwork can use `update --track-id --artwork`, but playlists require the manual API pattern below.

## Step 1: Find the Playlist ID

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

# Refresh token first by calling the CLI
# subprocess.run(["python3", SC, "list", "--limit", "1"], ...)

req = urllib.request.Request('https://api.soundcloud.com/me/playlists?limit=50', headers={
    'Authorization': f'OAuth {tokens["access_token"]}',
    'Accept': 'application/json; charset=utf-8',
})
with urllib.request.urlopen(req, timeout=30) as resp:
    playlists = json.loads(resp.read().decode('utf-8'))

for p in playlists:
    print(f'{p["id"]} | {len(p.get("tracks",[]))} tracks | {p["title"]}')
```

Match by title (Unicode titles display correctly). Note the `id` field.

**Pitfall:** Token may be expired. Run `soundcloud_api.py list --limit 1` first to trigger a token refresh, then proceed with raw API calls.

## Step 2: Upload Artwork via Multipart PUT

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

PLAYLIST_ID = 1234567890  # from Step 1
COVER_PATH = "/path/to/album_cover.png"  # 3000x3000 PNG preferred, must be <10MB

with open(COVER_PATH, 'rb') as f:
    img_data = f.read()

print(f'Image size: {len(img_data)/1024/1024:.1f}MB')

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

try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        print(f'✅ Updated: {result.get("title")} — {result.get("artwork_url")}')
except urllib.error.HTTPError as e:
    print(f'❌ Error {e.code}: {e.read().decode("utf-8")[:500]}')
```

The field name MUST be `playlist[artwork_data]` (not `playlist[artwork]`). PNG and JPEG are accepted. SoundCloud automatically creates multiple resolutions from the upload.

## Step 3: Verify

**⚠️ The PUT response returns the OLD cached CDN URL, not the new one.** The `artwork_url` field in the PUT response always shows the pre-existing artwork hash, even when the upload succeeds. To get the new CDN hash, re-fetch the playlist:

```python
req = urllib.request.Request(
    f'https://api.soundcloud.com/playlists/{PLAYLIST_ID}',
    headers={
        'Authorization': f'OAuth {tokens["access_token"]}',
        'Accept': 'application/json; charset=utf-8',
    }
)
with urllib.request.urlopen(req) as resp:
    pl = json.loads(resp.read().decode('utf-8'))
    print(f'New artwork URL: {pl.get("artwork_url")}')
```

A changed hash (e.g. `artworks-abc123` → `artworks-xyz789`) confirms the upload succeeded. Same hash = the old image is still being served; the PUT may have failed silently (check file size ≤ 10MB).

## File Size

- SoundCloud accepts images up to ~10MB
- 3000×3000 PNG covers are typically 7-10MB (acceptable)
- If over 10MB, convert to JPEG first: `ffmpeg -y -i cover.png -q:v 2 cover_2mb.jpg` (reduces to ~0.5MB)

## Common Pattern: Regenerate Cover → Update Playlist

1. Generate new cover with Venice AI + overlay-title.py
2. Send to user for review (1500x1500 JPEG via Telegram)
3. User approves
4. Update SoundCloud playlist artwork using this workflow
5. Also update per-track covers if needed: `soundcloud_api.py update --track-id ID --artwork path.png`

## Step 3 Verify — CDN Cache Quirk

⚠️ The PUT response returns the OLD cached CDN URL. Always re-fetch the playlist with GET /playlists/{ID} and compare `artwork_url` hashes to confirm the new image propagated.

## Unicode Titles in Lookups

Playlist titles with Unicode characters (₴, Δ, Ɇ, etc.) display correctly in `GET /me/playlists` responses. When searching for a playlist by title, match on the `title` field — do NOT rely on `permalink_url` slugs, which are ASCII-mangled.

## Converting Unicode Track Titles to Plain ASCII

When the user asks to strip Unicode styling from track titles (e.g. ƤɎƦØϾⱠΔ₤† → PYROCLAST):

1. Fetch the playlist track list via `GET /playlists/{ID}` — the API returns raw Unicode titles
2. Decode each character by matching Unicode glyphs to their intended Latin equivalents. Use the `cover-title-overlay` skill's `references/code-points.md` as a decoder ring — it maps characters like Δ→A, Ɇ→E, ₦→N, Ʀ→R, etc.
3. The user's rule: ALL CAPS plain ASCII, no hyphens (replace with spaces)
4. Update each track via `soundcloud_api.py update --track-id ID --title "NEW TITLE"`
5. The playlist page updates immediately — the track listing on the page reflects changes within seconds