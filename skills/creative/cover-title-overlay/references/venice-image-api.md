# Venice Image Generation API

## Endpoint
```
POST https://api.venice.ai/api/v1/image/generate
```
Note: singular "image", NOT "images/generate".

## Authentication
```
Authorization: Bearer $VENICE_API_KEY
Content-Type: application/json
```

## Current Model (August 2026)
**`flux-2-max`** — the active image generation model.

### Deprecated Models
- `ideogram-v4` — returns 404 Not Found. Do NOT use.
- `flux-dev` — returns 404 Not Found. Do NOT use.
- `stable-diffusion-3.5-large` — returns 404 Not Found. Do NOT use.

## Request Format
```json
{
  "model": "flux-2-max",
  "prompt": "Dark atmospheric cinematic 35mm film photography...",
  "width": 1024,
  "height": 1024,
  "negative_prompt": "text, words, letters, writing, typography, watermark"
}
```

### Size Constraints
- **Maximum: 1024×1024** — larger dimensions return 400 Bad Request
- Always generate at 1024×1024, then upscale to 3000×3000 with ffmpeg
- Do NOT use `aspect_ratio` parameter — use explicit `width` and `height`

## Response Format
```json
{
  "id": "...",
  "images": ["<base64_encoded_string>"],
  "request": {...},
  "timing": {...}
}
```

### ⚠️ NOT the audio format
The image endpoint returns `images` (array of base64 strings), NOT `data` (array of objects with `b64_json`). This is different from the Venice audio endpoints which use `data[].b64_json`.

Decode with: `base64.b64decode(result["images"][0])`

## Upscaling Pipeline
```bash
# Generate at 1024x1024, then upscale:
ffmpeg -y -i raw_1024.png \
  -vf "scale=3000:3000:flags=lanczos,unsharp=5:5:0.8:5:5:0" \
  -c:v png output_3000.png
```

The unsharp filter is essential — raw Lanczos from 1024 to 3000 looks soft without it.

## Error Codes
- **400 Bad Request** — usually means dimensions too large (max 1024×1024) or invalid model name
- **401 Unauthorized** — invalid or missing API key
- **404 Not Found** — deprecated/removed model name (ideogram-v4, flux-dev, etc.)

## Python Example
```python
import json, base64, urllib.request

API_KEY=os.environ.get("VENICE_API_KEY", "")
url = "https://api.venice.ai/api/v1/image/generate"

payload = json.dumps({
    "model": "flux-2-max",
    "prompt": "dark atmospheric photo, no text no words",
    "width": 1024,
    "height": 1024,
    "negative_prompt": "text, words, letters, writing"
}).encode("utf-8")

req = urllib.request.Request(url, data=payload, headers={
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}, method="POST")

with urllib.request.urlopen(req, timeout=120) as resp:
    result = json.loads(resp.read().decode("utf-8"))
    img_bytes = base64.b64decode(result["images"][0])
    with open("output.png", "wb") as f:
        f.write(img_bytes)
```