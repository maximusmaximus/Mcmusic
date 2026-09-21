# Redoing a Playlist Cover Based on Its Track Artwork

## When the user says "redo this playlist cover based on the art of the songs"

This is a specific workflow: the user wants a NEW playlist/album cover inspired by the visual style of the existing **individual track covers** on that playlist. You are NOT redoing the music — only the cover art.

## Full Workflow

### Step 1: Analyze the SoundCloud playlist

```bash
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py analyze --url "<SC_PLAYLIST_URL>" --telegram-chat <CHAT_ID>
```

This returns playlist metadata, per-track analysis, mood/genre breakdown, and thematic analysis.

> ⚠️ **The analyzer returns track titles as "Unknown" for Unicode-styled titles and does NOT include artwork URLs in the CLI output.** To get actual track titles and artwork URLs, use the raw SoundCloud API instead (see below).

### Step 2: Get track artwork URLs via raw API

After the analyzer, fetch the live playlist data from SoundCloud to get artwork URLs:

```python
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

# Fetch user's playlists
req = urllib.request.Request(
    'https://api.soundcloud.com/me/playlists?limit=50',
    headers={
        'Authorization': f'OAuth {tokens["access_token"]}',
        'Accept': 'application/json; charset=utf-8',
    }
)
with urllib.request.urlopen(req) as resp:
    playlists = json.loads(resp.read().decode('utf-8'))

# Find the target playlist by title (partial match for Unicode)
target = [p for p in playlists if '<KEYWORD>' in p['title']]

# Get track artwork URLs
for t in target[0]['tracks']:
    print(t['title'], t['artwork_url'])
```

This also solves the **Stale Playlist ID problem** — the analyzer may return `playlist_id: 4` (completely wrong) even when the SoundCloud shortlink resolves fine. Always fetch `/me/playlists` to get the live ID before generating artwork. See `references/stale-playlist-ids.md` for the full detection workflow.

**Token refresh:** Raw API calls don't auto-refresh tokens. Run `python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py list --limit 1` first to refresh, then the raw API calls will work.

### Step 3: Download existing track covers

```bash
mkdir -p /tmp/album-art-refs
curl -sL "<artwork_url_1>" -o /tmp/album-art-refs/track_1.jpg
curl -sL "<artwork_url_2>" -o /tmp/album-art-refs/track_2.jpg
# ... etc for all tracks
```

SoundCloud serves artwork at suffixes: `-large.jpg` (~100×100), `-t500x500.jpg` (~500×500). Use `-t500x500` for reference quality.

### Step 4: Generate a new playlist cover

```bash
# Delete old files first (no --force flag in gen_artwork.py)
rm -f /opt/data/music/artwork/covers/<FILENAME>*.png /opt/data/music/artwork/waveforms/<FILENAME>*.png

python3 /opt/data/skills/artwork/artwork/scripts/gen_artwork.py \
  --title "<FILENAME>" \
  --genre "<genre>" \
  --bpm <BPM> \
  --key "<KEY>" \
  --notes "<album-style establishing shot description tailored to the track visual DNA>"
```

Use the `--title` parameter for filenaming (plain ASCII, underscores for spaces). The `--notes` should describe an **album-style establishing shot** that matches the visual DNA observed across the track covers.

For VØIDRIDE playlists, the visual DNA consistently includes:
- Dark nightride / witch house aesthetic (nocturnal, foggy, neon-lit)
- Multiple cars together (not a single hero car — album/playlist style)
- Fedora/trench coat/katana man as silhouette
- Huge moon dominating the sky (not always — check what the track covers use)
- Purple/cyan neon glow
- Thick fog and atmosphere
- Wet asphalt / highway setting

**Animal/laser eye variant**: If the per-track analysis reveals each song has a named animal/creature energy (wolf, gorilla, snake, raven, shark, etc.), the user may ask for **animals with glowing laser eyes** instead of cars. See `references/voidride-animal-motif-covers.md` for the full motif mapping table and prompt template. This replaces the car/fedora composition entirely.

Prompt notes template (standard cars):
```
"wide cinematic establishing shot of multiple drift cars stacked in formation doing donuts under a massive moon, dark fedora figure with katana, thick rolling fog, [COLOR] neon glow, hurricane chaos energy, smoking tires, photorealistic"
```

**Transfer theme elements from track analysis into the notes:**
If the playlist has a strong conceptual theme (e.g., "digital decay and cyber-occultism" for SYNAPSE NECROPOLIS), build the notes around that. Include the number of tracks as visual elements (e.g., "five ghostly data phantoms rising from ground" for 5 tracks). Match the cold/grainy/spectral mood from the playlist analysis.

### Variant: "Combine Symbols" from Track Artwork

When the user says **"combine symbols from the track art"** instead of simply "based on the art", they want you to identify distinct visual motifs and color languages across the track covers and merge them into a single cohesive composition — not just a generic all-cars scene.

**Workflow addition for "combine symbols" requests:**

1. **Download all track covers** at `-t500x500.jpg` resolution
2. **Analyze color camps** per-channel: convert to RGB, mask non-black pixels (sum > 60), compute per-channel means, find dominant channel (R/G/B)
3. **Group tracks by dominant color** — same-camp tracks go on one side of the composition
4. **Build a split-color prompt** — mention specific color zones and how they interact (e.g., "frequency wave lines arcing across the divided sky")
5. **Count the tracks** — include that number as visual elements in the prompt
6. **Map track names to visual symbols** (e.g., "cemetery" → crosses, "phantom" → ghost shapes, "frequency" → wave lines, "doom" → fire)
7. **Choose a unifying title color** that works over both zones — gold (`#ffd700`) or white often works best

**When NOT to use:** If all track covers share a single dominant color (all dark blue, all dark red, etc.), use the standard all-cars scene instead.

### Step 5: Crop background to 3000, then overlay title

gen_artwork.py will FAIL at the title overlay step (uses system python3 without PIL). The `_bg.png` IS created and upscaled — BUT it's 4096×4096, not 3000×3000. **Do NOT overlay on the 4096 canvas then crop** — the title will be cut off (text scales to ~3686px wide but the 3000 crop removes 548px from each side).

**Correct order: crop bg first, then overlay at 3000:**

```bash
# Step 5a: Crop the clean background to 3000×3000 first
ffmpeg -y -i /opt/data/music/artwork/covers/<FILENAME>_bg.png \
  -vf "crop=3000:3000:548:548" /tmp/<FILENAME>_bg_3000.png

# Step 5b: Overlay title at the CORRECT canvas size
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image /tmp/<FILENAME>_bg_3000.png \
  --title "<UNICODE_STYLED_TITLE>" \
  --color "#HEX" \
  --output /opt/data/music/artwork/covers/<FILENAME>.png

# Step 5c: Clean up temp file
rm /tmp/<FILENAME>_bg_3000.png
```

Use the album's designated color from the color reference table (e.g. `#ff0033` for BLΔCK MΔSS, `#00ccff` for VØIDLINES) or `--auto-color` for automatic contrast detection. Note what color was used in your response to the user.

**Important:** gen_artwork.py's auto-generated Unicode title is WRONG for existing VØIDRIDE albums. Always use the actual Unicode title from the SoundCloud page, not the ASCII-to-Unicode conversion gen_artwork.py produces internally.

### Step 6: Create Telegram preview

```bash
ffmpeg -y -i /opt/data/music/artwork/covers/<FILENAME>.png \
  -vf "scale=1500:1500:flags=lanczos" -q:v 2 \
  -update 1 /tmp/<ALBUM>_preview.jpg
```

Use `-update 1` flag to avoid the "no image sequence pattern" warning.

### Step 7: Send for user review

Send the preview JPG and offer to upload to SoundCloud as the new playlist cover. Summarize:
- What visual elements went into the cover (tied to the track analysis)
- The auto-color chosen for the title
- That waveform artwork will also be generated after publishing

### Step 8: Publish to SoundCloud (after user approval)

Once the user says "publish", "upload", or "looks good", push the cover live:

```bash
# 8a. Downscale to 2000x2000 PNG (under 10MB SC limit for playlist artwork)
ffmpeg -y -i /opt/data/music/artwork/covers/<FILENAME>.png \
  -vf "scale=2000:2000:flags=lanczos" \
  /tmp/<FILENAME>_sc.png

# 8b. Upload via multipart PUT raw API (refresh token first!)
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py list --limit 1

python3 -c "
import json, urllib.request

with open('/opt/data/home/.hermes/credentials/soundcloud_tokens.json') as f:
    tokens = json.load(f)

PLAYLIST_ID = <LIVE_ID>

with open('/tmp/<FILENAME>_sc.png', 'rb') as f:
    img_data = f.read()

boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
body = (
    f'--{boundary}\r\n'
    'Content-Disposition: form-data; name=\"playlist[artwork_data]\"; filename=\"cover.png\"\r\n'
    'Content-Type: image/png\r\n\r\n'
).encode() + img_data + f'\r\n--{boundary}--\r\n'.encode()

req = urllib.request.Request(
    f'https://api.soundcloud.com/playlists/{PLAYLIST_ID}',
    data=body, method='PUT',
    headers={
        'Authorization': f'OAuth {tokens[\"access_token\"]}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Accept': 'application/json; charset=utf-8',
    }
)
with urllib.request.urlopen(req, timeout=120) as resp:
    result = json.loads(resp.read().decode('utf-8'))
    print(f'Updated: {result[\"title\"]}')
    print(f'artwork_url: {result.get(\"artwork_url\", \"?\")}')
"
```

**Verify success:** The `artwork_url` in the response should have a NEW CDN hash (different from the old one). Re-fetch the playlist via `GET /playlists/{ID}` to confirm if the response shows the old URL — the CDN may return stale cache. A new hash confirms the upload worked.

### Step 9: Generate waveform artwork for playlist tracks

After the cover is published, generate waveform banners for all playlist tracks:

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --playlist-id <LIVE_ID> \
  --output-dir /opt/data/music/artwork/waveforms
```

See `waveform-artwork` skill for details. Always use `/opt/hermes/.venv/bin/python3` — system python3 lacks PIL.

## ⚠️ Clarification Guard

When the user says "redo this playlist" and provides a SoundCloud URL, they might mean:
- **Redo the cover art** (most common — they want fresh cover art)
- **Redo the music** (reproduce the tracks)
- **Both**

If ambiguous, ask: "Do you want me to redo the **cover art** or the **playlist tracks** (music)?"

The phrase "based on our art of the songs" = cover art redo, using the individual track covers as visual reference material.

## Album vs Track Cover Rules

| Aspect | This workflow (playlist/album cover) |
|--------|--------------------------------------|
| Scene | Multiple cars together, wide establishing shot |
| Title position | Centered (no `--bottom`, no `--top`) |
| Composition | Sweeping vista, all elements visible |
| Color | Use `--auto-color` or the album's designated color |
| Moon | Use real lunar phase for today (gen_artwork.py handles this) |

## Key Pitfalls

- **Crop background FIRST, then overlay title (CRITICAL):** gen_artwork.py outputs 4096×4096 bg. If you overlay on the 4096 canvas, the title scales to ~3686px wide and gets clipped when cropped to 3000. Always crop the bg to 3000 first, then overlay.
- **gen_artwork.py generates wrong Unicode titles:** Its internal ASCII-to-Unicode converter produces incorrect titles (e.g. `ł₦†ɆƦłØƦƦɆ₦ϾɆ` instead of `ꐃ₦₮ɄɌꐃɄƦɌɆ₦₵Ɇᵾ₦`). Always pass the actual SoundCloud Unicode title to overlay-title.py.
- **Venice upscale can timeout at 120s:** Retry with a 300s manual Python call or fall back to ffmpeg Lanczos upscaling with unsharp filter.
- **Stale playlist IDs:** The SoundCloud shortlink may redirect to a stale ID. Always fetch `/me/playlists` to get the live ID before generating or publishing.
- **Token expiry:** Raw API calls (urllib) don't auto-refresh. Run `soundcloud_api.py list --limit 1` first to refresh the token.
- **gen_artwork.py skips existing files:** No `--force` flag. Delete `_bg.png` and `.png` from `covers/` and `waveforms/` before regenerating.
- **Title overlay needs venv Python:** System python3 lacks PIL. Always use `/opt/hermes/.venv/bin/python3` for overlay-title.py.
- **Playlist artwork >10MB fails:** Downscale to 2000×2000 PNG before uploading. JPG can silently fail for playlist artwork — use PNG.
- **Waveform generation needs venv Python:** Same PIL issue. Always use `/opt/hermes/.venv/bin/python3` for gen_waveform_art.py.
