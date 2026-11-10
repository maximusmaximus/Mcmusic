#!/usr/bin/env python3
"""
Overlay a Unicode-styled song or album title onto a cover art image with:
  1. Stacked 1-word-per-line layout where EACH word is independently scaled up to fill
     the full width of the screen (~92% canvas width).
  2. Multi-stop color gradients derived from the LEAST-USED colors in the image,
     with cross-cover deduplication so every cover in an album gets a unique gradient palette.
  3. Variable opacity across parts of the letterforms (high-opacity crest/rim transitioning
     into a translucent core so background detail shows through) plus layered drop shadows.

Usage:
    python3 overlay-title.py --image <bg_image> --title "<TITLE>" [--color <hex>] [--auto-color]
                             [--opacity 0.68] [--output <path>] [--no-glow] [--no-shadow]
                             [--top] [--bottom] [--stacked] [--single-line] [--album] [--spacing <px>]
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
    "ice_blue": "#38E5FF",
    "hyper_magenta": "#FF007F",
    "laser_magenta": "#FF00FF",
    "neon_fuchsia": "#FF10F0",
    "electric_violet": "#D000FF",
    "hot_pink": "#FF1493",
    "crimson_magenta": "#FF0055",
    "acid_yellow": "#FAFF00",
    "electric_volt": "#FFE600",
    "neon_yellow": "#FFFF00",
    "cyber_gold": "#FFD700",
    "solar_amber": "#FFB700",
    "neon_lime": "#39FF14",
    "radioactive_green": "#00FF66",
    "blaze_orange": "#FF6600",
}

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


def detect_least_used_gradient_colors(image_path, title="", output_path=None, top=False, bottom=True):
    """
    Analyzes the cover image's 360-degree hue distribution (36 bins of 10 degrees each),
    identifies the LEAST-USED color hues in the image, and selects a 3-stop gradient
    palette from those least-used colors.

    Also coordinates via a per-folder `.cover_palettes.json` registry so that every cover
    in the same album (album cover + each song cover) is guaranteed a unique color signature.
    """
    num_bins = 36  # 10 degrees per bin
    bin_weights = [0.0] * num_bins

    try:
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
            zone_mult = 2.0 if (zone_min_y <= y <= zone_max_y) else 1.0
            for x in range(w):
                r, g, b = thumb.getpixel((x, y))
                rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
                h_val, s_val, v_val = colorsys.rgb_to_hsv(rf, gf, bf)

                # Count chromatic weight; even low-saturation tints contribute slightly
                if v_val > 0.06 and s_val > 0.08:
                    weight = (s_val ** 1.2) * (v_val ** 1.1) * zone_mult
                    bin_idx = int((h_val * 360.0) // 10.0) % num_bins
                    bin_weights[bin_idx] += weight

        # Circular Gaussian smoothing across neighboring bins so broad color cast is captured
        smoothed = [0.0] * num_bins
        kernel = [(0, 0.40), (-1, 0.22), (1, 0.22), (-2, 0.08), (2, 0.08)]
        for i in range(num_bins):
            acc = 0.0
            for offset, kw in kernel:
                acc += bin_weights[(i + offset) % num_bins] * kw
            smoothed[i] = acc

        # Rank all 36 hue bins from LEAST used (lowest weight) to most used
        # Add a tiny deterministic tie-breaker based on title + extension-free stem so ties break uniquely per song
        stem_key = os.path.splitext(os.path.basename(output_path or image_path))[0].lower()
        seed_bytes = hashlib.sha256(f"{title}:{stem_key}".encode("utf-8")).digest()
        ranked_bins = sorted(
            range(num_bins),
            key=lambda b_idx: (
                round(smoothed[b_idx], 4),
                ((b_idx * 7 + seed_bytes[b_idx % len(seed_bytes)]) % num_bins) * 1e-6,
            ),
        )

        # Pool of least-used hues in this image (bottom 26 bins = excluding the top 10 dominant hue bins)
        least_used_hues = [(b_idx * 10.0 + 5.0) % 360.0 for b_idx in ranked_bins[:26]]
        hue_rank_map = {b_idx: rank for rank, b_idx in enumerate(ranked_bins)}

        # Check per-album palette registry so every cover in an album gets a distinct primary hue
        target_dir = os.path.dirname(os.path.abspath(output_path or image_path))
        registry_path = os.path.join(target_dir, ".cover_palettes.json")
        cover_key = os.path.splitext(os.path.basename(output_path or image_path))[0].lower()
        if cover_key.endswith("_cover"):
            cover_key = cover_key[:-6]

        registry = {}
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as rf:
                    registry = json.load(rf)
            except Exception:
                registry = {}

        other_used_hues = [
            float(v["primary_hue"])
            for k, v in registry.items()
            if k != cover_key and isinstance(v, dict) and "primary_hue" in v
        ]

        # Select Primary Hue from the least-used hues of this image,
        # enforcing strong angular separation (>= 48 deg) from every other cover in the same album
        hue_center = least_used_hues[0]
        if other_used_hues:
            picked = None
            for min_sep in (50.0, 44.0, 38.0, 30.0):
                for rank_idx, cand_hue in enumerate(least_used_hues):
                    min_dist_to_others = min(_hue_dist(cand_hue, oh) for oh in other_used_hues)
                    if min_dist_to_others >= min_sep:
                        picked = cand_hue
                        break
                if picked is not None:
                    break
            if picked is None:
                # Fallback: maximize angular distance from existing covers while preferring low usage rank
                picked = max(
                    least_used_hues,
                    key=lambda ch: min(_hue_dist(ch, oh) for oh in other_used_hues) * 3.0 - least_used_hues.index(ch) * 2.0,
                )
            hue_center = picked

        # Build a vivid, high-chroma 3-stop gradient arc around hue_center (spanning ~65-80 degrees)
        # oriented toward the neighboring direction that is ALSO least-used in the image.
        # Keeping the 3 stops within a 75-degree arc prevents muddy RGB midpoints and keeps each cover's
        # color signature 100% distinct from the other covers in the album.
        cw_bin = int(((hue_center + 35.0) % 360.0) // 10.0) % num_bins
        ccw_bin = int(((hue_center - 35.0) % 360.0) // 10.0) % num_bins
        direction = 1.0 if smoothed[cw_bin] <= smoothed[ccw_bin] else -1.0

        hue_1 = (hue_center - direction * 28.0) % 360.0
        hue_2 = hue_center % 360.0
        hue_3 = (hue_center + direction * 42.0) % 360.0

        # Vary saturation & brightness slightly across stops for luminous neon depth
        stop_1 = _hsv_to_rgb_tuple(hue_1, 0.96, 1.00)
        stop_2 = _hsv_to_rgb_tuple(hue_2, 0.90, 1.00)
        stop_3 = _hsv_to_rgb_tuple(hue_3, 0.82, 1.00)

        # Persist to per-album registry
        try:
            registry[cover_key] = {
                "title": title,
                "primary_hue": round(hue_center, 1),
                "hues": [round(hue_1, 1), round(hue_2, 1), round(hue_3, 1)],
                "stops_hex": [_rgb_to_hex(stop_1), _rgb_to_hex(stop_2), _rgb_to_hex(stop_3)],
            }
            with open(registry_path, "w", encoding="utf-8") as wf:
                json.dump(registry, wf, indent=2)
        except Exception:
            pass

        print(
            f"[gradient] Least-used hues for '{cover_key}': "
            f"{hue_1:.0f}° ({_rgb_to_hex(stop_1)}) -> "
            f"{hue_2:.0f}° ({_rgb_to_hex(stop_2)}) -> "
            f"{hue_3:.0f}° ({_rgb_to_hex(stop_3)})"
        )
        return [stop_1, stop_2, stop_3]
    except Exception as e:
        print(f"[gradient] Fallback gradient due to error ({e})", file=sys.stderr)
        return [(0, 240, 255), (255, 0, 127), (250, 255, 0)]


def detect_opposite_key_color(image_path, top=False, bottom=False):
    """Backwards-compatible helper returning the primary least-used hex color."""
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

    # Draw fill (interior glyph)
    draw_fill.text((draw_x, draw_y), word, font=font, fill=255)
    # Draw stroke + fill, then subtract fill to get pure outline ring if needed
    draw_stroke.text((draw_x, draw_y), word, font=font, fill=255, stroke_width=stroke_w, stroke_fill=255)

    # Crop tightly to the glyph fill bounds horizontally, keeping stroke padding
    fill_bbox = fill_img.getbbox() or (pad, pad, canvas_w - pad, canvas_h - pad)
    crop_left = max(0, fill_bbox[0] - stroke_w)
    crop_top = max(0, fill_bbox[1] - stroke_w)
    crop_right = min(canvas_w, fill_bbox[2] + stroke_w)
    crop_bottom = min(canvas_h, fill_bbox[3] + stroke_w)

    fill_cropped = fill_img.crop((crop_left, crop_top, crop_right, crop_bottom))
    stroke_cropped = stroke_img.crop((crop_left, crop_top, crop_right, crop_bottom))

    # Scale horizontally to exact target_w (plus 2*stroke_w), and cap height at max_line_h
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
      - RGB channels: smooth 3-stop diagonal gradient built from the image's least-used colors.
        Alternates gradient sweep angle slightly per line so each stacked word has dynamic interplay.
      - Alpha channel: variable opacity mask across parts of the text!
        Upper/outer crests and diagonal bands hit higher opacity (~88-94% of max),
        while lower/interior zones dip to translucent (~42-55%) so background detail shows through.
    """
    s1, s2, s3 = stops[0], stops[1], stops[2]
    if line_idx % 2 == 1:
        # Subtle shift on second word so top word and bottom word have dynamic gradient interplay
        s1, s2, s3 = stops[2], stops[1], stops[0]

    # Render at compact resolution then bilinear-upscale for speed on 3000x3000 canvases
    gw = min(w, 320)
    gh = min(h, 160)
    grad_small = Image.new("RGBA", (gw, gh))
    px = grad_small.load()

    max_alpha = max(0.35, min(0.96, base_opacity + 0.24))
    min_alpha = max(0.24, min(0.65, base_opacity - 0.34))

    for y in range(gh):
        yf = y / max(1, gh - 1)
        # Vertical opacity curve: high-opacity crest at top, translucent window in lower-middle,
        # anchored baseline edge at bottom
        vert_alpha_factor = 0.52 + 0.48 * math.cos(yf * math.pi * 1.30)

        for x in range(gw):
            xf = x / max(1, gw - 1)
            # Diagonal gradient parameter t in [0, 1]
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

            # Spatial wave modulation so distinct parts of the text alternate between bold/solid and translucent glass
            wave = 0.5 + 0.5 * math.sin((xf * 2.4 - yf * 1.5 + line_idx * 0.85) * math.pi)
            combined_factor = max(0.0, min(1.0, 0.55 * vert_alpha_factor + 0.45 * wave))
            alpha_val = int(round(255 * (min_alpha + (max_alpha - min_alpha) * combined_factor)))
            px[x, y] = (r, g, b, alpha_val)

    resample = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR
    return grad_small.resize((w, h), resample)


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
):
    """
    Renders title in stacked 1-word-per-line full-width typography (each word scaled to fill
    ~92% of screen width), filled with a multi-stop gradient derived from the image's least-used
    colors, with variable opacity across parts of the text and knocked-out dual-layer drop shadows.
    """
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    # Determine gradient stops
    if color_hex and not auto_color:
        if color_hex in CMY_NEON_PALETTE:
            color_hex = CMY_NEON_PALETTE[color_hex]
        c_hex = color_hex.lstrip("#")
        c1 = tuple(int(c_hex[i:i + 2], 16) for i in (0, 2, 4))
        h1, s1, v1 = colorsys.rgb_to_hsv(c1[0] / 255.0, c1[1] / 255.0, c1[2] / 255.0)
        c2 = _hsv_to_rgb_tuple((h1 * 360.0 + 30.0) % 360.0, max(0.88, s1), 1.0)
        c3 = _hsv_to_rgb_tuple((h1 * 360.0 + 60.0) % 360.0, max(0.82, s1), 1.0)
        stops = [c1, c2, c3]
    else:
        stops = detect_least_used_gradient_colors(
            image_path, title=title, output_path=output_path, top=top, bottom=bottom
        )

    font_path = get_best_font_path()
    target_w = int(w * target_ratio)
    stroke_w = max(3, int(w * 0.0038))
    shadow_offset_x = max(6, int(w * 0.0075))
    shadow_offset_y = max(7, int(w * 0.0090))

    # Automatically apply VØIDRIDE Unicode glyph styling if plain ASCII was passed
    styled_title = _stylize_if_ascii(title)

    # Split into lines: default is 1 word per line whenever stacked is True
    if stacked:
        if "\n" in styled_title:
            lines = [ln.strip() for ln in styled_title.split("\n") if ln.strip()]
        else:
            lines = [wd.strip() for wd in styled_title.split() if wd.strip()]
    else:
        lines = [styled_title.strip()]

    if not lines:
        lines = [styled_title.strip() or "VØłĐƦłĐɆ"]

    # Budget vertical height per word so 2-word (or 3-word) titles sit cleanly in the lower ~40% of the cover
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

    # Compute y positions (anchored at bottom by default, or top if requested)
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

    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    for idx, (word, fill_mask, stroke_mask, lh) in enumerate(rendered_lines):
        lw, lh_actual = fill_mask.size
        x_pos = (w - lw) // 2
        y_pos = y_positions[idx]

        # Build the gradient + variable opacity layer for this word first so we can modulate shadow & fill together
        grad_fill = _create_gradient_and_opacity_layer(lw, lh_actual, stops, base_opacity=opacity, line_idx=idx)
        var_alpha_map = grad_fill.split()[3]

        # Full-canvas glyph interior mask (used to knock out drop shadows from inside translucent letterforms!)
        canvas_fill_mask = Image.new("L", (w, h), 0)
        canvas_fill_mask.paste(fill_mask, (x_pos, y_pos))

        # 1. Layered drop shadows (soft ambient Gaussian shadow + crisp directional offset shadow),
        # spatially modulated across parts of the text AND knocked out inside the letter interior
        # so the background artwork shines cleanly through the translucent parts of the letters!
        if shadow:
            # Modulate shadow weight so parts of the text have heavy drop shadow and parts have lighter shadow
            shadow_mod = var_alpha_map.point(lambda a: max(70, min(255, int(a * 1.15))))
            mod_stroke = ImageChops.multiply(stroke_mask, shadow_mod)

            # Soft blurred ambient drop shadow
            soft_shadow_alpha = Image.new("L", (w, h), 0)
            soft_shadow_alpha.paste(
                mod_stroke.point(lambda p: int(p * 0.82)),
                (x_pos + int(shadow_offset_x * 1.45), y_pos + int(shadow_offset_y * 1.55)),
            )
            blur_r = max(4, int(w * 0.0055))
            soft_shadow_alpha = soft_shadow_alpha.filter(ImageFilter.GaussianBlur(radius=blur_r))
            # Knock out glyph interior so translucent text isn't darkened from behind
            soft_shadow_alpha = ImageChops.subtract(soft_shadow_alpha, canvas_fill_mask)
            soft_shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            soft_shadow_layer.paste((0, 0, 0, 255), (0, 0), soft_shadow_alpha)
            text_layer = Image.alpha_composite(text_layer, soft_shadow_layer)

            # Crisp directional offset drop shadow
            hard_shadow_alpha = Image.new("L", (w, h), 0)
            hard_shadow_alpha.paste(
                mod_stroke.point(lambda p: int(p * 0.92)),
                (x_pos + shadow_offset_x, y_pos + shadow_offset_y),
            )
            hard_shadow_alpha = ImageChops.subtract(hard_shadow_alpha, canvas_fill_mask)
            hard_shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            hard_shadow_layer.paste((0, 0, 0, 255), (0, 0), hard_shadow_alpha)
            text_layer = Image.alpha_composite(text_layer, hard_shadow_layer)

        # 2. Subtle chromatic neon glow halo outside the glyph edges
        if glow:
            glow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            glow_grad = _create_gradient_and_opacity_layer(lw, lh_actual, stops, base_opacity=0.38, line_idx=idx)
            outline_only = ImageChops.subtract(stroke_mask, fill_mask)
            glow_alpha = ImageChops.multiply(outline_only, glow_grad.split()[3])
            glow_grad.putalpha(glow_alpha)
            glow_layer.paste(glow_grad, (x_pos, y_pos), glow_grad)
            glow_blur = max(4, int(w * 0.005))
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=glow_blur))
            text_layer = Image.alpha_composite(text_layer, glow_layer)

        # 3. Crisp dark outline frame (ring = stroke_mask - fill_mask) modulated with text opacity
        outline_ring = ImageChops.subtract(stroke_mask, fill_mask)
        outline_mod = ImageChops.multiply(outline_ring, var_alpha_map.point(lambda a: max(130, min(255, int(a * 1.2)))))
        outline_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        outline_layer.paste((5, 5, 10, 255), (x_pos, y_pos), outline_mod)
        text_layer = Image.alpha_composite(text_layer, outline_layer)

        # 4. Multi-stop least-used color gradient fill with variable opacity across parts of the text
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
    parser.add_argument("--auto-color", action="store_true", help="Automatically select least-used color gradient from image")
    parser.add_argument("--opacity", type=float, default=0.68, help="Base font fill opacity between 0.0 and 1.0 (default: 0.68)")
    parser.add_argument("--output", default=None, help="Output file path (default: <input>-titled.png)")
    parser.add_argument("--no-glow", action="store_true", help="Skip neon glow effect")
    parser.add_argument("--no-shadow", action="store_true", help="Skip drop shadow effect")
    parser.add_argument("--top", action="store_true", help="Position title at top")
    parser.add_argument("--bottom", action="store_true", help="Position title at bottom")
    parser.add_argument("--stacked", action="store_true", help="Stack words one per line scaled to fill width (default for multi-word titles)")
    parser.add_argument("--single-line", action="store_true", help="Force single-line rendering")
    parser.add_argument("--album", action="store_true", help="Album title mode (stacked, justified, anchored at bottom)")
    parser.add_argument("--spacing", type=int, default=None, help="Explicit vertical pixel spacing between lines and at bottom")

    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"Error: Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    # Default to stacked (1 word per line, each word scaled to fill width) unless --single-line is explicitly set
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
    )


if __name__ == "__main__":
    main()