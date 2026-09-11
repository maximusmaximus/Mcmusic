# Album Cover Composition Patterns

VØIDRIDE albums use **different compositions for per-track covers vs. album covers**. Track covers focus on a single car as the hero element (with `--bottom` title). Album covers use wider, more expansive vistas with multiple elements assembled together (with centered title, no `--bottom` flag).

## Album Cover Compositions

### Pattern 1: Wide Vista (Default)
A panoramic view of the scene with the fedora man as a smaller figure in the background. One hero car in the foreground, silhouettes or other elements in the distance.

Best for: Amorphous atmospheric albums, ambient soundscape releases.

### Pattern 2: All Cars Stacked (Group Shot)
All per-track cars arranged in a loose composition, parked at different angles, their headlights creating crossing volumetric light beams through fog/mist. The fedora man (or trench coat man) stands as a silhouette in the foreground or middle ground.

```
An epic sweeping nighttime vista. Five distinctive nightride cars parked together on a dark wet asphalt road in a loose diagonal formation, each facing slightly different directions, their headlights cutting through thick swirling fog and smoke creating dramatic volumetric light beams piercing the haze. [CAR LIST with descriptions]. A massive full moon dominates the entire sky. In the medium foreground, a mysterious man in a long dark trench coat and wide-brimmed fedora hat stands as a silhouette, partially obscured by drifting fog and smoke. Thick rolling fog throughout. Dark atmospheric cinematic 35mm film photography, nightride witch house album cover art, moody noir atmosphere, anamorphic lens flare, Portra 800 film grain. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, ...
```

Used for: ꐃ₦₮ɄɌꐃɄɌɌɆ₵Ɇᵾ₦, CHERENKOV-HORIZON

### Pattern 3: Isometric Overhead (30° Perspective)
An isometric 3D view from a ~30° overhead angle, showing the central object or scene from above. Works especially well for architectural or interior settings (cathedrals, reactor vessels) where you want to show the full layout.

Used for: ₴łǤłⱠ Ɇ₦Ǥł₦ɇ (cathedral interior with sigil engine), ₴ɏ₦ΔƤ₴Ɇ ₦ɆϾƦØƤØⱠł₴ (cathedral interior with hybrid computer-car)

See `references/era-progression-scene.md` for the isometric prompt template.

### Pattern 4: Era Progression (All Eras Visible)
All five historical eras visible simultaneously in one sweeping composition, with the object progressively more overgrown from one era to the next.

Used for: ₴łǤłⱠ Ɇ₦Ǥł₦ɇ, ₴ɏ₦ΔƤ₴Ɇ ₦ɆϾƦØƤØⱠł₴

See `references/era-progression-scene.md` for prompt templates.

### Pattern 5: Cherenkov Reactor (Interior Scene All Cars)
Flooded nuclear reactor containment vessel interior with all 5 cars at different positions and angles, Cherenkov blue glow, fedora+katana silhouette.

Used for: CHERENKOV-HORIZON

See `references/cherenkov-reactor-scene.md` for prompt templates.

## Character Variants

The standard VØIDRIDE figure is a **man dressed all in black wearing a fedora hat** with optional katana. Common variants:

| Variant | When to Use | Prompt Addition |
|---------|-------------|-----------------|
| Fedora + katana | Default dark scene | "A man dressed all in black wearing a fedora hat holding a katana sword" |
| Fedora + cigar | Gritty/smoky scene | "A man in a dark fedora hat smoking a cigar, ember glowing" |
| Trench coat + fedora | Noir/album covers | "A mysterious man in a long dark trench coat and wide-brimmed fedora hat" |
| Fedora + katana + smoke | Atmospheric scene | "A man in black wearing a fedora hat holding a katana, cigarette smoke curling" |
| Bare silhouette | Minimal scene | "A dark silhouette of a man wearing a fedora hat" |

For album covers, prefer the **trench coat + fedora** variant — it's more imposing at the wider scale and creates a stronger noir silhouette against the assembled cars/moon/fog.

## Title Position for Album Covers

- **Album covers ALWAYS use centered title** (no `--bottom`, no `--top` flag)
- **Track covers ALWAYS use `--bottom`**