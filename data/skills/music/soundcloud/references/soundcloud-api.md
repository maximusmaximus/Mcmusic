# SoundCloud API Reference

Condensed reference for the endpoints and data shapes used by the `soundcloud` skill.
Source: SoundCloud API v2 (HTTPS), official developer docs.

## Authentication Endpoints

### Authorize (browser redirect)
`GET https://secure.soundcloud.com/authorize`

Params: `client_id`, `response_type=code`, `redirect_uri`, `code_challenge`, `code_challenge_method=S256`, `scope`

### Token Exchange
`POST https://secure.soundcloud.com/oauth2/token`

Form data:
- `grant_type=authorization_code` — initial exchange
- `grant_type=refresh_token` — refresh
- `code` — authorization code (exchange only)
- `redirect_uri` — must match the one used in authorize
- `client_id`, `client_secret`
- `code_verifier` — PKCE verifier (exchange only)
- `refresh_token` — the refresh token (refresh only)

Response:
```json
{
  "access_token": "2-...",
  "expires_in": 3600,
  "refresh_token": "2-...",
  "scope": "non-expiring",
  "token_type": "Bearer"
}
```

Key facts:
- Access tokens expire in ~1 hour (`expires_in: 3600`)
- Refresh tokens are **single-use** — each refresh returns a new refresh_token
- Store both the new access_token AND the new refresh_token on every refresh

## Track Endpoints

### Upload Track
`POST https://api.soundcloud.com/tracks`

Multipart form data. Fields:
- `track[asset_data]` — audio file (required)
- `track[artwork_data]` — cover art image (optional, JPG/PNG, min 800x800, max 10MB)
- `track[title]` — track title (required)
- `track[sharing]` — `public` or `private` (default: `public`)
- `track[downloadable]` — `true` or `false`
- `track[streamable]` — always `true`
- `track[description]` — markdown allowed
- `track[genre]` — e.g. "Electronic"
- `track[tag_list][0]`, `track[tag_list][1]`, ... — individual tags
- `track[release_date]` — ISO date
- `track[label_name]` — label

Auth: `Authorization: OAuth {access_token}`

Response: 201 Created with full track object.

### Update Track
`PUT https://api.soundcloud.com/tracks/{id}`

Same form fields as upload (minus `track[asset_data]`). Only send fields you want to change.

Response: 200 OK with updated track object.

### List My Tracks
`GET https://api.soundcloud.com/me/tracks`

Params: `limit` (default 10, max 200), `linked_partitioning=1`

Response:
```json
{
  "collection": [ { track object }, ... ],
  "next_href": "https://api.soundcloud.com/me/tracks?cursor=..."
}
```

### Get Track Details / Status
`GET https://api.soundcloud.com/tracks/{id}`

Track `state` values:
- `uploading` — still uploading
- `processing` — SoundCloud is encoding
- `finished` — live and playable
- `failed` — encoding error, re-upload needed

### Resolve URL
`GET https://api.soundcloud.com/resolve?url={soundcloud_url}`

Returns the object (track, user, playlist) the URL points to.

## Track Object Shape (key fields)

```json
{
  "id": 123456789,
  "title": "Track Title",
  "description": "...",
  "state": "finished",
  "sharing": "public",
  "downloadable": false,
  "genre": "Electronic",
  "tag_list": "witch house, dark trap",
  "duration": 180000,
  "created_at": "2026-07-14T12:00:00Z",
  "last_modified": "2026-07-14T12:05:00Z",
  "permalink_url": "https://soundcloud.com/user/track",
  "artwork_url": "https://i1.sndcdn.com/artworks-...-t500x500.jpg",
  "playback_count": 0,
  "download_count": 0,
  "favoritings_count": 0,
  "user": {
    "id": 98765,
    "username": "username",
    "permalink_url": "https://soundcloud.com/username"
  }
}
```

- `duration` is in **milliseconds**
- `tag_list` is a comma-separated string when reading, but uploaded as indexed array fields
- `artwork_url` suffix `-t500x500.jpg` can be replaced with `-t200x200.jpg`, `-original.jpg`, etc.

## Error Responses

429 Too Many Requests — rate limited. Retry with exponential backoff.
401 Unauthorized — token expired or invalid. Refresh or re-auth.
403 Forbidden — no permission for this resource.
404 Not Found — track doesn't exist or is private and not yours.
422 Unprocessable Entity — invalid metadata (missing title, bad artwork size, etc.)

Error body shape:
```json
{
  "errors": [
    { "error_message": "Title can't be blank" }
  ]
}
```

### Delete Track
`DELETE https://api.soundcloud.com/tracks/{id}`

Auth: `Authorization: OAuth {access_token}`

Response: 200 OK (no body) on success.

Note: Deletion is immediate and irreversible. No confirmation prompt from the API.

## Playlist (Set) Endpoints

### Create Playlist
`POST https://api.soundcloud.com/playlists`

**Must use JSON with string track IDs** — see `references/playlist-api.md` for full details and common pitfalls.

```bash
curl -X POST "https://api.soundcloud.com/playlists" \
  -H "Authorization: OAuth {access_token}" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "Accept: application/json; charset=utf-8" \
  -d '{"playlist":{"title":"Album Title","sharing":"public","tracks":[{"id":"123456789"},{"id":"987654321"}]}}'
```

### Update Playlist (add/change tracks)
`PUT https://api.soundcloud.com/playlists/{id}`

Same JSON format. **Replaces** the entire track list — include ALL tracks, not just new ones.

### Delete Playlist
`DELETE https://api.soundcloud.com/playlists/{id}`

Response: 200 OK on success. Irreversible.

### List My Playlists
`GET https://api.soundcloud.com/me/playlists?limit=50`

Returns a flat array (not a collection object like tracks).

### Playlist Object Shape

```json
{
  "id": 2280808634,
  "title": "Album Title",
  "description": "...",
  "sharing": "public",
  "track_count": 5,
  "tracks": [ { track objects } ],
  "permalink_url": "https://soundcloud.com/user/sets/album-title",
  "artwork_url": null,
  "genre": "",
  "tag_list": "",
  "label_name": null,
  "created_at": "2026/08/09 05:43:02 +0000"
}
```

## Rate Limits

- Uploads: ~1000/hour (undocumented, may vary)
- Read operations: higher limits
- Always handle 429 with backoff; the scripts do this automatically
