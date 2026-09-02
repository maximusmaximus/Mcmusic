# Venice Image Edit API Reference

Extracted from Venice API docs and tested 2026-08-25.

## Endpoints

### POST /image/edit
Edit one image with a text prompt (inpaint, restyle, remove elements).

```bash
curl https://api.venice.ai/api/v1/image/edit \
  -H "Authorization: Bearer $VENICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2-edit",
    "prompt": "Remove all text from this image",
    "image": "<base64>",
    "aspect_ratio": "1:1",
    "safe_mode": false,
    "resolution": "4K"
  }' \
  -o output.png
```

**Response:** Binary PNG (or JPEG/WebP depending on `output_format`). NOT JSON.

### POST /image/multi-edit
Combine multiple images with a single prompt. Uses `modelId` not `model`. Limited to model-specific max input images.

### POST /image/upscale
Upscale 2x or 4x. Returns PNG. Cap: 16,777,216 pixels after scaling.

### POST /image/background-remove
Produce transparent cutout. Returns PNG.

## Edit-Capable Models (from GET /models?type=inpaint)

Tested and verified:
- **gpt-image-2-edit** — Best quality, supports `resolution: "4K"` → 2880×2880. **DEFAULT for covers-notext**
- **firered-image-edit** — Fast, 1K only (1024×1024). Does NOT support `resolution` param (400 error)
- **flux-2-max-edit** — Good quality alternative
- **qwen-image-2-edit** — Good alternative
- **qwen-image-3-edit** — Latest Qwen
- **seedream-v5-pro-edit** — High-end
- **grok-imagine-edit** — Grok-based
- **nano-banana-2-edit** / **nano-banana-pro-edit** — Lightweight

Full list from API (Aug 2026): firered-image-edit, qwen-edit-uncensored, grok-imagine-edit, grok-imagine-quality-edit, grok-imagine-image-2-0-edit, qwen-image-2-edit, qwen-image-2-pro-edit, wan-2-7-pro-edit, flux-2-max-edit, gpt-image-2-edit, gpt-image-1-5-edit, nano-banana-2-edit, nano-banana-pro-edit, nano-banana-2-lite-edit, luma-uni-1-edit, luma-uni-1-max-edit, seedream-v5-lite-edit, seedream-v5-pro-edit, seedream-v4-edit, qwen-image-3-edit

## Key Parameters

| Param | Notes |
|-------|-------|
| `model` | Default `firered-image-edit`. Prefer `gpt-image-2-edit` for quality |
| `prompt` | Required, ≤32768 chars. Short & specific works best |
| `image` | Required. Base64 string, file upload, or HTTPS URL. <25MB |
| `aspect_ratio` | `auto`, `1:1`, `3:2`, `16:9`, `21:9`, `9:16`, `2:3`, `3:4`, `4:5` |
| `resolution` | `"1K"`, `"2K"`, `"4K"`. **Only some models support this** — gpt-image-2-edit does, firered-image-edit does NOT (400 error) |
| `quality` | `"high"`, `"medium"`, `"low"`. **Only gpt-image models** — others reject with 400 |
| `safe_mode` | Default `true`. Set `false` for dark/edgy album art — VØIDRIDE covers trigger filters |
| `output_format` | `jpeg`, `png`, `webp`. Default: PNG for 1K, JPEG for 2K/4K |

## Pitfalls Discovered During Testing

1. **Response is binary image data**, NOT JSON. Don't parse as JSON.
2. **`resolution: "4K"` causes 400 on firered-image-edit** — only use with gpt-image models.
3. **`quality: "high"` causes 400 on firered-image-edit** — only for gpt-image models.
4. **Large images (3000×3000 PNG ≈ 15MB base64)** — downscale to 2048 before sending to reduce payload and avoid timeout.
5. **gpt-image-2-edit returns 2880×2880 at 4K** — not exactly 3000, so always upscale to 3000 with ffmpeg/PIL.
6. **firered-image-edit returns 1024×1024** — much lower quality, only use for quick previews.
7. **`safe_mode: true`** will blur or reject dark album art — always set `false` for music covers.
8. **Rate limit: 4-second delay** between requests to avoid 429 errors.
9. **Timeout**: Set 120-300s for 4K edits.
10. **Endpoint path**: `/image/edit` (singular), NOT `/images/edit`.

## Text Removal Prompt

For cover art text removal, this prompt works well:

```
Remove all text, letters, typography, and words from this image. Fill in those areas with the surrounding background artwork and visual elements so it looks natural and seamless, as if the text was never there. The result should be a clean image with no text at all — just the artwork.
```