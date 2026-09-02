# Cherenkov Reactor Containment Scene Template

Used for: CHERENKOV-HORIZON (nuclear witch house album)
Visual theme: Flooded reactor containment vessel glowing with intense Cherenkov blue light, with VØIDRIDE night-riding motifs (cars, fedora silhouette, fog, headlights through mist).

## Per-Track Scene Variants

| Track | Car | Character | Scene Focus | Neon Color |
|-------|-----|-----------|-------------|------------|
| Opener | Black Cadillac | Fedora silhouette, smoking cigar, fog | Intense Cherenkov glow flooding up, headlights through blue fog | `#0088ff` |
| Smooth groove | Silver Ford Mustang | Fedora silhouette holding katana, smoke | Inner core glow, graphite blocks, fog drifting | `#00aaff` |
| Different lead | Grey Lincoln Continental | Fedora silhouette smoking cigar, fissure light | Fissure in wall, headlights through mist, geometric echo patterns | `#0044ff` |
| Tempo shift banger | Burgundy Dodge Charger | Fedora silhouette holding katana, ionized fog | Control room, green-blue ionized air, headlights sweeping dead consoles | `#00ffaa` |
| Cinematic closer | Obsidian Imperial Crown | Fedora silhouette smoking cigar across water, faint ember | Still water, memorial stillness, headlights through fog, moonlight | `#0066cc` |

Album cover: Centered title, all 5 cars stacked at different angles/positions throughout the reactor, fedora+katana silhouette, Cherenkov blue fog. Use `#0088ff`.

## Scene Prompt Template (Per Track)

Each track includes an **out-of-place car** parked inside the reactor, a **silhouetted man in black with a fedora** (sometimes with katana, sometimes smoking a cigar), **thick fog/steam**, and **headlights cutting through the mist** — all interior to the containment vessel.

```
Dark atmospheric cinematic 35mm film photography at night.
Inside a flooded nuclear reactor containment vessel, [CHERENKOV/BLUE GLOW DETAIL].
Thick swirling fog and radioactive steam [RISING/DRIFTING/HANGING].
A [CAR MODEL] is parked [POSITION], completely out of place inside the reactor,
its headlights cutting through the dense blue fog creating dramatic volumetric light beams.
A man dressed all in black wearing a fedora hat [HOLDING A KATANA / SMOKING A CIGAR]
stands as a dark silhouette [POSITION], partially obscured by fog.
[TRACK-SPECIFIC ARCHITECTURAL DETAIL — concrete, rebar, scaffolding, water].
Nuclear witch house album cover. Cinematic color grading, 35mm film grain,
[anamorphic lens flare]. Deep shadows with [HIGHLIGHT COLOR] highlights.
NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS,
NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNAGE,
NO SIGNS, NO CAPTIONS, NO GRAFFITI, NO WORDS ON PAVEMENT,
NO WORDS ON GROUND, NO PAINTED MARKINGS THAT LOOK LIKE LETTERS.
```

### Album Cover Prompt Pattern

For the album cover, stack **all 5 cars** at different positions and angles throughout the reactor composition — this creates a striking visual density that's distinct from the per-track single-car focus:

```
An epic sweeping vista at night inside a flooded nuclear reactor containment vessel.
[CHERENKOV GLOW + ARCHITECTURE + FOG]. FIVE different parked cars arranged in a dramatic
layered composition, stacked at different angles and directions throughout the reactor:
a [Car 1] in the foreground pointing [direction], a [Car 2] behind it angled [direction],
a [Car 3] further back [position], a [Car 4] on the side [direction],
and a [Car 5] in the deep background. All cars completely out of place.
Their headlights cut through the dense blue fog creating crossing volumetric light beams
in different directions. [FEDORA + KATANA SILHOUETTE DETAIL].
[MOONLIGHT/ADDITIONAL LIGHT]. Nuclear witch house album cover.
Cinematic color grading, 35mm film grain, anamorphic lens flare, epic scale.
HDR contrast, deep shadows with piercing blue highlights.
NO TEXT, ... [full negation list]
```

## Key Differences from Other VØIDRIDE Scene Types

- **Cars and characters ARE present** — this is NOT a pure architectural scene. The out-of-place car and fedora silhouette inside the reactor are intentional surreal juxtaposition
- **Fog and headlights are critical** — always describe fog/steam and headlights cutting through the mist as volumetric light beams
- **Night interior** — all scenes are at night inside the containment vessel (not exterior nightride road)
- **Cherenkov glow replaces lightning** — the blue radiation glow is the primary light source, not lightning
- **Water is present** — flooded reactor floor, not dry asphalt
- **Architecture: scaffolding, concrete, rebar** — containment vessel geometry as setting
- **Color palette is blue-dominant** — Cherenkov blue (#0088ff range) as primary, with track-specific accents
- **Extended negation list** — always include `NO WORDS ON GROUND, NO PAINTED MARKINGS THAT LOOK LIKE LETTERS` in addition to standard no-text negation
- **Album cover stacks all cars** — unlike other VØIDRIDE albums where the album cover shows a wider scene with one car, CHERENKOV-HORIZON's album cover has all 5 cars positioned throughout the reactor at different angles

## Generation Settings

- Model: `flux-2-max` (do NOT use ideogram-v4, returns 404)
- Resolution: 1024×1024 (max for flux-2-max)
- Upscale: ffmpeg Lanczos to 3000×3000 with unsharp filter
- Title position: `--bottom` for track covers, centered for album cover
- Font: Open Sans Bold via `overlay-title.py`

## Per-Track Complete Prompts (reference)

These are the finalized prompts from the CHERENKOV-HORIZON session. Use them as examples when building future nuclear/industrial scene variants:

**BLUE RADIATION (opener, `#0088ff`):** Black Cadillac parked inside reactor, fedora man smoking cigar, Cherenkov blue glow from radioactive water, headlights through dense blue fog, fractured concrete walls, corroded scaffolding.

**GRAPHITE CORE (smooth groove, `#00aaff`):** Silver Mustang inside collapsed graphite core, fedora man holding katana, faint cyan Cherenkov glow from within core, corroded control rod mechanisms, water dripping.

**FISSION ECHO (different lead, `#0044ff`):** Grey Lincoln Continental, fedora man smoking cigar, bright Cherenkov light through massive fissure in wall, geometric echo patterns, fractured concrete slabs, water cascading.

**GAMMA HAUNT (tempo shift, `#00ffaa`):** Burgundy Dodge Charger inside abandoned control room, fedora man holding katana, invisible gamma radiation as eerie green-blue ionized air glow, dead instrument panels, Geiger counter light particles.

**ISOTOPE REQUIEM (cinematic closer, `#0066cc`):** Obsidian Imperial Crown on wet concrete by still water, fedora silhouette smoking cigar across the water, last faint Cherenkov glow from decaying isotopes, collapsed scaffolding like gravestones, moonlight through fractured ceiling.

**Album:** All 5 cars stacked at different angles, fedora+katana silhouette, epic sweeping vista, centered title. This "stacked cars" pattern is one of several album cover composition patterns — see `references/album-cover-compositions.md` for the full catalog including isometric, era progression, and all-cars-assembled variants.

**Album cover key point:** Album covers use **centered title** (no `--bottom` flag). Track covers use `--bottom`. This is consistent across all VØIDRIDE albums.

## Album Cover Composition Patterns

VØIDRIDE album covers use one of several composition patterns depending on the scene type:

| Pattern | Used For | Description |
|---------|----------|-------------|
| **All-cars assembled** | Fog/night, underpass, ORIGINS | All track cars in loose diagonal formation, headlights through fog, fedora/trench coat silhouette, huge moon |
| **Stacked cars** | CHERENKOV-HORIZON | All cars at different angles/positions inside a specific environment (reactor, cathedral, etc.) |
| **Isometric 30°** | SIGIL ENGINE, SYNAPSE NECROPOLIS | Overhead isometric view showing all eras/variants of a single object simultaneously |
| **Era-progression vista** | SIGIL ENGINE, SYNAPSE NECROPOLIS (alternative) | Wide cathedral vista with all eras visible in a single sweeping view |

For **all-cars assembled** covers, the prompt pattern is:
```
An epic sweeping nighttime vista on a dark wet [SURFACE]. [N] distinctive nightride cars
parked together in a loose diagonal formation, each facing slightly different directions,
their headlights cutting through thick swirling fog and cigarette smoke.
[PER-CAR DESCRIPTIONS WITH LIGHTING COLORS].
A massive full moon dominates the entire sky, enormous and looming.
In the medium foreground, a mysterious man in a [COAT] and [HAT]
stands as a commanding silhouette, partially obscured by drifting fog and smoke.
[ALBUM_COLOR] neon underglow warmth cutting through the cold blue moonlight.
Dark atmospheric cinematic 35mm film photography, nightride witch house album cover art.
NO TEXT, ... [full negation list]
```

For **isometric** covers, add "isometric 3D view from a 30-degree overhead angle" and describe all eras/variants visible simultaneously in the same space.