# Solar Dissolution Scene Template

Derelict satellite silhouette dissolving into violent ultraviolet solar flare over a scorched horizon. Used for HELIOS-DECAY (scorched cosmic phonk, 140-155 BPM, Em).

## Core Concept

- **One object, five stages of dissolution** — each cover shows the same satellite at a progressively more destroyed state
- **Satellite always still partially glowing** — even as it dissolves, white-hot edges and trailing embers show it's not dead yet
- **Violent ultraviolet / deep purple color palette** — the dying sun dominates with UV and purple-white radiation
- **Scorched earth below** — cracked, blackened desert horizon beneath the blazing sky
- **Smoke, ionized particles, and atmospheric haze** — atmospheric consistency across all covers
- **Album cover**: panoramic sweep showing all 5 dissolution stages simultaneously

## Dissolution Stages

| Track | Stage | Satellite State | Key Visual |
|-------|-------|----------------|------------|
| CORONAL FLARE | 1 — First Contact | Mostly intact, solar panels torn, edges glowing white-hot where radiation hits | Solar flare erupts, satellite first touched |
| SOLAR CATHODE | 2 — External Breach | Hull sections dissolved, internal framework exposed, cables trailing, panels half-melted | Cathode-ray arcs, molten metal catching UV |
| RADIATIVE BURN | 3 — Critical Damage | Main body split open, hull plating peeling in radiant strips, skeleton framework | UV furnace fills half the sky |
| ORBITAL GRAVEYARD | 4 — Debris Field | Mostly skeleton, half-melted panels drooping, surrounded by fragments all glowing | Multiple satellite fragments, dying stars |
| SUNSTROKE SHADOW | 5 — Dissolution | Nearly gone, fragmenting shadow disintegrating into pure light | Satellite becomes shadow in the flare, final annihilation |

## Prompt Structure

### Track Prompt Template

```
Dark cinematic 35mm film photography. A [STAGE_DESCRIPTION], thick smoke haze and ionized particle haze, [SUN_DESCRIPTION], [SATELLITE_DESCRIPTION], [ATMOSPHERE]. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNAGE, NO SIGNS, NO CAPTIONS, NO GRAFFITI, NO WORDS ON PAVEMENT.
```

### Album Prompt Template

```
Dark cinematic 35mm film photography. Epic sweeping composition showing the full progression: a derelict satellite silhouette dissolving into a violent ultraviolet solar flare over a scorched horizon. The satellite starts intact on the left and progressively disintegrates across the frame until it becomes a shadow dissolving into pure light on the right. The massive dying sun fills the upper sky with coronal purple-white eruptions. Below, the scorched landscape stretches from cracked blackened desert to glowing ember fields. All five stages of dissolution visible simultaneously in one panoramic frame. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNAGE, NO SIGNS, NO CAPTIONS, NO GRAFFITI, NO WORDS ON PAVEMENT.
```

## Color Mapping

| Album | Track Colors | Album Color |
|-------|-------------|-------------|
| HELIOS-DECAY | #aa44ff, #ff44aa, #ff6600, #7700ff, #ff0044 | #cc00ff |

## Title Position

- **Track covers**: `--bottom` (satellite/solar scene dominates center)
- **Album cover**: centered (no flag)

## Generation Notes

- Use `flux-2-max` model (NOT ideogram-v4, which returns 404)
- Generate at 1024×1024, upscale to 3000×3000
- Venice API returns WebP — convert to PNG with ffmpeg
- Write scripts to files, run via `terminal()` (VENICE_API_KEY not in execute_code sandbox)