---
name: preview-to-album
description: Extends 20-second preview samples into full-length album tracks using the K3 inference pipeline. Handles batch production with live progress, sonic DNA injection, and post-hoc naming. Use when user says "make these into full tracks", "extend to album", "full version", or "produce album".
---

# Preview-to-Album Workflow

When producing samples or full albums, use `produce-album.py` which orchestrates `master-producer.py`
with the full K3 inference pipeline for each track.

## How Tracks Are Made (K3 Inference Pipeline)

### 1. Creative Director (K3, ~$0.03)
- K3 receives: album brief, DJ sonic DNA (prompt_prefix + reference prompts), variation rules, album context (previous tracks)
- K3 produces: JSON plan with title, BPM, key, genre, per-stem prompts and model selections
- **max_tokens: 3000** (K3 needs ~1900 for thinking + JSON — truncation at 1500 was the root cause of prior failures)
- **Prompt validation**: rejects plans with prompts < 30 chars (catches K3's lazy `"..."` placeholders)
- **Fallback**: retries 3x with exponential backoff, switches to qwen-3-7-plus on last retry, then injects sonic DNA prefix

### 2. Prompt Upscaling (qwen-3-7-plus, ~$0.03)
- Each stem prompt is enriched with vivid frequency, spatial, and textural details
- Transforms bare prompts into rich descriptions audio models respond to dramatically better

### 3. Stem Generation (Venice AI audio models, ~$2.08-2.29)
- Main stem: `elevenlabs-music` (instrumental) or `ace-step-15` (structured vocals)
- Texture: `stable-audio-25` — ambient harmonic support
- Accent: `elevenlabs-sound-effects-v2` — short transition SFX
- B-section: Demucs separation creates filtered breakdown from main

### 4. K3 Mix Engineer (qwen-3-7-plus, ~$0.01)
- Analyzes stem spectral data (BPM, key, centroid, RMS)
- Decides per-stem volume, pan, and EQ instead of hardcoded values
- Detects key clashes, frequency masking, spatial separation needs

### 5. Mastering + K3 Quality Controller (~$0.01)
- FFmpeg mastering chain: HP filter → compression → EQ → loudness normalization → limiter → fade
- K3 evaluates final QC metrics against genre benchmarks and DJ reference history
- Produces verdict (pass/marginal/fail), score, issues, suggestions

### Total cost per track: ~$2.37 (audio gen + inference)

## Delivery Rules

- **Samples (≤ 30s)**: Send **MP3 only** to Telegram
- **Full tracks (> 30s)**: Send **MP3 + FLAC** to Telegram
- **One updating message** for the entire batch — no spam
- **HERMES_SILENT=1** propagated to all subprocesses

## Workflow

### Step 1: Produce samples to find the sound
```bash
python3 /opt/data/skills/master-producer/master-producer/scripts/produce-album.py \
  --brief "McNightrideTM - smooth nightride phonk" \
  --tracks 5 --duration 20 --quality quick
```

### Step 2: Produce full tracks from the album brief
```bash
python3 /opt/data/skills/master-producer/master-producer/scripts/produce-album.py \
  --brief "McNightrideTM - smooth nightride phonk, heavy bass buildups and drops, spatial effects" \
  --tracks 5 --duration 180 --quality standard
```

### Step 3: Or replay locked plans from samples
```bash
python3 /opt/data/skills/master-producer/master-producer/scripts/master-producer.py \
  --plan /path/to/production_plan.json \
  --duration 180 --quality standard \
  --prompt "original prompt text"
```

## Batch Tracking

Every batch is saved to `profiles/<slug>/batches/<timestamp>.json` with:
- Album name, date, DJ profile
- Per-track: title, BPM, key, genre, direction, cost, production directory
- K3 QC verdict and score for each track
- Total cost and track count

## Post-Hoc Naming

When K3 fails to provide track titles, unnamed tracks ("Track N") get names via:
1. Venice text API generates evocative 1-3 word names based on track direction
2. Fallback: hardcoded direction-to-name map (e.g., "smooth groove" → "VELVET UNDERTOW")

## Live Progress Reporting

- `master-producer.py` writes phase progress to `/tmp/track_progress_N.json`
- `produce-album.py` spawns background thread that reads every 10s
- Updates single Telegram message with: phase, elapsed time, ETA, cost, completed tracks
- No per-stem or per-phase spam messages

## Quality Tier Upgrades

When going from `quick` (2 stems) to `standard` (3 stems) or `premium` (4 stems):
1. Locked stems (main, texture) → use exact preview prompts
2. Missing stems (accent, atmosphere) → K3 fills these using the locked plan's genre/BPM/key

## Important Notes

- The `--plan` flag ALWAYS overrides `--director`, `--research`, and `--compose`
- Production plans are saved automatically by the K3 Creative Director
- If a preview was made WITHOUT `--director` (legacy mode), produce full tracks fresh
- Batch JSON is saved per DJ in `profiles/<slug>/batches/` for production history
