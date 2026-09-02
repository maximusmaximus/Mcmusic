---
name: covers-notext
description: Remove text from cover art images using Venice AI image editing API (gpt-image-2-edit at 4K resolution). Creates clean no-text versions in covers-notext directory. Also supports pixelation fallback when API is unavailable.
tags: [cover-art, text-removal, inpainting, venice-api, image-editing]
---

# Covers No-Text: Remove Text from Cover Art

Remove text (titles, labels, watermarks) from album cover images using Venice AI's
image editing API. Creates clean no-text versions in `/opt/data/music/artwork/covers-notext/`.

## Quick Start

```bash
# Process a single cover (recommended model: gpt-image-2-edit)
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/covers-notext/scripts/remove_text.py \
  /opt/data/music/artwork/covers/Midnight_Protocol.png \
  /opt/data/music/artwork/covers-notext/Midnight_Protocol.png \
  gpt-image-2-edit

# Scale result to 3000x3000 if needed — use Venice upscale API (NOT local ffmpeg)
# See gen_artwork.py upscale_if_needed() or call directly:
# POST https://api.venice.ai/api/v1/image/upscale
# body: {"image": "<base64>", "scale": 2, "creativity": 0.01}
# Response: raw image/png binary
```

## Method: Venice AI Inpaint (Primary)

Uses Venice's `/image/edit` endpoint to intelligently remove text while preserving
and filling in the background art contextually.

### Model Selection

| Model | Resolution | Quality | Speed | Notes |
|-------|-----------|---------|-------|-------|
| `gpt-image-2-edit` | 2880×2880 (4K) | **Best** | ~30s | **DEFAULT** — high quality, good inpainting |
| `firered-image-edit` | 1024×1024 (1K) | Good | ~15s | Fast but low resolution — needs upscaling |
| `flux-2-max-edit` | Varies | Good | ~45s | Alternative |
| `qwen-image-2-edit` | Varies | Good | ~20s | Alternative |

⚠️ **`resolution: "4K"` is only supported by some models** (gpt-image-2-edit works).
`firered-image-edit` returns 400 error for resolution parameter — omit it.

### API Details

**Endpoint:** `POST https://api.venice.ai/api/v1/image/edit`

**Request:**
```json
{
  "model": "gpt-image-2-edit",
  "prompt": "Remove all text, letters, typography, and words from this image. Fill in those areas with the surrounding background artwork and visual elements so it looks natural and seamless, as if the text was never there. The result should be a clean image with no text at all — just the artwork.",
  "image": "<base64-encoded-image>",
  "aspect_ratio": "1:1",
  "safe_mode": false,
  "resolution": "4K"
}
```

**Response:** Binary PNG image data (NOT JSON).

**Key parameters:**
- `safe_mode`: Set to `false` for dark/edgy album art (VØIDRIDE covers trigger filters with `true`)
- `resolution`: `"4K"` for 2880×2880 output (gpt-image-2-edit only). Omit for models that don't support it
- `quality`: `"high"` — ONLY for gpt-image-2-edit (gpt-image-1-5-edit also supports it). Other models reject it
- `aspect_ratio`: `"1:1"` for square covers, `"auto"` to inherit from source

### Important Notes

- **Response is binary**, not JSON — write response content directly to file
- **File size limit**: Input image must be <25MB (3000×3000 PNG ≈ 10-15MB, base64 ≈ 14-20MB)
- **For large source images**: Consider downscaling to 2048×2048 before sending to reduce payload
- **Rate limit**: 4-second delay between requests to avoid 429 errors
- **Timeout**: Set to 120-300 seconds — 4K edits take 30-60s
- **PIL dependency**: Always use `/opt/hermes/.venv/bin/python3` — system python3 lacks Pillow

### Full Processing Pipeline

```
Source (3000×3000) → [optional: scale to 2048] → Venice /image/edit → 
  result (2880) → ffmpeg scale to 3000 → final output
```

```bash
# Step 1: Optional — downscale for faster upload
ffmpeg -y -i input.png -vf "scale=2048:2048:flags=lanczos" input_2048.png

# Step 2: Remove text via Venice API
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/covers-notext/scripts/remove_text.py \
  input_2048.png output.png gpt-image-2-edit

# Step 3: Scale to final resolution
ffmpeg -y -i output.png -vf "scale=3000:3000:flags=lanczos" output_3000.png
```

## Method: Pixelation Fallback (Offline)

When the Venice API is unavailable, use local pixelation with colors sampled from the artwork.

**Script:** `scripts/pixelate_notext.py`

```bash
# Single image
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/covers-notext/scripts/pixelate_notext.py \
  /opt/data/music/artwork/covers/Midnight_Protocol.png \
  /opt/data/music/artwork/covers-notext/Midnight_Protocol.png \
  32   # pixel size (default: 32)

# Batch all covers
python3 -c "
import sys; sys.path.insert(0, '/opt/hermes/.venv/lib/python3.13/site-packages')
sys.path.insert(0, '/opt/data/skills/creative/covers-notext/scripts')
from pixelate_notext import batch_process
batch_process('/opt/data/music/artwork/covers', '/opt/data/music/artwork/covers-notext', pixel_size=32)
"
```

**How it works:**
- Detects text region via sliding-window brightness scanning (bottom 30% of image)
- Extracts a 10-color palette from the artwork via bucket quantization
- Fills text region with configurable pixel blocks in matching colors
- 12% dark depth blocks, 5% bright glitch blocks, 2px dark grid lines between pixels
- Deterministic output (seeded random)

## Batch Processing All Covers

```bash
# Venice API method (preferred) — process each cover:
for f in /opt/data/music/artwork/covers/*.png; do
    fname=$(basename "$f")
    [[ "$fname" == *_space.png || "$fname" == *_sc.png ]] && continue
    [ -f "/opt/data/music/artwork/covers-notext/$fname" ] && continue
    
    /opt/hermes/.venv/bin/python3 /opt/data/skills/creative/covers-notext/scripts/remove_text.py \
        "$f" "/opt/data/music/artwork/covers-notext/$fname" gpt-image-2-edit
    
    # Scale to 3000 if needed
    /opt/hermes/.venv/bin/python3 -c "
from PIL import Image
img = Image.open('/opt/data/music/artwork/covers-notext/$fname')
if img.size != (3000, 3000):
    img = img.resize((3000, 3000), Image.LANCZOS)
    img.save('/opt/data/music/artwork/covers-notext/$fname')
"
    sleep 4  # Rate limit
done
```

## References

- **`references/venice-image-edit-api.md`** — Full API reference with all tested models, parameters, pitfalls, and text-removal prompts

## Scripts

- **`scripts/remove_text.py`** — Venice AI text removal (primary method). Auto-downscales large inputs, auto-upscales results to 3000×3000
- **`scripts/pixelate_notext.py`** — Local pixelation fallback (offline). Art-matched palette, configurable pixel size, batch mode

## Pitfalls

1. **Venice API returns binary**, not JSON — don't try to parse response as JSON
2. **`resolution: "4K"` only works with gpt-image-2-edit** — `firered-image-edit` returns 400 error
3. **`quality` param only for gpt-image models** — other models reject it with 400
4. **Rate limiting** — 4-second delay between requests to avoid 429
5. **Large payloads** — 3000×3000 PNG → ~15MB base64. Script auto-downscales to 2048; can disable if needed
6. **Not all edits are perfect** — AI may leave artifacts or partially remove text. Verify visually
7. **PIL dependency** — use `/opt/hermes/.venv/bin/python3` for Pillow. System python3 lacks it
8. **Venice endpoint** — `/image/edit` (singular "image"), NOT `/images/edit`
9. **`safe_mode: false` is essential** for dark album art — VØIDRIDE covers trigger content filters with `true`
10. **gpt-image-2-edit returns 2880×2880** at 4K, NOT 3000×3000 — script auto-scales to 3000