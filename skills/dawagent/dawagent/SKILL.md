---
name: dawagent
description: DAW Agent orchestration skill — bridges SoundCloud playlist analysis with music production. Analyze a playlist's sonic DNA, then generate original tracks inspired by it. The full analyze → understand → create pipeline.
tags: [daw, orchestration, soundcloud, analysis, production, workflow, pipeline, inspiration]
---

# DAWAGENT — SoundCloud Analysis → Music Production Pipeline

Orchestrates the full creative pipeline: analyze a SoundCloud playlist's sonic DNA, understand its
patterns, then generate original music inspired by it using the production pipeline.

## ⚠️ CRITICAL: How To Use This Skill

This is an **orchestration skill** — it tells you HOW to chain the soundcloud-analyzer and
master-producer/produce-album skills together. There is no single script to run.
You execute each step sequentially using the `terminal` tool.

**YOU MUST follow the pipeline in order. Do NOT skip steps.**

## 🎯 When To Use DAWAGENT

**User says any of:**
- "analyze this playlist and make something like it"
- "make music inspired by this SoundCloud playlist"
- "study this playlist and produce tracks in the same style"
- "what's the vibe of this playlist? now make me something similar"
- "reverse engineer this playlist's sound"
- Sends a SoundCloud URL + asks for original production

**Do NOT use for:**
- Just analyzing a playlist (use soundcloud-analyzer directly)
- Just producing music without a reference playlist (use master-producer directly)
- Searching existing analyzed tracks (use soundcloud-analyzer search directly)

## 🔁 The DAWAGENT Pipeline

### Step 1: ANALYZE — Extract the playlist's sonic DNA

```bash
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  analyze \
  --url "SOUNDCLOUD_PLAYLIST_URL" \
  --telegram-chat CHAT_ID
```

Parse the JSON output. Extract:
- `commonalities.genre_distribution` → dominant genres + weights
- `commonalities.production_patterns` → shared production techniques
- `commonalities.mood_progression` → emotional arc
- `commonalities.common_themes` → thematic threads
- `commonalities.recommended_context` → listening context
- `commonalities.unifying_elements` → what ties the tracks together
- Per-track `mood_tags`, `energy_level`, `bpm_estimate`, `key_signature_estimate`, `instrumentation`

**Tell the user:**
"🔍 Analyzed *[playlist_title]* — [track_count] tracks. Dominant vibe: [top genres], [top moods]. Now generating original tracks inspired by this DNA..."

### Step 2: SYNTHESIZE — Build a production brief from the DNA

Using the analysis data, construct a `--brief` for `produce-album.py` that captures the
playlist's essence. Your brief MUST include:

1. **Genre blend** — weighted from `genre_distribution` (e.g., "60% lo-fi hip-hop, 25% ambient electronica, 15% downtempo")
2. **Mood palette** — aggregated from all track `mood_tags` (e.g., "melancholic, introspective, nocturnal, dreamy")
3. **BPM range** — from the min/max `bpm_estimate` across tracks (e.g., "75-95 BPM")
4. **Key tendencies** — most common keys (e.g., "lean toward minor keys, especially D minor and A minor")
5. **Instrumentation DNA** — most frequent instruments across tracks (e.g., "Rhodes piano, vinyl crackle, tape-saturated drums, lush pad synths, subtle sub-bass")
6. **Production style** — from `production_patterns` (e.g., "lo-fi warmth, heavy reverb, tape saturation, side-chain pumping")
7. **Energy arc** — from `mood_progression` (e.g., "starts contemplative, builds slowly, peaks with emotional intensity, resolves gently")
8. **Listening context** — from `recommended_context` (e.g., "late-night study sessions, rainy day contemplation")
9. **DO NOT COPY** — add: "Create ORIGINAL compositions inspired by this sonic palette. Do not recreate or sample existing tracks."

### Step 3: PRODUCE — Generate the album

```bash
python3 /opt/data/skills/master-producer/master-producer/scripts/produce-album.py \
  --brief "YOUR SYNTHESIZED BRIEF FROM STEP 2" \
  --tracks N \
  --duration SECONDS \
  --quality standard \
  [--vocals-pct 0]
```

**Track count guidance:**
- User wants "a few tracks" → `--tracks 3`
- User wants "an EP" → `--tracks 5`
- User wants "a full set" → `--tracks 8-10`
- Default if unspecified → `--tracks 5`

**Duration guidance:**
- Match the average duration from the analyzed playlist
- Default → `--duration 180` (3 min)

### Step 4: REPORT — Deliver with context

After production, tell the user:

"🎵 **[Album Title]** — [N] original tracks inspired by *[playlist_title]*

Sonic DNA extracted from [track_count] tracks:
• Genres: [top genres]
• Mood: [mood palette summary]
• BPM range: [range]
• Signature sounds: [top 3-4 instruments]

[Then send the files as normal per output rules]"

## 🔍 Bonus: Search + Produce

If the user has ALREADY analyzed playlists and wants to produce based on a search:

### Step 1: Search
```bash
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  search \
  --query "USER'S DESCRIPTION" \
  --top-k 10
```

### Step 2: Use the search results as inspiration
Extract mood_tags, genres, descriptions from the top results and build a production brief.

### Step 3: Produce
Same as Step 3 above.

## 📋 Quick Reference: Available Commands

### SoundCloud Analyzer
| Command | Script | Key Args |
|---------|--------|----------|
| Analyze playlist | `soundcloud-analyzer.py analyze` | `--url URL --telegram-chat ID` |
| Search tracks | `soundcloud-analyzer.py search` | `--query "TEXT" --top-k N` |
| Describe playlist | `soundcloud-analyzer.py describe` | `--playlist-id N` |
| List playlists | `soundcloud-analyzer.py list` | (none) |

Script path: `/opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py`

### Music Production
| Command | Script | Key Args |
|---------|--------|----------|
| Single track | `master-producer.py` | `--prompt "..." --director --chat-id ID` |
| Album/batch | `produce-album.py` | `--brief "..." --tracks N --duration S` |
| Quick SFX | `venice-music.py` | `--model MODEL --prompt "..."` |

Script paths:
- `/opt/data/skills/master-producer/master-producer/scripts/master-producer.py`
- `/opt/data/skills/master-producer/master-producer/scripts/produce-album.py`
- `/opt/data/skills/venice-music/venice-music/scripts/venice-music.py`

## ⛔ Known Pitfalls

| Constraint | Details |
|-----------|---------|
| Private playlists | soundcloud-analyzer can only access **public** SoundCloud playlists |
| Large playlists | 50+ tracks = 10-20 min analysis time. Warn the user. |
| Brief length | produce-album.py brief should be 200-500 words. Don't dump raw JSON into it. |
| Originality | NEVER tell the production pipeline to "recreate" or "copy" specific tracks. Say "inspired by" |
| Sequential | You MUST wait for analysis to complete before producing. Don't run them in parallel. |
| Cost | Analysis is cheap (LLM + embeddings). Production is ~$2.30/track. Warn for large batches. |

## Example: Full Pipeline

**User:** "Analyze this playlist and make me 5 tracks like it: https://soundcloud.com/chillhop-music/sets/chillhop-essentials-fall-2024"

**You do:**

1. Analyze:
```bash
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  analyze --url "https://soundcloud.com/chillhop-music/sets/chillhop-essentials-fall-2024" \
  --telegram-chat 8293122782
```

2. Parse the output, then produce:
```bash
python3 /opt/data/skills/master-producer/master-producer/scripts/produce-album.py \
  --brief "5-track EP inspired by a chillhop/lo-fi playlist. Genre blend: 55% lo-fi hip-hop, 30% jazzhop, 15% downtempo. Mood: warm, nostalgic, cozy, autumnal, contemplative. BPM range: 75-90. Lean toward minor keys (Dm, Am, Em). Instrumentation: dusty vinyl crackle, Rhodes electric piano, muted jazz guitar, tape-saturated boom-bap drums, warm sub-bass, gentle brass samples, rain/nature foley. Production style: lo-fi warmth, heavy tape saturation, side-chain pumping, vintage compressor coloring, subtle bitcrushing. Energy arc: opens gently, middle tracks groove harder, closes with a meditative outro. Listening context: autumn study sessions, rainy afternoon cafe. Create ORIGINAL compositions inspired by this sonic palette." \
  --tracks 5 \
  --duration 180 \
  --quality standard \
  --vocals-pct 0
```

3. Deliver the 5 mastered tracks with a summary.
