---
name: dawagent
description: DAWAGENT integration — create and manage Ardour DAW sessions directly, or delegate complex production tasks to the autonomous @DAWAGENT_bot agent on Telegram.
tags: [daw, ardour, orchestration, mixing, mastering, stems, automation, production, session, delegation]
---

# DAWAGENT — Ardour DAW Production Integration

You have TWO ways to work with DAWAGENT:

1. **Direct session management** — Create/edit Ardour sessions locally via shared volumes (fast, no delegation needed)
2. **Delegate to @DAWAGENT_bot** — For complex multi-step production that needs the Ardour engine (Lua scripts, plugin chains, exports)

## 🔧 Method 1: Direct Session Management (Use This First)

You can create and manage Ardour sessions directly using the bundled scripts.
These work on the shared filesystem — no external container access needed.

**ALL commands use the `terminal` tool:**

```bash
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py COMMAND [OPTIONS]
```

### Health & Status
```bash
# Check shared volumes are accessible
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py health

# Full status (sessions, exports)
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py status
```

### Session Management
```bash
# Create a new session
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  session create --name "MySession" --sr 48000 --bpm 120

# List all sessions
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py session list

# Get session details
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py session info --name "MySession"
```

### Track Management
```bash
# Add audio track
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  track add --session "MySession" --name "Drums" --type audio

# Add MIDI track
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  track add --session "MySession" --name "Synth Lead" --type midi

# List tracks
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py \
  track list --session "MySession"
```

### Check Exports
```bash
# List exported files from DAWAGENT
python3 /opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py exports list
```

### Exported files are at:
`/opt/data/dawagent/exports/SESSION_NAME/`

## 📞 Method 2: Delegate to @DAWAGENT_bot (Complex Tasks)

For tasks that need the full Ardour engine (Lua scripts, LV2 plugin processing, audio rendering, export):

**Tell the user to message @DAWAGENT_bot on Telegram** with their complex production request.

@DAWAGENT_bot is an autonomous agent with:
- Ardour 8.4.0 headless engine (JACK2 + Xvfb)
- 30+ LV2 plugins (Calf, LSP, x42, Dragonfly Reverb)
- Lua scripting for session automation
- Venice AI reasoning (GLM 5.1)

### When to Delegate vs Handle Locally

| Task | Method |
|------|--------|
| Create session (BPM, sample rate) | **Local** — `dawctl_local.py session create` |
| Add/list tracks | **Local** — `dawctl_local.py track add/list` |
| View session structure | **Local** — `dawctl_local.py session info` |
| Check exports | **Local** — `dawctl_local.py exports list` |
| Import audio into tracks | **Delegate** → @DAWAGENT_bot |
| Add LV2 plugin chains | **Delegate** → @DAWAGENT_bot |
| Write automation curves | **Delegate** → @DAWAGENT_bot |
| Run Lua scripts in Ardour | **Delegate** → @DAWAGENT_bot |
| Render/bounce/export audio | **Delegate** → @DAWAGENT_bot |
| Complex multi-step mixing | **Delegate** → @DAWAGENT_bot |

### How to Delegate
When the user asks for something that needs the Ardour engine, respond like:

"🎛️ This needs the Ardour engine for [plugin processing / audio rendering / etc.]. I've set up the session structure here — now let's hand it to **@DAWAGENT_bot** for the heavy lifting. Send it this message:

*'Process session [SessionName] — [describe the task]'*"

### Shared Filesystem
Both agents share the same volumes:
- Sessions: `/opt/data/dawagent/sessions/`
- Exports: `/opt/data/dawagent/exports/`

So a session you create here is immediately visible to @DAWAGENT_bot, and any exports it produces are readable from here.

## ⛔ Rules
1. **NEVER try to run `podman exec`** — you're inside a container, that doesn't work
2. **Parse JSON output** from dawctl_local.py and respond naturally — NEVER paste raw JSON
3. **Use `terminal` tool** for all commands (NOT `process`)
4. Sessions created here ARE visible to the Ardour engine automatically via shared volumes
