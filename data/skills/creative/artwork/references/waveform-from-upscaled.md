# Waveform from Large Upscaled PNGs — ffmpeg Resize Workaround

## Problem

`gen_artwork.py` produces Venice-upscaled background PNGs at 4096×4096 (~22-27MB). Passing these to `gen_waveform_art.py --image` causes `413 Request Entity Too Large` on Venice's image edit API.

Additionally, the venv Python (`/opt/hermes/.venv/bin/python3`) can hang for 30+ seconds when loading PIL for large images, making the `convert RGB` + `thumbnail()` approach unreliable.

## Solution: ffmpeg resize, then PIL crop

Use ffmpeg for the fast resize to ≤1500px, then pass to gen_waveform_art.py:

```bash
# Step 1: Resize the upscaled 4096x4096 bg to 1500x1500 JPEG
ffmpeg -y -i /opt/data/music/artwork/covers/Track_Title_bg.png \
  -vf "scale=1500:1500:flags=lanczos" -frames:v 1 -update 1 \
  /tmp/waveform_source.jpg

# Step 2: Run waveform generation on the resized JPEG
/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py \
  --image /tmp/waveform_source.jpg \
  --title "TRACK TITLE" \
  --output-dir /opt/data/music/artwork/waveforms

# Step 3: Clean up
rm -f /tmp/waveform_source.jpg
```

## Why ffmpeg instead of PIL?

| Tool | Large PNG (22MB) | Result |
|------|------------------|--------|
| `ffmpeg scale=1500` | Instant (< 1s) | Reliable |
| `python3 -c "from PIL import Image; img.thumbnail(...)"` | Hangs 30-60s | Unreliable |

Use ffmpeg for all image pre-processing (resize, format conversion). Reserve venv Python for scripts that need PIL (overlay-title.py, gen_waveform_art.py final crop).
