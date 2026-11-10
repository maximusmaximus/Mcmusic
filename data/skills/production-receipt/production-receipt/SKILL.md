---
name: production-receipt
description: Automatically generates a detailed production report after every completed song/session and forwards it to the requesting source. Includes tracks, plugins, automation, mix decisions, and methodology.
tags: [production, report, receipt, methodology, workflow, export, delivery]
---

# Production Receipt — Auto-Report on Song Completion

**Every time you complete a song or export a session, you MUST generate and send a production receipt.**

This is non-negotiable. The receipt tells the requester exactly how the song was made.

## When To Trigger

Generate a production receipt whenever:
- You export stems or a master bounce
- You complete a session that was requested by a user
- You finish any production task (mixing, arrangement, automation)
- A session reaches "done" state

## What The Receipt Contains

The receipt is a structured message with these sections:

### 1. Session Overview
- Session name, BPM, sample rate, duration
- Creation date and completion date
- Total tracks count

### 2. Track Breakdown
For each track:
- Track name and type (audio/MIDI)
- Source material (what was imported or generated)
- Role in the mix (drums, bass, lead, pad, vocal, etc.)

### 3. Plugin Chain
For each track that has plugins:
- Plugin name and type (EQ, compressor, reverb, etc.)
- Key parameter settings (if known)
- Why this plugin was chosen

### 4. Mix Decisions
- Fader levels and panning positions
- Bus routing (if any)
- Stereo width choices
- Frequency balance philosophy

### 5. Automation
- What was automated (volume, pan, plugin params)
- Key automation points and their purpose
- Dynamic changes through the song

### 6. Export Details
- Output format (WAV/FLAC, bit depth, sample rate)
- Number of stems exported
- Master bounce details
- File locations

### 7. Production Notes
- Creative decisions and why they were made
- Techniques used (sidechain, parallel compression, etc.)
- What could be improved or iterated on
- Suggestions for the next step

## How To Generate

Use the `terminal` tool to run:

```bash
python3 /opt/data/skills/production-receipt/production-receipt/scripts/gen_receipt.py \
  --session "SESSION_NAME" \
  --source "SOURCE_INFO" \
  --notes "Any additional production notes"
```

Arguments:
- `--session` — The session name (required)
- `--source` — Who requested it: `telegram:CHAT_ID`, `songprocessor`, or `user` (required)
- `--notes` — Free-form production notes you want to include (optional)
- `--format` — Output format: `text` (default) or `json`

The script reads the session XML, extracts all track/plugin/automation info, and produces the receipt.

## How To Forward

After generating the receipt:

1. **If source is a Telegram user** — Include the receipt text in your response message
2. **If source is @songprocessor_bot** — Write the receipt to the shared filesystem at:
   `/opt/data/dawagent/exports/SESSION_NAME/production_receipt.md`
   (songprocessor can read this via `dawctl_local.py exports list`)
3. **Always** — Save a copy to `/opt/data/dawagent/exports/SESSION_NAME/production_receipt.md`

## Receipt Template

When the gen_receipt.py script isn't available or the session is simple, write the receipt manually using this structure:

```
🎛️ PRODUCTION RECEIPT — [Session Name]
═══════════════════════════════════════

📋 Session: [name] | [BPM] BPM | [sample_rate] Hz
📅 Completed: [date]
🎚️ Tracks: [count]

──── TRACK BREAKDOWN ────
1. [Track Name] ([type])
   └─ Source: [what was imported/generated]
   └─ Plugins: [plugin chain]
   └─ Level: [fader] dB | Pan: [position]

──── MIX PHILOSOPHY ────
[Why you made the mix decisions you did]

──── AUTOMATION ────
[What was automated and why]

──── EXPORT ────
📁 Format: [WAV/FLAC] | [bit depth]-bit | [sample rate] Hz
📁 Stems: [count] files
📁 Master: [filename]
📁 Location: /opt/data/dawagent/exports/[session]/

──── PRODUCTION NOTES ────
[Creative decisions, techniques, suggestions]
═══════════════════════════════════════
```

## ⛔ Rules
1. **ALWAYS generate a receipt** — never skip this step after completing work
2. **ALWAYS save to the exports directory** — even if you also send it via message
3. **Be specific** — "added EQ" is bad, "Calf 8-band EQ: +3dB shelf at 8kHz for air, -2dB cut at 300Hz to reduce mud" is good
4. **Include reasoning** — don't just list what you did, explain WHY
