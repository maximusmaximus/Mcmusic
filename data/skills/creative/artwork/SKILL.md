---
name: artwork
description: Cohesive 3000×3000 album & track cover art pipeline — single-pass Album Visual Showrunner in album_pipeline.py, Venice AI image.cover_primary (qwen-image-3-pro via model_registry.json), 3000×3000 upscale, clean 1240×400 waveform banner extraction, and album-locked luminous neon title overlays (WCAG Y >= 0.45).
tags: [cover-art, artwork, venice, image-generation, upscale, waveform, pipeline, soundcloud, playlist]
---

# Artwork — Cohesive 3000×3000 Cover Art Pipeline

Full-stack VØIDRIDE cover art generation governed by `model_registry.json` (`image.cover_primary`: `qwen-image-3-pro` → `grok-imagine-image-2-0` → `grok-imagine-image`).

## ⚠️ Critical Rule for Active or Staged Albums

**NEVER kill `album_pipeline.py` and NEVER call `gen_artwork.py` ad-hoc to redo an album or track cover during an album workflow!**

Always use the unified safe pipeline CLI:

```bash
# Redo Track 3 cover (signals /tmp/pipeline_flags/art_redo_3 if pipeline is running, or runs Showrunner + 3K upscale + cohesive overlay if idle):
/opt/hermes/.venv/bin/python3 /opt/data/scripts/album_pipeline.py --redo-cover 3

# Redo Track 3 cover with specific visual feedback:
/opt/hermes/.venv/bin/python3 /opt/data/scripts/album_pipeline.py --redo-cover 3 --redo-cover-feedback "deeper rain-drenched reflections inside the subterranean concrete bay"

# Redo the Album Cover or all 5 Track Covers:
/opt/hermes/.venv/bin/python3 /opt/data/scripts/album_pipeline.py --redo-cover album
/opt/hermes/.venv/bin/python3 /opt/data/scripts/album_pipeline.py --redo-cover all
```

Why:
1. If `album_pipeline.py` is currently running, `--redo-cover` safely writes the flag into `/tmp/pipeline_flags/` without interrupting or killing the orchestrator.
2. Every track cover stays locked to the **Album Visual Showrunner** blueprint (`visual_showrunner_plan.json`) — same physical architecture, weather, and neon lighting palette as `album_cover_bg.png`, with 5 distinct camera scales, zero off-world literal title puns, and motif caps (`fedora <= 1`, `katana <= 1`, `moon <= 2`).
3. Every cover is upscaled to `3000×3000`, overlaid with the album's cohesive luminous neon palette (`WCAG relative_luminance >= 0.45`), and exported as a `<= 8 MB` `3000×3000` RGB `.jpg`.

---

## Standalone Single-Track Cover (`gen_artwork.py`)

Only use `gen_artwork.py` for standalone non-album singles (always via `/opt/hermes/.venv/bin/python3`):

```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/artwork/scripts/gen_artwork.py \
  --title "TRACK TITLE" \
  --genre "dark nightride trap / witch-house" \
  --bpm 140 --key Fm \
  --album "PARENT ALBUM" \
  --album-anchor /opt/data/music/albums/parent-album/artwork/album_cover_bg.png \
  --force
```

`gen_artwork.py` automatically:
1. Resolves the active `image.cover_primary` model chain from `model_registry.json` (`qwen-image-3-pro` — never deprecated `grok-imagine-image-quality`).
2. Auto-detects matching album context and `album_cover_bg.png` anchor from `pipeline_state.json` / `current_proposals.json` if `--title` belongs to a proposal.
3. Generates a clean `1024×1024` untitled scene, upscales via Venice `/api/v1/image/upscale` (`scale=4`) + PIL Lanczos trim to exact **`3000×3000`**, crops the `1240×400` waveform banner **before** text overlay, and runs `overlay-title.py --stacked --bottom --auto-color [--album-anchor ...]` + exports a `<= 8 MB` `.jpg` companion.

## Output Files

| File | Location | Description |
|------|----------|-------------|
| `album_cover_bg.png` / `{Title}_bg.png` | `/opt/data/music/albums/{slug}/artwork/` | Clean `3000×3000` background (no text) |
| `album_cover.png` / `{Title}_cover.png` | `/opt/data/music/albums/{slug}/artwork/` | `3000×3000` master PNG with cohesive neon title overlay |
| `album_cover.jpg` / `{Title}_cover.jpg` | `/opt/data/music/albums/{slug}/artwork/` | `3000×3000` RGB JPEG (`<= 8 MB`) for Telegram & SoundCloud |
| `01_{Title}.jpg` + `album_cover.jpg` | `/opt/data/music/releases/{slug}/covers/` | Canonical `3000×3000` RGB release covers (`<= 8 MB`) |

## Related Skills

- **cover-title-overlay** — geometric stacked typography, album-locked neon palette (`--album` / `--album-anchor`), and WCAG `Y >= 0.45` luminance floor
- **waveform-artwork** — `1240×400` waveform banner generation
- **covers-notext** — remove stray text from backgrounds via Venice AI inpainting
