# VØIDRIDE Track Cover Generation Reference

## Scene Prompt Templates

Each VØIDRIDE track cover uses a cinematic scene with consistent elements. Generate
the background with ideogram-v4 (NO TEXT), then overlay the Unicode title with
`overlay-title.py --bottom`.

### Template 1: Default Fog/Night Scene

```
Dark atmospheric cinematic 35mm film photography. A [CAR] parked on wet
asphalt road in thick swirling fog and mist. Headlights cutting through
dense fog creating dramatic volumetric light beams. In the distant
background, a massive dark spaceship about to launch with engines glowing.
A man dressed all in black wearing a fedora hat holding a katana sword
stands as a dark silhouette in the medium background partially obscured
by fog. [LIGHTNING]. A massive full moon dominates the misty sky.
Dark nightride witch house album cover art. Cinematic color grading,
35mm film grain, anamorphic lens flare.
NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS,
NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS,
NO SIGNAGE, NO SIGNS, NO CAPTIONS.
```

### Template 2: Burning Man Duststorm Scene

Used for the ꐃ₦₮ɄɌꐃɄƦɌɆ₦₵Ɇ EP. When the user wants a playa/Burning Man setting:

```
Photorealistic cinematic 35mm film photograph. A [CAR] converted into a
Burning Man art car with massive subwoofer speakers bolted to the roof and
hood, parked on the cracked dry alkaline playa of Black Rock Desert during
an intense duststorm. Thick swirling dust and sand filling the air,
visibility reduced, atmospheric haze with [ACCENT]. In the far distance,
towering large-scale metal sculptures typical of Burning Man — a massive
metal lotus flower sculpture, a spiraling steel tower, and geometric
Burning Man effigy silhouette half-obscured by dust. A few people wearing
dust goggles and bandanas over their faces, dressed in layered desert
festival wear with coats and scarves, walking purposefully through the
storm like they belong there. In the foreground, a lone man wearing a dark
fedora hat and a flowing dark kimono over black clothes, holding a katana
sword at his side, casually smoking a cigarette, the ember glowing [NEON],
standing beside the art car as dust swirls around him. Intense realism,
Kodak Portra 400 film stock, natural vignette, film grain, dramatic side
lighting through the dust. Dark nightride witch house album cover art.
NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS,
NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS,
NO SIGNAGE, NO SIGNS, NO CAPTIONS, NO LOGO, NO LETTERING.
```

Key differences from the default scene:
- Car becomes an **art car with subwoofers** bolted on
- Setting is **Black Rock Desert playa** with **alkaline dust** instead of fog
- Large-scale **metal sculptures** replace the spaceship — each track gets UNIQUE sculptures, never reuse
- People wear **goggles and bandanas** instead of being silhouetted
- The fedora/kimono/katana man is **smoking a cigarette** with glowing ember
- Day/night alternation for visual variety across a multi-track set — roughly 2 day per 7 tracks
- Night scenes: drenched in multicolored glow (LED el-wire, neon underglow, firelight, lasers through dust)
- Day scenes: golden playa dust haze, diffused harsh sunlight, pale ochre sky
- Film stock: **Kodak Portra 400** for day scenes, **Kodak Portra 800 pushed 2 stops** for night scenes
- Extra negation items: **NO LOGO, NO LETTERING** (ideogram-v4 needs more negation for complex scenes)

### Day/Night Atmosphere Blocks

When generating Burning Man scenes, swap the atmosphere block based on time of day:

**Night atmosphere:**
```
Pitch black desert night with an intense duststorm. Everything glows —
LED el-wire wrapping every surface, neon art car underglow casting colorful light,
burning sculptures throwing amber and crimson light, laser beams cutting through the dust,
glowing bike lights trailing through the haze, chemical green and violet light painting
the dust clouds. The entire scene is drenched in multicolored glow and firelight piercing
the swirling dust.
```

**Day atmosphere:**
```
Blinding daytime duststorm on the cracked white alkaline playa. Harsh desert sun
diffused through thick blowing dust and sand, creating a desaturating golden haze.
Visibility reduced to 50 meters. Everything coated in a fine layer of playa dust.
Shadows are soft and diffused, the sky is a pale ochre bowl.
```

### Customizing Scenes

When the user describes a different setting (desert, city, underwater, etc.),
rewrite the entire scene prompt to match. Keep these invariant elements:
- The car (changing model per track as mapped)
- The fedora/kimono/katana man (as foreground character)
- The extended negation list
- "Dark nightride witch house album cover art" style anchor
- Film grain/cinematic color grading language

Replace the setting-specific elements (fog vs dust, spaceship vs sculptures, etc.)
while maintaining the VØIDRIDE dark atmospheric aesthetic.

### Template 3: Mars/Planetary Scene

Used for MARS DESCENT EP. Planet-specific atmosphere and terrain:

```
Dark atmospheric cinematic 35mm film photography. A [CAR] cruising on a
cracked [PLANET]-highway through thick swirling [DUST_COLOR] dust fog
and thin [PLANET] atmosphere. The car has a retro-futuristic space-age
modification — HID headlights cutting through the dust creating dramatic
volumetric light beams. The car's license plate reads [PLATE]. A glowing
neon road sign on the side of the highway reads VOIDRIDE in red and
white neon letters. In the distant background, towering [PLANET] rock
formations and a massive dark spaceship hovering above the horizon with
engines glowing. A dark silhouette of a man wearing a fedora hat and
a flowing dark coat holding a katana sword stands in the medium background
partially obscured by [DUST_COLOR] dust fog. [LIGHTNING] striking between
the rock formations. [MOONS]. The car looks fun and cool to drive, 90s
JDM import style but space-age modified. Dark nightride witch house album
cover art. Cinematic color grading, 35mm film grain, anamorphic lens flare,
[DUST_COLOR] [PLANET] dust haze.
NO TEXT EXCEPT THE NEON SIGN AND LICENSE PLATE, NO OTHER LETTERS,
NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY,
NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO CAPTIONS.
```

Key differences from Templates 1 & 2:
- **Planetary terrain** replaces fog/mist or playa dust — red-orange Mars soil, cracked highways
- **License plates** are explicitly requested via prompt text — custom void-style plate text per track
- **Neon road sign** reads VOIDRIDE — the only text the prompt allows
- **Spaceship** is in the background (same as Template 1)
- **Atmospheric color** changes per planet (Mars = red-orange, etc.)
- **Multiple moons** instead of single full moon (Mars has Phobos + Deimos)
- **Negation** uses softer "NO TEXT EXCEPT THE NEON SIGN AND LICENSE PLATE" — allowing the two intentional text elements while banning everything else
- **Cars** are "90s JDM import style but space-age modified" — fun cruising vibes

**MARS DESCENT EP car/plate mapping:**

| # | Title | Car | Plate | Neon Color |
|---|-------|-----|-------|------------|
| 1 | ł₦ł†łØ₦ ⱲɆłⱠ | Black '93 Skyline R32 GT-R, gold BBS wheels | VØID-1 | `#ff0044` |
| 2 | ΔƤØǤɇɇ ĐƦł₣† | Silver '95 Supra MK4, single turbo through hood | ZER0-G | `#00ccff` |
| 3 | ƤⱠΔ₴ӎ₳ ₴Ⱨɇ₳Ʀ | Red '91 3000GT VR-4, popup headlights raised | PL4SM4 | `#ff6600` |
| 4 | ǤƦΔⱲł†ɏ ⱠØϾҞ | Dark grey '94 Lexus SC400, air suspension | G-L0CK | `#aa00ff` |
| 5 | ȒɆĐ ƦɆɋɄłɆӎ | Midnight purple '96 S14 Silvia, drift aero | R3QU13M | `#22cc44` |

**Album/Playlist cover variant:** Use centered title (no `--bottom`), wider vista composition with ALL track-specific cars visible together in a loose diagonal formation, each facing slightly different directions. The album cover combines elements from every track cover — all cars, the fedora/fedora+katana or trench coat+fedora man as a silhouette, the huge full moon, fog/smoke, and headlights cutting through haze. Title centered vertically (no `--bottom` flag). This makes the album cover feel like "the whole world" while track covers are close-ups of individual moments.

**Album cover prompt pattern:**
```
An epic sweeping nighttime vista on a dark wet [SURFACE]. [N] distinctive nightride cars
parked together in a loose diagonal formation, each facing slightly different directions,
their headlights cutting through thick swirling fog and cigarette smoke, creating dramatic
volumetric light beams piercing the haze. [PER-CAR DESCRIPTIONS]. A massive full moon
dominates the entire sky, enormous and looming, casting cold silver-blue moonlight over
the entire scene. In the medium foreground, a mysterious man in a [COAT] and [HAT]
stands as a commanding silhouette, partially obscured by drifting fog and smoke.
[ALBUM_COLOR] neon underglow warmth cutting through the cold blue moonlight.
Dark atmospheric cinematic 35mm film photography, nightride witch house album cover art.
[CAMERA/FILM STOCK].
NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS,
NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNAGE, NO SIGNS,
NO CAPTIONS.
```

## Per-Track Car/Color/Lightning Mapping

Common mapping for EPs. Adjust per release.

### Default Fog Scene Mapping

| Track Position | Car | Lightning | Neon Color |
|----------------|-----|-----------|-------------|
| Opener (heavy) | Black Cadillac | Crimson red bolts | `#ff0044` |
| Smooth groove | Silver Ford Mustang | Ice-blue bolts | `#00ccff` |
| Title/dark | Grey Lincoln Continental | Violet purple bolts | `#aa00ff` |
| Aggressive | Burgundy Dodge Charger | Fiery orange bolts | `#ff6600` |
| Closer (atmospheric) | Obsidian Imperial Crown | Eerie green bolts | `#22cc44` |
| Extended (6+ tracks) | Dark Teal Mercury Cougar | Amber bolts | `#ff8800` |

For albums with more than 6 tracks, cycle back through the mapping starting from position 1 with slight variations (e.g., "Black Cadillac Fleetwood" instead of "Black Cadillac").

### ꐃ₦₮ɄɌꐃɄƦɌɆ₦₵Ɇ EP — Burning Man Duststorm Mapping

| # | Title | ASCII | Car | Accent | Neon |
|---|-------|-------|-----|--------|------|
| 1 | Ɇ₦†Ʀɏ₩ØɄ₦Đ | Entrywound | Black '67 Cadillac Fleetwood (art car) | Crimson red dust devil swirls | `#ff0044` |
| 2 | ǤⱠ₳₴₴Ʉ₦ĐɆƦ | Glassunder | Silver '69 Mustang fastback (art car) | Ice-blue playa dust whirlwinds | `#00ccff` |
| 3 | ᘔƦ₳₩Ⱡ₴₱₳Ӿɇ | Crawlspace | Grey '64 Lincoln Continental (art car) | Violet purple atmospheric haze | `#aa00ff` |
| 4 | ₦łǤⱧ†Ʀł†Ɇ | Nightrite | Burgundy '70 Charger R/T (art car) | Fiery orange ember sparks | `#ff6600` |
| 5 | Ʉ₦ĐɆɌƦØ₣† | Undercroft | Obsidian '67 Imperial Crown convertible (art car) | Eerie green chemical glow | `#22cc44` |

### ĐɆ₴ɆƦ† VØID Album — Burning Man Duststorm Mapping (7 tracks)

This set alternates between night and day scenes for visual variety.
Night scenes use multicolored glow (LED el-wire, underglow, lasers, firelight);
day scenes use golden playa dust haze with diffused harsh sunlight.

**Unique sculptures per track** — each cover gets completely different large-scale
metal sculptures in the distance. Never reuse the same sculpture across tracks
in a single album set.

| # | Unicode Title | ASCII | Car | Sculptures | Neon | Time |
|---|--------------|-------|-----|-----------|------|------|
| 1 | ₳₴Ⱨ ƤƦØ₵Ɇ₴₴łØ₦ | Ash Procession | Black '67 Cadillac Fleetwood (art car) | Towering metal lotus flower + spiraling steel tower with orange neon rings | `#ff4400` | Night |
| 2 | ĐɄ₦Ɇ ₩ƦΔł†Ⱨ | Dune Wraith | Matte black '69 Dodge Charger R/T (art car) | Massive angular steel dragon skeleton + tall geometric obelisk of welded rebar emitting blue light | `#ff8800` | Night |
| 3 | ӎłƦΔǤɇ ₴†Δ†ł₵ | Mirage Static | Gunmetal grey '64 Lincoln Continental (art car) | Giant ornate rotating metal mandala + twin towering steel crescents forming an archway | `#00ccff` | Day |
| 4 | ĐɄ₴† ӎɇƦłĐłΔ₦ | Dust Meridian | Sand-colored '72 Ford Bronco (art car) | Tall steel dharma wheel with fire spokes + huge curved metal whale skeleton emerging from playa | `#ffaa00` | Day |
| 5 | Ɇӎ฿ɇƦ ⱲłǤłⱠ | Ember Vigil | Dark burgundy '70 Plymouth Barracuda (art car) | Tall flickering steel flame sculpture + massive hexagonal metal hive with amber glowing cells | `#ff3300` | Night |
| 6 | ƤⱧ₳₦†Øӎ ƤƦł₴ӎ | Phantom Prism | Midnight blue '68 Mustang fastback (art car) | Giant geometric prism sculpture refracting light + intricate metal chandelier tower with hundreds of dangling crystals | `#aa00ff` | Night |
| 7 | Ɇӎ฿ɇƦ Ʀł†ɇ | Ember Rite | Charcoal '66 Imperial Crown convertible (art car) | Enormous coiling metal serpent sculpture + vast circular fire altar with burning rings and suspended iron lanterns | `#ff0044` | Night |

**Day scene atmosphere prompt addition:**
```
Blinding daytime duststorm on the cracked white alkaline playa. Harsh desert sun
diffused through thick blowing dust and sand, creating a desaturating golden haze.
Visibility reduced to 50 meters. Everything coated in fine playa dust. Shadows are
soft and diffused, the sky is a pale ochre bowl.
Film: Kodak Portra 400, warm golden tones, natural vignette, fine grain
```

**Night scene atmosphere prompt addition:**
```
Pitch black desert night with an intense duststorm. Everything glows — LED el-wire
wrapping every surface, neon art car underglow casting colorful light, burning
sculptures throwing amber and crimson light, laser beams cutting through the dust,
glowing bike lights trailing through the haze, chemical green and violet light
painting the dust clouds. The entire scene is drenched in multicolored glow and
firelight piercing the swirling dust.
Film: Kodak Portra 800 pushed 2 stops, high ISO grain, dramatic colored light through dust
```

## Per-Album Color Mapping

| Album | Neon Color (hex) |
|-------|-----------------|
| ₴ØɄ₦ĐĐɆ₴łǤ₵ | `#00ff44` green |
| Ʉ₦ĐɆɌ₱Δ$$ | `#ff8800` amber/orange |
| ØƦłǤł₦$ | `#ffd700` gold |
| ĐɆ₴ɆƦ† VØID | `#ffaa00` sand/amber (but per-track neon varies — see mapping table) |
| NΞØN ₳U฿ | `#00ffcc` cyan/electric green |
| SÉANCE ◊TEREO | `#aa00ff` purple |
| VØIDLINES | `#00ccff` ice blue |
| BLΔCK MΔSS | `#ff0033` crimson |
| CHERENKOV-HORIZON | `#0088ff` Cherenkov blue |
| HELIOS-DECAY | `#cc00ff` magenta violet |
| ꐃ₦₮ɄɌꐃɄƦɌɆ₵Ɇᵾ₦ | `#ff0044` crimson red |
| ₴ɏ₦ΔƤ₴Ɇ ₦ɆϾƦØƤØⱠł₴ | `#00ff66` green |
| ₴łǤłⱠ Ɇ₦Ǥł₦ɇ | `#aa00ff` purple |
| ₦ØϾ†ɄƦ₦Ɇ ØVɆɌƤ₳$$ | `#ff8800` amber/orange |
| Ⱡł₦Ɇ†łϾ ØVɆƦĐƦłVɇ | `#ff6600` fiery orange |

## Complete Workflow

```bash
# Step 1: Generate background (no text!)
# Use Venice API ideogram-v4 with scene prompt + extended negation list
# Write a .py script to /tmp/, run via terminal (NOT execute_code)
# API endpoint: POST https://api.venice.ai/api/v1/image/generate
# Response: { "images": ["<base64-webp>"] } at top level

# Step 2: Convert WebP to PNG and scale to 3000x3000
ffmpeg -y -i cover_raw.webp -vf \
  "scale=3000:3000:force_original_aspect_ratio=decrease,pad=3000:3000:(ow-iw)/2:(oh-ih)/2" \
  track_01_bg.png

# Step 3: Overlay Unicode title (bottom position for scene covers)
# MUST use venv Python — system python3 lacks Pillow
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image track_01_bg.png \
  --title "Ɇ₦†Ʀɏ₩ØɄ₦Đ" \
  --color "#ff0044" \
  --output track_01_cover.png \
  --bottom

# Step 4: Convert to JPEG for SoundCloud upload (max 10MB)
/opt/hermes/.venv/bin/python3 -c "
from PIL import Image
img = Image.open('track_01_cover.png').convert('RGB')
img.save('track_01_cover.jpg', 'JPEG', quality=95)
"

# Step 5: Upload to SoundCloud with plain ASCII track title
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py \
  upload --file track.mp3 --artwork track_01_cover.jpg \
  --title "Entrywound" --genre "Electronic" \
  --tags "witch house,dark trap,nightride" \
  --sharing public --downloadable
```

## Title Rules

- **Track titles on SoundCloud**: Plain ASCII (e.g., "Entrywound", "Glassunder")
- **Cover art**: Unicode-styled (e.g., "Ɇ₦†Ʀɏ₩ØɄ₦Đ", "ǤⱠ₳₴₴Ʉ₦ĐɆƦ")
- **Playlist titles**: Unicode-styled (e.g., "ꐃ₦₮ɄɌꐃɄƦɌɆ₦ᵾɆ")
- Verify Unicode titles against the producer profile catalog — similar-looking
  characters like Ɍ vs Ʀ or ៛ vs Ⱡ are different code points
- **Unique sculptures per track** — when generating a multi-track album cover set, each cover MUST have completely different sculptures. Never reuse the same sculpture description across tracks. List them explicitly in each prompt.
- **Day/night alternation** — for album sets with 5+ covers, alternate between night (glow-drenched) and day (golden dust haze) scenes to create visual variety. Aim for roughly 2 day scenes per 7 tracks, spaced mid-album.

## Batch Generation Tips

- Write a `.py` script file for batch generation — don't inline Python with `python3 -c`
  as Unicode title strings get mangled in shell escaping
- Rate limit: 4-second delay between Venice API requests to avoid 429 errors
- Venice returns WebP — always convert to PNG before overlaying
  (`ffmpeg -y -i raw.webp -c:v png bg.png`)
- **Use `/opt/hermes/.venv/bin/python3`** for all PIL-dependent scripts (overlay-title.py, image conversion). System `python3` does NOT have Pillow.
- Venice Image API: endpoint is `/api/v1/image/generate` (singular "image"), response is `{ "images": ["<base64>"] }` at top level — NOT `/api/v1/images/generate` and NOT `{ "data": [...] }`

## Venice Image API Quick Reference

```
Endpoint: POST https://api.venice.ai/api/v1/image/generate
Auth:     Bearer {VENICE_API_KEY}
Body:     {"model": "flux-2-max", "prompt": "...", "width": 1024, "height": 1024, "negative_prompt": "..."}
Response: {"images": ["<base64-webP-string>"], "id": "B-xxxx", "timing": {...}}

Key differences from audio API:
- Singular "/image/" not "/images/"
- Response is {"images": [...]} at TOP LEVEL, not nested under "data"
- Returns base64-encoded WebP, not URLs
- Must decode base64 then convert WebP→PNG with ffmpeg
- No "n" parameter — causes 400 validation error
- Max resolution 1024×1024 — larger dimensions return 400
- Always use flux-2-max (NOT ideogram-v4, which returns 404)
- Check len(img_bytes) < 10000 after base64 decode = content filtered/blank
- 4-second rate limit between requests
- Use VENICE_API_KEY env var (NOT VENICE_INFERENCE_KEY which is audio-only)
```

## Full Batch Album Workflow (End-to-End)

This is the complete workflow for producing an EP/album's cover art and uploading everything to SoundCloud.

### 1. Prepare Track Metadata

Pull Unicode titles from the producer profile catalog. Map each track to a car, lightning/accent color, and neon color.

### 2. Generate Backgrounds (Python script)

Write a `.py` script to `/tmp/` using the batch template from `venice-image-api.md`.

### 3. Convert & Scale (ffmpeg)

Convert WebP→PNG and scale to 3000×3000 for each background.

### 4. Overlay Titles (bottom position for scene covers)

Use venv Python: `/opt/hermes/.venv/bin/python3 overlay-title.py --bottom`

### 5. Compress to JPEG for SoundCloud (max 10MB)

Quality 95 on 3000×3000 typically produces 1-2MB files.

### 6–8. Upload tracks, create playlist, add artwork

See `venice-image-api.md` for SoundCloud upload workflow details.