#!/usr/bin/env python3
"""
Overlay a Unicode-styled song or album title onto a cover art image with:
  1. Stacked 1-word-per-line layout where EACH word is independently scaled up to fill
     the full width of the screen (~92% canvas width).
  2. Album-Cohesive Neon Palette Family (`--album-anchor` / `.cover_palettes.json`) so all
     covers on an album share one unified 2-3 hue lighting/typography family instead of
     scattering across a 6-color rainbow.
  3. Strict WCAG relative-luminance contrast floor (`Y >= 0.45`) + raised minimum interior
     opacity + adaptive bottom readability scrim so dark-on-dark unreadable text (e.g. deep
     indigo on pitch black) can never occur.

Usage:
    python3 overlay-title.py --image <bg_image> --title "<TITLE>" [--color <hex>] [--auto-color]
                             [--album-anchor <album_bg_image>] [--opacity 0.68] [--output <path>]
                             [--no-glow] [--no-shadow] [--top] [--bottom] [--stacked]
                             [--single-line] [--album] [--spacing <px>]
"""

import argparse
import colorsys
import hashlib
import json
import math
import os
import shutil
import sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# Validated font paths with complete native Unicode glyph coverage (31/31 chars)
FONT_CANDIDATES = [
    "/opt/data/.fonts/SegoeUI-Black.ttf",
    "/opt/data/.fonts/SegoeUI-Bold.ttf",
    "/opt/data/.fonts/Calibri-Bold.ttf",
    "/opt/data/.fonts/Arial-Bold.ttf",
    "C:/Windows/Fonts/seguibl.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "D:/hermes-music/data/.fonts/SegoeUI-Black.ttf",
    "D:/hermes-music/data/.fonts/SegoeUI-Bold.ttf",
    "D:/hermes-music/data/.fonts/Calibri-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

CMY_NEON_PALETTE = {
    "electric_cyan": "#00F0FF",
    "neon_cyan": "#00FFFF",
    "deep_cyan": "#00E5FF",
    "cyan_mint": "#00FFA3",
    "ice_blue": "#5CE6FF",
    "hyper_magenta": "#FF2E9F",
    "laser_magenta": "#FF4DFF",
    "neon_fuchsia": "#FF3DF0",
    "electric_violet": "#DF73FF",
    "hot_pink": "#FF4FA3",
    "crimson_magenta": "#FF477E",
    "acid_yellow": "#FAFF00",
    "electric_volt": "#FFE600",
    "neon_yellow": "#FFFF00",
    "cyber_gold": "#FFD700",
    "solar_amber": "#FFB700",
    "neon_lime": "#39FF14",
    "radioactive_green": "#00FF66",
    "blaze_orange": "#FF7A1A",
}

MIN_NEON_RELATIVE_LUMINANCE = 0.45
ARTWORK_COVERS_DIR = "/opt/data/music/artwork/covers"
DEFAULT_TARGET_WIDTH_RATIO = 0.92  # Each word fills 92% of screen width

UNICODE_MAP = {
    'A': '\u0394', 'B': '\u0e3f', 'C': '\u03fe', 'D': '\u0110', 'E': '\u0246',
    'F': '\u20a3', 'G': '\u01e4', 'H': '\u2c67', 'I': '\u0142', 'K': '\u049e',
    'L': '\u2c60', 'M': '\u04cd', 'N': '\u20a6', 'O': '\u00d8', 'P': '\u01a4',
    'Q': '\u024b', 'R': '\u01a6', 'S': '\u20a4', 'T': '\u2020', 'U': '\u0244',
    'V': '\u2c74', 'W': '\u20a9', 'X': '\u04fc', 'Y': '\u024e', 'Z': '\u007a',
}
ALWAYS_REPLACE = set('OARDLWIBET')
SOMETIMES_REPLACE = set('CNGHSFKMPUVXYQZ')


def _stylize_if_ascii(title):
    """Automatically apply VØIDRIDE Unicode glyph stylization if input is plain ASCII."""
    if any(ord(c) > 127 for c in title):
        return title
    res = []
    sec_count = {}
    for ch in title.upper():
        if ch in ALWAYS_REPLACE and ch in UNICODE_MAP:
            res.append(UNICODE_MAP[ch])
        elif ch in SOMETIMES_REPLACE and ch in UNICODE_MAP:
            cnt = sec_count.get(ch, 0)
            sec_count[ch] = cnt + 1
            res.append(UNICODE_MAP[ch] if cnt % 2 == 0 else ch)
        else:
            res.append(ch)
    return "".join(res)


def get_best_font_path():
    """Find the best existing font path with complete Unicode coverage."""
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return None


def _hue_dist(h1, h2):
    """Shortest angular distance between two hues in degrees (0..180)."""
    d = abs(h1 - h2) % 360.0
    return 360.0 - d if d > 180.0 else d


def _hsv_to_rgb_tuple(h_deg, s, v):
    rf, gf, bf = colorsys.hsv_to_rgb((h_deg % 360.0) / 360.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return (int(round(rf * 255)), int(round(gf * 255)), int(round(bf * 255)))


def _rgb_to_hex(rgb):
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _srgb_channel_to_linear(channel_255):
    v = max(0.0, min(1.0, channel_255 / 255.0))
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    """WCAG 2.1 linear relative luminance in [0.0, 1.0]."""
    return (
        0.2126 * _srgb_channel_to_linear(rgb[0])
        + 0.7152 * _srgb_channel_to_linear(rgb[1])
        + 0.0722 * _srgb_channel_to_linear(rgb[2])
    )


def ensure_luminous_neon_rgb(h_deg, s=0.92, v=1.0, min_luminance=MIN_NEON_RELATIVE_LUMINANCE):
    """
    Convert HSV hue into an unmistakable, high-contrast neon RGB color guaranteed to satisfy
    `relative_luminance(rgb) >= min_luminance`.

    Pure indigo/deep-blue hues (~220°-265°) have WCAG luminance as low as 0.08-0.14 even at
    V=1.0, making text nearly invisible against dark VØIDRIDE cover backgrounds. This helper
    gently steers deep indigo out of the perceptual dead-zone (toward electric ice-blue or
    luminous neon violet) and blends white-hot core energy (lowering S while keeping V=1.0)
    until the luminance floor is met.
    """
    hue = h_deg % 360.0
    val = max(0.96, min(1.0, v))
    sat = max(0.0, min(1.0, s))

    base_rgb = _hsv_to_rgb_tuple(hue, sat, val)
    if relative_luminance(base_rgb) >= min_luminance:
        return base_rgb

    # Nudge pure ultramarine/indigo dead-zone (222°..266°) gently toward ice-cyan or electric orchid
    adjusted_hue = hue
    if 222.0 <= hue <= 246.0:
        adjusted_hue = 206.0 + (hue - 222.0) * 0.45
    elif 246.0 < hue <= 268.0:
        adjusted_hue = 276.0 + (hue - 246.0) * 0.45

    cand_rgb = _hsv_to_rgb_tuple(adjusted_hue, sat, val)
    if relative_luminance(cand_rgb) >= min_luminance:
        return cand_rgb

    # Binary search on saturation in [0.15, sat] to mix white-hot neon luminance while keeping hue identity
    lo, hi = 0.12, sat
    best_rgb = _hsv_to_rgb_tuple(adjusted_hue, lo, 1.0)
    for _ in range(18):
        mid = (lo + hi) / 2.0
        rgb_mid = _hsv_to_rgb_tuple(adjusted_hue, mid, 1.0)
        if relative_luminance(rgb_mid) >= min_luminance:
            best_rgb = rgb_mid
            lo = mid  # Prefer maximum saturation that still meets the luminance floor
        else:
            hi = mid
    return best_rgb


def ensure_luminous_hex_stops(color_hex, min_luminance=MIN_NEON_RELATIVE_LUMINANCE):
    """Build a 3-stop luminous neon gradient from an explicit hex/named color while enforcing luminance floor."""
    if color_hex in CMY_NEON_PALETTE:
        color_hex = CMY_NEON_PALETTE[color_hex]
    c_hex = color_hex.lstrip("#")
    c_raw = tuple(int(c_hex[i:i + 2], 16) for i in (0, 2, 4))
    h1, s1, _ = colorsys.rgb_to_hsv(c_raw[0] / 255.0, c_raw[1] / 255.0, c_raw[2] / 255.0)
    base_deg = h1 * 360.0
    s_use = max(0.75, s1)
    return [
        ensure_luminous_neon_rgb(base_deg, s_use, 1.0, min_luminance=min_luminance),
        ensure_luminous_neon_rgb((base_deg + 26.0) % 360.0, max(0.72, s_use - 0.04), 1.0, min_luminance=min_luminance),
        ensure_luminous_neon_rgb((base_deg + 52.0) % 360.0, max(0.68, s_use - 0.08), 1.0, min_luminance=min_luminance),
    ]


def _compute_chromatic_hue_profile(image_path, top=False, bottom=True):
    """Return smoothed 36-bin (10°/bin) chromatic weight histogram for an image."""
    num_bins = 36
    bin_weights = [0.0] * num_bins
    img = Image.open(image_path).convert("RGB")
    resample = Image.Resampling.BOX if hasattr(Image, "Resampling") else Image.BOX
    thumb = img.resize((128, 128), resample)
    w, h = thumb.size

    if top:
        zone_min_y, zone_max_y = 0, int(h * 0.45)
    elif bottom:
        zone_min_y, zone_max_y = int(h * 0.50), h
    else:
        zone_min_y, zone_max_y = int(h * 0.25), int(h * 0.75)

    for y in range(h):
        zone_mult = 1.6 if (zone_min_y <= y <= zone_max_y) else 1.0
        for x in range(w):
            r, g, b = thumb.getpixel((x, y))
            h_val, s_val, v_val = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            if v_val > 0.10 and s_val > 0.14:
                weight = (s_val ** 1.3) * (v_val ** 1.1) * zone_mult
                bin_idx = int((h_val * 360.0) // 10.0) % num_bins
                bin_weights[bin_idx] += weight

    smoothed = [0.0] * num_bins
    kernel = [(0, 0.40), (-1, 0.22), (1, 0.22), (-2, 0.08), (2, 0.08)]
    for i in range(num_bins):
        acc = 0.0
        for offset, kw in kernel:
            acc += bin_weights[(i + offset) % num_bins] * kw
        smoothed[i] = acc
    return smoothed


def extract_album_neon_family(anchor_image_path):
    """
    Derive a cohesive 3-hue Album Signature Neon Family `[h_primary, h_secondary, h_bridge]`
    directly from the album cover's lighting palette so all 6 covers on an album belong to
    one unmistakable visual world instead of scattering across 6 unrelated rainbow colors.
    """
    smoothed = _compute_chromatic_hue_profile(anchor_image_path, top=False, bottom=False)
    total_chroma = sum(smoothed)

    if total_chroma < 1.0:
        # Near-monochrome silver/obsidian cover -> classic VØIDRIDE cyan + violet + mint family
        return [188.0, 286.0, 156.0]

    ranked_desc = sorted(range(len(smoothed)), key=lambda idx: smoothed[idx], reverse=True)
    h_dom = (ranked_desc[0] * 10.0 + 5.0) % 360.0
    dom_weight = smoothed[ranked_desc[0]]

    # Look for a genuine secondary neon lighting accent in the album cover (45°..165° from h_dom)
    h_sec = None
    for idx in ranked_desc[1:]:
        cand_h = (idx * 10.0 + 5.0) % 360.0
        dist = _hue_dist(cand_h, h_dom)
        if 45.0 <= dist <= 165.0 and smoothed[idx] >= dom_weight * 0.18:
            h_sec = cand_h
            break

    if h_sec is None:
        # Harmonious split-complementary neon partner that pops cleanly against h_dom
        h_sec = (h_dom + 135.0) % 360.0

    # Bridge hue sits 38° along the shorter arc from h_sec toward h_dom for smooth 3-stop gradients
    diff = ((h_dom - h_sec + 540.0) % 360.0) - 180.0
    step_sign = 1.0 if diff >= 0 else -1.0
    h_bridge = (h_sec + step_sign * min(42.0, abs(diff) * 0.5)) % 360.0
    return [round(h_dom, 1), round(h_sec, 1), round(h_bridge, 1)]


def _discover_album_anchor_path(image_path, output_path=None, explicit_anchor=None):
    if explicit_anchor and os.path.exists(explicit_anchor):
        return explicit_anchor
    for base_p in [output_path, image_path]:
        if not base_p:
            continue
        d = os.path.dirname(os.path.abspath(base_p))
        for cand_name in ("album_cover_bg.png", "album_cover_bg.jpg", "album_cover.png", "album_cover.jpg"):
            cand = os.path.join(d, cand_name)
            if os.path.exists(cand):
                return cand
    return None


def detect_least_used_gradient_colors(
    image_path,
    title="",
    output_path=None,
    top=False,
    bottom=True,
    album_anchor=None,
    is_album=False,
):
    """
    Selects a luminous, high-contrast 3-stop neon gradient (`WCAG Y >= 0.45` on every stop).

    When part of an album (via `--album`, `--album-anchor`, `album_cover*` in the folder, or
    `.cover_palettes.json`), locks ALL covers on the album to the Album's 3-Hue Signature Neon
    Family with subtle track-to-track sweep/harmonic variation (never a 6-color rainbow!).
    """
    try:
        target_dir = os.path.dirname(os.path.abspath(output_path or image_path))
        registry_path = os.path.join(target_dir, ".cover_palettes.json")
        cover_key = os.path.splitext(os.path.basename(output_path or image_path))[0].lower()
        if cover_key.endswith("_cover"):
            cover_key = cover_key[:-6]

        is_album_cover = bool(is_album or cover_key in ("album", "album_cover"))

        registry = {}
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as rf:
                    registry = json.load(rf)
            except Exception:
                registry = {}

        anchor_path = _discover_album_anchor_path(image_path, output_path=output_path, explicit_anchor=album_anchor)
        family_hues = None

        if isinstance(registry.get("_album_family"), dict):
            stored = registry["_album_family"].get("anchor_hues")
            if isinstance(stored, list) and len(stored) >= 3 and not is_album_cover:
                family_hues = [float(x) for x in stored[:3]]

        if family_hues is None and (is_album_cover or anchor_path):
            src_for_family = anchor_path if (anchor_path and not is_album_cover) else image_path
            family_hues = extract_album_neon_family(src_for_family)
            registry["_album_family"] = {
                "anchor_hues": family_hues,
                "source": os.path.basename(src_for_family),
            }

        if family_hues is not None:
            h_dom, h_sec, h_bridge = family_hues[0], family_hues[1], family_hues[2]
            if is_album_cover:
                # Album cover leads with high-contrast accent -> bridge -> primary world hue
                raw_hues = [h_sec, h_bridge, h_dom]
            else:
                # Deterministic per-track variation STRICTLY inside the album's neon family (±10° max drift)
                seed = hashlib.sha256(f"{cover_key}:{title}".encode("utf-8")).digest()
                variant_idx = seed[0] % 5
                micro_shift = ((seed[1] % 17) - 8) * 1.0  # -8° .. +8° harmonic shimmer
                patterns = [
                    [h_sec, h_bridge, h_dom],
                    [h_dom, h_bridge, h_sec],
                    [h_bridge, h_sec, (h_sec + 24.0) % 360.0],
                    [(h_dom - 14.0) % 360.0, h_dom, h_bridge],
                    [h_sec, (h_sec + 22.0) % 360.0, h_bridge],
                ]
                chosen = patterns[variant_idx]
                raw_hues = [(h + micro_shift) % 360.0 for h in chosen]
        else:
            # Standalone single cover: pick high-contrast accent against dominant background hue
            fam = extract_album_neon_family(image_path)
            raw_hues = [fam[1], fam[2], fam[0]]

        stop_1 = ensure_luminous_neon_rgb(raw_hues[0], 0.94, 1.00, min_luminance=MIN_NEON_RELATIVE_LUMINANCE)
        stop_2 = ensure_luminous_neon_rgb(raw_hues[1], 0.90, 1.00, min_luminance=MIN_NEON_RELATIVE_LUMINANCE)
        stop_3 = ensure_luminous_neon_rgb(raw_hues[2], 0.86, 1.00, min_luminance=MIN_NEON_RELATIVE_LUMINANCE)

        try:
            registry[cover_key] = {
                "title": title,
                "primary_hue": round(raw_hues[0], 1),
                "hues": [round(h, 1) for h in raw_hues],
                "stops_hex": [_rgb_to_hex(stop_1), _rgb_to_hex(stop_2), _rgb_to_hex(stop_3)],
                "luminance": [
                    round(relative_luminance(stop_1), 3),
                    round(relative_luminance(stop_2), 3),
                    round(relative_luminance(stop_3), 3),
                ],
            }
            with open(registry_path, "w", encoding="utf-8") as wf:
                json.dump(registry, wf, indent=2)
        except Exception:
            pass

        print(
            f"[gradient] Cohesive neon stops for '{cover_key}': "
            f"{raw_hues[0]:.0f}° ({_rgb_to_hex(stop_1)}, Y={relative_luminance(stop_1):.2f}) -> "
            f"{raw_hues[1]:.0f}° ({_rgb_to_hex(stop_2)}, Y={relative_luminance(stop_2):.2f}) -> "
            f"{raw_hues[2]:.0f}° ({_rgb_to_hex(stop_3)}, Y={relative_luminance(stop_3):.2f})"
        )
        return [stop_1, stop_2, stop_3]
    except Exception as e:
        print(f"[gradient] Fallback gradient due to error ({e})", file=sys.stderr)
        return [(0, 240, 255), (223, 115, 255), (0, 255, 163)]


def detect_opposite_key_color(image_path, top=False, bottom=False):
    """Backwards-compatible helper returning the primary high-contrast neon hex color."""
    stops = detect_least_used_gradient_colors(image_path, top=top, bottom=bottom)
    return _rgb_to_hex(stops[0])


detect_harmonious_cmy_color = detect_opposite_key_color


def find_font_size(draw, text_str, target_width, font_path, max_size=1800):
    """Binary search for largest font size where text_str fits within target_width."""
    lo, hi = 16, max_size
    while lo < hi:
        mid = (lo + hi + 1) // 2
        font = ImageFont.truetype(font_path, mid) if font_path else ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text_str, font=font)
        text_w = bbox[2] - bbox[0]
        if text_w <= target_width:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _render_word_mask_fitted(word, font_path, target_w, max_line_h, stroke_w):
    """
    Renders a single word (one line) scaled up so it fills `target_w` horizontally,
    while clamping vertical height to `max_line_h` so short 3-4 letter words fill the
    entire screen width without becoming taller than the cover height budget.
    Returns (fill_mask_L, stroke_mask_L, rendered_h).
    """
    dummy_img = Image.new("L", (16, 16), 0)
    dummy_draw = ImageDraw.Draw(dummy_img)

    font_size = find_font_size(dummy_draw, word, target_w, font_path, max_size=1800)
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    bbox = dummy_draw.textbbox((0, 0), word, font=font)
    nat_w = max(1, bbox[2] - bbox[0])
    nat_h = max(1, bbox[3] - bbox[1])

    pad = stroke_w * 3 + 12
    canvas_w = nat_w + pad * 2
    canvas_h = nat_h + pad * 2

    fill_img = Image.new("L", (canvas_w, canvas_h), 0)
    stroke_img = Image.new("L", (canvas_w, canvas_h), 0)

    draw_fill = ImageDraw.Draw(fill_img)
    draw_stroke = ImageDraw.Draw(stroke_img)

    draw_x = pad - bbox[0]
    draw_y = pad - bbox[1]

    draw_fill.text((draw_x, draw_y), word, font=font, fill=255)
    draw_stroke.text((draw_x, draw_y), word, font=font, fill=255, stroke_width=stroke_w, stroke_fill=255)

    fill_bbox = fill_img.getbbox() or (pad, pad, canvas_w - pad, canvas_h - pad)
    crop_left = max(0, fill_bbox[0] - stroke_w)
    crop_top = max(0, fill_bbox[1] - stroke_w)
    crop_right = min(canvas_w, fill_bbox[2] + stroke_w)
    crop_bottom = min(canvas_h, fill_bbox[3] + stroke_w)

    fill_cropped = fill_img.crop((crop_left, crop_top, crop_right, crop_bottom))
    stroke_cropped = stroke_img.crop((crop_left, crop_top, crop_right, crop_bottom))

    desired_w = target_w + stroke_w * 2
    scale_x = desired_w / max(1, fill_cropped.width)
    desired_h = int(round(fill_cropped.height * scale_x))
    if desired_h > max_line_h:
        desired_h = max_line_h

    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    fill_resized = fill_cropped.resize((desired_w, max(1, desired_h)), resample)
    stroke_resized = stroke_cropped.resize((desired_w, max(1, desired_h)), resample)

    return fill_resized, stroke_resized, max(1, desired_h)


def _create_gradient_and_opacity_layer(w, h, stops, base_opacity=0.72, line_idx=0):
    """
    Creates an RGBA image of size (w, h) for a word line:
      - RGB channels: smooth 3-stop diagonal gradient built from the album's luminous neon family.
      - Alpha channel: variable glass opacity with a strict legibility floor (`min_alpha >= 0.54`)
        so letter interiors never vanish into dark or busy backgrounds.
    """
    s1, s2, s3 = stops[0], stops[1], stops[2]
    if line_idx % 2 == 1:
        s1, s2, s3 = stops[2], stops[1], stops[0]

    gw = min(w, 320)
    gh = min(h, 160)
    grad_small = Image.new("RGBA", (gw, gh))
    px = grad_small.load()

    max_alpha = max(0.78, min(0.97, base_opacity + 0.24))
    min_alpha = max(0.54, min(0.80, base_opacity - 0.12))

    for y in range(gh):
        yf = y / max(1, gh - 1)
        vert_alpha_factor = 0.52 + 0.48 * math.cos(yf * math.pi * 1.30)

        for x in range(gw):
            xf = x / max(1, gw - 1)
            t = max(0.0, min(1.0, 0.78 * xf + 0.22 * yf))
            if t < 0.5:
                u = t * 2.0
                r = int(round(s1[0] * (1.0 - u) + s2[0] * u))
                g = int(round(s1[1] * (1.0 - u) + s2[1] * u))
                b = int(round(s1[2] * (1.0 - u) + s2[2] * u))
            else:
                u = (t - 0.5) * 2.0
                r = int(round(s2[0] * (1.0 - u) + s3[0] * u))
                g = int(round(s2[1] * (1.0 - u) + s3[1] * u))
                b = int(round(s2[2] * (1.0 - u) + s3[2] * u))

            wave = 0.5 + 0.5 * math.sin((xf * 2.4 - yf * 1.5 + line_idx * 0.85) * math.pi)
            combined_factor = max(0.0, min(1.0, 0.55 * vert_alpha_factor + 0.45 * wave))
            alpha_val = int(round(255 * (min_alpha + (max_alpha - min_alpha) * combined_factor)))
            px[x, y] = (r, g, b, alpha_val)

    resample = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR
    return grad_small.resize((w, h), resample)


def _apply_adaptive_readability_scrim(img_rgba, text_top_y, text_bottom_y, top_mode=False):
    """
    Measures background luminance in the title zone and applies a subtle, feather-edged
    obsidian vignette (`0% -> up to 46%` alpha) ONLY when bright reflections, headlights,
    or busy midtones would reduce title contrast.
    """
    w, h = img_rgba.size
    band_y0 = max(0, min(h - 1, text_top_y))
    band_y1 = max(band_y0 + 1, min(h, text_bottom_y))

    crop = img_rgba.crop((0, band_y0, w, band_y1)).convert("RGB")
    resample = Image.Resampling.BOX if hasattr(Image, "Resampling") else Image.BOX
    sample = crop.resize((64, 32), resample)
    lums = sorted(relative_luminance(sample.getpixel((x, y))) for y in range(32) for x in range(64))
    p80_lum = lums[int(len(lums) * 0.80)]

    # Always provide a light 18% anchor scrim, scaling up to 48% when bright highlights sit behind text
    peak_alpha = 0.18
    if p80_lum > 0.16:
        peak_alpha = min(0.48, 0.18 + (p80_lum - 0.16) * 0.70)

    scrim_small = Image.new("RGBA", (8, 128), (0, 0, 0, 0))
    spx = scrim_small.load()
    fade_margin = int(h * 0.10)

    if top_mode:
        fade_end = min(h, band_y1 + fade_margin)
        for sy in range(128):
            real_y = (sy / 127.0) * h
            if real_y >= fade_end:
                a = 0
            elif real_y <= band_y0:
                a = int(round(255 * peak_alpha))
            else:
                t = 1.0 - ((real_y - band_y0) / max(1.0, fade_end - band_y0))
                a = int(round(255 * peak_alpha * (t ** 1.4)))
            for sx in range(8):
                spx[sx, sy] = (4, 4, 10, a)
    else:
        fade_start = max(0, band_y0 - fade_margin)
        for sy in range(128):
            real_y = (sy / 127.0) * h
            if real_y <= fade_start:
                a = 0
            else:
                t = min(1.0, (real_y - fade_start) / max(1.0, h - fade_start))
                a = int(round(255 * peak_alpha * (t ** 1.35)))
            for sx in range(8):
                spx[sx, sy] = (4, 4, 10, a)

    bilin = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR
    scrim_full = scrim_small.resize((w, h), bilin)
    return Image.alpha_composite(img_rgba, scrim_full)


def overlay_title(
    image_path,
    title,
    color_hex=None,
    output_path=None,
    glow=True,
    shadow=True,
    top=False,
    bottom=True,
    auto_color=True,
    opacity=0.68,
    stacked=True,
    spacing=None,
    target_ratio=DEFAULT_TARGET_WIDTH_RATIO,
    album_anchor=None,
    is_album=False,
):
    """
    Renders title in stacked 1-word-per-line full-width typography (each word scaled to fill
    ~92% of screen width), filled with an album-cohesive neon gradient guaranteed to meet a
    strict WCAG relative-luminance contrast floor (`Y >= 0.45`).
    """
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    if color_hex and not auto_color:
        stops = ensure_luminous_hex_stops(color_hex, min_luminance=MIN_NEON_RELATIVE_LUMINANCE)
    else:
        stops = detect_least_used_gradient_colors(
            image_path,
            title=title,
            output_path=output_path,
            top=top,
            bottom=bottom,
            album_anchor=album_anchor,
            is_album=is_album,
        )

    font_path = get_best_font_path()
    target_w = int(w * target_ratio)
    stroke_w = max(3, int(w * 0.0040))
    shadow_offset_x = max(6, int(w * 0.0075))
    shadow_offset_y = max(7, int(w * 0.0090))

    styled_title = _stylize_if_ascii(title)

    if stacked:
        if "\n" in styled_title:
            lines = [ln.strip() for ln in styled_title.split("\n") if ln.strip()]
        else:
            lines = [wd.strip() for wd in styled_title.split() if wd.strip()]
    else:
        lines = [styled_title.strip()]

    if not lines:
        lines = [styled_title.strip() or "VØłĐƦłĐɆ"]

    max_total_text_h = int(h * 0.40)
    max_line_h = int(max_total_text_h / max(1, len(lines)))

    rendered_lines = []
    for word in lines:
        fill_mask, stroke_mask, line_h = _render_word_mask_fitted(
            word, font_path, target_w=target_w, max_line_h=max_line_h, stroke_w=stroke_w
        )
        rendered_lines.append((word, fill_mask, stroke_mask, line_h))

    avg_lh = sum(item[3] for item in rendered_lines) / len(rendered_lines)
    S = spacing if spacing is not None else max(10, int(avg_lh * 0.16))

    y_positions = [0] * len(rendered_lines)
    if top and not bottom:
        curr_top = S
        for i, (_, _, _, lh) in enumerate(rendered_lines):
            y_positions[i] = curr_top
            curr_top += lh + S
    else:
        curr_bottom = h - S
        for i in reversed(range(len(rendered_lines))):
            lh = rendered_lines[i][3]
            y_positions[i] = curr_bottom - lh
            curr_bottom = y_positions[i] - S

    # Apply subtle adaptive readability scrim behind the title zone before compositing text
    text_top_y = min(y_positions)
    text_bottom_y = max(y_positions[i] + rendered_lines[i][3] for i in range(len(rendered_lines)))
    img = _apply_adaptive_readability_scrim(img, text_top_y, text_bottom_y, top_mode=(top and not bottom))

    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    for idx, (word, fill_mask, stroke_mask, lh) in enumerate(rendered_lines):
        lw, lh_actual = fill_mask.size
        x_pos = (w - lw) // 2
        y_pos = y_positions[idx]

        grad_fill = _create_gradient_and_opacity_layer(lw, lh_actual, stops, base_opacity=opacity, line_idx=idx)
        var_alpha_map = grad_fill.split()[3]

        canvas_fill_mask = Image.new("L", (w, h), 0)
        canvas_fill_mask.paste(fill_mask, (x_pos, y_pos))

        if shadow:
            shadow_mod = var_alpha_map.point(lambda a: max(110, min(255, int(a * 1.15))))
            mod_stroke = ImageChops.multiply(stroke_mask, shadow_mod)

            soft_shadow_alpha = Image.new("L", (w, h), 0)
            soft_shadow_alpha.paste(
                mod_stroke.point(lambda p: int(p * 0.86)),
                (x_pos + int(shadow_offset_x * 1.45), y_pos + int(shadow_offset_y * 1.55)),
            )
            blur_r = max(4, int(w * 0.0055))
            soft_shadow_alpha = soft_shadow_alpha.filter(ImageFilter.GaussianBlur(radius=blur_r))
            soft_shadow_alpha = ImageChops.subtract(soft_shadow_alpha, canvas_fill_mask)
            soft_shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            soft_shadow_layer.paste((0, 0, 0, 255), (0, 0), soft_shadow_alpha)
            text_layer = Image.alpha_composite(text_layer, soft_shadow_layer)

            hard_shadow_alpha = Image.new("L", (w, h), 0)
            hard_shadow_alpha.paste(
                mod_stroke.point(lambda p: int(p * 0.94)),
                (x_pos + shadow_offset_x, y_pos + shadow_offset_y),
            )
            hard_shadow_alpha = ImageChops.subtract(hard_shadow_alpha, canvas_fill_mask)
            hard_shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            hard_shadow_layer.paste((0, 0, 0, 255), (0, 0), hard_shadow_alpha)
            text_layer = Image.alpha_composite(text_layer, hard_shadow_layer)

        if glow:
            glow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            glow_grad = _create_gradient_and_opacity_layer(lw, lh_actual, stops, base_opacity=0.42, line_idx=idx)
            outline_only = ImageChops.subtract(stroke_mask, fill_mask)
            glow_alpha = ImageChops.multiply(outline_only, glow_grad.split()[3])
            glow_grad.putalpha(glow_alpha)
            glow_layer.paste(glow_grad, (x_pos, y_pos), glow_grad)
            glow_blur = max(4, int(w * 0.005))
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=glow_blur))
            text_layer = Image.alpha_composite(text_layer, glow_layer)

        outline_ring = ImageChops.subtract(stroke_mask, fill_mask)
        outline_mod = ImageChops.multiply(outline_ring, var_alpha_map.point(lambda a: max(165, min(255, int(a * 1.2)))))
        outline_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        outline_layer.paste((5, 5, 10, 255), (x_pos, y_pos), outline_mod)
        text_layer = Image.alpha_composite(text_layer, outline_layer)

        combined_fill_alpha = ImageChops.multiply(fill_mask, var_alpha_map)
        grad_fill.putalpha(combined_fill_alpha)

        word_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        word_layer.paste(grad_fill, (x_pos, y_pos), grad_fill)
        text_layer = Image.alpha_composite(text_layer, word_layer)

    result = Image.alpha_composite(img, text_layer)

    if output_path is None:
        base, ext = os.path.splitext(image_path)
        output_path = f"{base}-titled{ext}"

    is_jpg = output_path.lower().endswith((".jpg", ".jpeg"))
    if is_jpg:
        result.convert("RGB").save(output_path, "JPEG", quality=95)
    else:
        if not output_path.lower().endswith(".png"):
            output_path = os.path.splitext(output_path)[0] + ".png"
        result.save(output_path, "PNG")
        # Always write a companion <8MB RGB JPEG alongside large >=2800px PNGs for Telegram/SoundCloud delivery
        if w >= 2800 and h >= 2800:
            jpg_companion = os.path.splitext(output_path)[0] + ".jpg"
            try:
                result.convert("RGB").save(jpg_companion, "JPEG", quality=95)
            except Exception:
                pass

    stops_hex = "/".join(_rgb_to_hex(s) for s in stops)
    print(
        f"Saved: {output_path} (Lines: {len(rendered_lines)}, Gradient: {stops_hex}, "
        f"BaseOpacity: {int(opacity*100)}%, Stroke: {stroke_w}px)"
    )

    try:
        if os.path.exists(ARTWORK_COVERS_DIR):
            archive_path = os.path.join(ARTWORK_COVERS_DIR, os.path.basename(output_path))
            if os.path.abspath(output_path) != os.path.abspath(archive_path):
                shutil.copy2(output_path, archive_path)
    except Exception:
        pass

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Overlay Unicode title onto cover art image")
    parser.add_argument("--image", required=True, help="Path to background image (PNG/WebP/JPEG)")
    parser.add_argument("--title", required=True, help="Unicode-styled track or album title to overlay")
    parser.add_argument("--color", default=None, help="Optional override color in hex or palette name")
    parser.add_argument("--auto-color", action="store_true", help="Automatically select album-cohesive neon gradient")
    parser.add_argument("--album-anchor", default=None, help="Optional path to album_cover_bg.png to lock palette cohesion")
    parser.add_argument("--opacity", type=float, default=0.68, help="Base font fill opacity between 0.0 and 1.0 (default: 0.68)")
    parser.add_argument("--output", default=None, help="Output file path (default: <input>-titled.png)")
    parser.add_argument("--no-glow", action="store_true", help="Skip neon glow effect")
    parser.add_argument("--no-shadow", action="store_true", help="Skip drop shadow effect")
    parser.add_argument("--top", action="store_true", help="Position title at top")
    parser.add_argument("--bottom", action="store_true", help="Position title at bottom")
    parser.add_argument("--stacked", action="store_true", help="Stack words one per line scaled to fill width (default for multi-word titles)")
    parser.add_argument("--single-line", action="store_true", help="Force single-line rendering")
    parser.add_argument("--album", action="store_true", help="Album title mode (establishes album neon family, anchored at bottom)")
    parser.add_argument("--spacing", type=int, default=None, help="Explicit vertical pixel spacing between lines and at bottom")

    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"Error: Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    is_stacked = not args.single_line

    overlay_title(
        image_path=args.image,
        title=args.title,
        color_hex=args.color,
        output_path=args.output,
        glow=not args.no_glow,
        shadow=not args.no_shadow,
        top=args.top,
        bottom=args.bottom or not args.top,
        auto_color=args.auto_color or (args.color is None),
        opacity=args.opacity,
        stacked=is_stacked,
        spacing=args.spacing,
        album_anchor=args.album_anchor,
        is_album=args.album,
    )


if __name__ == "__main__":
    main()
