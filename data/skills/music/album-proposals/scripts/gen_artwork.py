#!/usr/bin/env python3
"""gen_artwork.py — Generate album covers (3000x3000) and waveform banners (1240x400)
using Venice AI image generation.

FIXED VERSION: Uses venv Python path for overlay-title.py call to avoid PIL import error.

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

# FIX: Use venv Python which has Pillow installed
VENV_PYTHON = "/opt/hermes/.venv/bin/python3"


def log(msg):
    print(f"[artwork] {msg}", flush=True)


def generate_image(prompt, model="grok-imagine-image-quality", size="1024x1024"):
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
    """Upscale image using Venice AI /image/upscale endpoint."""
    import subprocess

    fp = Path(image_path)
    if not fp.exists():
        log("  ⚠ Image not found for upscale")
        return False

    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(fp)],
            capture_output=True, text=True, timeout=10)
        dims = probe.stdout.strip().split(",")
        cur_w, cur_h = int(dims[0]), int(dims[1])
    except Exception:
        cur_w, cur_h = 1024, 1024

    if cur_w >= target_w and cur_h >= target_h:
        log(f"  Already {cur_w}x{cur_h}, skip upscale")
        return True

    ratio = max(target_w / cur_w, target_h / cur_h)
    scale = 4 if ratio > 2 else 2

    log(f"  Upscaling {cur_w}x{cur_h} → {cur_w*scale}x{cur_h*scale} via Venice AI (scale={scale})...")

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

    fp.write_bytes(upscaled_data)
    log(f"  ✓ Venice upscale done")

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


NEON_COLORS_FOR_DARK = [
    (0, 240, 255), (0, 255, 255), (0, 255, 163), (255, 0, 127),
    (255, 16, 240), (208, 0, 255), (255, 16, 120), (250, 255, 0),
    (255, 230, 0), (255, 215, 0), (57, 255, 20),
]

DARK_COLORS_FOR_LIGHT = [
    (10, 10, 10), (25, 0, 51), (0, 0, 80), (50, 0, 0),
]

TEXT_STYLES = [
    {"name": "neon_glow", "shadow_color_shift": 0.6, "glow_layers": 4, "glow_expand": 6, "stroke_width": 0, "shadow_offset": (0, 0)},
    {"name": "hard_drop", "shadow_color_shift": 0, "glow_layers": 0, "glow_expand": 0, "stroke_width": 3, "shadow_offset": (8, 8)},
    {"name": "emboss_outline", "shadow_color_shift": 0, "glow_layers": 0, "glow_expand": 0, "stroke_width": 5, "shadow_offset": (4, 4)},
    {"name": "double_shadow", "shadow_color_shift": 0, "glow_layers": 0, "glow_expand": 0, "stroke_width": 2, "shadow_offset": (6, 6), "second_shadow_offset": (12, 12)},
    {"name": "glow_outline", "shadow_color_shift": 0.5, "glow_layers": 2, "glow_expand": 8, "stroke_width": 4, "shadow_offset": (0, 0)},
]


def get_dominant_color(image_path):
    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        small = img.resize((16, 16), Image.LANCZOS)
        pixels = list(small.getdata())
        r = sum(p[0] for p in pixels) // len(pixels)
        g = sum(p[1] for p in pixels) // len(pixels)
        b = sum(p[2] for p in pixels) // len(pixels)
        return (r, g, b)
    except Exception:
        return (0, 0, 0)


def _perceived_brightness(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def get_contrast_text_color(dominant_rgb):
    brightness = _perceived_brightness(*dominant_rgb)
    if brightness < 128:
        return random.choice(NEON_COLORS_FOR_DARK)
    return random.choice(DARK_COLORS_FOR_LIGHT)


def _pick_text_style():
    return random.choice(TEXT_STYLES)


def stylize_title(title):
    mapping = {
        "A": "Δ", "B": "฿", "C": "Ͼ", "D": "Đ", "E": "Ɇ",
        "F": "₣", "G": "Ǥ", "H": "Ⱨ", "I": "ł", "K": "Ҟ",
        "L": "Ⱡ", "M": "ӎ", "N": "₦", "O": "Ø", "P": "Ƥ",
        "Q": "ɋ", "R": "Ʀ", "S": "₴", "T": "†", "U": "Ʉ",
        "V": "ⱴ", "W": "₩", "X": "Ӿ", "Y": "Ɏ", "Z": "ɀ"
    }
    return "".join(mapping.get(c, c) for c in title.upper())


def overlay_title_on_cover(cover_path, title):
    """Overlay Unicode-styled title on cover image.

    FIX: Uses VENV_PYTHON (/opt/hermes/.venv/bin/python3) instead of system
    python3, because the system Python does not have Pillow (PIL) installed.
    The overlay-title.py script imports PIL and will crash with system python3.
    """
    import subprocess
    log(f"  Running official cover-title-overlay tool on {cover_path}")
    title_unicode = stylize_title(title)

    cmd = [
        VENV_PYTHON,  # FIXED: was "python3" — system python3 lacks PIL
        "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py",
        "--image", str(cover_path),
        "--title", title_unicode,
        "--auto-color",
        "--output", str(cover_path)
    ]
    subprocess.run(cmd, check=True)
    log(f"  Title overlay complete: {title_unicode}")


def get_moon_phase(date=None):
    """Calculate the current moon phase."""
    from datetime import datetime, timezone
    if date is None:
        date = datetime.now(timezone.utc)
    ref = datetime(2000, 1, 6, 18, 14, 0, tzinfo=timezone.utc)
    SYNODIC = 29.53058867
    days_since = (date - ref).total_seconds() / 86400.0
    cycle = (days_since % SYNODIC) / SYNODIC
    illumination = round((1 - math.cos(2 * math.pi * cycle)) / 2 * 100)

    if cycle < 0.0625:
        name, emoji = "new moon", "🌑"
        visual = "completely dark new moon, faint corona glow at the edges"
    elif cycle < 0.1875:
        name, emoji = "waxing crescent", "🌒"
        visual = f"thin waxing crescent moon, {illumination}% illuminated, delicate silver arc on the right side"
    elif cycle < 0.3125:
        name, emoji = "first quarter", "��"
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


# ── VØIDRIDE Visual DNA ──────────────────────────────────────────────
VISUAL_DNA = [
    "sleek matte-black car drifting through rain-slicked streets at night, headlights cutting through fog",
    "JDM sports car with neon underglow parked in a dark alley, wet asphalt reflections",
    "lone car racing down an empty highway at night, taillights streaking red through mist",
    "motorcycle silhouette on a rain-soaked overpass, city lights blurred below",
    "silhouette of a man in a dark trenchcoat and fedora standing in fog, backlit by neon",
    "mysterious figure in black with a wide-brim hat, face hidden in shadow, smoke rising",
    "dark-dressed man with fedora walking through a rain-drenched neon alley, puddle reflections",
    "lone figure in a long coat, standing on a rooftop overlooking a dark cyberpunk cityscape",
    "katana blade catching neon light, held by a shadowed figure in the rain",
    "Japanese sword resting against a wall in a dark room, {moon_phase} moonlight on the blade",
    "glowing katana edge slicing through smoke and haze, sparks trailing",
    "thick smoke and haze rolling through neon-lit streets, volumetric light beams",
    "dense fog bank consuming a city skyline at night, only neon signs visible",
    "smoke plumes curling around industrial structures, backlit by harsh spotlights",
    "atmospheric mist in an abandoned parking garage, single fluorescent light flickering",
    "abandoned warehouse with broken skylights, {moon_phase} moonlight casting geometric shadows through broken glass",
    "parking lot with fresh sideshow skid marks, tire smoke still hanging in the air, distant city lights",
    "industrial loading dock at night, shipping containers stacked, single sodium lamp",
    "dark underpass with graffiti-covered walls, puddles reflecting distant headlights",
    "rooftop view of a sprawling dark city, radio towers blinking red, {moon_phase} moon hanging low on the horizon",
    "spacecraft cockpit view of a dying star, instrument panels glowing amber",
    "derelict space station orbiting a gas giant, hull breach venting atmosphere",
    "astronaut silhouette against a supernova, visor reflecting the explosion",
    "{moon_phase} moon rising over a dark ocean, silver light cutting across black water, waves reflecting the lunar glow",
    "dark desert highway stretching to the horizon, {moon_phase} moon dominating the sky, long shadows across cracked earth",
    "figure standing on a cliff edge silhouetted against a massive {moon_phase} moon, wind-swept coat, dramatic scale",
    "abandoned rooftop with a {moon_phase} moon reflected in a rain puddle, antenna silhouettes framing the sky",
    "neon signs reflecting in rain puddles — pink, cyan, amber, bleeding into each other",
    "single neon strip casting a harsh colored shadow across a concrete wall",
    "bioluminescent fog rolling through a dark corridor, eerie cyan glow",
]

VISUAL_RULES = (
    "NO TEXT, NO WORDS, NO LETTERS, NO GRAFFITI TEXT, NO WRITING ON SURFACES. "
    "Professional high-velocity music album artwork, dynamic 3/4 low-angle tracking shot, "
    "Dutch tilt composition, kinetic velocity and illuminated water/tire spray, "
    "harsh volumetric rim lighting, anamorphic lens flare, photorealistic dark cyberpunk aesthetic."
)


def build_cover_prompt(title, genre="dark trap", bpm=140, key="Fm", notes=""):
    n_elements = random.choice([2, 2, 3])
    elements = random.sample(VISUAL_DNA, min(n_elements, len(VISUAL_DNA)))
    moon = get_moon_phase()
    resolved = []
    has_moon = False
    for el in elements:
        if "{moon_phase}" in el:
            el = el.replace("{moon_phase}", moon["visual"])
            has_moon = True
        resolved.append(el)
    scene = "; ".join(resolved)
    moon_instruction = ""
    if has_moon:
        moon_instruction = (
            f" IMPORTANT: The moon MUST be depicted as a {moon['name']} "
            f"({moon['illumination']}% illuminated). "
            f"Do NOT show a full moon unless it is actually full. "
            f"The lunar phase must be astronomically accurate."
        )
    key_lower = key.lower() if key else "fm"
    mood = "haunting, melancholic" if "m" in key_lower else "intense, electric"
    if bpm and bpm > 160:
        tempo_feel = "frenetic, high-energy"
    elif bpm and bpm > 130:
        tempo_feel = "driving, relentless"
    elif bpm and bpm > 100:
        tempo_feel = "brooding, steady pulse"
    else:
        tempo_feel = "slow, heavy, suffocating"
    prompt = (
        f"Dark cinematic album cover without any text or typography. "
        f"Genre: {genre}, {bpm} BPM, {mood}, {tempo_feel}. "
        f"Scene: {scene}. "
        f"Deep blacks, dark purples, neon accents, spectral light, industrial textures. "
        f"{VISUAL_RULES}"
        f"{moon_instruction} "
        f"{notes} "
        f"NO TEXT, NO LETTERS, NO WORDS, NO WATERMARKS, NO TYPOGRAPHY."
    ).strip()
    return prompt


def generate_cover(title, genre="dark trap", bpm=140, key="Fm", notes=""):
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
    image_data = generate_image(prompt, size="1024x1024")
    if not image_data:
        raise RuntimeError(f"Failed to generate background image for '{title}'.")
    bg_path.write_bytes(image_data)
    log(f"  Saved clean background: {bg_path}")
    upscale_if_needed(bg_path, 3000, 3000)
    log(f"  Generating waveform banner from clean background (before text)...")
    crop_waveform(bg_path, waveform_path)
    shutil.copyfile(bg_path, cover_path)
    overlay_title_on_cover(cover_path, title)
    return str(cover_path), str(waveform_path)


def batch_generate():
    sessions_dir = Path("/opt/data/dawagent/sessions")
    productions_dir = Path("/opt/data/music/productions")
    tracks = []
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
                    title = session.replace("VOIDRIDE_Sample_", "VOIDRIDE Sample ").replace("VOIDRIDE_Full_", "")
                    for part in ["_01_", "_02_", "_03_", "_04_", "_05_", "_06_", "_07_", "_08_", "_09_", "_10_"]:
                        if part in title:
                            title = title.split(part, 1)[-1].replace("_", " ")
                            break
                    if not title or title.startswith("VOIDRIDE"):
                        title = session.replace("_", " ")
                    tracks.append({
                        "title": title, "bpm": bpm,
                        "genre": "dark nightride trap / witch-house",
                        "key": "Fm", "notes": notes
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
                title=track["title"], genre=track.get("genre", "dark trap"),
                bpm=track.get("bpm", 140), key=track.get("key", "Fm"),
                notes=track.get("notes", "")
            )
            results.append({"title": track["title"], "cover": cover, "waveform": waveform, "status": "ok"})
        except Exception as e:
            log(f"  ERROR: {e}")
            results.append({"title": track["title"], "status": "error", "error": str(e)})
    log(f"\n{'='*40}")
    log(f"Generated {sum(1 for r in results if r['status']=='ok')}/{len(results)} covers")
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
