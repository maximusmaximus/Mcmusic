#!/usr/bin/env python3
"""
gen_artwork.py — Generate album covers (3000x3000) and waveform banners (1240x400)
using Venice AI image generation.

Usage:
  python3 gen_artwork.py --title "Track Title" --genre "dark trap" --bpm 140 --key Fm
  python3 gen_artwork.py --batch  # Generate for all tracks missing artwork
"""
import argparse
import base64
import json
import math
import os
import random
import sys
import urllib.request
from pathlib import Path

VENICE_API_KEY = os.environ.get("VENICE_API_KEY", "")
ARTWORK_DIR = Path(os.environ.get("ARTWORK_DIR", "/opt/data/music/artwork"))
COVERS_DIR = ARTWORK_DIR / "covers"
WAVEFORMS_DIR = ARTWORK_DIR / "waveforms"

def log(msg):
    print(f"[artwork] {msg}", flush=True)

def generate_image(prompt, model="fluently-xl", size="1024x1024"):
    """Generate an image via Venice AI.

    IMPORTANT Venice API rules:
    - Do NOT pass "n": 1 — causes 400 error. Venice generates 1 image by default.
    - Do NOT request sizes > 1024x1024 — causes 400. Generate at 1024x1024 and upscale.
    - Endpoint: /api/v1/images/generations (NOT /api/v1/image/generate)
    - For square covers, use aspect_ratio "1:1" or size "1024x1024"
    """
    url = "https://api.venice.ai/api/v1/images/generations"
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "response_format": "b64_json"
    }
    # Do NOT add "n": 1 — Venice returns 400 for this param
    data = json.dumps(payload).encode()

    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json"
    })

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise RuntimeError(f"Venice API {e.code}: {body}") from e

    b64 = result["data"][0]["b64_json"]
    return base64.b64decode(b64)

def upscale_if_needed(image_path, target_w, target_h):
    """Upscale image using Venice AI /image/upscale endpoint.

    Venice upscale API:
    - POST https://api.venice.ai/api/v1/image/upscale
    - Params: image (base64), scale (2 or 4), creativity (0-0.02)
    - Response: raw image/png binary
    - Min input: 256x256 (65536px). Max output: 16M pixels.
    """
    import subprocess

    fp = Path(image_path)
    if not fp.exists():
        log("  ⚠ Image not found for upscale")
        return False

    # Read current dimensions via ffprobe
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(fp)],
            capture_output=True, text=True, timeout=10)
        dims = probe.stdout.strip().split(",")
        cur_w, cur_h = int(dims[0]), int(dims[1])
    except Exception:
        cur_w, cur_h = 1024, 1024  # assume Venice default

    if cur_w >= target_w and cur_h >= target_h:
        log(f"  Already {cur_w}x{cur_h}, skip upscale")
        return True

    # Determine scale factor (Venice supports 2 or 4 only)
    ratio = max(target_w / cur_w, target_h / cur_h)
    scale = 4 if ratio > 2 else 2

    log(f"  Upscaling {cur_w}x{cur_h} → {cur_w*scale}x{cur_h*scale} via Venice AI (scale={scale})...")

    # Read image and encode as base64
    with open(fp, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    url = "https://api.venice.ai/api/v1/image/upscale"
    payload = json.dumps({
        "image": img_b64,
        "scale": scale,
        "creativity": 0.01,
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            upscaled_data = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        log(f"  ⚠ Venice upscale failed ({e.code}): {body}")
        # Fallback to ffmpeg
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(fp),
                "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
                "-update", "1", str(fp)
            ], check=True, capture_output=True, timeout=60)
            log(f"  Fallback: ffmpeg resize to {target_w}x{target_h}")
            return True
        except Exception:
            return False

    # Write upscaled image
    fp.write_bytes(upscaled_data)
    log(f"  ✓ Venice upscale done")

    # If Venice output is larger than target, crop to exact size
    upscaled_w = cur_w * scale
    upscaled_h = cur_h * scale
    if upscaled_w > target_w or upscaled_h > target_h:
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(fp),
                "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
                "-update", "1", str(fp)
            ], check=True, capture_output=True, timeout=60)
            log(f"  Trimmed to {target_w}x{target_h}")
        except Exception:
            pass

    return True

def crop_waveform(cover_path, waveform_path, target_w=1240, target_h=400):
    """Crop a horizontal slice from the cover image for the waveform banner."""
    try:
        import subprocess
        # Crop from center of image, take a horizontal band
        subprocess.run([
            "convert", str(cover_path),
            "-gravity", "center",
            "-crop", f"{target_w}x{target_h}+0+0",
            "+repage",
            "-quality", "95",
            str(waveform_path)
        ], check=True, capture_output=True)
        log(f"  Waveform cropped: {target_w}x{target_h}")
        return True
    except FileNotFoundError:
        try:
            from PIL import Image
            img = Image.open(cover_path)
            w, h = img.size
            # Take a horizontal band from the center-bottom (more interesting area)
            crop_top = int(h * 0.55)
            crop_bottom = crop_top + int(h * 0.25)
            cropped = img.crop((0, crop_top, w, crop_bottom))
            cropped = cropped.resize((target_w, target_h), Image.LANCZOS)
            cropped.save(waveform_path, quality=95)
            log(f"  Waveform cropped: {target_w}x{target_h}")
            return True
        except ImportError:
            log("  WARNING: No crop tool available")
            return False

def sanitize_filename(title):
    """Clean title for use as filename."""
    return "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip().replace(" ", "_")


# ---------------------------------------------------------------------------
# Cover text overlay system — high-contrast title over generated artwork
# ---------------------------------------------------------------------------

# High-voltage CMY & Neon accent palette for dark backgrounds
NEON_COLORS_FOR_DARK = [
    (0, 240, 255),    # electric cyan
    (0, 255, 255),    # pure neon cyan
    (0, 255, 163),    # cyan mint
    (255, 0, 127),    # hyper magenta
    (255, 16, 240),   # neon fuchsia
    (208, 0, 255),    # electric violet
    (255, 16, 120),   # hot magenta
    (250, 255, 0),    # acid yellow
    (255, 230, 0),    # electric volt yellow
    (255, 215, 0),    # cyber gold
    (57, 255, 20),    # neon green
]

# Subdued dark palette for light backgrounds
DARK_COLORS_FOR_LIGHT = [
    (10, 10, 10),     # near-black
    (25, 0, 51),      # midnight purple
    (0, 0, 80),       # deep navy
    (50, 0, 0),       # dark crimson
]

# Text style presets — each is a dict consumed by overlay_title_on_cover
TEXT_STYLES = [
    {
        "name": "neon_glow",
        "shadow_color_shift": 0.6,   # fraction to dim text color for glow layers
        "glow_layers": 4,            # number of expanding blur layers
        "glow_expand": 6,            # px expansion per layer
        "stroke_width": 0,
        "shadow_offset": (0, 0),
    },
    {
        "name": "hard_drop",
        "shadow_color_shift": 0,     # pure black shadow
        "glow_layers": 0,
        "glow_expand": 0,
        "stroke_width": 3,
        "shadow_offset": (8, 8),
    },
    {
        "name": "emboss_outline",
        "shadow_color_shift": 0,
        "glow_layers": 0,
        "glow_expand": 0,
        "stroke_width": 5,
        "shadow_offset": (4, 4),
    },
    {
        "name": "double_shadow",
        "shadow_color_shift": 0,
        "glow_layers": 0,
        "glow_expand": 0,
        "stroke_width": 2,
        "shadow_offset": (6, 6),
        "second_shadow_offset": (12, 12),
    },
    {
        "name": "glow_outline",
        "shadow_color_shift": 0.5,
        "glow_layers": 2,
        "glow_expand": 8,
        "stroke_width": 4,
        "shadow_offset": (0, 0),
    },
]


def get_dominant_color(image_path):
    """Analyze the cover image and return (R, G, B) of the dominant/average color.

    Down-samples to a tiny image to cheaply compute the average colour.
    Falls back to black (0,0,0) on error.
    """
    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        # Shrink to 16x16 for fast averaging
        small = img.resize((16, 16), Image.LANCZOS)
        pixels = list(small.getdata())
        r = sum(p[0] for p in pixels) // len(pixels)
        g = sum(p[1] for p in pixels) // len(pixels)
        b = sum(p[2] for p in pixels) // len(pixels)
        return (r, g, b)
    except Exception:
        return (0, 0, 0)


def _perceived_brightness(r, g, b):
    """Return perceived brightness 0-255 using the luminance formula."""
    return 0.299 * r + 0.587 * g + 0.114 * b


def get_contrast_text_color(dominant_rgb):
    """Choose a text colour that maximises contrast against the dominant cover colour.

    - Dark backgrounds (brightness < 128): pick from the neon palette
    - Light backgrounds (brightness >= 128): pick from the dark palette
    Returns (R, G, B).
    """
    brightness = _perceived_brightness(*dominant_rgb)
    if brightness < 128:
        return random.choice(NEON_COLORS_FOR_DARK)
    else:
        return random.choice(DARK_COLORS_FOR_LIGHT)


def _pick_text_style():
    """Randomly select one of the pre-defined text styles."""
    return random.choice(TEXT_STYLES)


def overlay_title_on_cover(cover_path, title):
    """Render the track title onto the cover image with high-contrast styling.

    Steps:
      1. Analyse dominant colour of the cover.
      2. Choose a high-contrast text colour (neon for dark, dark for light).
      3. Pick a random text style (glow / drop-shadow / outline).
      4. Render the title onto the lower portion of the cover.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        log("  WARNING: Pillow not available — skipping title overlay")
        return

    img = Image.open(cover_path).convert("RGBA")
    w, h = img.size

    dominant = get_dominant_color(cover_path)
    text_color = get_contrast_text_color(dominant)
    style = _pick_text_style()

    log(f"  Title overlay: dominant={dominant}, text_color={text_color}, style={style['name']}")

    # --- Font selection ---
    # Try a few common paths; fall back to default bitmap font
    font = None
    target_font_size = max(60, int(h * 0.055))  # ~5.5% of image height
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, target_font_size)
                break
            except Exception:
                continue
    if font is None:
        # Pillow default — small but functional
        font = ImageFont.load_default()
        log("  WARNING: No TrueType font found, using default bitmap font")

    # --- Measure text ---
    dummy_draw = ImageDraw.Draw(img)
    bbox = dummy_draw.textbbox((0, 0), title.upper(), font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # If text is wider than image, shrink font until it fits (with padding)
    max_text_w = int(w * 0.88)
    while text_w > max_text_w and target_font_size > 20:
        target_font_size -= 4
        try:
            font = ImageFont.truetype(fp, target_font_size)  # noqa: F821 — fp last matched
        except Exception:
            break
        bbox = dummy_draw.textbbox((0, 0), title.upper(), font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

    # Position: centered horizontally, in the lower ~15% of the image
    text_x = (w - text_w) // 2
    text_y = int(h * 0.83) - text_h // 2

    # --- Compositing layers ---
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    shadow_offset = style.get("shadow_offset", (6, 6))
    stroke_w = style.get("stroke_width", 0)

    # Derive shadow colour
    shift = style.get("shadow_color_shift", 0)
    if shift > 0:
        shadow_color = tuple(max(0, int(c * shift)) for c in text_color) + (180,)
    else:
        shadow_color = (0, 0, 0, 200)

    # Layer 1: optional second shadow (double_shadow style)
    if "second_shadow_offset" in style:
        sx2, sy2 = style["second_shadow_offset"]
        draw.text(
            (text_x + sx2, text_y + sy2),
            title.upper(), font=font, fill=(0, 0, 0, 120),
        )

    # Layer 2: primary shadow / drop
    if shadow_offset != (0, 0):
        sx, sy = shadow_offset
        draw.text(
            (text_x + sx, text_y + sy),
            title.upper(), font=font, fill=shadow_color,
        )

    # Layer 3: glow (multiple expanding blurred copies)
    glow_layers = style.get("glow_layers", 0)
    glow_expand = style.get("glow_expand", 6)
    if glow_layers > 0:
        for i in range(glow_layers, 0, -1):
            glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow)
            alpha = max(30, 160 // (i + 1))
            glow_color = text_color + (alpha,)
            glow_draw.text(
                (text_x, text_y), title.upper(), font=font, fill=glow_color,
                stroke_width=i * glow_expand,
                stroke_fill=text_color + (alpha // 2,),
            )
            glow = glow.filter(ImageFilter.GaussianBlur(radius=i * glow_expand))
            overlay = Image.alpha_composite(overlay, glow)
        # Refresh draw after compositing glow layers
        draw = ImageDraw.Draw(overlay)

    # Layer 4: main text with optional stroke
    text_fill = text_color + (255,)
    stroke_fill = (0, 0, 0, 255) if _perceived_brightness(*text_color) > 128 else (255, 255, 255, 80)
    draw.text(
        (text_x, text_y),
        title.upper(), font=font, fill=text_fill,
        stroke_width=stroke_w, stroke_fill=stroke_fill,
    )

    # Composite onto original
    result = Image.alpha_composite(img, overlay).convert("RGB")
    result.save(cover_path, quality=95)
    log(f"  Title overlay complete: '{title.upper()}'")



# ──────────────────────────────────────────────────────────────────────
# Moon phase calculator — returns the actual lunar phase for a given date.
# Used to ensure cover art reflects the real moon when moon elements
# are selected from the VISUAL_DNA bank.
# ──────────────────────────────────────────────────────────────────────
from datetime import datetime, timezone

def get_moon_phase(date=None):
    """Calculate the current moon phase.

    Returns a dict with:
      - name: e.g. "waxing crescent"
      - illumination: 0-100 percent
      - emoji: 🌑🌒🌓🌔🌕🌖🌗🌘
      - description: e.g. "waxing crescent moon, 23% illuminated, thin silver arc"
      - prompt_fragment: ready-to-use text for image prompts
    """
    if date is None:
        date = datetime.now(timezone.utc)

    # Known new moon reference: Jan 6, 2000 18:14 UTC
    ref = datetime(2000, 1, 6, 18, 14, 0, tzinfo=timezone.utc)
    SYNODIC = 29.53058867  # days

    days_since = (date - ref).total_seconds() / 86400.0
    cycle = (days_since % SYNODIC) / SYNODIC  # 0.0 to 1.0

    illumination = round((1 - math.cos(2 * math.pi * cycle)) / 2 * 100)

    # Phase name and emoji
    if cycle < 0.0625:
        name, emoji = "new moon", "🌑"
        visual = "completely dark new moon, faint corona glow at the edges"
    elif cycle < 0.1875:
        name, emoji = "waxing crescent", "🌒"
        visual = f"thin waxing crescent moon, {illumination}% illuminated, delicate silver arc on the right side"
    elif cycle < 0.3125:
        name, emoji = "first quarter", "🌓"
        visual = f"first quarter half-moon, {illumination}% illuminated, right half lit sharp terminator line"
    elif cycle < 0.4375:
        name, emoji = "waxing gibbous", "🌔"
        visual = f"waxing gibbous moon, {illumination}% illuminated, mostly lit with shadow on the left"
    elif cycle < 0.5625:
        name, emoji = "full moon", "🌕"
        visual = f"full moon, {illumination}% illuminated, complete bright disc with visible craters and mare"
    elif cycle < 0.6875:
        name, emoji = "waning gibbous", "🌖"
        visual = f"waning gibbous moon, {illumination}% illuminated, shadow creeping in from the right"
    elif cycle < 0.8125:
        name, emoji = "last quarter", "🌗"
        visual = f"last quarter half-moon, {illumination}% illuminated, left half lit sharp terminator line"
    elif cycle < 0.9375:
        name, emoji = "waning crescent", "🌘"
        visual = f"thin waning crescent moon, {illumination}% illuminated, fading silver arc on the left side"
    else:
        name, emoji = "new moon", "🌑"
        visual = "completely dark new moon, faint corona glow at the edges"

    prompt_fragment = (
        f"In the sky: a photorealistic {visual}, "
        f"astronomically accurate {name} phase, lunar surface detail visible"
    )

    return {
        "name": name,
        "illumination": illumination,
        "emoji": emoji,
        "description": f"{name}, {illumination}% illuminated",
        "visual": visual,
        "prompt_fragment": prompt_fragment,
    }


# ──────────────────────────────────────────────────────────────────────
# VØIDRIDE Visual DNA — recurring motifs mixed into every cover prompt.
# Add new themes here as the catalog grows. The prompt builder randomly
# picks 2-3 from this list and weaves them into the scene.
#
# Entries containing {moon_phase} are resolved at build time to the
# actual lunar phase for the release date.
# ──────────────────────────────────────────────────────────────────────
VISUAL_DNA = [
    # Vehicles & night riding
    "sleek matte-black car drifting through rain-slicked streets at night, headlights cutting through fog",
    "JDM sports car with neon underglow parked in a dark alley, wet asphalt reflections",
    "lone car racing down an empty highway at night, taillights streaking red through mist",
    "motorcycle silhouette on a rain-soaked overpass, city lights blurred below",

    # The Figure — dark dressed, fedora, mysterious
    "silhouette of a man in a dark trenchcoat and fedora standing in fog, backlit by neon",
    "mysterious figure in black with a wide-brim hat, face hidden in shadow, smoke rising",
    "dark-dressed man with fedora walking through a rain-drenched neon alley, puddle reflections",
    "lone figure in a long coat, standing on a rooftop overlooking a dark cyberpunk cityscape",

    # Katana / weapons aesthetic
    "katana blade catching neon light, held by a shadowed figure in the rain",
    "Japanese sword resting against a wall in a dark room, {moon_phase} moonlight on the blade",
    "glowing katana edge slicing through smoke and haze, sparks trailing",

    # Smoke, haze, atmosphere
    "thick smoke and haze rolling through neon-lit streets, volumetric light beams",
    "dense fog bank consuming a city skyline at night, only neon signs visible",
    "smoke plumes curling around industrial structures, backlit by harsh spotlights",
    "atmospheric mist in an abandoned parking garage, single fluorescent light flickering",

    # Urban / industrial
    "abandoned warehouse with broken skylights, {moon_phase} moonlight casting geometric shadows through broken glass",
    "parking lot with fresh sideshow skid marks, tire smoke still hanging in the air, distant city lights",
    "industrial loading dock at night, shipping containers stacked, single sodium lamp",
    "dark underpass with graffiti-covered walls, puddles reflecting distant headlights",
    "rooftop view of a sprawling dark city, radio towers blinking red, {moon_phase} moon hanging low on the horizon",

    # Space / cosmic
    "spacecraft cockpit view of a dying star, instrument panels glowing amber",
    "derelict space station orbiting a gas giant, hull breach venting atmosphere",
    "astronaut silhouette against a supernova, visor reflecting the explosion",

    # Moon scenes (always use real phase via {moon_phase})
    "{moon_phase} moon rising over a dark ocean, silver light cutting across black water, waves reflecting the lunar glow",
    "dark desert highway stretching to the horizon, {moon_phase} moon dominating the sky, long shadows across cracked earth",
    "figure standing on a cliff edge silhouetted against a massive {moon_phase} moon, wind-swept coat, dramatic scale",
    "abandoned rooftop with a {moon_phase} moon reflected in a rain puddle, antenna silhouettes framing the sky",

    # Neon & color
    "neon signs reflecting in rain puddles — pink, cyan, amber, bleeding into each other",
    "single neon strip casting a harsh colored shadow across a concrete wall",
    "bioluminescent fog rolling through a dark corridor, eerie cyan glow",
]

# Additional visual rules that are always included
VISUAL_RULES = (
    "NO TEXT, NO WORDS, NO LETTERS, NO GRAFFITI TEXT, NO WRITING ON SURFACES. "
    "Professional high-velocity music album artwork, dynamic 3/4 low-angle tracking shot, "
    "Dutch tilt composition, kinetic velocity and illuminated water/tire spray, "
    "harsh volumetric rim lighting, anamorphic lens flare, photorealistic dark cyberpunk aesthetic."
)

def build_cover_prompt(title, genre="dark trap", bpm=140, key="Fm", notes=""):
    """Build a rich prompt for album cover generation.

    Mixes 2-3 elements from the VISUAL_DNA bank with the track's
    genre and mood to maintain consistent VØIDRIDE aesthetics while
    keeping each cover unique.

    Moon elements are resolved to the actual lunar phase for today.
    """
    # Pick 2-3 random visual DNA elements
    n_elements = random.choice([2, 2, 3])
    elements = random.sample(VISUAL_DNA, min(n_elements, len(VISUAL_DNA)))

    # Resolve {moon_phase} placeholders with the real moon phase
    moon = get_moon_phase()
    resolved = []
    has_moon = False
    for el in elements:
        if "{moon_phase}" in el:
            el = el.replace("{moon_phase}", moon["visual"])
            has_moon = True
        resolved.append(el)

    # Build scene description from DNA elements
    scene = "; ".join(resolved)

    # If any element used the moon, add the precise phase instruction
    moon_instruction = ""
    if has_moon:
        moon_instruction = (
            f" IMPORTANT: The moon MUST be depicted as a {moon['name']} "
            f"({moon['illumination']}% illuminated). "
            f"Do NOT show a full moon unless it is actually full. "
            f"The lunar phase must be astronomically accurate."
        )

    # Mood from musical key (minor = darker, major = slightly brighter)
    key_lower = key.lower() if key else "fm"
    mood = "haunting, melancholic" if "m" in key_lower else "intense, electric"

    # Tempo feel
    if bpm and bpm > 160:
        tempo_feel = "frenetic, high-energy"
    elif bpm and bpm > 130:
        tempo_feel = "driving, relentless"
    elif bpm and bpm > 100:
        tempo_feel = "brooding, steady pulse"
    else:
        tempo_feel = "slow, heavy, suffocating"

    prompt = (
        f"Dark cinematic album cover for '{title}'. "
        f"Genre: {genre}, {bpm} BPM, {mood}, {tempo_feel}. "
        f"Scene: {scene}. "
        f"Deep blacks, dark purples, neon accents, spectral light, industrial textures. "
        f"{VISUAL_RULES}"
        f"{moon_instruction} "
        f"{notes}"
    ).strip()

    return prompt

def generate_cover(title, genre="dark trap", bpm=140, key="Fm", notes=""):
    """Generate a cover + waveform for a single track.
    
    Waveform banner (1240x400) is generated directly from the clean background
    BEFORE any title text overlay is applied.
    """
    import shutil
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    WAVEFORMS_DIR.mkdir(parents=True, exist_ok=True)
    
    filename = sanitize_filename(title)
    bg_path = COVERS_DIR / f"{filename}_bg.png"
    cover_path = COVERS_DIR / f"{filename}.png"
    waveform_path = WAVEFORMS_DIR / f"{filename}_waveform.png"
    
    if cover_path.exists():
        log(f"Cover already exists: {cover_path}")
        if not waveform_path.exists():
            source_img = bg_path if bg_path.exists() else cover_path
            crop_waveform(source_img, waveform_path)
        return str(cover_path), str(waveform_path)
    
    log(f"Generating cover: {title}")
    prompt = build_cover_prompt(title, genre, bpm, key, notes)
    log(f"  Prompt: {prompt[:100]}...")
    
    # Generate clean background at max Venice resolution, then upscale
    image_data = generate_image(prompt, width=1024, height=1024)
    if not image_data:
        raise RuntimeError(f"Failed to generate background image for '{title}'. Fallback generation is disabled.")
    
    # Save clean background image (no text)
    bg_path.write_bytes(image_data)
    log(f"  Saved clean background: {bg_path}")
    upscale_if_needed(bg_path, 3000, 3000)
    
    # ── STEP A: Generate waveform banner from clean background BEFORE text overlay ──
    log(f"  Generating waveform banner from clean background (before text)...")
    crop_waveform(bg_path, waveform_path)
    
    # ── STEP B: Copy background to cover path and overlay stylized track title ──
    shutil.copyfile(bg_path, cover_path)
    overlay_title_on_cover(cover_path, title)
    
    return str(cover_path), str(waveform_path)

def batch_generate():
    """Generate artwork for all tracks that don't have covers yet."""
    # Check handoff manifests for track info
    sessions_dir = Path("/opt/data/dawagent/sessions")
    
    # Also check production dirs
    productions_dir = Path("/opt/data/music/productions")
    
    tracks = []
    
    # From handoff manifests
    if sessions_dir.exists():
        for session_dir in sorted(sessions_dir.iterdir()):
            manifest = session_dir / "handoff.json"
            if manifest.exists():
                try:
                    with open(manifest) as f:
                        data = json.load(f)
                    session = data.get("session", session_dir.name)
                    bpm = data.get("bpm", 140)
                    notes = data.get("notes", "")
                    
                    # Extract title from session name
                    title = session.replace("VOIDRIDE_Sample_", "VOIDRIDE Sample ").replace("VOIDRIDE_Full_", "")
                    for part in ["_01_", "_02_", "_03_", "_04_", "_05_", "_06_", "_07_", "_08_", "_09_", "_10_"]:
                        if part in title:
                            title = title.split(part, 1)[-1].replace("_", " ")
                            break
                    
                    if not title or title.startswith("VOIDRIDE"):
                        title = session.replace("_", " ")
                    
                    tracks.append({
                        "title": title,
                        "bpm": bpm,
                        "genre": "dark nightride trap / witch-house",
                        "key": "Fm",
                        "notes": notes
                    })
                except Exception:
                    continue
    
    if not tracks:
        log("No tracks found to generate artwork for")
        return
    
    log(f"Found {len(tracks)} tracks")
    results = []
    
    for track in tracks:
        try:
            cover, waveform = generate_cover(
                title=track["title"],
                genre=track.get("genre", "dark trap"),
                bpm=track.get("bpm", 140),
                key=track.get("key", "Fm"),
                notes=track.get("notes", "")
            )
            results.append({"title": track["title"], "cover": cover, "waveform": waveform, "status": "ok"})
        except Exception as e:
            log(f"  ERROR: {e}")
            results.append({"title": track["title"], "status": "error", "error": str(e)})
    
    # Summary
    log(f"\n{'='*40}")
    log(f"Generated {sum(1 for r in results if r['status']=='ok')}/{len(results)} covers")
    for r in results:
        status = "✅" if r["status"] == "ok" else "❌"
        log(f"  {status} {r['title']}")
    
    return results

def main():
    parser = argparse.ArgumentParser(description="Generate album artwork")
    parser.add_argument("--title", help="Track title")
    parser.add_argument("--genre", default="dark nightride trap / witch-house")
    parser.add_argument("--bpm", type=int, default=140)
    parser.add_argument("--key", default="Fm")
    parser.add_argument("--notes", default="")
    parser.add_argument("--batch", action="store_true", help="Generate for all tracks")
    args = parser.parse_args()
    
    if args.batch:
        results = batch_generate()
        if results:
            print(json.dumps(results, indent=2))
    elif args.title:
        cover, waveform = generate_cover(args.title, args.genre, args.bpm, args.key, args.notes)
        print(json.dumps({"title": args.title, "cover": cover, "waveform": waveform}))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
