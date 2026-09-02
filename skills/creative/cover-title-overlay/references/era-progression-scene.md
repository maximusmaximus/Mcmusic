# Era Progression Scene Template

Same object aging across 5 historical eras. Cathedral setting with thick incense smoke, the object always still ON and glowing. Used for SIGIL ENGINE and SYNAPSE NECROPOLIS.

## Core Concept

- **One scene, one object, five eras** — each cover shows the same location (cathedral) and the same object (computer or computer-car) at a different point in time
- **Object always still on** — regardless of era, the computing elements still glow/pulse with light
- **Progressive overgrowth** — moss → ivy → ferns → vines → trees as the era gets older
- **Cathedral ages too** — the building itself shows era-appropriate decay and modification
- **Album cover**: all 5 eras visible simultaneously in one sweeping vista

## Era Definitions

| Era | Year | Object State | Cathedral State | Growth |
|-----|------|-------------|-----------------|--------|
| Near Future | 2077 | Pristine holographic, floating data streams, flawless | Immaculate, fiber optic cables through stone, holographic stained glass | None |
| Cold War | 1983 | CRT monitors, beige plastic, dusty, first tiny moss patches | Military cables strung between pillars, some mortar crumbling | Tiny moss at base |
| Mod Era | 1967 | Room-sized mainframe, vacuum tubes, olive-green, moderate ivy | Cracked stone, Mod op-art projections, ivy on walls | Moderate moss and ivy on panels |
| Art Deco | 1924 | Brass & mahogany difference engine, punched cards, ferns in gears | Tarnished brass fixtures, cracked stained glass, geometric engravings | Significant ferns and vines through mechanisms |
| Medieval Gothic | 1347 | Iron & crystal orrery, occult symbols, heavily overgrown, single crystal still pulsing | Ruins, trees growing inside, collapsed roof, centuries of moss | Heavy overgrowth, small trees, nearly consumed |

## Variant A: Computer Only (SIGIL ENGINE)

The computer is a standalone object sitting in the nave — holographic terminal, CRT, mainframe, difference engine, orrery depending on era. No car.

### Track Prompt Template

```
Dark atmospheric cinematic 35mm film photography. Inside a [ERA_DESCRIPTION] cathedral, thick smoke haze and incense filling the nave. A dark sleek nightride interceptor car parked on the stone floor with headlights cutting through [COLOR]-tinged smoke haze. In the center of the nave sits [COMPUTER_DESCRIPTION]. [ERA_SECTOR_PROMPT]. [COLOR_HEX] neon light emanating from the computer through the haze. Cinematic color grading, 35mm film grain, anamorphic lens flare, moody occult dark electronic album cover art, [ERA_STYLE] era aesthetic. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNAGE, NO SIGNS, NO CAPTIONS, NO GRAFFITI, NO WORDS ON PAVEMENT
```

### Album Prompt Template

```
An epic sweeping vista inside a vast gothic cathedral at night, thick smoke haze and incense filling the nave, a dark sleek nightride interceptor car parked on the stone floor with headlights cutting through the [COLOR] incense haze, [FIVE_OBJECTS] visible in the scene arranged in a line from near-future to medieval: [LIST_5_ERAS], each progressively more overgrown with vines and moss than the last, the oldest one nearly consumed by foliage but its [COLOR] crystal still glowing, [COLOR_HEX] neon light emanating from all the computers through the smoke, cathedral vaulted ceiling lost in darkness above, cinematic film photography, atmospheric, moody, occult dark electronic album cover art, NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNAGE, NO SIGNS, NO CAPTIONS, NO GRAFFITI, NO WORDS ON PAVEMENT
```

## Variant B: Hybrid Computer-Car (SYNAPSE NECROPOLIS)

The car IS the computer — the vehicle's body fuses with computing machinery. The same car ages across eras, always still on and glowing.

### Isometric Album Cover Pattern

For album-level covers using the era-progression scene, use an **isometric 3D view from a 30-degree overhead angle** instead of a flat vista. This gives the scene a striking, collectible look that distinguishes the album cover from the track covers.

**Example prompt for isometric album cover:**
```
An isometric 3D view from a 30-degree overhead angle inside a vast gothic cathedral at night.
Thick incense smoke and haze filling the nave. [DESCRIPTION OF ALL ERAS VISIBLE SIMULTANEOUSLY].
[ALBUM_COLOR] neon light emanating from the [OBJECT] through centuries of smoke and haze.
Dark atmospheric cinematic film photography, isometric perspective, moody, occult dark electronic album cover art.
NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS,
NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNAGE, NO SIGNS,
NO CAPTIONS, NO GRAFFITI, NO WORDS ON PAVEMENT
```

Title overlay: **centered vertically** (no `--bottom` flag for album covers).

### Key Prompt Elements

- **2077**: "sleek hybrid computer-car… body a seamless blend of aerodynamic car chassis and holographic display panels, floating data streams emanating from its hood and windshield, pristine and flawless"
- **1983**: "chunky CRT monitors embedded in the dashboard, beige plastic housing panels bolted onto the car's frame, cassette tape drives in the trunk, a slight layer of dust, first tiny tendrils of moss growing at the tire bases"
- **1967**: "massive room-sized mainframe components grafted onto the vehicle, vacuum tubes glowing along the roofline, spinning reel-to-reel tape drives built into the rear, olive-green enameled panels, moderate moss and ivy creeping across the hood and fenders"
- **1924**: "brass and mahogany mechanical computer-car with spinning brass gears visible through opened hood panels, punched card readers built into the doors, ornate Art Deco geometric engravings on brass body panels, significant ferns and vines growing through the wheel arches"
- **1347**: "dark iron and crystal arcanomechanical computing device fused with the car's frame, clockwork gears meshed with occult symbols carved into iron panels, heavily overgrown with thick vines wrapping around the chassis, small trees growing through the engine bay, a single purple crystal at the center of the grille still pulsing with light"

### Album Prompt Template

```
An epic sweeping vista inside a vast gothic cathedral at night, thick smoke haze and incense filling the nave, a single hybrid computer-car parked on the stone floor with headlights cutting through [COLOR]-tinged incense haze, the car IS the computer — its body a fusion of vehicle and computing machine, showing all five eras of its existence simultaneously: a holographic near-future hood (pristine), 1980s CRT dashboard panels (slight dust), 1960s mainframe vacuum tubes along the roofline (moderate ivy), 1920s brass gear mechanisms visible through opened side panels (ferns and vines), and an ancient iron-and-crystal orrery core at its heart (heavily overgrown but still glowing [COLOR]). The cathedral shows all eras too: holographic projections on one wall, Cold War cables draped between pillars, Mod op-art on the ceiling, Art Deco brass fixtures tarnished green, and medieval stone ruins with trees growing through. [COLOR_HEX] and ghostly [ACCENT] light emanating from the car through centuries of smoke and incense haze. Cinematic film photography, atmospheric, moody, occult dark electronic album cover art. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNAGE, NO SIGNS, NO CAPTIONS, NO GRAFFITI, NO WORDS ON PAVEMENT
```

## Color Mapping

| Album | Neon Color | Accent |
|-------|-----------|--------|
| SIGIL ENGINE | #aa00ff (purple) | — |
| SYNAPSE NECROPOLIS | #00ff66 (green) | purple haze |

## Album Cover Perspective Variant

The user may request an **isometric** (30° overhead) view for the album cover instead of the standard sweeping vista. This shifts the composition from a wide panoramic shot to a 3D overhead perspective showing all five eras simultaneously from above.

Isometric prompt pattern — replace the standard album prompt with:
- Start with "An isometric 3D view from a 30-degree overhead angle" instead of "An epic sweeping vista"
- The car/computer remains the central hero object, seen from above at ~30°
- All five eras visible simultaneously arranged around the central object
- Keep the cathedral/setting description
- Center the title vertically (no `--bottom` flag, same as standard album covers)

Example isometric prompt (Variant B — hybrid computer-car):
```
An isometric 3D view from a 30-degree overhead angle inside a vast gothic cathedral at night, thick smoke haze and incense filling the nave, a single hybrid computer-car parked on the stone floor with headlights cutting through [COLOR]-tinged incense haze, the car IS the computer — its body a fusion of vehicle and computing machine, showing all five eras of its existence simultaneously: a holographic near-future hood (...), 1980s CRT dashboard panels (...), 1960s mainframe vacuum tubes (...), 1920s brass gear mechanisms (...), and an ancient iron-and-crystal orrery core (...). [COLOR_HEX] neon light emanating from the car through centuries of smoke and incense haze. Cinematic film photography, isometric perspective, moody, occult dark electronic album cover art. NO TEXT, NO LETTERS, ...
```

## Title Position

- **Track covers**: `--bottom` (scene lives in center, title anchored at bottom)
- **Album cover**: centered (no position flag — default)

## Generation Notes

- ideogram-v4 is **DEPRECATED** (returns 404) — use `flux-2-max` instead (max resolution **1024×1024**)
- Venice API returns **WebP** — convert to PNG with ffmpeg before overlay
- Always upscale from 1024×1024 to 3000×3000 with `ffmpeg -i input.png -vf "scale=3000:3000:flags=lanczos,unsharp=5:5:0.8:5:5:0" output.png`
- Write generation scripts to `/tmp/` files and run via `terminal()` (NOT `execute_code` — VENICE_API_KEY not available in Python sandbox)
- Covers over 10MB need JPG conversion for Telegram delivery: `ffmpeg -y -i cover.png -q:v 2 cover.jpg`