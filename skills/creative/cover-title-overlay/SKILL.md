---
name: cover-title-overlay
description: Overlay Unicode-styled song titles onto cover art images with multi-font Unicode fallback (Segoe UI Symbol / Historic / Black / DejaVu Sans), scaled to fill width, neon glow, angled drop shadow, and CMY neon palettes. Supports --bottom (VØIDRIDE scene covers), --top, --auto-color, and centered positioning. Two-step process — generate background via Venice AI flux-2-max (no text), then overlay title.
tags: [cover-art, title-overlay, neon-text, unicode, album-art, cmy-palette]
---

# Cover Title Overlay

Overlay a Unicode-styled song title onto a cover art image (background only, no text).
The title is scaled horizontally to fill ~90% of the image width. Default position is
centered vertically, but for VØIDRIDE scene covers the preferred position is **bottom**
(`--bottom` flag) — keeps the title clear of the central scene action.

**Unicode Font Fallback Stack**: Automatically searches and chains `SegoeUISymbol.ttf`, `SegoeUIHistoric.ttf`, `SegoeUI-Black.ttf`, and `DejaVuSans-Bold.ttf` to guarantee 100% glyph coverage for all exotic Unicode code points (Coptic, Cyrillic, Latin Extended-B, Currency signs, Math symbols) with zero `.notdef` / tofu boxes.

**CMY Neon Palette**: Supports high-voltage neon colors including Electric Cyan (`#00F0FF`), Hyper Magenta (`#FF007F`), Acid Yellow (`#FAFF00`), Cyan Mint (`#00FFA3`), Laser Fuchsia (`#FF10F0`), and Electric Volt (`#FFE600`), or automatic contrast matching via `--auto-color`.

## Script Usage

```bash
# High-Voltage Electric Cyan (at bottom)
python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image background.png \
  --title "Ⱡł₦Ɇ†łϾ ØVɆƦĐƦłVɇ" \
  --color "#00F0FF" \
  --bottom

# Hyper Magenta with auto-color matching
python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image background.png \
  --title "Ɇ₦†Ʀɏ₩ØɄ₦Đ" \
  --auto-color \
  --bottom

# Acid Yellow centered
python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image background.png \
  --title "฿ⱠΔϾҞ†ØƤ" \
  --color "#FAFF00"
```

## Arguments

| Arg | Required | Description |
|-----|----------|-------------|
| `--image` | Yes | Path to background image (PNG/WebP/JPEG) |
| `--title` | Yes | Unicode-styled title text to overlay |
| `--color` | No | Neon color in hex (e.g. `#00F0FF`, `#FF007F`, `#FAFF00`) or preset name |
| `--auto-color`| No | Automatically detect background tones and select highest-contrast CMY neon color |
| `--output` | No | Output path (default: `<input>-titled.png`) |
| `--bottom` | No | Position title at bottom (8% from bottom — recommended for VØIDRIDE scenes) |
| `--top` | No | Position title at top (8% from top) |
| `--no-glow`| No | Skip neon glow effect |
| `--no-shadow`| No | Skip drop shadow effect |
| `--no-glow` | No | Skip neon glow effect |
| `--no-shadow` | No | Skip angled drop shadow |
| `--top` | No | Position title at top (8% from top edge) |
| `--bottom` | No | Position title at bottom (8% from bottom edge) |

## Title Positioning

By default the title is centered vertically. Use `--top` or `--bottom` to reposition:

- `--top` — Title at 8% from the top edge (good for scene covers where the bottom has detail)
- `--bottom` — Title at 8% from the bottom edge (VØIDRIDE default — keeps the title clear of the central action)
- No flag — Title centered vertically (good for abstract/nebula backgrounds)

The user's preference for VØIDRIDE track covers is **`--bottom`** (the scene art — car, spaceship, silhouette — lives in the center; title anchored at bottom).

## Album vs. Track Covers (Important)

VØIDRIDE cover art has two distinct generation patterns:

**Track covers** — per-track scene art. One car (unique per track), the fedora/kimono/katana man, per-track sculptures, `--bottom` title position. The scene focuses on a single car as the hero element.

**Album covers** — the playlist/album-level art. Use **centered** title position (no `--bottom`, no `--top`). The user's consistent preference is for album covers to feel like "the whole world" — track covers are close-ups of individual moments within that world. There are three established album cover composition styles:

1. **All-cars-together** (most common, user's default): All track cars parked together in a loose diagonal formation on wet asphalt, each facing different directions, headlights cutting through fog/smoke. Include the fedora/trench-coat + katana man standing as a silhouette. A towering full moon should dominate the sky, enormous and looming. Title centered vertically. Example prompt pattern: *"Six distinctive nightride cars parked together on wet asphalt in a loose diagonal formation, each facing different directions, huge dominating full moon, man in trench coat and fedora silhouette in fog."*

2. **Isometric overhead view**: 30-degree isometric 3D angle looking down at the scene — shows the entire layout from above. Works especially well for interior/cathedral scenes where multiple eras or elements need to be visible simultaneously. Title centered vertically.

3. **Epic sweeping vista**: Wide establishing shot of the entire world — distant car silhouettes, landscape features, atmospheric sweep. Use when the scene has a natural landscape to show off.

**Method 3: Composite from Existing Track Covers (user may request this)**

When the user says "use images from the album" or "only use the other track covers", they want the album cover composited from the actual existing track cover artwork — NOT a new AI-generated scene. This preserves the visual DNA of the individual tracks.

**Steps:**
1. Locate all track cover PNGs (3000×3000) from `/opt/data/music/artwork/covers/`
2. Arrange in a grid (3×2 for 6 tracks, etc.) with slight overlap for seamless blending
3. Composite in Pillow (PIL): paste covers onto canvas, add dark vignette for cohesion, apply Gaussian blur blend at 30% for dreamy feel
4. Darken overall by 30% so the centered title pops
5. Overlay the album title **centered** (no `--bottom`) using `overlay-title.py`
6. Save as PNG (3000×3000) and JPG (1500×1500 for Telegram preview)

**Pillow approach** (use venv Python `/opt/hermes/.venv/bin/python3`):
```python
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw
# Load all 6 track covers (3000×3000 each)
# Canvas = 3000×3000, grid = 3 cols × 2 rows
# Cell = 1000×1500 each, with 40px overlap
# Paste each cover (resized to cell + overlap), then:
#   - Dark vignette overlay (radial, edges dark, center clear)
#   - Blur blend at 0.3 alpha for dreamy composite
#   - Darken by 0.7 brightness
#   - Overlay title centered with album color
```

**When to use each method:**
- **Method 1 (AI-generated all-cars scene)**: Default when no track covers exist yet, or when the user describes a specific visual scene
- **Method 2 (Isometric)**: When user says "isometric view" or "overhead angle"
- **Method 3 (Composite from existing)**: When user says "use the other track covers" or "combine elements from the tracks"

**Key album cover elements the user always wants:**
- All track cars present and visible (not just one hero car)
- Huge full moon dominating the sky when outdoor/night scene
- Man in trench coat and fedora as silhouette
- Fog, smoke, and headlight beams
- Title centered vertically (never bottom-anchored for albums)

Prompting tips for album covers:
- Start with "An epic sweeping vista" or similar expansive framing
- Include the fedora/kimono/katana man as a grounding figure, but smaller in frame
- Mention multiple sculptures or elements in the distance
- Use the album's neon color (not per-track colors)
- The scene should capture the dominant time-of-day (night for most VØIDRIDE albums, day/night split if the album has both)
- Title is overlaid centered, not at bottom

## How It Works

1. **Font scaling** — Binary search finds the largest Open Sans Bold size where the title fills ~90% of image width
2. **Positioning** — Title is centered horizontally; vertical position depends on `--top`/`--bottom`/default flags
3. **Layer order** (bottom to top):
   - Angled drop shadow (9px/80α → 7px/150α → 6px/220α) — down-right for depth
   - Neon glow (5px/25α → 3px/50α → 2px/90α radius layers)
   - Main text (full saturation, 255α)
   - White-hot core highlight (color+130, 120α, offset -1px)

## Color Reference (VØIDRIDE Albums)

| Album | Neon Color (hex) |
|-------|-----------------|
| ₴ØɄ₦ĐĐɆ₴łǤ₵ | `#00ff44` green |
| Ʉ₦ĐɆɌ₱Δ$$ | `#ff8800` amber/orange |
| ØƦłǤł₦$ | `#ffd700` gold |
| ĐɆ₴ɆƦ† VØID | `#ffaa00` sand/amber (but per-track neon varies — see mapping table) |
| NΞØN ₳U฿ | `#00ffcc` cyan/electric green |
| SÉANCE ◊TEREO | `#aa00ff` purple |
| VØIDLINES | `#00ccff` ice blue |
| BLΔCK MΔSS | `#ff0033` crimson |
| CHERENKOV-HORIZON | `#0088ff` Cherenkov blue — track colors: `#0088ff`, `#00aaff`, `#0044ff`, `#00ffaa`, `#0066cc` |
| HELIOS-DECAY | `#cc00ff` magenta violet — track colors: `#aa44ff`, `#ff44aa`, `#ff6600`, `#7700ff`, `#ff0044` |
| HELIOS-DECAY | `#cc00ff` magenta violet — track colors: `#aa44ff`, `#ff44aa`, `#ff6600`, `#7700ff`, `#ff0044` |
| CHERENKOV-HORIZON | `#0088ff` Cherenkov blue — track colors: `#0088ff`, `#00aaff`, `#0044ff`, `#00ffaa`, `#0066cc` |
| ₴łǤłⱠ Ɇ₦Ǥł₦ɇ | `#aa00ff` purple |
| ₴ɏ₦ΔƤ₴Ɇ ₦ɆϾƦØƤØⱠł₴ | `#00ff66` green — accent: purple haze |
| ꐃ₦₮ɄɌꐃɄɌɌɆ₦₵Ɇᵾ₦ | `#ff8800` amber/orange |
| CRYOCLASTIC-ZERO | `#00ddff` ice cyan — track colors: `#00ddff`, `#88ccff`, `#00aacc`, `#44eeff`, `#0099bb` |

## VØIDRIDE Track Cover — Full Scene Pattern

Per-track covers use a cinematic scene with car, spaceship, man silhouette, fog, lightning, and moon. Generate the background with **no text** (ideogram-v4), then overlay the Unicode title.

**Step 1: Generate background (flux-2-max)**

```
Dark atmospheric cinematic 35mm film photography. A [CAR] parked on wet
asphalt road in thick swirling fog and mist. Headlights cutting through
dense fog creating dramatic volumetric light beams. In the distant
background, a massive dark spaceship about to launch with engines glowing.
A man dressed all in black wearing a fedora hat holding a katana sword
stands as a dark silhouette in the medium background partially obscured
by fog. [COLOR] lightning bolts striking in the distance. A massive full
moon dominates the misty sky. Dark nightride witch house album cover art.
Cinematic color grading, 35mm film grain, anamorphic lens flare.
NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS,
NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS,
NO SIGNAGE, NO SIGNS, NO CAPTIONS.
```

**Burning Man scene specialization:** When the user asks for a playa/duststorm setting, switch to Template 2 (Burning Man Duststorm) in `references/voidride-track-covers.md`. For album sets of 5+ tracks, alternate between night (glow-drenched, Portra 800) and day (golden dust haze, Portra 400) scenes — roughly 2 day per 7 tracks, spaced mid-album. Each track gets unique sculptures; never reuse the same sculpture across tracks in a single set.

**Parking Lot / Sideshow scene specialization:** When the user says "just the parking lot", "no characters", "skid marks", or "sideshow", switch to the Parking Lot template in `references/parking-lot-sideshow-scene.md`. This template has no cars, no characters — just empty lot with neon skid marks. Always include `NO GRAFFITI, NO WORDS ON PAVEMENT` in the negation list.

**⚠️ Pitfall:** ideogram-v4 sometimes renders text artifacts (e.g. "Image blocked by...") even with "no text" in the prompt. Use the extended negation list above (no type, no fonts, no watermarks, no labels, no signage, no signs, no captions). If text still appears, regenerate with a different seed.

**⚠️ Pitfall — Ground/surface text:** ideogram-v4 tends to render graffiti, words on pavement, or text on the ground/road surface even when the full negation list is used. For scenes with visible ground surfaces (parking lots, roads, highways), add `NO GRAFFITI, NO WORDS ON PAVEMENT, NO TEXT ON GROUND, NO PAINTED MARKINGS THAT LOOK LIKE LETTERS` to the negation prompt.

**⚠️ Pitfall — ideogram-v4 is deprecated (returns 404).** Use `flux-2-max` instead. The model name `ideogram-v4` no longer works on the Venice API — all calls return 404 Not Found. Replace with `flux-2-max` in all generation scripts and prompts.

**⚠️ Pitfall — flux-2-max maximum resolution is 1024×1024.** The API returns a 400 error for dimensions larger than 1024. Always set `width: 1024, height: 1024`. After generation, upscale to 3000×3000 with Lanczos + sharpening before overlaying titles: `ffmpeg -i input.png -vf "scale=3000:3000:flags=lanczos,unsharp=5:5:0.8:5:5:0" output.png`. Do NOT skip the unsharp filter — raw Lanczos upscaling from 1024 looks soft at 3000.

**⚠️ Pitfall — Venice Image API response format.** The response uses `{ "images": ["<base64_string>"] }` at the top level — NOT `{ "data": [{ "b64_json": "..." }] }`. Always decode `result["images"][0]` as base64. The `data` format is for audio endpoints, not image generation.

**⚠️ Pitfall — Always reference existing artwork first.** When a user says "make covers like the ones on album X" or references an existing SoundCloud playlist, download and inspect the existing covers BEFORE generating new ones. Use `soundcloud_api.py list` to get artwork URLs, then `ffprobe` to check dimensions. Generating for the wrong album wastes time and credits.

**⚠️ Day/night variety:** For album cover sets with 5+ tracks, alternate between night scenes (multicolored glow, lasers, firelight) and day scenes (golden dust haze, diffused sunlight). ~2 day scenes per 7 tracks. See `references/voidride-track-covers.md` for the DESERT VOID day/night mapping with unique sculptures per track.

### Default Fog Scene Mapping

| Track Position | Car | Lightning | Neon Color |
|----------------|-----|-----------|-------------|
| Opener (heavy) | Black Cadillac | Crimson red bolts | `#ff0044` |
| Smooth groove | Silver Ford Mustang | Ice-blue bolts | `#00ccff` |
| Title/dark | Grey Lincoln Continental | Violet purple bolts | `#aa00ff` |
| Aggressive | Burgundy Dodge Charger | Fiery orange bolts | `#ff6600` |
| Closer (atmospheric) | Obsidian Imperial Crown | Eerie green bolts | `#22cc44` |
| Extended (6+ tracks) | Dark Teal Mercury Cougar | Amber bolts | `#ff8800` |

For albums with more than 6 tracks, cycle back through the mapping starting from position 1 with slight variations (e.g., "Black Cadillac Fleetwood" instead of "Black Cadillac").

### Step 2: Overlay title (bottom position)

```bash
python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image track_01_bg.png \
  --title "Ɇ₦†Ʀɏ₩ØɄ₦Đ" \
  --color "#ff0044" \
  --output track_01_cover.png \
  --bottom
```

## Getting the Title

Use the `unicode-track-titles` skill to convert plain titles to Unicode-styled versions. The title must match the **actual song title on file** (the Unicode version). Always verify against the track metadata before overlaying.

## Font Dependency

Open Sans Bold must be at: `/opt/data/.fonts/OpenSans-Bold.ttf`
If missing: `wget -q https://github.com/google/fonts/raw/main/ofl/opensans/OpenSans-Bold.ttf -O /opt/data/.fonts/OpenSans-Bold.ttf`

## Pitfalls

- **USE THE BATCH TEMPLATE** — Before writing a cover generation script from scratch, copy `templates/batch-cover-gen.py` to `/tmp/gen_<album>_covers.py` and modify the TRACKS list, SCENE_TEMPLATE, and ALBUM_SCENE. The template already handles: ideogram-v4 API calls, blank-image retries (3 attempts), 3000x3000 Lanczos upscaling, title overlay, AND Telegram 1500x1500 JPG downscaling for delivery. Building from scratch duplicates ~200 lines of boilerplate that already works.
- **Load unicode code points from the reference** — Before populating the TRACKS list with Unicode titles, load `unicode-track-titles/references/code-points.md` via skill_view to get the verified `\u` escape sequences. The template's code point section may not have every character you need (X, Y, F, Q, Z were missing until patched — always verify against the reference file).
- **Write scripts to files, don't inline Python with Unicode** — When generating multiple covers in a batch, write a `.py` script to `/tmp/` and run it via `terminal()`. Inline `python3 -c '...'` commands mangle Unicode characters in title strings and break f-templates. File-based scripts handle Unicode correctly.
- **⚠️ `write_file` can corrupt `os.environ.get()` lines** — The `write_file` tool may mangle Python lines containing `os.environ.get("VENICE_API_KEY", "")`. The env var call gets corrupted (e.g. `API_KEY=*** "")`). When writing batch generation scripts via `write_file`, always use `terminal()` with a heredoc (`cat > /tmp/script.py << 'EOF'`) instead — heredocs preserve the content verbatim and avoid this corruption. After writing, verify the first few lines of the file before running.
- **PIL is NOT in the system Python** — `/usr/bin/python3` does NOT have Pillow installed. The overlay script imports PIL, so always run it with the venv Python: `/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py`. If you get `ModuleNotFoundError: No module named 'PIL'`, you used the system python3 — switch to the venv one. The `execute_code` sandbox also lacks PIL; use `terminal()` for any PIL-dependent code.
- **Venice API key env var** — Use `$VENICE_API_KEY` in shell commands or `os.environ.get("VENICE_API_KEY")` in Python. Do NOT use `VENICE_INFERENCE_KEY` — that's for audio models only.
- **⚠️ VENICE_API_KEY is NOT available in `execute_code`** — The Python sandbox used by `execute_code` does NOT inherit shell environment variables. Calling `os.environ.get("VENICE_API_KEY")` returns empty string. **Always write your generation script to a `.py` file and run it via `terminal()`** (which inherits shell env). Alternatively, pass the key explicitly: `VENICE_API_KEY="$VENICE_API_KEY" python3 /tmp/gen_covers.py`. Do NOT use `execute_code` for Venice API calls — it will fail with 401 Authentication errors every time.
- **Venice Image API endpoint** — The correct endpoint is `POST https://api.venice.ai/api/v1/image/generate` (singular "image", NOT "images"). Response format is `{ "images": ["<base64>"] }` at the top level — NOT `{ "data": [{ "url": "..." }] }`. Always decode `result["images"][0]` as base64.
- **Venice Image API model** — Use `flux-2-max` (NOT `ideogram-v4`, which returns 404). Maximum resolution is 1024×1024; use `width`/`height` params (NOT `aspect_ratio`). See `references/venice-image-api.md` for full API spec, deprecated models, and Python example.
- **ideogram-v4 mangles Unicode** — always generate backgrounds without text, then overlay with this script
- **Always prompt "no text, no letters, no characters, no words, no logos"** for background generation — the more emphatic the negation, the less likely ideogram adds unwanted text
- **Venice returns WebP** — must convert to PNG before overlay: `ffmpeg -y -i raw.webp -c:v png background.png`
- **SoundCloud needs 800×800 min** — scale up if needed: `ffmpeg -y -i input.png -vf "scale=800:800:force_original_aspect_ratio=decrease,pad=800:800:(ow-iw)/2:(oh-ih)/2" output.png`
- **Dark backgrounds compress better** — very dark nebula images can be 400KB vs 900KB for brighter ones. Both are valid; don't judge by file size.
- **ideogram-v4 adds text on pavement/asphalt** — parking lot and street scenes are especially prone to this. Always include `NO GRAFFITI, NO WORDS ON PAVEMENT` in the negation list for parking lot scenes. If unwanted text persists, regenerate with a stronger negation block.
- **ideogram-v4 can return near-blank images** — if a raw WebP file is under 10KB (or the resulting bg.png is suspiciously small like < 50KB), ideogram likely returned a solid-color/near-blank image. Regenerate it.
- **Sanitize filenames immediately after generation** — Venice API output filenames with spaces when track titles contain spaces. Run `mv` to replace spaces with underscores before ffmpeg and overlay steps.
- **Title must match the catalog exactly** — always pull the Unicode title from the producer profile's catalog, not from memory or guesswork. Characters like Ɍ vs Ʀ and ៛ vs Ⱡ look similar but are different code points.
- **Scene prompts can be overridden per-album** — the default fog/car/night/lightning/moon scene is just one template. If the user describes a different setting (Burning Man, desert, Mars, city, parking lot, etc.), rewrite the entire scene prompt to match. See `references/voidride-track-covers.md` for three scene templates: Fog/Night (default), Burning Man Duststorm, and Mars/Planetary. See `references/parking-lot-sideshow-scene.md` for the parking lot sideshow template.
- **When the scene includes intentional text elements** (license plates, neon signs, road signs), use a soft negation: `"NO TEXT EXCEPT THE NEON SIGN AND LICENSE PLATE, NO OTHER LETTERS..."` instead of the full ban. The full no-text ban will remove even text you want rendered.
- **⚠️ Telegram `send_photo` compresses PNG→JPEG** — When delivering covers via Telegram, ALWAYS send BOTH:
  1. As photo (inline preview — Telegram will JPEG-compress, that's OK for preview)
  2. As document with `--force-document` flag (preserves original PNG quality)
  The user expects PNG files. If you only `send_photo`, they get lossy JPEG regardless of the source format.
- **⚠️ Telegram 10MB photo size limit** — `send_photo` rejects files over 10MB. 3000×3000 PNG covers (especially album covers with complex scenes, which can be 10-12MB) will fail silently with a warning. Before sending as a photo, downscale to 1500×1500 JPG for the preview:
  ```bash
  ffmpeg -y -i cover_3000.png -vf "scale=1500:1500:flags=lanczos" -q:v 2 cover_1500.jpg
  ```
  Send the small JPG as the photo preview, then send the full 3000×3000 PNG as a document. For batch delivery, pre-convert all covers:
  ```bash
  for f in /path/to/covers/*_cover.png; do
    name=$(basename "$f" .png)
    ffmpeg -y -i "$f" -vf "scale=1500:1500:flags=lanczos" -q:v 2 "/tmp/covers_tg/${name}.jpg"
  done
  ```
  This reduces 10-11MB PNGs to ~0.5-0.7MB JPGs that Telegram accepts as photos.
- **⚠️ Confirm which album before generating covers.** If the user says "redo the covers" or references a playlist, ALWAYS confirm which album/EP they mean before generating. Generating 6 covers for the wrong album wastes credits and time.
- **⚠️ Check ideogram output file size.** ideogram-v4 sometimes returns near-blank images (1-2KB WebP). Always check `len(img_bytes)` after base64 decode — if under 10KB, regenerate immediately. A blank background will produce a black/near-black cover that's unusable.
- **⚠️ Venice API output filenames may contain spaces.** When running batch generation scripts, the raw WebP filenames from your own naming can include spaces (e.g. `03_REDLINE WRAITH_raw.webp`). Always sanitize filenames (replace spaces with underscores) before passing to ffmpeg or overlay-title.py, or write the script to use underscore-only naming from the start.

## Fixing Covers with Unwanted Text

When ideogram-v4 adds stray text/graffiti/words to a background (even with the full negation list), use this two-step fix workflow instead of regenerating from scratch:

### Step 1: Remove text from the existing background

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/covers-notext/scripts/remove_text.py \
  /path/to/track_04_bg.png \
  /path/to/covers-notext/track_04_notext.png \
  gpt-image-2-edit
```

This uses Venice AI's gpt-image-2-edit model to inpaint text out of the background while preserving the artwork. Takes ~2-3 minutes at 4K resolution.

### Step 2: Re-overlay the title on the cleaned background

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image /path/to/covers-notext/track_04_notext.png \
  --title "ØVɆƦ₴†ɄɆƦ ƤƦØ†ØϾØⱠ" \
  --color "#ff6600" \
  --output /path/to/covers/track_04_cover.png \
  --bottom
```

### When to use this vs. regenerate

- **Fix workflow** (remove_text → re-overlay): Use when the background artwork itself is good but has stray text, graffiti, or labels. Faster (~3 min) and cheaper than a full regeneration. Preserves the existing scene composition.
- **Full regenerate**: Use when the entire background is wrong (wrong car, wrong colors, wrong scene). Slower and costs another ideogram-v4 generation.

### Pitfalls

- The `remove_text.py` script can timeout at 120s — use a 300s timeout for 4K edits.
- Always verify the cleaned background visually before re-overlaying — AI inpainting can leave subtle artifacts.
- Save the cleaned notext version alongside the originals so you don't have to re-run removal if the overlay needs adjusting.

## No-Text Variant (pixelate-text.py)

Generate "no-text" versions of covers where any overlaid title is replaced by a chunky pixel mosaic whose colors are sampled from the artwork itself (no rainbow). Useful for social media previews, wallpaper versions, or anywhere you want the art without the title.

### Workflow

```bash
# Single cover
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/pixelate-text.py \
  --input /opt/data/music/artwork/covers/Song_Title.png \
  --output /opt/data/music/artwork/covers-notext/Song_Title.png

# Batch all covers in directory
for f in /opt/data/music/artwork/covers/*.png; do
  name=$(basename "$f")
  # Skip files that are clearly not track covers (playlist covers, _space, _titled, _sm, _sc variants)
  case "$name" in
    *_space.png|*_titled.png|*_titled_sm.jpg|*_sc.png|*playlist*) continue ;;
  esac
  /opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/pixelate-text.py \
    --input "$f" \
    --output "/opt/data/music/artwork/covers-notext/$name"
done
```

### Options

| Arg | Default | Description |
|-----|---------|-------------|
| `--pixel-size` | 32 | Block size in pixels. 20=fine, 32=extra chunky (default), 40=mega-chunky |
| `--padding` | 40 | Pixels of padding around detected text region |
| `--window-height` | 350 | Sliding window height for detection (px). Increase for very large glow effects. |
| `--palette-colors` | 10 | Number of dominant colors to extract from artwork for pixel blocks |
| `--seed` | 42 | Random seed for reproducible pixel patterns |

### Detection Algorithm

The script auto-detects the text band using a sliding-window scorer:
1. Measures background brightness from the top-center (sky/background area)
2. Scores each row in the bottom 30% of the image for bright pixels (above bg median + 50) and highly-saturated neon pixels (sat > 80, max channel > 140)
3. Slides a configurable window to find the densest cluster of text content
4. Adds padding around the detected region

This works well for VØIDRIDE-style covers (dark background, neon Open Sans Bold text at bottom) and similar high-contrast layouts.

### Style Details

- **Art-matched palette** — colors are extracted FROM the cover artwork itself (no rainbow). The script samples the whole image, clusters similar colors, and picks the dominant palette, so the pixel blocks blend into the piece naturally
- **Extra chunky blocks** — default 32px (user preference). Use `--pixel-size 20` for finer, `--pixel-size 40` for mega-chunky
- **Block distribution**: 83% normal palette blocks, 12% dark depth blocks, 5% bright glitch pops
- **2px dark grid lines** on top/left edges of each block for chunky retro-censorship feel
- **Reproducible**: same seed always produces same output

**User preference**: No rainbow gradient across columns. Colors must come from the artwork palette so the censor blocks feel like they belong in the composition.

## No-Text Variant: Pixelate Text Out of Covers

For creating text-free versions of covers (e.g., for karaoke lyrics videos, clean artwork prints, or remix covers), use the `pixelate-notext.py` script. It detects the text band at the bottom of a cover and fills it with **chunky pixel blocks colored from the artwork's own palette** — so the censorship blends in rather than clashing.

**Style preferences (user-confirmed):** Extra chunky (32px blocks), no rainbow gradient — colors sampled from the artwork itself. Dark depth blocks (12%) and bright glitch pops (5%) for texture. Dark 2px grid lines between pixels for definition.

### Single cover
```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/pixelate-notext.py \
  /opt/data/music/artwork/covers/Midnight_Protocol.png \
  /opt/data/music/artwork/covers-notext/Midnight_Protocol.png
```

### Batch all covers
```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/pixelate-notext.py \
  /opt/data/music/artwork/covers /opt/data/music/artwork/covers-notext --batch
```

Options: `--pixel-size 32` (default, extra chunky), `--padding 40` (pixels of padding around detected text). The script excludes `_space.png` and `_sc.png` variants by default.

Output directory: `/opt/data/music/artwork/covers-notext/` — the single source of truth for text-free covers, maintained alongside the originals in `/opt/data/music/artwork/covers/`.

### How text detection works
The script scans the bottom 30% of the image for bright/colored pixel clusters (neon text + glow on dark backgrounds) using a sliding window. Background brightness is measured from the top-center of the image. The detected region is extended with 40px padding to fully cover glow and shadow layers.

## Updating Playlist Artwork After Cover Regeneration

When a user asks to redo an album cover (e.g., new perspective, title repositioning), the workflow is:

1. **Generate new background** with Venice `flux-2-max` (1024×1024, no-text prompt)
2. **Upscale** to 3000×3000 with `ffmpeg` Lanczos + unsharp
3. **Overlay title** with `overlay-title.py` (centered for albums, `--bottom` for tracks)
4. **Create Telegram JPG** at 1500×1500 for preview
5. **Send to user for review** before updating SoundCloud
6. **Update SC playlist artwork** via raw multipart PUT to `/playlists/{ID}` (see SoundCloud skill)
7. **Save cover** to both `/opt/data/music/releases/<album>/covers/` and `/opt/data/music/artwork/covers/`

Key: Always send the new cover to the user FIRST and get approval before updating SoundCloud. The overlay script archives a copy to `/opt/data/music/artwork/covers/` automatically.

## Related Skills & References

- **unicode-track-titles** — stylize plain titles with Unicode characters before overlaying
- **`references/album-cover-compositions.md`** — Album cover composition patterns (all-cars-stacked, isometric, era progression, wide vista) and character variants (trench coat, fedora, katana, cigar)
- **soundcloud** — full Venice API background generation workflow (Step 1), plus SoundCloud upload. See its `references/cover-art-generation.md`
- **master-producer** — Venice image API reference, style presets, model comparison. See its `references/venice-image-api.md`
- **`references/voidride-track-covers.md`** — VØIDRIDE full scene prompt template, per-track car/color/lightning mapping, per-album color map, complete end-to-end workflow, and title rules (plain ASCII for SoundCloud tracks, Unicode for covers/playlists).
- **`references/album-cover-compositions.md`** — Album cover composition patterns: all cars stacked, isometric overhead, era progression, wide vista, and character variants (trench coat, fedora, katana, cigar). Title position rules for album vs track covers.
- **`references/mars-descent-scene.md`** — Mars/alien landscape scene template for sci-fi covers (different from fog/night or Burning Man), includes per-track car/plate mapping, ideogram-v4 text handling for neon signs + license plates.
- **`references/sideshow-parking-lot-scene.md`** — Empty parking lot with sideshow skid marks (no characters, no vehicles). Per-track neon color mapping, anti-graffiti negation prompts, playlist artwork update via raw API, generation pipeline.
- **`references/parking-lot-sideshow-scene.md`** — Parking lot/sideshow scene template (no characters, just skid marks): per-track color mapping
- **`references/cyberpunk-city-scene.md`** — Rain-slicked cyberpunk metropolis scene template: interceptor cars, neon reflections, brutalist cityscape. Per-track car/color/accent mapping for ₴ØɄ₦ĐĐɆ₴łǤ₵, comparison table with other scene types, playlist cover variant with overlapping colors, and regeneration workflow.
- **`references/era-progression-scene.md`** — Same object aging across 5 historical eras: cathedral setting, hybrid computer-car always still on but progressively more overgrown. Per-era prompt structure (2077 holographic → 1983 CRT → 1967 mainframe → 1924 Art Deco → 1347 medieval). Used for SIGIL ENGINE and SYNAPSE NECROPOLIS.
- **`references/cherenkov-reactor-scene.md`** — Flooded nuclear reactor containment vessel scene template (interior, Cherenkov blue glow, water, concrete, scaffolding). Per-track color mapping, prompt template, and key differences from other VØIDRIDE scene types. Used for CHERENKOV-HORIZON and future nuclear/industrial albums.
- **`references/solar-dissolution-scene.md`** — Derelict satellite dissolving into violent ultraviolet solar flare over scorched horizon. Five stages of progressive dissolution (intact → debris → shadow). Per-stage prompts, UV/purple color palette. Used for HELIOS-DECAY.
- **`references/cherenkov-reactor-scene.md`** — Flooded nuclear reactor containment vessel glowing with intense Cherenkov blue light beneath fractured concrete and corroded scaffolding. Five per-track variations (intense glow, core glow, fissure echo, ionized air, memorial stillness). Per-track neon color map (electric blue → toxic green-blue → cold cerulean). Used for CHERENKOV-HORIZON and future nuclear/industrial albums.
- **`references/cryoclastic-zero-scene.md`** — Antarctic ice cavern scene template: crashed military transport, dying cyan flares, ice crystal fog, frozen scaffolding. Per-track car/color mapping for CRYOCLASTIC-ZERO and future glacial/frozen albums. Interior setting with cyan/cold-white palette.
- **`references/sc-playlist-artwork-update.md`** — SoundCloud playlist artwork update via raw multipart PUT API. Use this when updating an existing playlist's cover image — `soundcloud_api.py` doesn't have a dedicated command for playlist artwork updates, so use the urllib multipart approach documented here.
- **`scripts/pixelate-text.py`** — Generates no-text variants: auto-detects title text band and replaces it with a chunky pixel mosaic using colors extracted from the artwork. See "No-Text Variant" section above.
- **`templates/batch-cover-gen.py`** — Copy-and-modify template for batch cover art generation (5 track covers + 1 album cover). Handles ideogram-v4 API calls, blank-image retries, 3000x3000 upscaling, title overlay, and Telegram downscaling. Edit the TRACKS list and run.