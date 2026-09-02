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

### Generate waveform art directly from clean background image (Recommended)

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --image /opt/data/music/artwork/albums/<album>/01_track_bg.png \
  --title "TRACK TITLE" \
  --output-dir /opt/data/music/artwork/waveforms
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

## Dependencies

- `requests` — HTTP client (pre-installed in venv)
- `Pillow` (PIL) — Image processing for crop/resize (**installed in venv only** — system python3 lacks it)
- Venice API key — Set via `VENICE_API_KEY` environment variable
- SoundCloud OAuth tokens — Must be present at `~/.hermes/credentials/soundcloud_tokens.json`

**Always run with `/opt/hermes/.venv/bin/python3`** — never system `python3`.
