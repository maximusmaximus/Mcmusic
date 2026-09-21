---
name: album-proposals
description: Album concept generation, taste profile refinement, and pipeline orchestration. Propose albums with AI, refine based on user taste, and handle the full pipeline from selection through production to publishing.
category: music
tags: [album, proposals, pipeline, taste-profile, refine, batch, production]
---

# Album Proposals — Concept Generation to Production Pipeline

End-to-end system for generating album concepts, refining them based on user taste, and orchestrating production through a multi-phase pipeline.

## Scripts

| Script | Path | Purpose |
|--------|------|---------|
| propose_albums.py | `/opt/data/scripts/propose_albums.py` | Generate/refine album proposals |
| album_pipeline.py | `/opt/data/scripts/album_pipeline.py` | Full production pipeline (needs TELEGRAM_BOT_TOKEN) |
| taste_profile.json | `/opt/data/music/proposals/taste_profile.json` | Auto-populated preference tracker |

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
3. **Phase 3 — Artwork**: Generates cover via the `artwork` skill (Venice AI → upscale → title overlay → waveform banner). Load `skill_view(name='artwork')` for the detailed workflow and pitfalls.
4. **Phase 4 — Final Review**: Packages release, user decides publish or go back
5. **Phase 5 — Publish**: Uploads to SoundCloud via publish_release.py

## Pipeline vs Direct Production

- **Gateway/Telegram button flow**: `album_pipeline.py` runs autonomously — needs `TELEGRAM_BOT_TOKEN` set in environment
- **Agent/text flow (no Telegram buttons)**: If pipeline fails with `Missing required environment variable: TELEGRAM_BOT_TOKEN`, run `produce-album.py` directly with enriched brief
- **Never run `produce-album.py` when `[pipeline]` notifications are active** — the pipeline is already handling production
- **When producing manually**: Write the brief to a `.sh` script first (handles special characters properly), then `bash` it
- **Execution strategy for multi-track albums**: 5-track albums at `standard` quality and `--duration 180` can exceed 600s (the foreground timeout limit). Use **background mode** for >3 tracks:
  ```bash
  # Write brief to .sh, then run in background:
  terminal(command="bash /path/to/brief.sh", background=true, notify_on_complete=true, timeout=1200)
  ```
  For 2-3 tracks or `--duration 60`, foreground is fine with `timeout=600`.
- **`--chat-id` when running manually**: When `TELEGRAM_BOT_TOKEN` is missing, `--chat-id` is ignored. Don't bother passing it — there'll be no Telegram progress updates. Inform the user the album is being produced and deliver all tracks at once when done.

## Recovering from Failed Album Production

`produce-album.py` can fail mid-album (credit exhaustion, API errors, timeouts):

1. Find completed tracks: `find /opt/data/music/productions -name "master_*.mp3" | sort`
2. Each completed track has `production_plan.json` (title, BPM, key) and `production_metadata.json`
3. Clean up partial sessions: remove dirs with 0 `master_*.mp3` files
4. Present completed tracks with metadata to the user
5. Let user decide: add credits, use cheaper models, or pause
6. If resuming: write brief to `.sh` script and re-run (tracks regenerate from scratch)

## User Selection Flow (agent/text mode)

**⚠️ CRITICAL: LOAD THIS SKILL FIRST.**  
Before presenting proposals to the user, you MUST have loaded this skill via `skill_view(name='album-proposals')` and followed the formatting below. The user expects a specific presentation style and will correct you if you guess the format. Do not present proposals in a raw JSON dump, in a flat list, or in any format not documented here.

1. Run `propose_albums.py --force` or `--refine "direction"`
2. Read the output proposals from `/opt/data/music/proposals/current_proposals.json`
3. **Present proposals in a clean numbered format** — the user expects inline-style selection like buttons. Format each as:

   ```
   **[N] [EMOJI] [ALBUM NAME]**
   *[subgenre]*
   [BPM range] BPM · [Key]
   Tracks: [TRACK 1] · [TRACK 2] · [TRACK 3] · [TRACK 4] · [TRACK 5]
   *[One-line visual description]*
   ```

   - Use a distinct emoji per proposal for visual scanning
   - Keep it compact — the visual description is one short line, not a paragraph
   - End with "Just tell me which number" to drive selection
   - Highlight the best match with a ★ marker and brief reasoning

4. User picks one → run `produce-album.py` with enriched brief (include VØIDRIDE sonic DNA from profile)
5. Deliver completed tracks, handle next steps (credits, redo, artwork, publish)

   **When TELEGRAM_BOT_TOKEN is missing**: The buttons/ratings flow from `album_pipeline.py` is unavailable (the script will log "No TELEGRAM_BOT_TOKEN, skipping send" — ignore this). Present proposals in the numbered format above and have the user type their choice number. Do NOT mention buttons or the pipeline — just handle the selection yourself.

## Cover Art Generation

Cover art is Phase 3 of the pipeline, handled via the **`artwork`** skill. Load `skill_view(name='artwork')` for the full workflow:

- **Script:** `scripts/gen_artwork.py` — builds prompts, calls Venice API, upscales, overlays titles, creates waveforms
- **References:** cover-art-generation.md, playlist-cover-redo.md, voidride-animal-motif-covers.md, stale-playlist-ids.md, python3-pil-fix.md, waveform-from-upscaled.md

**Quick reference:**
```bash
python3 /opt/data/skills/creative/artwork/scripts/gen_artwork.py \
  --title "TRACK TITLE" \
  --genre "dark nightride trap / witch house" \
  --bpm 140 --key "Fm" \
  --notes "Optional scene descriptors"
```

## ⚠️ Pitfalls

- `album_pipeline.py` **requires** `TELEGRAM_BOT_TOKEN` — silently exits with error if missing
- When producing manually via `produce-album.py`, you MUST enrich the brief with the active profile's sonic DNA (VØIDRIDE constraints: no galloping, no helicopter noise, 808 dominant, etc.)
- Venice may return 402 (insufficient credits) mid-production — check logs for the error
- Write briefs to `.sh` files when they contain special characters — inline bash with complex strings breaks
- Track completion: only check for `master_*.mp3` files — WAV/FLAC alone doesn't mean the track completed successfully
- **Timeout on multi-track albums**: 5 tracks at `standard` quality takes 8-15 minutes total, exceeding the 600s foreground timeout. Use `background=true, notify_on_complete=true` for >3 tracks. See "Execution strategy" above.
- **No `--resume` flag**: produce-album.py always starts from scratch — there is no resume-from-track-N option. If a production fails mid-way, clean up empty directories (those with 0 master_*.mp3 files), inform the user, and re-run the full brief. Tracks will regenerate with different titles and sonic variations.
