# Album Cover Art Generation for SoundCloud Playlists

## Two-Step Cover Pattern (Recommended)

Ideogram-v4 often mangles Unicode characters in generated text. The reliable approach is:

1. **Generate background only** — prompt ideogram-v4 with an extended negation ("NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNAGE, NO SIGNS, NO CAPTIONS") and a space/mood description. Short negation lists like "no text" alone are often insufficient — ideogram-v4 sometimes still renders text artifacts like "Image blocked by..." even with "no text, no letters". Use the full list.
2. **Overlay title text** — use the `cover-title-overlay` skill script for Open Sans Bold rendering with neon glow + drop shadow

```bash
# Step 2: Overlay title (after generating background with Venice API)
python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image cover_bg.png \
  --title "Ɇ₦†Ʀɏ₩ØɄ₦Đ" \
  --color "#ff0044" \
  --output final_cover.png \
  --bottom     # VØIDRIDE default: title at bottom for scene covers

# Optional flags:
#   --top         Title at top (8% from top edge)
#   --bottom      Title at bottom (8% from bottom edge) — VØIDRIDE default
#   --no-glow     Skip neon glow effect
#   --no-shadow   Skip drop shadow
```

The overlay script handles font scaling (fills ~90% width), vertical centering, neon glow (3 radii), angled drop shadow (3 layers), and white-hot core highlight. Font is Open Sans Bold at `/opt/data/.fonts/OpenSans-Bold.ttf`. See the `cover-title-overlay` skill for full details.

## Model Selection

- **ideogram-v4** — DEFAULT for cover art ($0.06/image, best text/logo rendering, best poses, least content filtering)
- **gpt-image-2** — most realistic ($0.27-0.84)
- **seedream-v5-pro** — alternative ($0.06-0.11)
- **flux-2-pro** — simple compositions only ($0.03)

Full model list: `curl -s "https://api.venice.ai/api/v1/models?type=image" -H "Authorization: Bearer $VENICE_API_KEY"`

## VØIDRIDE Cover Art Style

Neon Unicode-styled album title text in **Open Sans Bold** (not Helvetica — Open Sans renders Unicode characters better), centered and filling the image, on a deep space abstract background. Each album gets a distinct neon color:

| Album | Neon Color (hex) |
|-------|-----------------|
| ₴ØɄ₦ĐĐɆ₴łǤ₵ | `#00ff44` green |
| Ʉ₦ĐɆɌ₱Δ$$ | `#ff8800` amber/orange |
| ØƦłǤł₦$ | `#ffd700` gold |
| ĐɆ$ɆƦ† VØID | `#ffaa00` sand/amber |
| NΞØN ₳U฿ | `#00ffcc` cyan/electric green |
| SÉANCE ◊TEREO | `#aa00ff` purple |
| VØIDLINES | `#00ccff` ice blue |
| BLΔCK MΔSS | `#ff0033` crimson |

Per-track color/car themes also available in `master-producer/references/venice-image-api.md`.

## API Pattern (Venice Image API)

```python
import json, base64, os, subprocess, urllib.request

API_KEY = os.environ.get("VENICE_INFERENCE_KEY", "")
API_URL = "https://api.venice.ai/api/v1/image/generate"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# Step 1: Generate BACKGROUND ONLY (no text)
prompt = (
    "Deep space nebula background with swirling neon crimson cosmic dust, "
    "dark atmospheric void, stars, digital art style, "
    "no text, no letters, no characters, no words, no logos"
)

payload = {
    "model": "ideogram-v4",
    "prompt": prompt,
    "aspect_ratio": "1:1",  # REQUIRED — do NOT use width/height params
    "seed": hash("BLΔCK MΔSS") % 99999,
}

req = urllib.request.Request(API_URL, json.dumps(payload).encode(), headers=HEADERS)
req.add_header("Content-Type", "application/json")
resp = urllib.request.urlopen(req, timeout=120)
data = json.loads(resp.read().decode())

# Decode base64 image (Venice returns WebP regardless of extension)
img_bytes = base64.b64decode(data["images"][0])
with open("/tmp/cover_raw.webp", "wb") as f:
    f.write(img_bytes)

# Convert WebP → PNG
subprocess.run([
    "ffmpeg", "-y", "-i", "/tmp/cover_raw.webp",
    "-c:v", "png", "/tmp/cover_bg.png"
], check=True)

# Step 2: Overlay title (separate script)
subprocess.run([
    "python3", "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py",
    "--image", "/tmp/cover_bg.png",
    "--title", "BLΔCK MΔSS",
    "--color", "#ff0033",
    "--output", "/tmp/final_cover.png"
], check=True)
```

**Important:** PIL is NOT available in the execute_code sandbox. Run PIL overlay code via the hermes_tools `terminal()` command or the dedicated `overlay-title.py` script. The Venice API key is also unavailable in execute_code — use `terminal()` for image generation scripts too.

## Critical API Notes

1. **Use `aspect_ratio: "1:1"`**, NOT `width`/`height` params — passing numeric dimensions causes HTTP 400
2. **Do NOT pass `"n": 1` or `"num_images": 1`** — causes HTTP 400 error (API generates 1 image by default)
3. **Production covers should be 3000×3000** — scale up from API output for maximum quality. SoundCloud requires 800×800 minimum but VØIDRIDE covers should be 3000×3000. Scale with: `ffmpeg -y -i raw.webp -vf "scale=3000:3000:force_original_aspect_ratio=decrease,pad=3000:3000:(ow-iw)/2:(oh-ih)/2" bg.png`
4. **Venice returns WebP** — must convert to PNG/JPEG for SoundCloud upload
5. **Always prompt "no text, no letters, no characters"** for background generation — overlay titles separately via the `cover-title-overlay` skill

## Upload to SoundCloud Playlist

Scale to 800×800 minimum and upload:

```bash
ffmpeg -y -i final_cover.png -vf "scale=800:800" cover_800.png
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py \
  update --track-id PLAYLIST_ID --artwork cover_800.png
```

For playlists, use `playlist[artwork_data]` multipart PUT (NOT `track[artwork_data]` — that 500s). See the main SKILL.md "Add Artwork to Playlist" section for the Python pattern.

## SoundCloud Unicode Permalink Quirk

SoundCloud permalinks strip many Unicode characters: Δ→d, Ø→empty, $→stripped. Track **display titles** preserve Unicode correctly, but URL slugs look different. Always reference tracks by `track_id`, not permalink.

## Inline PIL Code (for reference / custom rendering)

For cases where you need custom rendering beyond what `overlay-title.py` provides, here's the PIL approach that the script implements:

```python
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/opt/data/.fonts/OpenSans-Bold.ttf"

# Scale font to fill ~90% of image width
target_width = int(w * 0.90)
font_size = 24
while text_w < target_width:
    font_size += 2
    # measure...
while text_w > target_width:
    font_size -= 1
    # measure...

# Angled drop shadow (3 layers for softness)
for ldx, ldy, la in [(9, 9, 80), (7, 7, 150), (6, 6, 220)]:
    draw.text((x+ldx, y+ldy), title, font=font, fill=(0, 0, 0, la))

# Neon glow (3 radii: 5px/25alpha, 3px/50alpha, 2px/90alpha)
for radius, alpha in [(5, 25), (3, 50), (2, 90)]:
    for dx in range(-radius, radius+1):
        for dy in range(-radius, radius+1):
            if dist <= radius:
                draw.text((x+dx, y+dy), title, font=font, fill=(*color, alpha))

# Main text (max saturation)
draw.text((x, y), title, font=font, fill=(*color, 255))

# White-hot core highlight
bright_core = tuple(min(255, c+130) for c in color) + (120,)
draw.text((x-1, y-1), title, font=font, fill=bright_core)
```