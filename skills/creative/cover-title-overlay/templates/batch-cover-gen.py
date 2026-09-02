#!/usr/bin/env python3
"""
Batch Cover Art Generation Template
Generates N track covers + 1 album cover using flux-2-max + overlay-title.py.

Usage:
  1. Copy this file to /tmp/gen_<album>_covers.py
  2. Edit the TRACKS list with per-track titles, cars, colors
  3. Run: python3 /tmp/gen_<album>_covers.py

Features:
  - Unicode title construction from code point escapes
  - Blank image detection (size < 10KB = regenerate)
  - Retry loop (up to 3 attempts per cover)
  - Automatic 3000x3000 upscaling with Lanczos + unsharp
  - Track covers use --bottom, album cover uses centered
"""
import subprocess
import os
import base64
import json
import urllib.request

API_KEY = os.environ.get("VENICE_API_KEY", "")
API_URL = "https://api.venice.ai/api/v1/image/generate"
VENV_PY = "/opt/hermes/.venv/bin/python3"
OVERLAY_SCRIPT = "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py"
OUT_DIR = "/opt/data/music/artwork/<album-slug>"

os.makedirs(OUT_DIR, exist_ok=True)

# === Unicode Character Code Points ===
# See unicode-track-titles/references/code-points.md for full table
T_M = "\u04ce"; T_I = "\u0142"; T_D = "\u0110"; T_N = "\u20a6"; T_G = "\u01e4"
T_H = "\u2c67"; T_T = "\u2020"; T_R = "\u01a6"; T_A = "\u0394"; T_L = "\u2c60"
T_S = "\u20a4"; T_O = "\u00d8"; T_W = "\u20a9"; T_C = "\u03fe"; T_E = "\u0246"
T_e = "\u0247"; T_P = "\u01a4"; T_U = "\u0244"; T_K = "\u049e"; T_B = "\u0e3f"
T_V = "\u2c74"; T_X = "\u04fc"; T_Y = "\u024e"; T_F = "\u20a3"; T_Q = "\u024b"
T_Z = "\u007a"

# === High-Voltage CMY Neon Track Definitions ===
# (unicode_title, car_description, accent_description, neon_color_hex, filename_prefix)
TRACKS = [
    ("TITLE_1", "Matte black widebody Dodge Charger Interceptor", "crimson taillight streaks and blue underglow", "#00F0FF", "01_track_one"),     # Electric Cyan
    ("TITLE_2", "Gunmetal Toyota Chaser JZX100 drift spec", "hyper-magenta tire sparks and headlight flare", "#FF007F", "02_track_two"),      # Hyper Magenta
    ("TITLE_3", "Midnight purple Nissan Skyline R34 GT-R", "acid-yellow ground reflections and turbo flame", "#FAFF00", "03_track_three"),    # Acid Yellow
    ("TITLE_4", "Aggressive carbon-fiber Ford Falcon XB GT coupe", "cyan-mint fog illumination and brake glow", "#00FFA3", "04_track_four"),     # Cyan Mint
    ("TITLE_5", "Obsidian widebody Chevrolet Camaro", "laser-fuchsia sign reflections and electric arc", "#FF10F0", "05_track_five"),          # Laser Fuchsia
]

ALBUM_TITLE = "ALBUM_TITLE_UNICODE"
ALBUM_COLOR = "#00F0FF"  # High-voltage Electric Cyan

NEGATION = (
    "NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, "
    "NO SYMBOLS, NO TYPOGRAPHY, NO TYPE, NO FONTS, NO WATERMARKS, NO LABELS, "
    "NO SIGNAGE, NO SIGNS, NO CAPTIONS, NO GRAFFITI, NO WORDS ON PAVEMENT, "
    "NO TEXT ON GROUND, NO PAINTED MARKINGS THAT LOOK LIKE LETTERS."
)

SCENE_TEMPLATE = (
    "Dynamic high-velocity cinematic 35mm film photography. Low-angle 3/4 tracking shot "
    "with a 5-degree Dutch tilt. A {car} aggressively drifting sideways through a rain-slicked "
    "cyberpunk metropolis at night, tires spinning with violent kinetic spray and spark showers "
    "across reflective wet asphalt with {accent}. 1/30s panning shutter motion blur creates vibrant "
    "light trails from crimson and neon taillights while the vehicle remains in razor-sharp focus. "
    "Towering brutalist mega-structures, harsh colored rim lighting, volumetric steam rising from vents, "
    "a solitary silhouette in a dark coat and fedora in the mid-ground. Anamorphic lens flare, "
    "deep chiaroscuro shadows, hyper-detailed surface reflections, Kodak Portra 800 pushed 2 stops. " + NEGATION
)

ALBUM_SCENE = (
    "Epic panoramic cinematic 35mm film photograph with intense dynamic composition. "
    "Ultra-wide low-angle shot overlooking a multi-level cyberpunk metropolis in a torrential downpour. "
    "{hero_car} takes center stage in a high-speed drift, headlights piercing the darkness with "
    "volumetric light beams and casting long glowing reflections on mirror-like wet asphalt. "
    "Multiple interceptor vehicle light trails streak through sweeping elevated highway ramps. "
    "Brutalist skyscrapers with glowing neon grids reach into stormy clouds pierced by lightning. "
    "Cinematic color grading, 35mm film grain, anamorphic horizontal lens flare, "
    "extreme depth of field, Kodak Portra 800 pushed 2 stops. " + NEGATION
)


def generate_bg(prompt, output_path, max_retries=3):
    """Generate background via flux-2-max with blank-image retry."""
    payload = json.dumps({
        "model": "flux-2-max",
        "prompt": prompt,
        "width": 1024,
        "height": 1024,
        "negative_prompt": NEGATION,
    }).encode("utf-8")

    req = urllib.request.Request(API_URL, data=payload, method="POST")
    req.add_header("Authorization", "Bearer " + API_KEY)
    req.add_header("Content-Type", "application/json")

    for attempt in range(max_retries):
        print(f"  Attempt {attempt + 1}...")
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            result = json.loads(resp.read().decode())
            if "images" in result and len(result["images"]) > 0:
                img_bytes = base64.b64decode(result["images"][0])
                print(f"  Image size: {len(img_bytes)} bytes")
                if len(img_bytes) >= 10000:
                    raw_path = output_path.replace(".png", "_raw.webp")
                    with open(raw_path, "wb") as f:
                        f.write(img_bytes)
                    subprocess.run([
                        "ffmpeg", "-y", "-i", raw_path,
                        "-vf", "scale=3000:3000:flags=lanczos,unsharp=5:5:0.8:5:5:0",
                        "-c:v", "png", output_path
                    ], check=True, capture_output=True)
                    print(f"  Generated: {output_path}")
                    return True
                else:
                    print("  Too small (blank image), retrying...")
            else:
                print("  No images in response")
        except Exception as e:
            print(f"  Error: {e}")
    print("  FAILED after {} attempts".format(max_retries))
    return False


WAVEFORMS_DIR = "/opt/data/music/artwork/waveforms"
WAVEFORM_SCRIPT = "/opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py"
os.makedirs(WAVEFORMS_DIR, exist_ok=True)


def generate_waveform_banner(bg_path, title):
    """Generate 1240x400 panoramic waveform banner from clean background BEFORE title overlay."""
    if not os.path.exists(WAVEFORM_SCRIPT):
        # Fallback to direct ffmpeg crop if script not present
        dst = os.path.join(WAVEFORMS_DIR, f"{title.upper()}_waveform.png")
        subprocess.run([
            "ffmpeg", "-y", "-i", bg_path,
            "-vf", "crop=in_w:in_w*400/1240:0:(in_h-in_w*400/1240)/2+in_h*0.1,scale=1240:400:flags=lanczos",
            dst
        ], check=True, capture_output=True)
        print(f"  Waveform (ffmpeg crop): {dst}")
        return

    cmd = [VENV_PY, WAVEFORM_SCRIPT,
           "--image", bg_path,
           "--title", title,
           "--output-dir", WAVEFORMS_DIR,
           "--force"]
    try:
        subprocess.run(cmd, check=True)
        print(f"  Waveform banner generated in {WAVEFORMS_DIR}")
    except Exception as e:
        print(f"  WARNING: Waveform generation failed: {e}")


def overlay_title(bg_path, title, color, output_path, bottom=True):
    cmd = [VENV_PY, OVERLAY_SCRIPT,
           "--image", bg_path, "--title", title,
           "--color", color, "--output", output_path]
    if bottom:
        cmd.append("--bottom")
    subprocess.run(cmd, check=True)
    print(f"  Titled: {output_path}")


# === GENERATE TRACK COVERS ===
print("=" * 60)
print("COVER ART GENERATION")
print("=" * 60)

for i, (title, car, accent, color, prefix) in enumerate(TRACKS):
    print(f"\n--- Track {i + 1}: {prefix} ---")
    bg_path = os.path.join(OUT_DIR, prefix + "_bg.png")
    cover_path = os.path.join(OUT_DIR, prefix + "_cover.png")
    prompt = SCENE_TEMPLATE.format(car=car, accent=accent)
    print("  Generating background...")
    if generate_bg(prompt, bg_path):
        # Step A: Waveform banner from clean background (BEFORE title overlay)
        print("  Generating waveform banner from clean background (before text)...")
        generate_waveform_banner(bg_path, title=prefix)
        # Step B: Overlay title text onto cover
        print("  Overlaying title...")
        overlay_title(bg_path, title, color, cover_path, bottom=True)
    else:
        print("  SKIPPING (background generation failed)")

# === GENERATE ALBUM COVER ===
print(f"\n--- Album Cover ---")
album_bg_path = os.path.join(OUT_DIR, "album_bg.png")
album_cover_path = os.path.join(OUT_DIR, "album_cover.png")
hero_car = TRACKS[0][1]  # Use track 1's car as hero
prompt = ALBUM_SCENE.format(hero_car=hero_car)
print("  Generating album background...")
if generate_bg(prompt, album_bg_path):
    print("  Overlaying album title (centered)...")
    overlay_title(album_bg_path, ALBUM_TITLE, ALBUM_COLOR, album_cover_path, bottom=False)

print(f"\n{'=' * 60}")
print("COVER ART GENERATION COMPLETE")
print(f"Output: {OUT_DIR}")
print(f"{'=' * 60}")

# === DOWNSCALE FOR TELEGRAM DELIVERY ===
print("\nDownscaling for Telegram delivery...")
tg_dir = "/tmp/covers_tg"
os.makedirs(tg_dir, exist_ok=True)
for prefix in [t[4] for t in TRACKS] + ["album"]:
    src = os.path.join(OUT_DIR, f"{prefix.replace('album', 'album')}_cover.png")
    dst = os.path.join(tg_dir, f"{prefix}_cover.jpg")
    if not os.path.exists(src):
        # Try alternate naming
        src = os.path.join(OUT_DIR, f"{prefix}_cover.png")
    if os.path.exists(src):
        subprocess.run([
            "ffmpeg", "-y", "-i", src,
            "-vf", "scale=1500:1500:flags=lanczos", "-q:v", "2", dst
        ], check=True, capture_output=True)
        print(f"  {dst} ({os.path.getsize(dst) / 1024 / 1024:.1f} MB)")
print("\nDone! Send the JPG files as photos, PNG files as documents.")
