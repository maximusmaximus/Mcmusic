#!/usr/bin/env python3
"""gen_artwork.py — Generate cohesive 3000x3000 album/track covers and 1240x400 waveform banners
using Venice AI image generation (governed by model_registry.json).

NOTE: For active or staged album productions, ALWAYS prefer:
  /opt/hermes/.venv/bin/python3 /opt/data/scripts/album_pipeline.py --redo-cover <album|all|1..5>
so track covers remain locked to the Album Visual Showrunner blueprint without interrupting an active pipeline.

Usage:
  python3 gen_artwork.py --title "Track Title" --genre "dark trap" --bpm 140 --key Fm [--album "ALBUM" --album-visual "..." --album-anchor /path/to/album_cover_bg.png]
  python3 gen_artwork.py --batch
"""
import argparse
import base64
import json
import math
import os
import random
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Wire model_registry from /opt/data/scripts or repo scripts directory
for _cand_scripts in (
    "/opt/data/scripts",
    str(Path(__file__).resolve().parents[4] / "scripts"),
    str(Path(__file__).resolve().parents[4] / "data" / "scripts"),
):
    if os.path.isdir(_cand_scripts) and _cand_scripts not in sys.path:
        sys.path.insert(0, _cand_scripts)

try:
    from model_registry import get_role_chain as _get_role_chain
except Exception:
    def _get_role_chain(_role, fallback):
        return list(fallback)

VENICE_API_KEY = os.environ.get("VENICE_API_KEY", "")
VENICE_API_BASE = os.environ.get("VENICE_API_BASE", "https://api.venice.ai/api/v1").rstrip("/")
ARTWORK_DIR = Path(os.environ.get("ARTWORK_DIR", "/opt/data/music/artwork"))
COVERS_DIR = ARTWORK_DIR / "covers"
WAVEFORMS_DIR = ARTWORK_DIR / "waveforms"

VENV_PYTHON = "/opt/hermes/.venv/bin/python3" if os.path.exists("/opt/hermes/.venv/bin/python3") else sys.executable


def log(msg):
    print(f"[artwork] {msg}", flush=True)


def get_cover_model_chain():
    return _get_role_chain(
        "image.cover_primary",
        ["qwen-image-3-pro", "grok-imagine-image-2-0", "grok-imagine-image"],
    )


def generate_image(prompt, model=None, size="1024x1024"):
    """Generate an image via Venice AI /images/generations using model_registry fallback chain."""
    models = [model] if model else get_cover_model_chain()
    try:
        w_str, h_str = str(size).lower().split("x", 1)
        width, height = int(w_str), int(h_str)
    except Exception:
        width, height = 1024, 1024

    url = f"{VENICE_API_BASE}/images/generations"
    last_err = None
    for mid in models:
        payload = {
            "model": mid,
            "prompt": prompt,
            "width": width,
            "height": height,
            "response_format": "b64_json",
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {VENICE_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "VOIDRIDE-Artwork/2.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                result = json.loads(resp.read())
            item = (result.get("data") or result.get("images") or [None])[0]
            if isinstance(item, dict) and item.get("b64_json"):
                log(f"  ✓ Generated 1024x1024 cover with {mid}")
                return base64.b64decode(item["b64_json"])
            if isinstance(item, str):
                log(f"  ✓ Generated 1024x1024 cover with {mid}")
                return base64.b64decode(item)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            last_err = f"Venice API {e.code} ({mid}): {body}"
            log(f"  ⚠ {last_err}")
        except Exception as e:
            last_err = f"{mid}: {e}"
            log(f"  ⚠ {last_err}")
    raise RuntimeError(last_err or "All Venice image models failed")


def _pil_resize_exact(image_path, target_w, target_h):
    """Resize image cleanly to exact target dimensions using PIL Lanczos + subtle UnsharpMask."""
    from PIL import Image, ImageFilter

    fp = Path(image_path)
    with Image.open(fp) as im:
        rgb = im.convert("RGB")
        if rgb.size != (target_w, target_h):
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            rgb = rgb.resize((target_w, target_h), resample)
            rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.6, percent=115, threshold=3))
        tmp_path = fp.with_suffix(".tmp.png")
        rgb.save(tmp_path, "PNG")
    os.replace(tmp_path, fp)


def upscale_if_needed(image_path, target_w=3000, target_h=3000):
    """Upscale image to exact 3000x3000 using Venice /image/upscale + safe PIL Lanczos trim."""
    from PIL import Image

    fp = Path(image_path)
    if not fp.exists():
        log("  ⚠ Image not found for upscale")
        return False

    try:
        with Image.open(fp) as im:
            cur_w, cur_h = im.size
    except Exception:
        cur_w, cur_h = 1024, 1024

    if cur_w >= target_w and cur_h >= target_h:
        if (cur_w, cur_h) != (target_w, target_h):
            _pil_resize_exact(fp, target_w, target_h)
        log(f"  Already >= {target_w}x{target_h}, verified {target_w}x{target_h}")
        return True

    ratio = max(target_w / max(cur_w, 1), target_h / max(cur_h, 1))
    scale = 4 if ratio > 2 else 2
    log(f"  Upscaling {cur_w}x{cur_h} → {target_w}x{target_h} via Venice AI (scale={scale})...")

    img_b64 = base64.b64encode(fp.read_bytes()).decode("ascii")
    url = f"{VENICE_API_BASE}/image/upscale"
    payload = json.dumps({"image": img_b64, "scale": scale, "creativity": 0.01}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {VENICE_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "VOIDRIDE-Artwork/2.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            upscaled_data = resp.read()
        if upscaled_data and len(upscaled_data) > 1024:
            fp.write_bytes(upscaled_data)
            log("  ✓ Venice neural upscale complete")
    except Exception as e:
        log(f"  ⚠ Venice upscale unavailable ({e}); applying local Lanczos + UnsharpMask 3000x3000 fallback")

    _pil_resize_exact(fp, target_w, target_h)
    log(f"  ✓ Final master dimensions locked at {target_w}x{target_h}")
    return True


def save_bounded_jpg_companion(png_path, max_bytes=8_000_000):
    """Export a <= 8 MB 3000x3000 RGB .jpg companion beside png_path."""
    from PIL import Image

    src = Path(png_path)
    jpg_path = src.with_suffix(".jpg")
    with Image.open(src) as im:
        rgb = im.convert("RGB")
        for q in (95, 91, 86, 80):
            rgb.save(jpg_path, "JPEG", quality=q)
            if jpg_path.stat().st_size <= max_bytes:
                break
    return str(jpg_path)


def crop_waveform(cover_path, waveform_path, target_w=1240, target_h=400):
    """Crop a clean horizontal slice from the untitled background for the waveform banner."""
    from PIL import Image

    img = Image.open(cover_path).convert("RGB")
    w, h = img.size
    crop_top = int(h * 0.42)
    crop_bottom = min(h, crop_top + int(h * 0.28))
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    cropped = img.crop((0, crop_top, w, crop_bottom)).resize((target_w, target_h), resample)
    Path(waveform_path).parent.mkdir(parents=True, exist_ok=True)
    cropped.save(waveform_path, "PNG")
    log(f"  Waveform cropped: {target_w}x{target_h}")
    return True


def sanitize_filename(title):
    return "".join(c if c.isalnum() or c in " -_" else "" for c in str(title)).strip().replace(" ", "_")


def resolve_overlay_script():
    for cand in (
        Path("/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py"),
        Path(__file__).resolve().parents[2] / "cover-title-overlay" / "scripts" / "overlay-title.py",
        Path(__file__).resolve().parents[3] / "creative" / "cover-title-overlay" / "scripts" / "overlay-title.py",
    ):
        if cand.exists():
            return str(cand)
    return "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py"


def auto_detect_album_context(title, album=None, album_visual=None, album_anchor=None):
    """
    Auto-detect matching album world, blueprint prompt, and album_cover_bg.png anchor
    from pipeline_state.json or current_proposals.json so standalone cover runs never
    drift out of the album's cohesive visual world.
    """
    title_norm = str(title or "").strip().upper()
    detected_album = album or ""
    detected_visual = album_visual or ""
    detected_anchor = album_anchor or ""
    blueprint_prompt = ""

    candidate_proposals = []
    for st_path in ("/opt/data/music/pipeline_state.json", "D:/music/pipeline_state.json"):
        if os.path.exists(st_path):
            try:
                st = json.loads(Path(st_path).read_text(encoding="utf-8"))
                if isinstance(st.get("proposal"), dict):
                    candidate_proposals.append(st["proposal"])
            except Exception:
                pass
    for prop_path in (
        "/opt/data/music/proposals/current_proposals.json",
        "D:/music/proposals/current_proposals.json",
    ):
        if os.path.exists(prop_path):
            try:
                raw = json.loads(Path(prop_path).read_text(encoding="utf-8"))
                props = raw.get("proposals", raw) if isinstance(raw, dict) else raw
                if isinstance(props, list):
                    candidate_proposals.extend(p for p in props if isinstance(p, dict))
            except Exception:
                pass

    matched_prop = None
    for prop in candidate_proposals:
        p_album = str(prop.get("album", "")).strip()
        p_tracks = [str(t).strip().upper() for t in prop.get("tracks", [])]
        if detected_album and p_album.upper() == detected_album.strip().upper():
            matched_prop = prop
            break
        if title_norm and (title_norm in p_tracks or title_norm == p_album.upper()):
            matched_prop = prop
            break

    if matched_prop:
        if not detected_album:
            detected_album = str(matched_prop.get("album", "")).strip()
        if not detected_visual:
            detected_visual = str(matched_prop.get("visual", "")).strip()

    if detected_album:
        slug = detected_album.lower().replace(" ", "-").replace("_", "-")
        for base in ("/opt/data/music/albums", "D:/music/albums"):
            art_dir = Path(base) / slug / "artwork"
            if art_dir.is_dir():
                if not detected_anchor:
                    for anc_name in ("album_cover_bg.png", "album_cover.png", "album_cover.jpg"):
                        anc = art_dir / anc_name
                        if anc.exists():
                            detected_anchor = str(anc)
                            break
                bp_file = art_dir / "visual_showrunner_plan.json"
                if bp_file.exists():
                    try:
                        bp = json.loads(bp_file.read_text(encoding="utf-8"))
                        for item in bp.get("tracks", []):
                            if str(item.get("title", "")).strip().upper() == title_norm:
                                blueprint_prompt = str(item.get("image_prompt", "")).strip()
                                break
                    except Exception:
                        pass
                break

    return {
        "album": detected_album,
        "album_visual": detected_visual,
        "album_anchor": detected_anchor,
        "blueprint_prompt": blueprint_prompt,
    }


def overlay_title_on_cover(cover_path, title, is_album=False, album_anchor=None):
    """Overlay clean geometric stacked title locked to the album's luminous neon palette."""
    script_path = resolve_overlay_script()
    log(f"  Running official cover-title-overlay tool on {cover_path}")
    cmd = [
        VENV_PYTHON,
        script_path,
        "--image", str(cover_path),
        "--title", str(title).strip().upper(),
        "--stacked",
        "--bottom",
        "--auto-color",
        "--output", str(cover_path),
    ]
    if is_album:
        cmd.append("--album")
    elif album_anchor and os.path.exists(album_anchor):
        cmd.extend(["--album-anchor", str(album_anchor)])
    subprocess.run(cmd, check=True)
    save_bounded_jpg_companion(cover_path)
    log(f"  Title overlay complete: {str(title).strip().upper()}")


def get_moon_phase(date=None):
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

    return {
        "name": name,
        "illumination": illumination,
        "emoji": emoji,
        "description": f"{name}, {illumination}% illuminated",
        "visual": visual,
    }


VISUAL_DNA = [
    "sleek matte-black car drifting through rain-slicked streets at night, headlights cutting through fog",
    "JDM sports car with neon underglow parked in a dark alley, wet asphalt reflections",
    "lone car racing down an empty highway at night, taillights streaking red through mist",
    "motorcycle silhouette on a rain-soaked overpass, city lights blurred below",
    "thick smoke and haze rolling through neon-lit streets, volumetric light beams",
    "dense fog bank consuming a city skyline at night, only neon signs visible",
    "atmospheric mist in an abandoned subterranean concrete garage, single cold neon strip flickering",
    "abandoned glass atrium with cracked skylights, {moon_phase} moonlight casting geometric shadows",
    "dark rain-drenched underpass with wet concrete columns, puddles reflecting distant tail-lights",
    "neon reflections bleeding into rain puddles across obsidian asphalt",
]

VISUAL_RULES = (
    "NO TEXT, NO WORDS, NO LETTERS, NO GRAFFITI TEXT, NO WRITING ON SURFACES, NO SIGNAGE. "
    "Professional dark nocturnal music album artwork, crisp anamorphic lens depth, "
    "wet specular reflections, atmospheric volumetric haze, photorealistic dark nocturnal aesthetic."
)


def build_cover_prompt(title, genre="dark trap", bpm=140, key="Fm", notes="", album="", album_visual="", blueprint_prompt=""):
    if blueprint_prompt:
        if notes:
            return f"{blueprint_prompt} Additional direction: {notes}. {VISUAL_RULES}".strip()
        return blueprint_prompt

    moon = get_moon_phase()
    key_lower = key.lower() if key else "fm"
    mood = "haunting, melancholic" if "m" in key_lower else "intense, electric"
    tempo_feel = "driving, relentless" if (bpm and bpm > 130) else "brooding, hypnotic nocturnal pulse"

    if album_visual:
        scene = (
            f"A distinct camera angle inside the exact shared physical world of '{album or title}': {album_visual}. "
            f"Express the mood of '{title}' purely through lighting, lens framing, and atmospheric texture inside this same environment — "
            f"never drift into literal off-world title puns."
        )
    else:
        elements = random.sample(VISUAL_DNA, 2)
        resolved = [el.replace("{moon_phase}", moon["visual"]) for el in elements]
        scene = "; ".join(resolved)

    return (
        f"Dark cinematic album cover without any text or typography. "
        f"Genre: {genre}, {bpm} BPM, {mood}, {tempo_feel}. "
        f"{scene} "
        f"Deep obsidian blacks, cohesive nocturnal neon rim-light, wet specular surfaces. "
        f"{VISUAL_RULES} "
        f"{notes} "
        f"NO TEXT, NO LETTERS, NO WORDS, NO WATERMARKS, NO TYPOGRAPHY."
    ).strip()


def generate_cover(
    title,
    genre="dark trap",
    bpm=140,
    key="Fm",
    notes="",
    album=None,
    album_visual=None,
    album_anchor=None,
    is_album=False,
    force=False,
):
    import shutil

    ctx = auto_detect_album_context(title, album=album, album_visual=album_visual, album_anchor=album_anchor)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    WAVEFORMS_DIR.mkdir(parents=True, exist_ok=True)

    filename = sanitize_filename(title)
    bg_path = COVERS_DIR / f"{filename}_bg.png"
    cover_path = COVERS_DIR / f"{filename}.png"
    waveform_path = WAVEFORMS_DIR / f"{filename}_waveform.png"

    if cover_path.exists() and not force:
        log(f"Cover already exists: {cover_path}")
        if not waveform_path.exists():
            source_img = bg_path if bg_path.exists() else cover_path
            crop_waveform(source_img, waveform_path)
        return str(cover_path), str(waveform_path)

    log(f"Generating cover: {title} (album={ctx['album'] or 'standalone'})")
    prompt = build_cover_prompt(
        title,
        genre=genre,
        bpm=bpm,
        key=key,
        notes=notes,
        album=ctx["album"],
        album_visual=ctx["album_visual"],
        blueprint_prompt=ctx["blueprint_prompt"],
    )
    log(f"  Prompt: {prompt[:120]}...")
    image_data = generate_image(prompt, size="1024x1024")
    if not image_data:
        raise RuntimeError(f"Failed to generate background image for '{title}'.")

    bg_path.write_bytes(image_data)
    log(f"  Saved clean background: {bg_path}")
    upscale_if_needed(bg_path, 3000, 3000)
    log("  Generating waveform banner from clean 3000x3000 background (before text)...")
    crop_waveform(bg_path, waveform_path)
    shutil.copyfile(bg_path, cover_path)
    overlay_title_on_cover(
        cover_path,
        title,
        is_album=is_album,
        album_anchor=ctx["album_anchor"] or None,
    )
    return str(cover_path), str(waveform_path)


def batch_generate():
    sessions_dir = Path("/opt/data/dawagent/sessions")
    tracks = []
    if sessions_dir.exists():
        for session_dir in sorted(sessions_dir.iterdir()):
            manifest = session_dir / "handoff.json"
            if manifest.exists():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
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
                        "title": title,
                        "bpm": bpm,
                        "genre": "dark nightride trap / witch-house",
                        "key": "Fm",
                        "notes": notes,
                    })
                except Exception:
                    continue
    if not tracks:
        log("No tracks found to generate artwork for")
        return []
    log(f"Found {len(tracks)} tracks")
    results = []
    for track in tracks:
        try:
            cover, waveform = generate_cover(
                title=track["title"],
                genre=track.get("genre", "dark trap"),
                bpm=track.get("bpm", 140),
                key=track.get("key", "Fm"),
                notes=track.get("notes", ""),
            )
            results.append({"title": track["title"], "cover": cover, "waveform": waveform, "status": "ok"})
        except Exception as e:
            log(f"  ERROR: {e}")
            results.append({"title": track["title"], "status": "error", "error": str(e)})
    log(f"\n{'=' * 40}")
    log(f"Generated {sum(1 for r in results if r['status'] == 'ok')}/{len(results)} covers")
    return results


def main():
    parser = argparse.ArgumentParser(description="Generate cohesive 3000x3000 VØIDRIDE cover artwork")
    parser.add_argument("--title", help="Track or album title")
    parser.add_argument("--genre", default="dark nightride trap / witch-house")
    parser.add_argument("--bpm", type=int, default=140)
    parser.add_argument("--key", default="Fm")
    parser.add_argument("--notes", default="")
    parser.add_argument("--album", default=None, help="Parent album name for visual world cohesion")
    parser.add_argument("--album-visual", default=None, help="Parent album visual world description")
    parser.add_argument("--album-anchor", default=None, help="Path to album_cover_bg.png to lock neon title palette")
    parser.add_argument("--is-album", action="store_true", help="Treat cover as parent album cover")
    parser.add_argument("--force", action="store_true", help="Regenerate even if output file already exists")
    parser.add_argument("--batch", action="store_true", help="Generate for all tracks")
    args = parser.parse_args()
    if args.batch:
        results = batch_generate()
        if results:
            print(json.dumps(results, indent=2))
    elif args.title:
        cover, waveform = generate_cover(
            args.title,
            genre=args.genre,
            bpm=args.bpm,
            key=args.key,
            notes=args.notes,
            album=args.album,
            album_visual=args.album_visual,
            album_anchor=args.album_anchor,
            is_album=args.is_album,
            force=args.force,
        )
        print(json.dumps({"title": args.title, "cover": cover, "waveform": waveform}))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
