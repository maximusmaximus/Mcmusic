---
name: waveform-artwork
description: Generate panoramic scene-extension banners (1240x400) from SoundCloud cover art using Venice AI image editing.
version: 1.0.0
tags: [soundcloud, artwork, waveform, venice, image-generation, banner, music]
---

# Waveform Artwork Generator

Generate panoramic scene-extension banners for SoundCloud tracks by remixing each track's existing cover art into a wide cinematic scene.

## ⚠️ CRITICAL: How To Use This Skill

**YOU MUST use the `terminal` tool** to run the script. Do NOT use `process` — image editing can take 10-30 seconds per track.

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  ARGS [OPTIONS]
```

**⚠️ Use `/opt/hermes/.venv/bin/python3` — NOT `python3`.** The system Python does NOT have Pillow installed. Running with `python3` crashes with `ModuleNotFoundError: No module named 'PIL'` at the crop step. Always use the venv Python.

## Pipeline

1. **Input** — Takes the clean, text-free background artwork (`_bg.png`) at cover generation time, or a track cover image/URL.
2. **Edit** — Sends the artwork directly to Venice `/api/v1/image/edit` with a scene-extension prompt and `aspect_ratio: "16:9"` — the edit model **sees** the original cover and expands it into a wide panoramic scene, preserving colors, mood, and atmosphere without text artifacts.
3. **Crop** — Crops and resizes to exactly `1240x400` using PIL LANCZOS resampling.
4. **Save** — Saves to `waveforms/{TRACK}_waveform.png`.

> **Workflow Rule**: Always generate waveform banners **BEFORE** title text overlay is applied to the cover. This guarantees zero text/typography artifacts on the banner. Fallback text-to-image generation is strictly disabled.

## Commands

### Generate waveform art directly from a local cover image

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --image /opt/data/music/artwork/albums/<album>/01_track_bg.png \
  --title "TRACK TITLE" \
  --output-dir /opt/data/music/artwork/waveforms
```

**⚠️ Only use local files when the album has NOT been published yet.** For already-published albums, the local cover directory may have different artwork than what's on SoundCloud. Follow the [Published Album Workflow](#-published-album-workflow-local-covers-may-be-stale) below instead.

**⚠️ Venice-upscaled PNGs (4096×4096, ~27MB) cause 413 errors** — gen_artwork.py produces upscaled `_bg.png` files that are too large for Venice's image edit API. Pre-process before passing to `--image`:

```bash
/opt/hermes/.venv/bin/python3 -c "
from PIL import Image
img = Image.open('/path/to/cover_bg.png')
img = img.convert('RGB')         # RGBA unsupported by JPEG
img.thumbnail((1500, 1500), Image.LANCZOS)
img.save('/tmp/waveform_source.jpg', 'JPEG', quality=92)
print(f'Saved {img.size} RGB JPEG')
"

/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --image /tmp/waveform_source.jpg \
  --title "TRACK TITLE" \
  --output-dir /opt/data/music/artwork/waveforms

rm -f /tmp/waveform_source.jpg
```

### Generate waveform art for a SoundCloud playlist/album

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --playlist-id 2287519329 \
  --output-dir /opt/data/music/artwork/waveforms
```

### Generate for a single SoundCloud track

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --track-id 2386286106 \
  --output-dir /opt/data/music/artwork/waveforms
```

### Force regeneration (overwrite existing)

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --playlist-id 2287519329 \
  --output-dir /app/music/artwork/waveforms \
  --force
```

### Use a different image model

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --playlist-id 2287519329 \
  --image-model fluently-xl \
  --output-dir /app/music/artwork/waveforms
```

## Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--playlist-id` | One of playlist-id or track-id | — | SoundCloud playlist/album ID (repeatable) |
| `--track-id` | One of playlist-id or track-id | — | SoundCloud track ID (repeatable) |
| `--output-dir` | No | `/app/music/artwork/waveforms` | Output directory for generated PNGs |
| `--prompt` | No | Built-in scene extension prompt | Custom prompt for the edit model |
| `--force` | No | `false` | Regenerate even if file exists |

## How It Works

The script uses Venice's **image edit** endpoint (`/api/v1/image/edit`) which accepts an input image and a text prompt. Unlike text-to-image generation (which requires describing the art from scratch), the edit model directly **sees** the cover art and remixes it:

- **Input**: Cover art URL from SoundCloud (passed directly — no download needed)
- **Aspect ratio**: `16:9` → Venice outputs 1280×720
- **Crop**: Center-bottom band cropped and resized to `1240x400` via PIL LANCZOS

## Output

- **Filename format**: `{TRACK_TITLE}_waveform.png` (uppercase, underscores)
- **Dimensions**: `1240x400` pixels
- **Format**: PNG, high quality
- **Example**: `UNDERCROFT_waveform.png`, `GHOSTSHIFT_waveform.png`

### JSON stdout output

```json
{
  "success": true,
  "total": 5,
  "generated": 5,
  "skipped": 0,
  "errors": 0,
  "output_dir": "/app/music/artwork/waveforms",
  "results": [
    {
      "title": "UNDERCROFT",
      "track_id": 2386286106,
      "file": "/app/music/artwork/waveforms/UNDERCROFT_waveform.png",
      "status": "ok",
      "size_bytes": 1234567
    }
  ]
}
```

## OUTPUT DELIVERY RULES

1. **Do NOT paste the JSON output** in the chat — parse it and respond naturally
2. **Do NOT show the terminal command, script logs, or code** to the user
3. After the script finishes, write a brief, conversational summary:
   - How many waveforms were generated
   - Where they were saved
   - Any errors encountered
4. If asked, mention which image model and vision model were used

## ⛔ Known Pitfalls

| Constraint | Details |
|-----------|---------|
| PIL / venv Python | **CRITICAL**: System `python3` does NOT have Pillow. The script crashes with `ModuleNotFoundError: No module named 'PIL'` at the crop step. Always use `/opt/hermes/.venv/bin/python3` to run this script. This applies to ALL example commands in this skill. |
| Rate limiting | Venice may rate-limit on rapid-fire requests — script has 1s delay between tracks |
| SoundCloud auth | Tokens may expire — script auto-refreshes, but if refresh fails, re-run OAuth flow |
| No cover art | If a track has no artwork, falls back to a generic dark electronic aesthetic prompt |
| Generation time | Each track takes ~20-40 seconds (edit + crop) |
| **Local covers ≠ published covers** | The local release directory at `/opt/data/music/releases/<album>/covers/` may have DIFFERENT cover art than what's published on SoundCloud. This happens when covers were regenerated locally after the initial SC upload, or when cover generation and SC publish happened at different times. **Never trust local covers for already-published albums.** Always verify against SC's actual artwork before generating waveforms. |
| **Venice-upscaled PNGs cause 413** | Venice-upscaled `_bg.png` files from gen_artwork.py are 4096×4096, ~27MB. Passing these to `--image` causes `413 Request Entity Too Large` on Venice's image edit API. **Fix**: Convert RGB, thumbnail to ≤1500px, save as JPEG before passing to gen_waveform_art.py. |

## 🚨 Published Album Workflow (Local Covers May Be Stale)

When generating waveform covers for an album that's **already published on SoundCloud**, the local `/opt/data/music/releases/<album>/covers/` directory may have different/outdated artwork than what's actually on SC. **Always get the true covers from SoundCloud directly.**

### Step 1: Find Track IDs

```bash
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py list --limit 50 --json
```

Look for the tracks belonging to the album. Note their `id` fields.

### Step 2: Get Artwork URLs from SC API

```bash
# Read the OAuth token
TOKEN=*** -c "import json; print(json.load(open('/root/.hermes/credentials/soundcloud_tokens.json'))['access_token'])")

# For each track ID, get the artwork_url
curl -s -H "Authorization: OAuth $TOKEN" \
  "https://api.soundcloud.com/tracks/<TRACK_ID>" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('artwork_url','N/A'))"
```

The response contains an `artwork_url` like `https://i1.sndcdn.com/artworks-XXXXX-large.jpg`.

### Step 3: Download at Adequate Resolution

SoundCloud serves artwork at suffixes:
- `-large.jpg` — ~100×100 (thumbnail, too small for Venice image edit)
- `-t500x500.jpg` — ~500×500 (good enough for scene extension)
- `-original.jpg` — full resolution (may not exist or be large)

Replace `-large` with `-t500x500` in the URL to get usable resolution:

```bash
ARTWORK_URL=***  # from Step 2
FULL_URL="${ARTWORK_URL/-large/-t500x500}"
curl -sL "$FULL_URL" -o /tmp/artwork/TRACK_NAME.jpg
```

### Step 4: Generate Waveforms from Downloaded Artwork

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --image /tmp/artwork/TRACK_NAME.jpg \
  --title "TRACK NAME" \
  --output-dir /opt/data/music/waveforms
```

### Step 5: Copy to Release Covers Directory

```bash
cp /opt/data/music/waveforms/*_waveform.png /opt/data/music/releases/<album>/covers/
```

## Dependencies

- `requests` — HTTP client (pre-installed in venv)
- `Pillow` (PIL) — Image processing for crop/resize (**installed in venv only** — system python3 lacks it)
- Venice API key — Set via `VENICE_API_KEY` environment variable
- SoundCloud OAuth tokens — Must be present at `~/.hermes/credentials/soundcloud_tokens.json`

**Always run with `/opt/hermes/.venv/bin/python3`** — never system `python3`.
