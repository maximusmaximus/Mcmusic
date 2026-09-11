# Mars/Alien Landscape Scene — VØIDRIDE Cover Art

Used for MARS DESCENT EP and other sci-fi space landscape covers.

## Template

```
Dark atmospheric cinematic 35mm film photography, Mars landscape at night. A [CAR]
cruising on a cracked red Martian highway through thick swirling red-orange dust fog
and thin Martian atmosphere. The car has retro-futuristic space-age modifications —
HID headlights cutting through the dust creating dramatic volumetric light beams.
The car's license plate reads [PLATE]. A glowing neon road sign on the side of the
highway reads VOIDRIDE in neon letters. In the distant background, towering Martian
rock formations and a massive dark spaceship hovering above the horizon with engines
glowing. A dark silhouette of a man wearing a fedora hat and a flowing dark coat
holding a katana sword stands in the medium background partially obscured by red dust
fog. [LIGHTNING] striking between the rock formations. Two small red Martian moons
in the dusty sky. The car looks fun and cool to drive, 90s JDM import style but
space-age modified. Dark nightride witch house album cover art. Cinematic color grading,
35mm film grain, anamorphic lens flare, red-orange Martian dust haze.
NO TEXT EXCEPT THE NEON SIGN AND LICENSE PLATE, NO OTHER LETTERS,
NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY,
NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO CAPTIONS.
```

## Key Differences from Fog/Night Scene

- **Setting**: Mars landscape with red-orange dust, not Earth fog
- **Car**: 90s JDM import style with space-age mods (cruising, not just parked)
- **License plate**: Explicit in prompt with void-style text (e.g., VØID-1, ZER0-G, PL4SM4)
- **Neon sign**: VOIDRIDE road sign on the highway (prompt allows this specific text)
- **Atmosphere**: Red-orange Martian dust haze instead of white fog
- **Sky**: Two small Martian moons instead of one Earth moon
- **Background**: Spaceship hovering over horizon + Martian rock formations
- **Color**: Red-orange/amber overall cast instead of blue/green

## Per-Track Car/Plate Mapping (Mars Descent EP)

| # | Title | Unicode | Car | Plate | Neon |
|---|-------|---------|-----|-------|------|
| 1 | IGNITION VEIL | ł₦ł₮łØ₦ ⱲɆłⱠ | Black '93 Skyline R32 GT-R, gold BBS wheels | VØID-1 | `#ff0044` crimson |
| 2 | APOGEE DRIFT | ΔƤØǤɇɇ ĐƦł₣† | Silver '95 Supra MK4, massive single turbo hood | ZER0-G | `#00ccff` ice-blue |
| 3 | PLASMA SHEAR | ƤⱠΔ₴ӎ₳ ₴Ⱨɇ₳Ʀ | Red '91 3000GT VR-4, popup headlights raised | PL4SM4 | `#ff6600` orange |
| 4 | GRAVITY LOCK | ǤƦΔⱲł†ɏ ⱠØϾҞ | Grey '94 Lexus SC400, air suspension stance | G-L0CK | `#aa00ff` violet |
| 5 | RED REQUIEM | ȒɆĐ ƦɆɋɄłɆӎ | Midnight purple '96 S14 Silvia, drift aero | R3QU13M | `#22cc44` green |

## ideogram-v4 Text Handling

When the prompt includes specific text elements (neon sign, license plate) that you WANT rendered:
- Use "NO TEXT EXCEPT [specific items]" phrasing
- Be explicit about what text is allowed: "reads VOIDRIDE", "reads VØID-1"
- ideogram-v4 may still garble text — acceptable for artistic covers
- The overlay-title.py step handles the main title text anyway

## Batch Generation Script Pattern

Write a `.py` script to `/tmp/` for batch generation — inline `python3 -c` mangles Unicode.
4-second rate limit between Venice API requests.