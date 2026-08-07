---
name: producer-profiles
description: Create and manage Producer Profiles — reusable identities with signature sound, default models, mastering presets, and a catalog of linked productions. Select a profile before producing to apply its style automatically.
tags: [profiles, producer, identity, presets, catalog, management, music]
---

# Producer Profiles

Create, manage, and switch between Producer Profiles. Each profile defines a unique sonic identity
with default models, style preferences, mastering settings, and a catalog of productions.

## ⚠️ CRITICAL: How To Use This Skill

**YOU MUST use the `terminal` tool** to run the management script.

```bash
python3 /opt/data/skills/producer-profiles/producer-profiles/scripts/profiles.py ACTION [OPTIONS]
```

## Actions

### Create a new profile
```bash
python3 scripts/profiles.py create \
  --name "Neon Nights" \
  --description "Dark synthwave producer, retro-futuristic soundscapes" \
  --genres "synthwave, darkwave, retrowave" \
  --mood "dark, brooding, atmospheric" \
  --instruments "analog synths, heavy bass, drum machines" \
  --influences "Perturbator, Carpenter Brut, Kavinsky" \
  --prompt-prefix "Dark synthwave, retro-futuristic, analog synthesizers, heavy bass" \
  --main-model elevenlabs-music \
  --quality standard \
  --duration 90 \
  --instrumental
```

### List all profiles
```bash
python3 scripts/profiles.py list
```

### Show profile details
```bash
python3 scripts/profiles.py show --name "Neon Nights"
```

### Select active profile (sets default for future productions)
```bash
python3 scripts/profiles.py select --name "Neon Nights"
```

### Show which profile is active
```bash
python3 scripts/profiles.py active
```

### Update a profile
```bash
python3 scripts/profiles.py update --name "Neon Nights" --mood "euphoric, uplifting" --duration 120
```

### Link a production to a profile's catalog
```bash
python3 scripts/profiles.py link --name "Neon Nights" --file "/opt/data/music/productions/20260706_dark-synth/master_final.mp3" --title "Midnight Runner"
```

### View a profile's catalog
```bash
python3 scripts/profiles.py catalog --name "Neon Nights"
```

### Delete a profile
```bash
python3 scripts/profiles.py delete --name "Neon Nights"
```

### Export a profile (for sharing or backup)
```bash
python3 scripts/profiles.py export --name "Neon Nights"
```

## Using Profiles with Master Producer

When a profile is active, tell the user which profile is selected before producing.
Pass the profile's settings to the master-producer script:

```bash
# Get the active profile's settings as JSON
PROFILE=$(python3 scripts/profiles.py active --json)

# Then use those values with master-producer:
python3 /opt/data/skills/master-producer/master-producer/scripts/master-producer.py \
  --prompt "$(echo $PROFILE | jq -r '.prompt_prefix') User's additional prompt here" \
  --quality "$(echo $PROFILE | jq -r '.defaults.quality')" \
  --duration "$(echo $PROFILE | jq -r '.defaults.duration')" \
  --main-model "$(echo $PROFILE | jq -r '.defaults.main_model')"
```

Or more simply, use the `produce` action which wraps master-producer with profile defaults:
```bash
python3 scripts/profiles.py produce --prompt "a midnight highway chase scene" --lyrics "optional lyrics"
```

## Profile Structure

Each profile is stored at `/opt/data/music/profiles/<slug>/profile.json`:

```json
{
  "name": "Neon Nights",
  "slug": "neon-nights",
  "description": "Dark synthwave producer...",
  "style": {
    "genres": ["synthwave", "darkwave"],
    "mood": "dark, brooding",
    "instruments": "analog synths, heavy bass",
    "influences": "Perturbator, Kavinsky",
    "era": ""
  },
  "defaults": {
    "main_model": "elevenlabs-music",
    "quality": "standard",
    "duration": 90,
    "instrumental": true
  },
  "mastering": {
    "target_lufs": -14,
    "bass_boost_db": 1,
    "presence_boost_db": 2,
    "air_boost_db": 1.5,
    "compression_ratio": 4
  },
  "prompt_prefix": "Dark synthwave, retro-futuristic...",
  "catalog": []
}
```

## Tips for the Agent

1. **When user says "produce" or "make music"** — check if a profile is active first and apply its defaults
2. **When creating profiles** — ask the user about genre, mood, and influences to build a rich prompt_prefix
3. **After a production completes** — it auto-links to the profile's catalog, just mention it briefly
4. **When user asks "who am I"** — show the active profile name and a brief summary, NOT the raw JSON

## ⚠️ OUTPUT RULES

1. **NEVER paste raw JSON** from any profiles.py command into the chat
2. Parse the JSON yourself and respond with a natural, friendly message
3. For `produce`: ONLY send the final mastered file — no stems, no intermediate files
4. For `list`: Summarize profiles naturally: "You have 2 profiles: Neon Nights (active), Lo-Fi Larry"
5. For `create`: "✅ Created 'Neon Nights' — synthwave, dark and brooding. Set as active."
6. **No code blocks, no file paths, no technical details** — keep it musical, not technical
