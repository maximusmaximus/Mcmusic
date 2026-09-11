---
name: soundcloud
description: "Upload, update, list, and manage tracks and playlists on SoundCloud via the official API."
version: 1.3.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [soundcloud, music, upload, oauth, api, tracks, social-media]
    related_skills: [venice-music, master-producer, soundcloud-analyzer, producer-profiles]
---

# SoundCloud Manager

Upload, update, list, and manage SoundCloud tracks via OAuth 2.1 PKCE. Token refresh is automatic after one-time auth.

> **References:** `references/oauth-quirks.md` · `references/soundcloud-api.md` · `references/playlist-api.md` · `references/release-directory.md` · `references/track-replacement-workflow.md` · `references/replace-track-in-published-album.md` · `references/publish-fallback-workflow.md`

## 🚀 Publishing Albums (USE THIS)

For album/EP releases, **always use `publish_release.py`** — it handles upload, playlist, tags, artwork, and label in one command with user confirmation buttons:

```bash
# Review gate: sends summary + Publish/Preview/Edit/Cancel buttons to Telegram
python3 /opt/data/skills/music/soundcloud/scripts/publish_release.py --release mars-descent

# Send audio for user review first, then publish buttons
python3 /opt/data/skills/music/soundcloud/scripts/publish_release.py --release mars-descent --preview

# Skip gates, publish immediately
python3 /opt/data/skills/music/soundcloud/scripts/publish_release.py --release mars-descent --confirm

# List release-ready albums
python3 /opt/data/skills/music/soundcloud/scripts/publish_release.py --list
```

Reads `release.json` + `tracks_meta.json` from `/opt/data/music/releases/<album>/`, auto-discovers artwork. See `references/release-directory.md` for structure.

For full end-to-end album publishing with per-track artwork, tags, label, and playlist creation, see `references/publish-release-pattern.md` — it documents the proven Python subprocess script pattern used for CHERENKOV-HORIZON and subsequent releases.

**⛔ Do NOT manually piece together upload → tags → playlist → artwork. Use this script.**

**User preference — skip review gate on explicit "Publish":** When the user says "Publish" or "Promote and Publish", they mean upload to SoundCloud immediately. Skip the review-files-first step in that case. Only send files for review when the user hasn't explicitly requested publishing.

## CLI Commands

All via `python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py`:

| Command | Usage |
|---------|-------|
| `upload` | `upload --file track.flac --title "Title" --tags "tag1 tag2" --genre Electronic --artwork cover.png --sharing public --downloadable --label "VØIDRIDE"` |
| `update` | `update --track-id ID --title "New" --tags "new tags" --genre Bass --artwork new.png --sharing private` |
| `list` | `list [--limit 50] [--json]` |
| `status` | `status --track-id ID` (states: `finished`=live, `processing`=encoding, `failed`=re-upload) |
| `batch-upload` | `batch-upload --dir /path/ --genre Electronic --tags "tag1 tag2" [--artwork-dir /covers/]` |
| `create-playlist` | `create-playlist --title "Album" --track-ids "123,456,789" [--artwork cover.png]` |

## First-Time Auth

```bash
# Native Linux (browser redirect works):
python3 /opt/data/skills/music/soundcloud/scripts/oauth_flow.py --auth

# WSL/headless (browser can't reach WSL):
python3 /opt/data/skills/music/soundcloud/scripts/oauth_flow.py --auth-url
# → Copy URL to Windows browser → authorize → copy callback URL
python3 /opt/data/skills/music/soundcloud/scripts/oauth_flow.py --exchange-url 'http://127.0.0.1:8080/callback?code=XXXXX'
```

Requires `SOUNDCLOUD_CLIENT_ID` + `SOUNDCLOUD_CLIENT_SECRET` env vars. Redirect URI must be `http://127.0.0.1:8080/callback`.

Tokens stored at `~/.hermes/credentials/soundcloud_tokens.json` (auto-refreshed, single-use refresh tokens).

## Publishing Rules (HARD RULES)

1. **SEND AUDIO FOR REVIEW BEFORE UPLOADING.** Never publish without user approval. No exceptions.
   - **User preference — skip review gate on explicit "Publish":** When the user says "Publish" or "Promote and Publish" (or similar imperative), go straight to `--confirm`. Don't send previews first.
   - **No Telegram available?** Send files manually via `MEDIA:` paths in your response, then ask for approval. Once approved, use `--confirm` to publish.
2. **FLAC ONLY.** Always upload FLAC masters — never MP3. SC re-encodes; lossless source = best quality.
3. **NO production details in descriptions.** No version numbers, LUFS stats, stem info, or how-it-was-made notes. Description = track name + genre/vibe only.
4. **NO poems in descriptions** unless user explicitly asks.
5. **Track titles: plain ASCII.** "Entrywound" not "Ɇ₦₮ƦɎ₩ØɄ₦Đ". Unicode belongs on cover art and playlist titles only.
6. **Cover art: Unicode-styled titles.** "BLΔCK MΔSS" not "BLACK MASS". Use Open Sans Bold (not Helvetica).
7. **Re-mix stems before regenerating.** Remove/reduce a bad stem rather than regenerating the whole track.

## Replacing a Track in a Published Album

When a user asks to replace a track in a published album:

1. **Find playlist + track ID** from `release.json`'s `soundcloud.track_ids` array
2. **DELETE** the track via raw API call: `DELETE /tracks/{id}`
3. **PUT** the playlist with remaining track IDs (PUT replaces the entire list)
4. **Update** `release.json` with the new track ID array
5. **Produce** a replacement track using the SAME model as the original (`production_plan.json` → `stems.main.model`)
6. **DAWAGENT** — Demucs separation + session handoff
7. **Cover art** — title overlay for the new track
8. **Upload** new track + update playlist with new ID

See `references/replacing-tracks.md` for the full step-by-step workflow with API examples.

## Playlist Creation (JSON format required)

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

payload = json.dumps({
    "playlist": {
        "title": "Album Title",
        "sharing": "public",
        "tracks": [{"id": "123456"}, {"id": "789012"}]  # STRING IDs, not ints!
    }
}).encode('utf-8')

req = urllib.request.Request("https://api.soundcloud.com/playlists", data=payload, method='POST')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Content-Type', 'application/json; charset=utf-8')
req.add_header('Accept', 'application/json; charset=utf-8')  # REQUIRED — 422 without this
resp = urllib.request.urlopen(req)
```

**PUT replaces** the entire track list — include ALL track IDs, not just new ones.

### Playlist Artwork

Must use `playlist[artwork_data]` (not `track[artwork_data]` — that 500s on playlists):

```python
boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
with open('cover.png', 'rb') as f:
    img_data = f.read()
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"playlist[artwork_data]\"; "
        f"filename=\"cover.png\"\r\nContent-Type: image/png\r\n\r\n").encode() + img_data + f"\r\n--{boundary}--\r\n".encode()
req = urllib.request.Request(f"https://api.soundcloud.com/playlists/{PLAYLIST_ID}", data=body, method='PUT')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
```

### Delete Track/Playlist

```python
req = urllib.request.Request(f"https://api.soundcloud.com/tracks/{TRACK_ID}", method='DELETE')
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
urllib.request.urlopen(req)  # 200 = success, irreversible
```

### Update Playlist Artwork (Raw API)

To update an existing playlist's cover without re-creating it, use multipart PUT.
**If you get 401 Unauthorized, run `soundcloud_api.py list` first to refresh the token, then retry.**

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

PLAYLIST_ID = 123456  # Replace with actual playlist ID
with open('cover.png', 'rb') as f:
    img_data = f.read()

boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
body = (
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="playlist[artwork_data]"; filename="cover.png"\r\n'
    f'Content-Type: image/png\r\n\r\n'
).encode() + img_data + f'\r\n--{boundary}--\r\n'.encode()

req = urllib.request.Request(
    f'https://api.soundcloud.com/playlists/{PLAYLIST_ID}',
    data=body, method='PUT',
    headers={
        'Authorization': f'OAuth {tokens["access_token"]}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Accept': 'application/json; charset=utf-8',
    }
)
with urllib.request.urlopen(req, timeout=120) as resp:
    result = json.loads(resp.read().decode('utf-8'))
    print(f'Updated: {result.get("title", "?")} artwork_url={result.get("artwork_url", "?")}')
```

**Important:** Use `playlist[artwork_data]` (NOT `track[artwork_data]` — that 500s on playlists). PNG works more reliably than JPG for playlist artwork. Files must be under 10MB.

## Venice Audio Models

| Model | Use | Cost |
|-------|-----|------|
| ace-step-15 | DEFAULT vocal songs | $0.03 |
| minimax-music-v2 | Freeform vocals | $0.04 |
| elevenlabs-music | Premium | $0.69 |
| stable-audio-25 | Ambient/cinematic | $0.19 |
| elevenlabs-sound-effects-v2 | SFX only | $0.02 |

## Replacing a Track in a Published Album

When a track in a published album needs to be removed and replaced:

1. Find the album's release directory at `/opt/data/music/releases/<album-slug>/`
2. Read `release.json` — published albums use pipeline format with `soundcloud.track_ids` array
3. Index into track_ids to find the SC ID of the target track
4. **Delete** the track via DELETE API call (irreversible — plays/comments lost)
5. **Update playlist** via `update-playlist --track-ids` with remaining track IDs
6. **Update release.json** — remove the deleted track ID from the array
7. **Produce replacement** using `master-producer.py` (same model as original — check `production_plan.json`)
8. **Send preview** (MP3) for user review
9. Post-approval: Demucs → DAWAGENT → copy to release dir → upload via `publish_release.py --confirm`

See `references/replace-track-in-published-album.md` for the full workflow with code samples and edge cases.

## Pitfalls (deduplicated)

### Auth & Tokens
1. **`scope=non-expiring` is FORBIDDEN.** SC returns 403. Don't include scope in auth URL.
2. **Token endpoint:** `POST https://api.soundcloud.com/oauth2/token` (NOT `secure.soundcloud.com`).
3. **Auth codes expire in ~10 min.** `invalid_grant` = code expired, re-authorize.
4. **Raw API calls don't auto-refresh tokens.** Run any `soundcloud_api.py` command first to refresh, then retry raw calls.

### Upload & Encoding
5. **Encoding takes time.** After upload, state goes `processing` → `finished`. Use `status` to check.
6. **Content ID false positives.** AI-generated tracks can be flagged. Track disappears + 404. Must regenerate with different prompt (re-upload of same audio gets flagged again).
7. **Encoding failure (returned 404): re-upload fixes it.** Sometimes a track returns 404 immediately after upload (state never reaches `finished`). This is an encoding glitch, not a content-ID flag. Re-uploading the **same file** usually works — try this before regenerating with a different prompt.
7. **No audio replacement API.** To fix audio: upload new track → copy metadata → delete old track. Plays/comments are lost.
8. **No `--artist` flag.** Use `--label "VØIDRIDE"` instead.

### Tags
9. **Tags often fail on initial upload.** Always run a separate `update --tags` pass after uploading.
10. **Tags fail during encoding.** If `state: "unknown"` or `state: "processing"`, tag updates return 200 OK but `tag_list` stays empty. Don't waste API calls re-applying. **Pattern:** Upload all tracks → create playlist → add artwork → wait 2-3 minutes → `status --track-id` until `state: "finished"` → apply tags + label in a single batch. Each retry during encoding is wasted effort and risks rate limits.

### Titles & Unicode
11. **`$` is stripped from titles** on both upload and update. Use `₴`, `§`, or `₿` instead.
12. **Permalinks are ASCII-mangled** (`VØIDRIDE` → `v-idride`). Always use `track_id` for API operations, never permalink.
13. **Don't mix Unicode + plain in playlist names.** Either all Unicode ("₴ØɄ₦ĐĐɆ₴łǤ₵") or all plain ("MARS DESCENT").

### Artwork
14. **Must be SQUARE 1:1, min 800×800, max 10MB.** Venice outputs WebP — convert: `ffmpeg -i cover.webp cover.png`. Always use `aspect_ratio: "1:1"` when generating.
15. **3000×3000 PNGs often exceed 10MB.** Resize to 2000×2000: `ffmpeg -i cover.png -vf "scale=2000:2000:flags=lanczos" resized.png`. Or use JPG: `ffmpeg -i cover.png -q:v 2 cover.jpg`.
16. **Playlist artwork: JPG can silently fail.** Try PNG first (under 10MB). Track artwork is more tolerant.
17. **Upload fails silently — check artwork size first.** When `publish_release.py` reports `✗ Upload failed:` with NO error message (empty string after the colon), the most likely cause is cover art exceeding the 10MB SoundCloud limit. Resize all covers to 2000×2000 PNG before retrying: `ffmpeg -y -i cover.png -vf "scale=2000:2000:flags=lanczos" -compression_level 6 cover_2k.png`. If multiple tracks fail simultaneously with blank error messages, check artwork sizes before debugging other causes.
18. **After re-generating covers (e.g. title overlay applied post-promotion), sync them back to both directories:**

18. **Removing a track from a published album requires updating both SoundCloud AND local metadata.** After deleting a track from SoundCloud: (a) update the playlist via `update-playlist` with remaining track IDs, (b) remove the track ID from `release.json`'s `soundcloud.track_ids`, and (c) update `tracks_meta.json` if the track count changed. The local release directory is the source of truth for re-publishing — keep it in sync.

19. **After replacing a removed track with a new one, the playlist edit includes ALL IDs.** Use `update-playlist --track-ids` with every track ID (all remaining originals + the new one). The PUT method replaces the entire playlist — omitting an ID removes that track.
    - `publish_release.py`'s `find_artwork()` searches `/opt/data/music/artwork/covers/`
    - The promote script copies from artwork/covers → release
    - But if covers are generated directly into the release directory (e.g. via a batch script), they WON'T be found by `find_artwork()`
    - Fix: `cp /opt/data/music/releases/<album>/covers/*_cover.png /opt/data/music/artwork/covers/`

### Playlists
17. **Track IDs must be STRINGS in JSON.** Integer IDs silently create empty playlists. Both `Content-Type` and `Accept` headers with `application/json; charset=utf-8` are required.
18. **No `delete` command in the CLI.** Use direct DELETE API call (see above).
19. **`soundcloud_api.py list` only shows tracks, NOT playlists.** To find playlist IDs for artwork updates or management, use the raw API `/me/playlists` endpoint:
    ```python
    req = urllib.request.Request('https://api.soundcloud.com/me/playlists?limit=50', headers={
        'Authorization': f'OAuth {tokens["access_token"]}',
        'Accept': 'application/json; charset=utf-8',
    })
    ```
    Match by title (Unicode works). The `soundcloud_api.py` CLI has no playlist-list command.
20. **Playlist artwork multipart PUT uses `playlist[artwork_data]` (NOT `track[artwork_data]`).** Using `track[artwork_data]` returns 500 on playlists.
21. **`tracks_meta.json` must be a JSON ARRAY, not a dict.** `publish_release.py` indexes tracks by integer position (`tracks_meta[0]`, `tracks_meta[1]`). If you write it as `{"tracks": [...]}`, the script raises `KeyError: 0`. The correct format is a flat list of per-track objects at the top level.

### "Unknown" State
22. **Track state can be `unknown` instead of `processing` / `finished`.** This is a valid live state — the track is public and playable despite never reaching `finished`. The `status` command and encoding-polling loop may never see `finished`, causing spurious timeouts. Check the SoundCloud playlist URL or play the track in-browser to verify. Do not re-upload on `unknown`.

### Tags: Raw API vs CLI
23. **CLI `update --tags` returns 200 OK but `tag_list` stays empty when state is `unknown`.** This is a SoundCloud API quirk — the CLI tool sends the right payload but SC ignores it for tracks in non-standard states. The **raw API PUT** `/tracks/{id}` always works regardless of state. See `references/publish-fallback-workflow.md` for the full script.

### publish_release.py Silent Failure — Manual Fallback
24. **When `publish_release.py` fails with empty `Upload failed:` errors on ALL tracks (even after artwork is resized under 10MB), don't debug the script — fall back to manual upload.** The root cause could be token freshness, the tag_metadata.py pre-pass corrupting files, or JSON parsing in the upload response handler. Upload each track individually via `soundcloud_api.py upload`, create the playlist, apply tags via raw API, and update `release.json`. See `references/publish-fallback-workflow.md` for the complete step-by-step.

## SoundCloud Analyzer

Analyze public playlists with AI tagging + vector search. Separate skill — see `soundcloud-analyzer` SKILL.md.

```bash
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  analyze --url "https://soundcloud.com/user/sets/playlist" --telegram-chat CHAT_ID

python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  search --query "dark ambient" --top-k 5
```
