# Cover Art Generation (previously standalone `artwork` skill)

Generate album/playlist cover art and waveform banners using Venice AI image generation (`grok-imagine-image-quality` model). Covers are 3000×3000 PNG with Unicode-styled titles.

## Script

`scripts/gen_artwork.py` (in this skill directory)

## Quick Start — Single Track Cover

```bash
python3 scripts/gen_artwork.py \
  --title "TRACK TITLE" \
  --genre "dark nightride trap / witch house" \
  --bpm 140 \
  --key "Fm" \
  --notes "Optional additional scene descriptors"
```

This generates:
- `covers/<Title>_bg.png` — clean no-text background (upscaled to 4K)
- `covers/<Title>.png` — background + Unicode title overlay
- `waveforms/<Title>_waveform.png` — waveform banner (1240×400)

(Outputs land in `/opt/data/music/artwork/covers/`, `/opt/data/music/artwork/waveforms/`)

## Quick Start — Playlist/Album Cover (Manual)

For playlist or album covers, generate the background via gen_artwork.py, then overlay the title separately:

```bash
# Step 1: Generate background
python3 scripts/gen_artwork.py \
  --title "DESERT VOID" \
  --genre "dark nightride trap / witch house" \
  --bpm 140 --key "Fm" \
  --notes "Custom scene description"

# Step 2: Crop background to 3000, then overlay title
ffmpeg -y -i covers/DESERT_VOID_bg.png \
  -vf "crop=3000:3000:548:548" /tmp/DESERT_VOID_bg_3000.png

/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image /tmp/DESERT_VOID_bg_3000.png \
  --title "ĐɆ₴ɆƦ† ⱴØłĐ" \
  --auto-color \
  --output covers/DESERT_VOID.png

rm /tmp/DESERT_VOID_bg_3000.png

# Step 3: Copy to album directory
cp covers/DESERT_VOID.png /opt/data/music/artwork/albums/desert-void/
cp covers/DESERT_VOID_bg.png /opt/data/music/artwork/albums/desert-void/DESERT_VOID_playlist_space.png
```

## Arguments

| Arg | Required | Description |
|-----|----------|-------------|
| `--title` | Yes | Track or album title for filenaming and overlay |
| `--genre` | No | Genre for prompt building (default: dark nightride trap / witch-house) |
| `--bpm` | No | Tempo for mood selection (default: 140) |
| `--key` | No | Musical key for mood (default: Fm) |
| `--notes` | No | Additional scene descriptors |
| `--batch` | No | Generate artwork for all tracks without covers (reads handoff manifests) |

## How It Works

1. `build_cover_prompt()` — picks 2-3 random elements from VISUAL_DNA list, resolves `{moon_phase}` placeholders to the real lunar phase, builds a rich prompt with genre/BPM/key mood
2. `generate_image()` — calls Venice API `/api/v1/images/generations` with `grok-imagine-image-quality` at 1024×1024
3. `upscale_if_needed()` — upscales via Venice `/api/v1/image/upscale` (scale=4, creativity=0.01) to ~4096×4096, then crops to 3000×3000
4. `crop_waveform()` — crops a 1240×400 horizontal band from the clean background
5. `overlay_title_on_cover()` — runs cover-title-overlay.py

## Visual DNA Motifs

Recurring motifs mixed into every cover prompt (2-3 are randomly selected):
- Vehicles (cars drifting, JDM, motorcycles)
- Dark figure in trench coat and fedora
- Katana and weapons aesthetic
- Smoke, haze, atmosphere
- Urban and industrial scenes
- Space and cosmic
- Moon scenes (with real lunar phase injection)
- Neon and color accents

## Critical Pitfalls

### Overlay Title Step Fails with System Python3
gen_artwork.py hardcodes `"python3"` to call overlay-title.py, but the system Python3 lacks Pillow. The overlay ALWAYS fails. After gen_artwork.py generates `_bg.png`, run overlay manually:
```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image covers/ALBUM_bg.png \
  --title "ĐɆ₴ɆƦ† ⱴØłĐ" \
  --auto-color \
  --output covers/ALBUM.png
```

### Crop Background FIRST, Then Overlay Title
If you overlay on 4096×4096 and THEN crop to 3000×3000, title text gets cut off on both sides. Correct order: crop bg to 3000 → overlay title at 3000 scale.

### Covered Already Exists — No `--force` Flag
gen_artwork.py checks `if cover_path.exists()` and exits. Delete old files first:
```bash
rm -f covers/<FILENAME>*.png waveforms/<FILENAME>*.png
```

### Spaces Become Underscores in Filenames
gen_artwork.py sanitizes titles: `"HADAL GRIP"` → `HADAL_GRIP_bg.png`. Use underscore-form filenames when referencing outputs.

### Prompt Length Limit — 1500 Character Cap
Venice API enforces 1500-char max on prompt field. Keep `--notes` under ~300 chars.

### Venice API Key Not Available in execute_code
Script reads `VENICE_API_KEY` from environment. Always run via `terminal()`.

### Waveform Crop Fails Silently
`crop_waveform()` needs ImageMagick or PIL. If unavailable, waveform files are never created — use the `waveform-artwork` skill instead.

### Upscale Timeout (120s default)
The Venice upscale can timeout at 120 seconds. Retry with 300-second timeout or fall back to ffmpeg Lanczos scaling.

### SC Playlist Upload Size Limit
3000×3000 PNG can be 15MB+ (over SC's ~10MB limit). Downscale to 2000×2000 PNG before uploading.

### Playlist Cover Redo Workflow
See `references/playlist-cover-redo.md` for the complete workflow when the user says "redo this playlist cover." Also see `references/voidride-animal-motif-covers.md` for the animal/laser eye composition pattern when track analysis reveals creature motifs.

### Stale SoundCloud Playlist IDs
When updating playlist artwork, the share link may resolve to a stale 404 ID (playlist was recreated). Always fetch `/me/playlists` to find the live version. See `references/stale-playlist-ids.md`.

### gen_artwork.py Auto Unicode Titles: When to Trust vs Replace
- **New track** (no prior Unicode title) → auto-generated title from gen_artwork.py is usually fine
- **Existing track on SoundCloud** → lookup actual Unicode title from SC page or cover filenames
- **When in doubt** → use `unicode-track-titles` skill manually
- The `--title` argument is for file naming only, not visual overlay text — you overwrite the `.png` with overlay-title.py either way

### Regenerating a Cover (Redo Workflow)
1. Delete old files (covers/ and waveforms/)
2. Regenerate with revised `--notes` (watch 1500-char limit)
3. Crop bg to 3000, overlay title manually
4. Preview as 1500×1500 JPG via ffmpeg
5. Send for user approval
6. If uploading to SC: downscale to 2000×2000 PNG, find playlist ID, multipart PUT
7. Save to `/opt/data/music/artwork/albums/<album-name>/`

### "Combine Symbols" Variant
When user says "combine symbols from the track art" (not just "based on art"):
1. Download all track covers at `-t500x500.jpg`
2. Analyze per-channel pixel patterns to find color camps
3. Group tracks by dominant color; same-camp tracks on same side
4. Build prompt encoding color split
5. Map track names to visual symbols
6. Choose unifying title color over both zones (gold works well)

## Reference Files in This Skill

| File | Contents |
|------|----------|
| `references/playlist-cover-redo.md` | Full workflow: analyze SC playlist → download track artwork → generate new playlist cover → deliver |
| `references/python3-pil-fix.md` | Fix for missing PIL in overlay step |
| `references/stale-playlist-ids.md` | Detecting and resolving stale SC playlist IDs |
| `references/voidride-animal-motif-covers.md` | Animal/laser eye composition pattern for VØIDRIDE albums |
