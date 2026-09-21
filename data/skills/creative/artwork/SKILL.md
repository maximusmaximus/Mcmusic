---
name: artwork
description: Full album/playlist cover art pipeline — background generation via Venice AI (grok-imagine-image-quality), upscale to 3000×3000, waveform banner extraction (1240×400), Unicode title overlay, and SoundCloud playlist cover workflows. Includes gen_artwork.py, overlay-title.py, and gen_waveform_art.py integration.
tags: [cover-art, artwork, venice, image-generation, upscale, waveform, pipeline, soundcloud, playlist]
---

# Artwork — Cover Generation Pipeline

Full-stack album cover art generation: Venice AI background → upscale → waveform banner → Unicode title overlay.

## Pipeline

```
PHASE 1:  Background generation (Venice grok-imagine-image-quality, 1024×1024, no-text prompt)
PHASE 2:  Upscale to 3000×3000 (Venice /api/v1/image/upscale scale=4)
PHASE 3a: Waveform banner from clean bg (1240×400 crop, BEFORE text)
PHASE 3b: Crop bg to 3000×3000, overlay title (cover-title-overlay)
PHASE 4:  Telegram preview (1500×1500 JPG)
```

## Scripts

### gen_artwork.py (single or batch)
```bash
python3 scripts/gen_artwork.py \
  --title "Track Title" --genre "dark trap" --bpm 140 --key Fm

python3 scripts/gen_artwork.py --batch
```

### Gen_artwork only
```bash
python3 scripts/gen_artwork.py \
  --title "Orbital Scrapline" \
  --genre "dark space trap / cosmic" \
  --bpm 120 --key Fm \
  --notes "derelict spacecraft graveyard, orbital debris field"
```

## ⚠️ Known Bugs in gen_artwork.py

The `gen_artwork.py` script calls `overlay_title_on_cover()` with hardcoded `"python3"` (system Python). Since system Python lacks PIL, this step **always crashes** with `ModuleNotFoundError: No module named 'PIL'`.

**Workaround:** After gen_artwork.py finishes the background + upscale phase (which succeeds), run overlay-title.py manually with venv Python:

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image /opt/data/music/artwork/covers/Track_Title.png \
  --title "UNICODE_TITLE" \
  --auto-color \
  --bottom \
  --output /opt/data/music/artwork/covers/Track_Title.png
```

The background (`_bg.png`) and upscale are fine — it's only the overlay step that needs manual intervention.

### Bug 2: Upscale trim to 3000×3000 silently fails

After Venice upscales 1024×1024 → 4096×4096, `gen_artwork.py` tries to trim to 3000×3000 with:

```python
ffmpeg -i file.png -vf "scale=3000:3000" -update 1 file.png
```

This **silently fails** — ffmpeg cannot use `-update 1` to overwrite the same file it's reading. The exception is caught with `pass`, so no error is reported. The output files end up at 4096×4096 instead of 3000×3000.

**Fix:** If the user asks for 3000×3000 covers (or you need to verify size), resize manually with the temp file pattern:

```bash
ffmpeg -y -i /opt/data/music/artwork/covers/Track_Title.png \
  -vf "scale=3000:3000:flags=lanczos" \
  /tmp/track_resized.png && \
mv /tmp/track_resized.png /opt/data/music/artwork/covers/Track_Title.png
```

Or batch-resize all covers at once:

```bash
for f in HULLSTATIC SALVAGE_DRIFT COLDWELD; do
  ffmpeg -y -i "/opt/data/music/artwork/covers/${f}.png" \
    -vf "scale=3000:3000:flags=lanczos" \
    "/tmp/${f}_3k.png" && \
  mv "/tmp/${f}_3k.png" "/opt/data/music/artwork/covers/${f}.png"
done
```

### Rule: NEVER use `-update 1` to overwrite the input file

ffmpeg's `-update 1` only works for output files that differ from the input. When input == output, ffmpeg silently errors. Always write to a temp path, then `mv` to replace.

## Batch Album Cover Workflow (For Multi-Track Releases)

When the user asks for covers of ALL tracks in a release (e.g. "all album covers from orbital scrapline"):

### Step 1: Generate backgrounds (gen_artwork.py for each track)
Run gen_artwork.py for each track. It will generate the background + upscale, then crash on the overlay step. That's expected.

```bash
for title in "HULLSTATIC" "SALVAGE DRIFT" "COLDWELD"; do
  python3 scripts/gen_artwork.py \
    --title "$title" \
    --genre "dark space trap / cosmic" \
    --bpm 120 --key Fm \
    --notes "appropriate scene description"
done
```

Ignore the error — backgrounds and upscales are done.

### Step 2: Overlay titles with venv Python
Run overlay-title.py for each track using the venv Python:

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image "/opt/data/music/artwork/covers/HULLSTATIC.png" \
  --title "ⱧɄⱠⱠ₴†Δ†łϾ" \
  --auto-color --output "/opt/data/music/artwork/covers/HULLSTATIC.png"
```

### Step 3: Generate waveform banners
Pre-resize each background to ≤1500px JPEG (avoids Venice 413 error), then pass to gen_waveform_art.py:

```bash
export VENV=/opt/hermes/.venv/bin/python3
for track in HULLSTATIC SALVAGE_DRIFT; do
  ffmpeg -y -i "/opt/data/music/artwork/covers/${track}_bg.png" \
    -vf "scale=1500:1500:flags=lanczos" -frames:v 1 -update 1 "/tmp/wf_${track}.jpg"
  $VENV /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
    --image "/tmp/wf_${track}.jpg" \
    --title "$(echo $track | tr '_' ' ')" \
    --output-dir /opt/data/music/artwork/waveforms
done
```

### Step 4: Resize covers to 3000×3000 if needed
Venice upscales to 4096×4096 but gen_artwork.py's trim to 3000×3000 silently fails. If user asks for 3K covers:

```bash
for f in HULLSTATIC SALVAGE_DRIFT COLDWELD KESSLER_CASCADE REENTRY; do
  ffmpeg -y -i "/opt/data/music/artwork/covers/${f}.png" \
    -vf "scale=3000:3000:flags=lanczos" "/tmp/${f}_3k.png" && \
  mv "/tmp/${f}_3k.png" "/opt/data/music/artwork/covers/${f}.png"
done
```

### Step 5: Deliver
Send each cover via MEDIA: path. For batch delivery, send them one by one.

## Waveform Banner Workflow

Waveform banners (1240×400) are generated from the **clean background BEFORE text overlay**.

### From freshly-generated covers (not published yet)

gen_artwork.py already extracts the waveform from `_bg.png` before applying text. But it also uses system `python3`, so the waveform crop step may fail too (ImageMagick `convert` or PIL unavailable). Use ffmpeg as fallback:

```bash
# Resize upscaled PNG to ≤1500px (Venice edit API rejects 27MB PNGs with 413)
ffmpeg -y -i /opt/data/music/artwork/covers/Track_Title_bg.png \
  -vf "scale=1500:1500:flags=lanczos" -frames:v 1 -update 1 \
  /tmp/waveform_source.jpg

# Pass to gen_waveform_art.py (runs via venv Python which has PIL)
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --image /tmp/waveform_source.jpg \
  --title "TRACK TITLE" \
  --output-dir /opt/data/music/artwork/waveforms

rm -f /tmp/waveform_source.jpg
```

### From already-published SoundCloud tracks

Follow the **Published Album Workflow** in the `waveform-artwork` skill — always pull cover URLs from SoundCloud directly; local covers may be stale.

## PIL/Venv Quirk

The venv Python (`/opt/hermes/.venv/bin/python3`) has PIL installed but can be slow to start. For simple resize operations (resizing a PNG to ≤1500px), **ffmpeg is faster and more reliable**:
- `ffmpeg ... scale=1500:1500:flags=lanczos -frames:v 1 -update 1` works instantly
- The venv `python3 -c "from PIL import Image; img.thumbnail(...)"` can hang for 30+ seconds on large images

Use ffmpeg for all image pre-processing; reserve venv Python for scripts that actually need PIL (overlay-title.py, gen_waveform_art.py).

## Output Files

| File | Location | Description |
|------|----------|-------------|
| `{Title}_bg.png` | `/opt/data/music/artwork/covers/` | Clean background (no text), upscaled to 4096×4096 |
| `{Title}.png` | `/opt/data/music/artwork/covers/` | Final cover with Unicode title overlay |
| `{TITLE}_waveform.png` | `/opt/data/music/artwork/waveforms/` | Waveform banner 1240×400 |

## References & Related Skills

### Reference Files (in this skill)

| File | Contents |
|------|----------|
| `references/cover-art-generation.md` | Full cover art pipeline reference — arguments, workflow, Visual DNA motifs, argument table, all known pitfalls (1500-char limit, SC upload size, upscale timeout, empty state recovery) |
| `references/playlist-cover-redo.md` | Complete workflow for regenerating SoundCloud playlist covers based on individual track artwork |
| `references/python3-pil-fix.md` | Fix for missing PIL in overlay step (VENV_PYTHON constant + code change) |
| `references/stale-playlist-ids.md` | Detecting and resolving stale SC playlist IDs after cover re-upload |
| `references/voidride-animal-motif-covers.md` | Animal/laser eye composition pattern for VØIDRIDE albums |
| `references/waveform-from-upscaled.md` | ffmpeg resize workaround for 4K PNG → waveform source (Venice 413 avoidance) |

### Scripts (in this skill)

| Script | Purpose |
|--------|---------|
| `scripts/gen_artwork.py` | Main cover generation — builds prompts, calls Venice API, upscales, calls overlay-title.py and gen_waveform_art.py |

### Related Skills

- **cover-title-overlay** — text overlay script details, Unicode title rules, scene templates, album vs track positioning
- **waveform-artwork** — waveform banner generation, SC published album workflow, detailed pitfall list
- **covers-notext** — remove stray text from backgrounds via Venice AI inpainting
- **unicode-track-titles** — stylize plain track titles with Unicode characters
- **album-proposals** — uses this skill for Phase 3 (artwork) of the end-to-end album pipeline
