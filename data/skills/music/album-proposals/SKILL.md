---
name: album-proposals
description: Album concept generation, taste profile refinement, and pipeline orchestration. Propose albums with AI, refine based on user taste, and handle the full pipeline from selection through production to publishing.
category: music
tags: [album, proposals, pipeline, taste-profile, refine, batch, production, cover-art, artwork, venice-api, image-generation]
---

# Album Proposals — Concept Generation to Production Pipeline

End-to-end system for generating album concepts, refining them based on user taste, and orchestrating production through a multi-phase pipeline.

## Scripts

| Script | Path | Purpose |
|--------|------|---------|
| propose_albums.py | `/opt/data/scripts/propose_albums.py` | Generate/refine album proposals |
| album_pipeline.py | `/opt/data/scripts/album_pipeline.py` | Full production pipeline (needs TELEGRAM_BOT_TOKEN) |
| taste_profile.json | `/opt/data/music/proposals/taste_profile.json` | Auto-populated preference tracker |
| gen_artwork.py | `scripts/gen_artwork.py` | Cover art generation via Venice AI (covers, upscale, waveforms) |

## Proposal Generation

```bash
# Fresh proposals
python3 /opt/data/scripts/propose_albums.py --force

# Anchor to specific themes
python3 /opt/data/scripts/propose_albums.py --force --seed-themes "cyberpunk ronin, nocturnal drift racing"

# Refine existing proposals in a direction
python3 /opt/data/scripts/propose_albums.py --refine "Hurricane apocalypse in SoCal, cars fleeing, Fast & Furious end-of-world vibes"
```

The script generates 5 proposals, each with: album name, track titles, BPM range, key, visual prompt for cover art, and a detailed musical brief.

## Taste Profile System

`/opt/data/music/proposals/taste_profile.json` tracks user preferences automatically:
- **likes**: themes/subgenres the user selected or loved
- **dislikes**: themes/subgenres the user hated or skipped
- **preferred_subgenres**: reinforced via selections
- **rejected_subgenres**: avoided on subsequent runs

Propose_albums.py consults this file when generating new concepts — liked themes get reinforced, disliked themes get avoided. Use `--refine` to iterate without resetting the profile.

## Pipeline Flow (album_pipeline.py)

When the user selects a proposal via Telegram buttons, `album_pipeline.py` handles:
1. **Phase 1 — Produce**: Runs `produce-album.py` with VØIDRIDE sonic DNA enrichment
2. **Phase 2 — Song Review**: Sends MP3s, waits for approval/redo/reject via Telegram inline buttons + flag file polling
3. **Phase 3 — Artwork**: Generates cover via Venice API (grok-imagine-image-quality), overlays titles, waveform art. See `references/cover-art-generation.md` and `scripts/gen_artwork.py` for the detailed workflow and pitfalls.
4. **Phase 4 — Final Review**: Packages release, user decides publish or go back
5. **Phase 5 — Publish**: Uploads to SoundCloud via publish_release.py

## Pipeline vs Direct Production

- **Gateway/Telegram button flow**: `album_pipeline.py` runs autonomously — needs `TELEGRAM_BOT_TOKEN` set in environment
- **Agent/text flow (no Telegram buttons)**: If pipeline fails with `Missing required environment variable: TELEGRAM_BOT_TOKEN`, run `produce-album.py` directly with enriched brief
- **Never run `produce-album.py` when `[pipeline]` notifications are active** — the pipeline is already handling production
- **When producing manually**: Write the brief to a `.sh` script first (handles special characters properly), then `bash` it

## Recovering from Failed Album Production

`produce-album.py` can fail mid-album (credit exhaustion, API errors, timeouts):

1. Find completed tracks: `find /opt/data/music/productions -name "master_*.mp3" | sort`
2. Each completed track has `production_plan.json` (title, BPM, key) and `production_metadata.json`
3. Clean up partial sessions: remove dirs with 0 `master_*.mp3` files
4. Present completed tracks with metadata to the user
5. Let user decide: add credits, use cheaper models, or pause
6. If resuming: write brief to `.sh` script and re-run (tracks regenerate from scratch)

## User Selection Flow (agent/text mode)

1. Run `propose_albums.py --force` or `--refine "direction"`
2. Read the output proposals from `/opt/data/music/proposals/current_proposals.json`
3. Present proposals to user with: album name, subgenre, BPM range, key, visual description
4. User picks one → run `produce-album.py` with enriched brief (include VØIDRIDE sonic DNA from profile)
5. Deliver completed tracks, handle next steps (credits, redo, artwork, publish)

## Cover Art Generation

Cover art is Phase 3 of the pipeline, handled via Venice AI image generation. The detailed workflow, scripts, and hard-won pitfalls live under this skill's sub-files:

| Resource | What it covers |
|----------|---------------|
| `scripts/gen_artwork.py` | Main cover generation script — builds prompts, calls Venice API, upscales, overlays titles, creates waveforms |
| `references/cover-art-generation.md` | Full reference: usage, arguments, how it works, all known pitfalls (system Python vs venv, crop-before-overlay rule, 1500-char prompt limit, 120s upscale timeout, stale SC playlist IDs, SC upload size limits) |
| `references/playlist-cover-redo.md` | Workflow for regenerating playlist covers based on individual track artwork |
| `references/voidride-animal-motif-covers.md` | Animal/laser eye composition pattern for VØIDRIDE albums |
| `references/stale-playlist-ids.md` | Detecting and resolving stale SC playlist IDs after cover upload |
| `references/python3-pil-fix.md` | Fix for missing Pillow in the overlay step |

**Quick reference** — single track cover:
```bash
python3 scripts/gen_artwork.py \
  --title "TRACK TITLE" \
  --genre "dark nightride trap / witch house" \
  --bpm 140 --key "Fm" \
  --notes "Optional scene descriptors"
```

**Key pitfalls to remember:**
- gen_artwork.py calls `overlay-title.py` with system Python3 which lacks PIL — the overlay ALWAYS fails. After gen, crop bg to 3000×3000 and overlay manually with the venv Python
- Must crop to 3000×3000 BEFORE overlaying title, not after (text gets clipped)
- No `--force` flag — delete old files before regenerating
- 1500-char prompt cap — keep `--notes` under ~300 chars
- Spaces in titles become underscores in filenames

For full details on every pitfall and the SC upload workflow, see `references/cover-art-generation.md`.

## ⚠️ Pitfalls

- `album_pipeline.py` **requires** `TELEGRAM_BOT_TOKEN` — silently exits with error if missing
- When producing manually via `produce-album.py`, you MUST enrich the brief with the active profile's sonic DNA (VØIDRIDE constraints: no galloping, no helicopter noise, 808 dominant, etc.)
- Venice may return 402 (insufficient credits) mid-production — check logs for the error
- Write briefs to `.sh` files when they contain special characters — inline bash with complex strings breaks
- Track completion: only check for `master_*.mp3` files — WAV/FLAC alone doesn't mean the track completed successfully
