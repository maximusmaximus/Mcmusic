---
name: master-producer
description: Studio-quality music production with multi-pass K3 inference pipeline. Generates stems via Venice AI models, uses K3 for creative direction, prompt upscaling, intelligent mixing, mastering decisions, and quality control. Creates layered, radio-ready productions from a single prompt.
tags: [music, production, mastering, mixing, studio, stems, multi-model, k3, inference, professional]
---

# Master Producer — AI Studio Production with K3 Inference Pipeline

Orchestrate multiple Venice AI audio models with a multi-pass K3 inference pipeline that makes
intelligent, adaptive decisions at every stage of production instead of using hardcoded defaults.

## ⚠️ CRITICAL: How To Use This Skill

**YOU MUST use the `terminal` tool** to run the script. Generation takes 3-15 minutes depending on quality tier.

### Single Track
```bash
python3 /opt/data/skills/master-producer/master-producer/scripts/master-producer.py \
  --prompt "SONG DESCRIPTION" \
  [--lyrics "LYRICS"] \
  [--quality standard] \
  [--duration 60] \
  [--target streaming] \
  [--chat-id TELEGRAM_CHAT_ID]
```

### Album / Batch (PREFERRED for multiple tracks)
```bash
python3 /opt/data/skills/master-producer/master-producer/scripts/produce-album.py \
  --brief "ALBUM BRIEF" \
  --tracks 5 \
  --duration 180 \
  --quality standard \
  [--vocals-pct 5]
```

**IMPORTANT RULES:**
1. Use `terminal` tool, NOT `process` — this is a long-running multi-step pipeline
2. Warn the user this takes **3-15 minutes per track** and costs ~$2.30/track
3. **ONLY send the final mastered file** to the user, NOT stems or intermediate files
4. **Do NOT paste JSON output** in chat — parse it and respond naturally

## K3 Inference Pipeline (5 Passes)

Every track runs through 5 inference passes. Each pass makes adaptive decisions instead of using
hardcoded defaults. All passes gracefully fall back if inference fails — nothing breaks.

### Pass 1: Creative Director (kimi-k3)
- Receives: album brief, DJ's sonic DNA, reference prompts from best published tracks, variation rules
- Produces: structured JSON plan with per-stem prompts, model selections, BPM, key, title
- **Key detail**: K3 is a thinking model that needs `max_tokens: 3000` (uses ~1200 for reasoning + ~600 for JSON)
- Validates: rejects plans with placeholder prompts (< 30 chars), forces retry
- Fallback: switches to `qwen-3-7-plus` on last retry, then injects sonic DNA prefix

### Pass 1c: Prompt Upscaling (qwen-3-7-plus)
- Receives: each stem prompt from K3's plan
- Produces: enriched version with vivid frequency descriptions, spatial positioning, dynamic characteristics, textural details
- Example: `"145 BPM phonk"` → `"Dark atmospheric phonk at 145 BPM, sub-bass 808 rumbling at 30-60Hz with gritty saturation, wide stereo field with panning hi-hats, punchy snare at center with sharp 2kHz attack, spectral reverb tails fading left to right"`
- Cost: ~$0.01 per stem
- Fallback: uses K3's original prompt unchanged

### Pass 2: Mix Engineer (qwen-3-7-plus)
- Receives: spectral analysis of all generated stems (BPM, key, centroid, RMS energy)
- Produces: per-stem volume, pan position, and EQ (lowpass/highpass) decisions
- Detects: key clashes between stems, frequency masking, spatial separation needs
- Example: `"texture key (Fm) clashes with main (Dm) — applying lowpass at 800Hz to hide dissonance, panning right for space"`
- Cost: ~$0.01 per track
- Fallback: uses STEM_CONFIG hardcoded volumes (main: 1.0, texture: 0.35, accent: 0.25)

### Pass 3: Mastering Engineer (planned, infrastructure ready)
- Receives: mix analysis (LUFS, spectral balance, dynamic range)
- Produces: LUFS target, EQ shape, limiter ratio based on genre conventions
- Example: phonk → -12 LUFS aggressive, ambient → -16 LUFS dynamic
- Fallback: uses target profile defaults (-14 LUFS for streaming)

### Pass 4: Quality Controller (qwen-3-7-plus)
- Receives: final QC report (LUFS, true peak, BPM, key) + DJ reference benchmarks
- Produces: verdict (pass/marginal/fail), score (1-10), specific issues, suggestions for next time
- Stored in: `qc_report.k3_verdict`, `qc_report.k3_score`, `qc_report.k3_suggestions`
- Cost: ~$0.01 per track
- Fallback: standard QC metrics only (no verdict)

### Total Inference Cost
~$0.08/track on top of ~$2.29 audio generation = **3.5% overhead for significantly better quality**

## Production Pipeline (Full)

```
PHASE 0: Creative Director (K3)
  └─ Pass 1c: Prompt Upscaling
PHASE 1: Stem Generation (Venice AI audio models)
  └─ PHASE 1b: B-Section Generation (Demucs separation + filtered breakdown)
  └─ PHASE 1c: Stem Analysis (BPM, key, spectral centroid, RMS)
  └─ PHASE 1d: Per-Stem Effects (Pedalboard processing)
PHASE 2: Mixing (K3 Mix Engineer → ffmpeg)
PHASE 3: Mastering (ffmpeg mastering chain)
  └─ PHASE 3b: Matchering (reference-based mastering, if reference available)
PHASE 4: QC Analysis + K3 Quality Controller
PHASE 5: Delivery (Telegram audio + batch tracking)
```

## Quality Tiers

| Tier | Stems | Est. Time | Est. Cost | Best For |
|------|-------|-----------|-----------|----------|
| `quick` | 2 (main + texture) | 3-5 min | ~$1 | Demos, previews |
| `standard` | 3 (main + texture + accent) | 5-10 min | ~$2.30 | Good quality tracks |
| `premium` | 4 (main + texture + accent + atmosphere) | 8-15 min | ~$3 | Release-ready productions |

## Stem Model Selection

| Stem | Default Model | Role |
|------|--------------|------|
| **Main** | `elevenlabs-music` (instrumental) / `ace-step-15` (structured vocals) | Core track |
| **Texture** | `stable-audio-25` | Ambient harmonic support |
| **Accent** | `elevenlabs-sound-effects-v2` | Short transition SFX |
| **Atmosphere** | `stable-audio-25` | Wide ambient bed |

## DJ Profiles & Sonic DNA

The pipeline loads the active DJ profile from `/opt/data/music/profiles/<slug>/profile.json`.
Profile includes:
- **Sonic DNA**: preferred models, BPM range, keys, genres learned from production history
- **Prompt prefix**: the sonic signature that made the DJ's best tracks sound good
- **Reference prompts**: exact prompts from published tracks for K3 to match quality
- **Catalog**: all past productions with QC metrics for reference benchmarks

## Album Production (produce-album.py)

For batch production of multiple tracks:
- **One updating Telegram message** with phase, elapsed time, ETA, and cost
- **HERMES_SILENT=1** propagated to all subprocesses — zero spam
- **Per-track variation rules** (heavy opener, smooth groove, tempo shift, etc.)
- **Post-hoc naming** via Venice text API for any tracks K3 didn't title
- **Batch tracking** saved to `profiles/<slug>/batches/<timestamp>.json`

### Album Arguments
```
--brief TEXT       Album description
--tracks N         Number of tracks (default: 5)
--duration SECS    Per-track duration (default: 60)
--quality TIER     quick/standard/premium
--vocals-pct N     Percentage of tracks with vocals (default: 0)
--preview          Force MP3-only delivery (no FLAC)
```

## Target Profiles

| Profile | Loudness | Format | Use Case |
|---------|----------|--------|----------|
| `streaming` | -14 LUFS | MP3 320k / FLAC 48k-24bit | Spotify, Apple, YouTube |
| `l-acoustics` | -18 LUFS | AIFF 96k/24-bit + L-ISA stems | L-Acoustics PA rigs |
| `club` | -8 LUFS | WAV 48k/24-bit | Club systems, DJ sets |
| `headphones` | -16 LUFS | FLAC 48k/24-bit | Critical listening |

## Prompt Tips

For best results, describe:
- **Genre & mood**: "dark synthwave, mysterious and brooding"
- **Core instruments**: "analog synths, heavy bass, drum machine"
- **Atmosphere**: "foggy night, neon-lit city streets"
- **Energy arc**: "starts soft, builds to intense climax"
- **Specific effects**: "wide stereo reverb, spatial panning, heavy sidechain"

K3 + prompt upscaling will enhance these into vivid, model-optimized prompts automatically.
