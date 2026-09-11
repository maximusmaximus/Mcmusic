# Sideshow Parking Lot Scene — VØIDRIDE Cover Art

Used when the user wants a parking lot with sideshow skid marks (no characters, no cars, no figures).
This is a variant of the fog/night scene — same atmospheric feeling but the hero element
is the tire marks on wet asphalt, not a character or vehicle.

## Template

```
Dark atmospheric cinematic 35mm film photography at night.
An empty parking lot viewed from a slight angle, wet dark asphalt
with dramatic [COLOR] skid marks and tire burnout patterns
across the pavement like a sideshow just happened — donut circles,
figure-8 drift marks, long diagonal brake streaks, and aggressive
tire rotation burns all in [NEON COLOR DESCRIPTION] reflecting off the wet surface.
Heavy fog rolling across the background. Dim overhead parking lot
lights casting long shadows through the mist. The wet pavement
reflects the [NEON COLOR DESCRIPTION] from the skid marks creating a cinematic glow.
Absolutely no people, no characters, no cars, no vehicles, no figures,
no silhouettes — just the empty lot with the sideshow skid marks.
Dark nightride witch house album cover art. Cinematic color grading,
35mm film grain, anamorphic lens flare. Heavy [COLOR NAME] throughout.
NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS,
NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS,
NO SIGNAGE, NO SIGNS, NO CAPTIONS, NO GRAFFITI, NO WORDS ON PAVEMENT,
NO TEXT ON GROUND, NO PAINTED MARKINGS THAT LOOK LIKE LETTERS.
```

## Key Differences from Fog/Night Scene

- **No characters**: No man, no silhouette, no katana, no fedora — nothing human
- **No vehicles**: No car, no spaceship — the "hero" element is the skid marks
- **Ground emphasis**: Wet asphalt with visible tire marks is the focus
- **Anti-text critical**: Must include graffiti/pavement negation since ideogram-v4
  loves to add words on asphalt surfaces
- **Lighting**: Reflected neon from the skid marks on wet pavement replaces
  the lightning/moonlight of the fog scene

## Per-Track Color Mapping

Each track gets a unique neon color. The playlist cover uses all colors overlapping.

| Track Position | Neon Color | Hex |
|----------------|-----------|-----|
| Opener | Crimson red | `#ff0044` |
| Second | Ice-blue | `#00ccff` |
| Third | Fiery orange | `#ff6600` |
| Fourth | Violet purple | `#aa00ff` |
| Fifth | Eerie green | `#22cc44` or `#00ff44` |
| Sixth | Cyan | `#00ffcc` |
| Seventh | Amber gold | `#ffaa00` |
| Eighth | Hot pink | `#ff3388` |

For playlist covers: "multicolored skid marks in crimson red, ice-blue, fiery orange, violet purple, eerie green, cyan, and amber gold neon glow"

## Generation Pipeline

1. Generate backgrounds with ideogram-v4 (1536×1536 native)
2. Upscale to 3000×3000 with: `ffmpeg -vf "scale=3000:3000:flags=lanczos,unsharp=5:5:0.8:5:5:0"`
3. Overlay Unicode title with `overlay-title.py --bottom`
4. Convert to JPG for SoundCloud: `ffmpeg -q:v 2`

## SoundCloud Playlist Artwork Update

The `soundcloud_api.py update` command does NOT support playlist artwork.
Use raw API multipart upload:

```python
import json, urllib.request

with open(token_path) as f:
    tokens = json.load(f)

with open(artwork_jpg_path, 'rb') as img:
    artwork_data = img.read()

boundary = '----FormBoundary7MA4YWxkTrZu54W'
body = b'--' + boundary.encode() + b'\r\n'
body += b'Content-Disposition: form-data; name="playlist[artwork_data]"; filename="artwork.jpg"\r\n'
body += b'Content-Type: image/jpeg\r\n\r\n'
body += artwork_data
body += b'\r\n--' + boundary.encode() + b'--\r\n'

req = urllib.request.Request(
    f'https://api.soundcloud.com/playlists/{playlist_id}',
    data=body, method='PUT'
)
req.add_header('Authorization', f'OAuth {tokens["access_token"]}')
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
resp = urllib.request.urlopen(req, timeout=120)
result = json.loads(resp.read().decode())
```

## Albums That Use This Scene

- **₴ØɄ₦ĐĐɆ₴łǤ₵** (7 tracks) — Sideshow skid marks, no characters, parking lot only