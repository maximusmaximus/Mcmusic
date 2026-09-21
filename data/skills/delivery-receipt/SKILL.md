---
name: delivery-receipt
description: Generates production receipts with local FLAC links and VLC playlists for Windows review. Handles "send the windows playlist link to review", "local win playlist", and file recall for past productions. Auto-copies mastered files from DAWAGENT exports to D:\music\exports\, creates .m3u8 playlists, packages releases via secure-share, and delivers them to Telegram.
---

# Delivery Receipt & File Recall Skill

Creates production receipts, handles file recall, and delivers Windows VLC playlists and review packages.

## 🎶 Windows Playlist Review Trigger ("send the windows playlist link to review")

When the user asks:
- **"send the windows playlist link to review"**
- **"send the local win playlist"**
- **"windows playlist link to review"**
- or any variation asking for the local Windows playlist or review link

### Command to Execute:
```bash
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/send_windows_playlist.py [--session <session_name>]
```
*(If `--session` is omitted, it automatically targets the most recent production/export in `/opt/data/music/exports/`).*

### What this command does:
1. Locates the target session in `/opt/data/music/exports/`.
2. Verifies or generates the Windows VLC `.m3u8` playlist referencing `D:\music\exports\<session>\` local paths.
3. Automatically triggers `secure-share` to package the full release folder into a ZIP archive and obtains the live Cloudflare `[EXTERNAL LINK]`.
4. Sends the `.m3u8` playlist file directly as a document to Telegram.
5. Sends the local Windows file path and the Cloudflare download link to Telegram for review.

---

## What It Does

### After Production (auto or manual)
1. **Copies FLAC masters** from Podman volume to `/opt/data/music/exports/<session>/` (→ `D:\music\exports\<session>\` on Windows)
2. **Converts WAV → FLAC** if FLACs don't exist yet (48kHz/24-bit lossless)
3. **Creates a VLC `.m3u8` playlist** with Windows-formatted paths
4. **Sends via Telegram**: Receipt with local file links + playlist file

### File Recall (when user asks for past files)
1. **Lists** all available export sessions
2. **Sends MP3s** via Telegram (FLAC is too large for TG's 50MB limit)
3. **Provides Windows paths** to FLAC files for local access
4. **Sends VLC playlists** for easy review

## Scripts

### send_windows_playlist.py — Automatic Windows playlist + Cloudflare review package
```bash
# Send latest export
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/send_windows_playlist.py

# Send specific session
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/send_windows_playlist.py --session saltflat-armory
```

### deliver_receipt.py — Generate receipts + FLAC exports
```bash
# Generate receipt + send via Telegram
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/deliver_receipt.py \
  --session spatial-ship --send-telegram

# Generate only (no Telegram)
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/deliver_receipt.py \
  --session spatial-ship --no-send
```

### recall_exports.py — Find and send past productions
```bash
# List all available exports
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/recall_exports.py --list

# Search by name
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/recall_exports.py --search "mars"

# Get details for a session
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/recall_exports.py --session mars-descent-v2

# Send MP3s + playlist via Telegram
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/recall_exports.py --session mars-descent-v2 --send
```

### promote_release.py — Promote exports to canonical releases
```bash
# List all releases
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/promote_release.py --list

# Single-session album (works correctly)
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/promote_release.py \
  --from "session-exact-name" \
  --as "album-slug" \
  --artwork-dir "/opt/data/music/artwork/covers/album-slug"
```

**⚠️ The `--from` flag requires an exact session name**, not a glob pattern. `--from "nocturne-overpass-*"` will fail — use the exact name like `--from "nocturne-overpass-midnight-radial"`.

**⚠️ Multi-session albums: DO NOT call promote_release.py per-track!** Calling it multiple times with the same `--as` flag overwrites the release directory instead of accumulating tracks. See the full "Multi-Session Album Promotion" pitfall below.

### tag_metadata.py — Embed full metadata into FLAC/MP3
```bash
# Tag with artist profile (auto-fills artist, copyright, publisher)
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/tag_metadata.py \
  --session mars-descent-v3 --profile vidride --album "MARS DESCENT" \
  --tracks-json /opt/data/music/exports/mars-descent-v3/tracks_meta.json

# Manual override
python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/tag_metadata.py \
  --session my-session --artist "ARTIST" --album "ALBUM" --genre "Genre"
```

**Embedded metadata fields:**
| Field | Example |
|-------|---------|
| artist / album_artist | VØIDRIDE |
| album | MARS DESCENT |
| title | IGNITION VEIL |
| track | 1/5 |
| genre | Dark Nightride Trap / Aggressive Witch House |
| date | 2026 |
| copyright | © 2026 Max Infeld |
| publisher | VØIDRIDE |
| producer | VØIDRIDE |
| BPM / TBPM | 155 |
| TKEY / initialkey | Cm |
| encoded_by | ffmpeg / Venice AI / Spotify Pedalboard |
| comment | Stems: Venice AI (ElevenLabs, Stable Audio) \| FX: Spotify Pedalboard \| Mastering: ffmpeg |

**Artist profiles** (built-in):
- `vidride` → Artist: VØIDRIDE, Copyright: Max Infeld, Publisher: VØIDRIDE

**ALWAYS tag after creating exports.** The `tracks_meta.json` file should contain per-track BPM, key, and genre from the production metadata.

## Publishing Pipeline

After promoting a release, the files in `/opt/data/music/releases/<album>/` are the single source of truth for SoundCloud upload. The `soundcloud` skill references this release directory for track metadata, file paths, and cover art. Key files:

- `release.json` — album name, track order, status (`"release-ready"`), source (e.g. `"dawagent-mix-mastered"`)
- `tracks_meta.json` — per-track BPM, key, genre (used for SoundCloud tags)
- `*_MASTER.flac` / `*_MASTER.mp3` — mastered audio files
- `{album}_playlist.m3u8` — playback order

Cover art lives at `/opt/data/music/artwork/covers/{album_slug}_{track_num}_{TRACK_NAME}.png` (3000×3000).

## Path Mapping

| Container Path | WSL Path | Windows Path |
|---------------|----------|-------------|
| `/opt/data/music/exports/` | `/mnt/d/music/exports/` | `D:\music\exports\` |

## Multi-Track Album Promotion

When an album has tracks in separate export sessions (e.g., `nocturne-overpass-midnight-radial`, `nocturne-overpass-shadow-chaser`, etc.), you **must** promote each session individually with `--from <session> --as <album>`:

```bash
for session in nocturne-overpass-midnight-radial nocturne-overpass-shadow-chaser nocturne-overpass-phosphor-run nocturne-overpass-rain-sickle nocturne-overpass-carbon-apparition; do
  python3 /opt/data/skills/delivery-receipt/delivery-receipt/scripts/promote_release.py \
    --from "$session" --as "nocturne-overpass" --artwork-dir "/opt/data/music/artwork/nocturne-overpass"
done
```

**⚠️ Pitfall:** Each `--from` call **overwrites** the release directory instead of accumulating. After promoting all sessions, the release directory will only contain the LAST session's files. You must manually copy FLAC/MP3 files from all export sessions into the release directory and rewrite `release.json` with full track data. Use this pattern:

```python
import shutil, json, os

release_dir = "/opt/data/music/releases/<album>"
sessions = [("track-slug-1", 1), ("track-slug-2", 2), ...]
track_titles = {"track-slug-1": "TRACK TITLE 1", ...}

for session, num in sessions:
    export_dir = f"/opt/data/music/exports/<album>-{session}"
    flac_src = f"{export_dir}/<album>-{session}_MASTER.flac"
    flac_dst = f"{release_dir}/{num:02d}_{track_titles[session].replace(' ', '_')}_MASTER.flac"
    if not os.path.exists(flac_dst):
        shutil.copy2(flac_src, flac_dst)
```

Then rebuild `release.json` with all track metadata (title, BPM, key, genre, cover filename) and copy cover art from the artwork directory.

## Sending Files via Telegram

### General Rule — NEVER rename file extensions
Send files with their **original extension**. Telegram's `MEDIA:` handler and `sendDocument` both work natively with all file types. `.m3u8`, `.flac`, `.mp3`, `.json`, `.png`, `.jpg` — send them as-is. No `.bin` copies, no rename instructions.

### Images (PNG, JPG, WEBP)
Telegram's `MEDIA:` auto-renders images as **photo bubbles** (compressed). For uncompressed document download of a PNG/JPG, use `sendDocument` with the original extension — the receive-side download button preserves quality. If quality matters (cover art, 3000×3000 PNGs), send via `sendMessage` with the `MEDIA:` path — it renders inline at readable size; the user can tap to save the original.

### Audio files
- MP3 files send natively as audio bubbles — inline playback with waveform
- FLAC masters (25-35MB from DAWAGENT) can be sent directly — fit under Telegram's 50MB limit
- FLAC productions (unmastered, 40-70MB) may exceed the limit — send MP3 instead + provide local FLAC path
- Always send the `.m3u8` VLC playlist **alongside** FLAC files so the user has both audio and a playback list
- **DELIVER FILES CLEANLY**: Use `MEDIA:/path` entries without displaying the file path as text. The user prefers to receive files as native attachments, not as text links they have to tap. Each MEDIA: line should be accompanied by brief descriptive text (e.g. "Sending all 5 tracks"), not the raw path. If sending multiple files, group them under a single message instead of one file per message.

## ⚠️ Critical Rules
- **FLAC via Telegram**: Check file size against Telegram's 50MB limit. DAWAGENT FLAC masters from `/opt/data/music/exports/` are typically 25-35MB and CAN be sent directly. Production FLACs (unmastered, in `/productions/`) are often 40-70MB and may exceed the limit — for those, send MP3 instead and provide the local FLAC path. Always check with `ls -lh` before assuming a FLAC is too large.
- **ALWAYS tag metadata** before delivering — use `tag_metadata.py` with the appropriate profile
- **Send files with original extensions** — `.m3u8`, `.flac`, `.mp3`, `.json`, `.png`, `.jpg` all work natively via `MEDIA:` and `sendDocument`
- **Cover art PNGs over 10MB** need JPG conversion for Telegram's `send_photo` limit: `ffmpeg -y -i cover.png -q:v 2 cover.jpg`
- Look in `/opt/data/music/exports/` for finished files, NOT `/opt/data/music/productions/`
- If exports don't exist for a session, run `deliver_receipt.py` first to create them

## 📚 Reference: Batch Playlist Generation

For backfilling playlists across many legacy export sessions (e.g., productions that predated the delivery-receipt pipeline), see `references/batch-playlist-generation.md`. Covers the scan-identify-generate pattern used to create playlists for 16+ sessions in one pass.
