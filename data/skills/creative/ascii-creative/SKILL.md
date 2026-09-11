---
name: ascii-creative
description: "ASCII art and video: pyfiglet, cowsay, image-to-ASCII, and full video-to-ASCII conversion with audio-reactive and generative modes."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ASCII, art, video, generative, pyfiglet, cowsay, spectrogram, creative]
---

# ASCII Creative

Unified skill for ASCII art and video creation. Two tools:

1. **ASCII Art** — Static ASCII art: pyfiglet banners, cowsay, image-to-ASCII, boxes
2. **ASCII Video** — Animated ASCII: video-to-ASCII, audio-reactive, generative, hybrid modes

## When to use

Load this skill for any ASCII-based creative output — static art, animated video, or audio visualization.

## Quick dispatch

| Task | Section | Reference |
|------|---------|-----------|
| Static ASCII art, banners, image conversion | [ASCII Art](#ascii-art) | `references/ascii-art.md` |
| Animated ASCII video, audio-reactive, generative | [ASCII Video](#ascii-video) | `references/ascii-video.md` + `references/asciivid-*.md` |

---

## ASCII Art

Static ASCII art generation using pyfiglet, cowsay, boxes, and image-to-ASCII converters.

### Quick start

```bash
# Banner text
python3 -c "from pyfiglet import Figlet; print(Figlet().renderText('Hello'))"

# Cowsay
python3 -c "from cowsay import cowsay; cowsay('Hello World')"

# Image to ASCII
python3 -c "from ascii_magic import from_image; art = from_image('photo.jpg'); art.to_terminal()"
```

### Key features

- **pyfiglet:** 300+ font styles for banner text
- **cowsay:** Character speech bubbles
- **boxes:** Text framing and decoration
- **image-to-ASCII:** Convert images to colored ASCII art

See `references/ascii-art.md` for full details.

---

## ASCII Video

Animated ASCII video with 6 modes, audio visualization, and generative art.

### Modes

1. **video-to-ASCII** — Convert video files to ASCII animation
2. **audio-reactive** — Audio waveform/spectrogram driven ASCII art
3. **generative** — Procedural ASCII art (matrix rain, plasma, etc.)
4. **hybrid** — Video + audio overlay
5. **lyrics/text** — Synced text display
6. **TTS narration** — Text-to-speech with ASCII visualization

### Quick start

```bash
# Video to ASCII
python3 asciivid.py --mode video --input clip.mp4 --output ascii_clip.mp4

# Audio-reactive
python3 asciivid.py --mode audio --input song.mp3 --style spectrogram

# Generative
python3 asciivid.py --mode generative --effect matrix_rain --duration 30
```

### Stack

Python 3.10+, NumPy, SciPy, Pillow, ffmpeg, concurrent.futures

### Reference files

| File | Content |
|------|---------|
| `references/ascii-video.md` | Full SKILL.md content |
| `references/asciivid-architecture.md` | Pipeline architecture |
| `references/asciivid-composition.md` | Composition and layout |
| `references/asciivid-effects.md` | Visual effects catalog |
| `references/asciivid-inputs.md` | Input formats and handling |
| `references/asciivid-optimization.md` | Performance tuning |
| `references/asciivid-scenes.md` | Scene definitions |
| `references/asciivid-shaders.md` | ASCII shader reference |
| `references/asciivid-troubleshooting.md` | Common errors and fixes |

### Standard

"First-render excellence" — aim for publishable output on the first generation pass.
