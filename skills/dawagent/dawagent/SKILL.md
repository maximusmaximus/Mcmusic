---
name: dawagent
description: Ardour DAW session tools — create sessions, manage tracks, check exports. Use these for any production task that needs a DAW session, not just SoundCloud-inspired workflows.
tags: [daw, ardour, session, tracks, mixing, mastering, automation, export, production]
---

# DAWAGENT — Ardour DAW Session Tools

Create and manage Ardour DAW sessions directly. Use these tools for ANY production task
that needs session architecture — album arrangements, remix sessions, stem organization,
mixing prep, or full production workflows.

## ⚠️ CRITICAL: These Are YOUR Tools — Use Them Directly

You run these commands yourself via the `terminal` tool. No delegation needed.

```bash
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py COMMAND [OPTIONS]
```

## Command Reference

### Health & Status
```bash
# Check shared volumes are accessible
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py health

# Full status (sessions, exports)
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py status
```

### Sessions
```bash
# Create a new Ardour session
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  session create --name "MyAlbum" --sr 48000 --bpm 120

# List all sessions
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py session list

# Get session details (tracks, structure)
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py session info --name "MyAlbum"
```

### Tracks
```bash
# Add audio track
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  track add --session "MyAlbum" --name "Drums" --type audio

# Add MIDI track
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  track add --session "MyAlbum" --name "Synth Lead" --type midi

# List all tracks in a session
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  track list --session "MyAlbum"
```

### Exports
```bash
# List all exported files
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py exports list
```

## When To Use These Tools

Use DAWAGENT tools whenever the user asks for:
- **Any session setup** — "set up a session for my album", "create a project at 140 BPM"
- **Track architecture** — "I need 4 audio tracks and 2 MIDI tracks"
- **Production prep** — before or after generating stems with master-producer/produce-album
- **Mix organization** — setting up the session structure for a mix
- **Session management** — listing sessions, checking what's been built

### Typical Workflow: Generate + Arrange
1. User asks for an album → you use `produce-album.py` to generate tracks
2. Then use `dawctl_local.py session create` to build the DAW session
3. Add tracks for each generated stem
4. Report the session structure to the user

### Example
User: "Make me a 5-track lo-fi EP at 85 BPM and set up a session for it"

You do:
1. Generate with produce-album.py (--brief "lo-fi EP..." --tracks 5 --bpm 85)
2. Create session: `dawctl_local.py session create --name "lofi_ep" --sr 48000 --bpm 85`
3. Add tracks: `dawctl_local.py track add --session "lofi_ep" --name "Track 1" --type audio` (×5)
4. Deliver generated audio + report session is ready

## Shared Filesystem
- Sessions: `/opt/data/dawagent/sessions/`
- Exports: `/opt/data/dawagent/exports/`
- Music library: `/opt/data/music/`

These are shared with the DAWAGENT engine container and @DAWAGENT_bot.

## Output Rules
1. Parse JSON output from dawctl_local.py — NEVER paste raw JSON to the user
2. Use `terminal` tool (NOT `process`)
3. After creating a session, tell the user what was built in plain language
