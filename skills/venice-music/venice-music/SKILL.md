---
name: venice-music
description: Generate music, songs, sound effects, and audio using the Venice AI audio generation API. Supports 6 models for vocals, instrumentals, ambient, and foley. Handles the full async queue lifecycle (queue → poll → retrieve → complete).
tags: [music, audio, venice, generation, songs, sound-effects, instrumental, foley]
---

# Venice Music Generation

Generate music, songs, sound effects, and audio using the Venice AI platform.

## ⚠️ CRITICAL: How To Use This Skill

**YOU MUST use the `terminal` tool** to run the script. Do NOT use `process` — it cannot handle long-running commands.

```bash
python3 /opt/data/skills/venice-music/venice-music/scripts/venice-music.py \
  --model MODEL_ID \
  --prompt "DESCRIPTION" \
  [--lyrics "LYRICS"] \
  [--duration SECONDS] \
  [--instrumental] \
  [--output /opt/data/music] \
  [--chat-id TELEGRAM_CHAT_ID]
```

**You MUST always pass `--chat-id`** with the user's Telegram chat ID so they receive live progress updates.

**IMPORTANT RULES:**
1. Use `terminal` tool, NOT `process` — generation takes 30-300 seconds
2. Do NOT use `curl` to call the Venice Audio API directly — the script handles everything
3. The script outputs JSON to stdout — parse it yourself to get the `"file"` path
4. Tell the user which model you selected BEFORE starting generation
5. Warn that generation takes 1-5 minutes depending on model and duration

**OUTPUT DELIVERY RULES:**
1. **Do NOT paste the JSON output** in the chat — parse it and respond naturally
2. **Do NOT show the terminal command, script logs, or code** to the user
3. After the script finishes, extract `"file"` from the JSON, send the file, and write a brief message:
   "🎵 Here's your [genre] track! Generated with [model]."
4. That's it — no code blocks, no file paths, no technical output

## Model Selection Guide

### 1. Song with Vocals + Lyrics
**User says:** "write me a song", "sing these lyrics", provides lyrics text
- **Use:** `minimax-music-v2` — Best for lyrics + music
- **Fallback:** `ace-step-15` — Supports lyrics, outputs FLAC
- **⛔ NOT `elevenlabs-music`** — Venice API rejects `lyrics_prompt` for this model
- **Set:** `--lyrics "user's lyrics here"`
- **⛔ Do NOT pass `--duration`** with minimax-music-v2

### 2. Song Without Specific Lyrics (Style/Genre)
**User says:** "make a rock song", "create a dance track"
- **Use:** `minimax-music-v2` — Great stylistic cohesion
- **Fallback:** `elevenlabs-music` with `--duration`
- **⛔ Do NOT pass `--duration`** with minimax-music-v2

### 3. Instrumental Only
**User says:** "instrumental", "no vocals", "just the music"
- **Use:** `elevenlabs-music` with `--instrumental`
- **Fallback:** `stable-audio-25`

### 4. Long/Complex Song Structure
**User says:** "3 minute song", "full track with intro/verse/chorus"
- **Use:** `ace-step-15` — Best for long-form structure, FLAC output
- **⛔ ace-step-15 ONLY accepts durations:** 60, 90, 120, 150, 180, or 210 seconds

### 5. Ambient / Soundscapes / Loops
**User says:** "ambient", "background music", "soundscape", "loop"
- **Use:** `stable-audio-25` — Max 180 seconds, WAV output
- **Note:** This model is slow (~3-4 min generation time)

### 6. Sound Effects / Foley
**User says:** "sound effect", "foley", specific sounds
- **Use:** `elevenlabs-sound-effects-v2` (fast, realistic)
- **Fallback:** `mmaudio-v2-text-to-audio` (diverse but slow)
- **⛔ Do NOT pass `--duration`** — auto-determined

### 7. Cinematic Audio Cues
**User says:** "cinematic", "movie score", "transition", "whoosh"
- **Use:** `mmaudio-v2-text-to-audio`
- **⛔ Do NOT pass `--duration`** — auto-determined

## ⛔ Known Pitfalls (API Constraints)

| Constraint | Details |
|-----------|---------|
| `elevenlabs-music` + `--lyrics` | **400 error.** Venice rejects lyrics_prompt for this model |
| `minimax-music-v2` + `--duration` | **400 error.** This model auto-determines length |
| `ace-step-15` duration | **Only accepts 60/90/120/150/180/210.** Other values = 400 error |
| SFX models + `--duration` | **Ignored.** SFX models auto-determine clip length |
| `stable-audio-25` speed | **Slow.** Expect 3-4 minutes generation time |
| `mmaudio-v2-text-to-audio` speed | **Very slow.** 2-3 minutes for short clips |

## Output Formats

| Model | Format | Quality |
|-------|--------|---------|
| `elevenlabs-music` | MP3 | Good |
| `minimax-music-v2` | MP3 | Good |
| `ace-step-15` | FLAC | Lossless (best) |
| `stable-audio-25` | WAV | Uncompressed (best) |
| `elevenlabs-sound-effects-v2` | MP3 | Good |
| `mmaudio-v2-text-to-audio` | MP3 | Good |

## Script Output (JSON on stdout)

Success:
```json
{"success": true, "file": "/opt/data/music/20260706_143022_elevenlabs-music.mp3", "model": "elevenlabs-music", "duration_requested": 60, "generation_time_seconds": 45.2}
```

Error:
```json
{"success": false, "error": "Detailed error message"}
```

## Prompt Tips

**Music:** Include genre + mood + instruments + tempo
- ✅ "Lo-fi hip hop, melancholic mood, vinyl crackle, soft drums, slow tempo"
- ❌ "Make some music"

**Sound Effects:** Be specific about sound + environment
- ✅ "Glass breaking in an empty warehouse with echo"
- ❌ "Breaking sound"

**Lyrics:** Use structure tags: `[Intro]`, `[Verse]`, `[Chorus]`, `[Bridge]`, `[Outro]`

## Examples

```bash
# Song with lyrics (minimax — NO --duration!)
python3 /opt/data/skills/venice-music/venice-music/scripts/venice-music.py \
  --model minimax-music-v2 \
  --prompt "Fast punk rock, distorted guitars" \
  --lyrics "[Verse] Bugs in the code [Chorus] We code till dawn"

# Instrumental (elevenlabs — with --duration and --instrumental)
python3 /opt/data/skills/venice-music/venice-music/scripts/venice-music.py \
  --model elevenlabs-music \
  --prompt "Epic orchestral cinematic trailer music" \
  --instrumental --duration 90

# Ambient (stable-audio — with --duration)
python3 /opt/data/skills/venice-music/venice-music/scripts/venice-music.py \
  --model stable-audio-25 \
  --prompt "Peaceful ambient, gentle rain, warm pad synth" \
  --duration 60

# Sound effect (no --duration!)
python3 /opt/data/skills/venice-music/venice-music/scripts/venice-music.py \
  --model elevenlabs-sound-effects-v2 \
  --prompt "Sci-fi door opening with hydraulic hiss"
```
