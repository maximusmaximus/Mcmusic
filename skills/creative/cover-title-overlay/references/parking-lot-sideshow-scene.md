# Parking Lot / Sideshow Skid Marks Scene — VØIDRIDE Cover Art

Used for ₴ØɄ₦ĐĐɆ₴łǤ₵ and any album where the concept is an empty parking lot with sideshow skid marks. No characters, no cars — just the pavement evidence of a car having done tricks.

## Key Concept

Each track's cover is the **same parking lot** (or visually similar lot), but with **different neon-colored skid marks** (donut circles, figure-8s, drift streaks, brake marks) in the track's signature color. The lot is empty — the car has already left. Wet asphalt reflects the neon glow. Fog in the background. Dim overhead parking lot lights casting long shadows.

**NO characters, NO vehicles, NO figures.** The scene is a forensic documentation of a sideshow that already happened, told only through the tire marks left behind.

## Template

```
Dark atmospheric cinematic 35mm film photography at night. An empty parking
lot viewed from a slight angle, wet dark asphalt with dramatic [COLOR_NAME]
skid marks and tire burnout patterns across the pavement like a sideshow just
happened — donut circles, figure-8 drift marks, long diagonal brake streaks,
and aggressive tire rotation burns all in [NEON_COLOR_DESCRIPTION] reflecting
off the wet surface. Heavy fog rolling across the background. Dim overhead
parking lot lights casting long shadows through the mist. The wet pavement
reflects the [NEON_COLOR_DESCRIPTION] from the skid marks creating a cinematic
glow. Absolutely no people, no characters, no cars, no vehicles, no figures,
no silhouettes — just the empty lot with the sideshow skid marks. Dark
nightride witch house album cover art. Cinematic color grading, 35mm film
grain, anamorphic lens flare. Heavy [NEON_COLOR_DESCRIPTION] throughout.
NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS,
NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS,
NO SIGNAGE, NO SIGNS, NO CAPTIONS.
```

## Playlist Cover Variant

Same empty parking lot but with **ALL colors overlapping** — multicolored skid marks from all tracks, creating a rainbow-burn effect on the wet asphalt. This represents the complete album rather than a single track.

```
...donut circles, figure-8 drift marks, long diagonal brake streaks in
crimson red, ice-blue, fiery orange, violet purple, eerie green, cyan,
and amber gold neon glow reflecting off the wet surface...
```

Use the album's signature color for the title overlay (for ₴ØɄ₦ĐĐɆ₴łǤ₵, that's `#00ff44` green).

## Per-Track Color Mapping (₴ØɄ₦ĐĐɆ₴łǤ₵)

| # | Title | Unicode | Neon Color | Color Description |
|---|-------|---------|------------|-------------------|
| 01 | THUNDERVEIL | †ⱧɄ₦ĐɆƦⱲɆłⱠ | `#ff0044` | Crimson red |
| 02 | RAINSHADOW | ƦΔł₦₴ⱧΔĐØ₩ | `#00ccff` | Ice-blue |
| 03 | REDLINE WRAITH | ƦɆĐⱠł₦Ɇ ₩ƦΔł†Ⱨ | `#ff6600` | Fiery orange |
| 04 | HOLLOW CHOIR | ⱧØⱠⱠØ₩ ϾⱧØłƦ | `#aa00ff` | Violet purple |
| 05 | STORMHEX | ₴†ØƦҞⱧɆӾ | `#00ff44` | Eerie green |
| 06 | GHOSTSHIFT | ǤⱧØ₴†₴Ⱨł₣† | `#00ffcc` | Cyan |
| 07 | CLOUDBURIAL | ϾⱠØɄĐɃɄƦł₳Ⱡ | `#ffaa00` | Amber gold |

## Comparison with Other Scene Types

| Feature | Fog/Night (Default) | Burning Man | Mars | Parking Lot |
|---------|---------------------|-------------|------|-------------|
| Setting | Wet road, fog | Playa duststorm | Mars highway | Empty parking lot |
| Characters | Fedora/katana man | Fedora/kimono man + people | Fedora man silhouette | **None** |
| Vehicles | Parked car | Art car | JDM space car | **None** |
| Signature element | Lightning | Neon underglow | Spaceship | Skid marks |
| Title position | `--bottom` | `--bottom` | `--bottom` | `--bottom` |
| Text in prompt | No text | No text | Neon sign + plate ok | No text |

## Generation Pitfalls

- **ideogram-v4 can return near-blank images** — Always check the output file size. A valid 1024×1024 WebP should be 100KB+. If under 10KB, regenerate immediately.
- **Spaces in filenames** — Use underscore-separated filenames in batch scripts (e.g., `01_THUNDERVEIL_raw.webp`, not `01 THUNDERVEIL raw.webp`). Spaces break bash for loops and ffmpeg commands.
- **Same parking lot, different colors** — The prompt intentionally describes the same parking lot each time. The only change per track is the neon color of the skid marks. This creates a cohesive visual series across the EP/album.