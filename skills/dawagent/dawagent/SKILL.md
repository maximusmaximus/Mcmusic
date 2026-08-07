---
name: dawagent
description: DAWAGENT orchestrator — delegates complex music production tasks to a specialized Ardour DAW container. Handles multi-track arrangement, deep mixing, plugin automation, stem separation + re-processing, full session construction, and iterative production workflows.
tags: [daw, ardour, orchestration, mixing, mastering, stems, automation, production, lua, osc, session]
---

# DAWAGENT — Ardour DAW Production Agent

Delegates complex, professional-grade music production tasks to a specialized Podman container
running Ardour 8 with Lua scripting and OSC control.

## ⚠️ CRITICAL: When To Use DAWAGENT vs Master-Producer

| Task | Use This |
|------|----------|
| Generate music from a prompt | `master-producer.py` |
| Quick song/beat generation | `master-producer.py --director` |
| Album batch generation | `produce-album.py` |
| **Multi-track arrangement from existing stems** | **DAWAGENT** |
| **Deep mixing with plugin chains** | **DAWAGENT** |
| **Plugin automation curves** | **DAWAGENT** |
| **Stem separation + re-processing** | **DAWAGENT** |
| **Full DAW session construction** | **DAWAGENT** |
| **Precise automation (EQ sweeps, compression, sidechain)** | **DAWAGENT** |
| **Iterative production (import → arrange → mix → export cycle)** | **DAWAGENT** |
| Analyze SoundCloud playlists | `soundcloud-analyzer.py` |
| Analyze playlist → generate inspired tracks | DAWAGENT pipeline (analyze → produce) |

## 🚀 Container Management

### Check if DAWAGENT is running
```bash
podman ps --filter name=dawagent --format "{{.Names}} {{.Status}}"
```

### Start DAWAGENT (if not running)
```bash
cd /app && podman-compose up -d dawagent
```
Or manually:
```bash
podman start dawagent
```

### Health check
```bash
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py health
```

### Full status (JACK, Ardour, sessions)
```bash
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py status
```

## 🎛️ dawctl.py — Command Reference

All commands run via: `podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py <command>`

All output is JSON to stdout.

### Session Management

```bash
# Create a new session
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  session create --name "MySession" --sr 48000 --bpm 120

# List all sessions
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py session list
```

### Track Management

```bash
# Add an audio track
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  track add --session "MySession" --name "Vocals" --type audio

# Add a MIDI track
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  track add --session "MySession" --name "Synth Lead" --type midi

# List tracks in a session
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  track list --session "MySession"
```

### Export

```bash
# Export stems + master
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  export all --session "MySession" --output-dir /opt/dawagent/exports/MySession
```

### Run Custom Lua Scripts

```bash
# Run a bundled Lua script
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  lua --session "MySession" --script init_session

# Run with full path
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  lua --session "MySession" --script /opt/dawagent/lua/mix_balance.lua
```

## 📂 Shared Volumes

| Volume | DAWAGENT Path | Hermes Path | Purpose |
|--------|--------------|-------------|---------|
| `dawagent-sessions` | `/opt/dawagent/sessions` | `/opt/data/dawagent/sessions` | Ardour session files |
| `dawagent-exports` | `/opt/dawagent/exports` | `/opt/data/dawagent/exports` | Exported stems & masters |
| Music library | `/opt/dawagent/imports` (read-only) | `/opt/data/music` | Source audio for import |

## 🎵 Available Lua Scripts

| Script | Purpose |
|--------|---------|
| `init_session.lua` | Create session with standard template |
| `import_audio.lua` | Import audio files to tracks |
| `import_midi.lua` | Import MIDI files to tracks |
| `add_plugin.lua` | Load LV2/CLAP plugin on a track |
| `write_automation.lua` | Write automation curves |
| `mix_balance.lua` | Set fader levels, panning, bus routing |
| `export_session.lua` | Export stems and master bounce |
| `utils.lua` | Common helper functions |

## 🔌 Installed Plugins (LV2)

| Suite | Plugins |
|-------|---------|
| **Calf** | Reverb, EQ, Compressor, Limiter, Phaser, Flanger, Delay, Saturator, Bass Enhancer |
| **LSP** | Parametric EQ, Compressor, Gate, Limiter, Delay, Reverb, Oscilloscope, Spectrum |
| **x42** | Meters, EQ, Delay, Stereo tools, Phase, Tuner |
| **Dragonfly** | Hall Reverb, Room Reverb, Plate Reverb, Early Reflections |

## 🔁 Production Workflows

### Workflow 1: Import Stems → Mix → Export

When the user has existing stems (from master-producer or external):

```bash
# 1. Create session
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  session create --name "remix_project" --sr 48000 --bpm 128

# 2. Add tracks for each stem
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  track add --session "remix_project" --name "Drums" --type audio
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  track add --session "remix_project" --name "Bass" --type audio
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  track add --session "remix_project" --name "Synth" --type audio
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  track add --session "remix_project" --name "Vocals" --type audio

# 3. Import audio stems via Lua
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  lua --session "remix_project" --script import_audio \
  --args "/opt/dawagent/imports/drums.wav" "Drums"

# 4. Apply mixing via Lua
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  lua --session "remix_project" --script mix_balance

# 5. Export final master
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  export all --session "remix_project" --output-dir /opt/dawagent/exports/remix_project
```

### Workflow 2: SoundCloud Analysis → DAWAGENT Production

Full pipeline: analyze reference → generate stems → arrange in DAW → mix → export:

```bash
# 1. Analyze the reference playlist (soundcloud-analyzer)
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  analyze --url "https://soundcloud.com/user/sets/playlist" \
  --telegram-chat CHAT_ID

# 2. Generate stems using master-producer (informed by analysis)
python3 /opt/data/skills/master-producer/master-producer/scripts/produce-album.py \
  --brief "SYNTHESIZED BRIEF FROM ANALYSIS" \
  --tracks 3 --duration 180 --quality standard

# 3. Import generated stems into DAWAGENT session
podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py \
  session create --name "inspired_session" --sr 48000 --bpm 90

# 4. Import, arrange, mix, and export via DAWAGENT
# (run Lua scripts for import, plugin chains, automation, export)
```

### Workflow 3: Iterative Production

Agent-driven iterative refinement:

```
1. Create session → import source material
2. Add plugin chains (EQ → Comp → Reverb per track)
3. Write automation curves
4. Export first draft → review
5. Adjust mix → re-export
6. Final master export
```

## ⛔ Known Constraints

| Constraint | Details |
|-----------|---------|
| **Headless only** | No GUI — all operations via Lua scripts, OSC, or XML manipulation |
| **Offline audio** | JACK dummy backend — no real-time monitoring, offline processing only |
| **Plugin scan** | First run may take time as Ardour scans installed LV2 plugins |
| **Session XML** | Creating from scratch works for simple sessions; complex routing needs Lua |
| **Container volumes** | DAWAGENT only sees mounted volumes — use shared paths for file exchange |
| **No MIDI synthesis** | Ardour needs instrument plugins for MIDI playback — use LV2 synths if needed |

## 💡 Communication Protocol

**Parent → DAWAGENT**: Always via `podman exec dawagent python3 /opt/dawagent/scripts/dawctl.py ...`
**DAWAGENT → Parent**: JSON output from dawctl.py, exported files in shared volumes
**File handoff**: Hermes reads exports from `/opt/data/dawagent/exports/`

**NEVER** connect via MCP — tool namespace collisions. Always use `podman exec`.
