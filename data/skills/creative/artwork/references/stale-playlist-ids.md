# Stale Playlist IDs on SoundCloud

When a user shares an `on.soundcloud.com` link to a playlist, the redirect may point
to a **stale version** that returns 404 when you try to update its artwork. This happens
when the user deleted the old playlist and re-created it (possibly with a Unicode-styled
title and more tracks).

## Symptom

- User shares link → redirects to `soundcloud.com/ridethevoid/sets/desert-void`
- `GET /playlists/{id}` returns 404 for that ID
- A different playlist ID exists with the same content but a Unicode-styled title
  (e.g. "ĐɆ₴ɆƦ† VØID") and possibly more tracks

## Root Cause

SoundCloud playlist IDs change when a playlist's metadata is significantly altered
or when it's re-created. The old `on.soundcloud.com` shortlink may still resolve to
the old (now-deleted) playlist's permalink slug, which persists after the underlying
ID is gone.

## Resolution

1. Fetch all playlists: `GET /me/playlists?limit=50`
2. Search for both ASCII and Unicode variants of the title (e.g. "DESERT VOID" and "ĐɆ₴ɆƦ† VØID")
3. The live version will have:
   - A non-404 ID when you `GET /playlists/{id}`
   - The correct track count
   - Unicode-styled title (if the user converted it)
4. Upload the new artwork to the live ID
