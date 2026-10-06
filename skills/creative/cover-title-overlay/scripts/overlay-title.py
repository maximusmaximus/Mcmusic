#!/usr/bin/env python3
"""
Overlay a Unicode-styled song or album title onto a cover art image with high-voltage
chromatic inverted typography, 60% font fill opacity, and crisp black framing.

Usage:
    python3 overlay-title.py --image <bg_image> --title "<TITLE>" [--color <hex>] [--auto-color] [--opacity 0.60] [--output <path>] [--no-glow] [--no-shadow] [--top] [--bottom] [--stacked] [--album] [--spacing <px>]

Single-line mode:
    The title is centered vertically (or placed at top/bottom) and scaled horizontally to fill ~90% of the image width.

Stacked album mode (--stacked or --album):
    The title is split into lines (by newline or space). Each line is scaled and justified to fill out the width (~90%).
    Anchored at the bottom of the canvas, where the bottom margin exactly equals the vertical spacing between the words.
"""

import argparse
import os
import shutil
import sys
import math
import colorsys
from PIL import Image, ImageDraw, ImageFont

# Validated font paths with complete native Unicode glyph coverage (31/31 chars)
FONT_CANDIDATES = [
    "/opt/data/.fonts/SegoeUI-Bold.ttf",
    "/opt/data/.fonts/SegoeUI-Black.ttf",
    "/opt/data/.fonts/Calibri-Bold.ttf",
    "/opt/data/.fonts/Arial-Bold.ttf",
    "C:/Windows/Fonts/seguibl.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "D:/hermes-music/data/.fonts/SegoeUI-Bold.ttf",
    "D:/hermes-music/data/.fonts/SegoeUI-Black.ttf",
    "D:/hermes-music/data/.fonts/Calibri-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

# High-voltage CMY Neon Palette Matrix
CMY_NEON_PALETTE = {
    # Cyans
    "electric_cyan": "#00F0FF",
    "neon_cyan": "#00FFFF",
    "deep_cyan": "#00E5FF",
    "cyan_mint": "#00FFA3",
    "ice_blue": "#38E5FF",

    # Magentas & Fuchsias
    "hyper_magenta": "#FF007F",
    "laser_magenta": "#FF00FF",
    "neon_fuchsia": "#FF10F0",
    "electric_violet": "#D000FF",
    "hot_pink": "#FF1493",
    "crimson_magenta": "#FF0055",

    # Yellows & Golds
    "acid_yellow": "#FAFF00",
    "electric_volt": "#FFE600",
    "neon_yellow": "#FFFF00",
    "cyber_gold": "#FFD700",
    "solar_amber": "#FFB700",

    # Accents
    "neon_lime": "#39FF14",
    "radioactive_green": "#00FF66",
    "blaze_orange": "#FF6600",
}

ARTWORK_COVERS_DIR = "/opt/data/music/artwork/covers"
DEFAULT_TARGET_WIDTH_RATIO = 0.90  # Title fills 90% of image width


def get_best_font_path():
    """Find the best existing font path with complete Unicode coverage."""
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return None


def find_font_size(draw, title, img_width, font_path, target_ratio=DEFAULT_TARGET_WIDTH_RATIO):
    """Binary search for largest font size where title fits within target_ratio * img_width."""
    target_width = int(img_width * target_ratio)
    lo, hi = 12, 500

    while lo < hi:
        mid = (lo + hi + 1) // 2
        font = ImageFont.truetype(font_path, mid) if font_path else ImageFont.load_default()
        bbox = draw.textbbox((0, 0), title, font=font)
        text_w = bbox[2] - bbox[0]
        if text_w <= target_width:
            lo = mid
        else:
            hi = mid - 1

    return lo


def detect_opposite_key_color(image_path, top=False, bottom=False):
    """
    Extracts the key color (dominant chromatic lighting/accent hue) of the artwork,
    with targeted spatial weighting on the zone where the title will sit,
    and returns its exact chromatic opposite (complementary color) at 100% saturation and vibrancy.
    """
    try:
        img = Image.open(image_path).convert("RGB")
        # Resize to 128x128 for fast, robust pixel sampling
        thumb = img.resize((128, 128), Image.Resampling.BOX if hasattr(Image, "Resampling") else Image.BOX)
        w, h = thumb.size

        weighted_cos = 0.0
        weighted_sin = 0.0
        total_weight = 0.0
        total_r, total_g, total_b = 0, 0, 0

        # Focus zone corresponding to text position
        if top:
            zone_min_y, zone_max_y = 0, int(h * 0.40)
        elif bottom:
            zone_min_y, zone_max_y = int(h * 0.60), h
        else:
            zone_min_y, zone_max_y = int(h * 0.25), int(h * 0.75)

        for y in range(h):
            in_zone = (zone_min_y <= y <= zone_max_y)
            zone_multiplier = 2.5 if in_zone else 1.0

            for x in range(w):
                r, g, b = thumb.getpixel((x, y))
                total_r += r
                total_g += g
                total_b += b
                rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
                h_val, s_val, v_val = colorsys.rgb_to_hsv(rf, gf, bf)

                # Focus on luminous, chromatic highlights and midtones
                if v_val > 0.10 and s_val > 0.15:
                    weight = (s_val ** 1.5) * (v_val ** 1.2) * zone_multiplier
                    angle = h_val * 2.0 * math.pi
                    weighted_cos += weight * math.cos(angle)
                    weighted_sin += weight * math.sin(angle)
                    total_weight += weight

        if total_weight > 0.05:
            mean_angle = math.atan2(weighted_sin, weighted_cos)
            if mean_angle < 0:
                mean_angle += 2.0 * math.pi
            key_hue = (mean_angle / (2.0 * math.pi)) * 360.0
            opposite_hue = (key_hue + 180.0) % 360.0
        else:
            # Fallback for near-monochrome / grayscale scenes
            avg_lum = (total_r * 0.299 + total_g * 0.587 + total_b * 0.114) / (max(1, w * h))
            if avg_lum < 128:
                chosen = "#00F0FF"
            else:
                chosen = "#000000"
            print(f"[color] Low chromatic saturation (lum={avg_lum:.1f}) -> fallback {chosen}")
            return chosen

        # Exact chromatic complement at 100% saturation and maximum brightness
        opp_rf, opp_gf, opp_bf = colorsys.hsv_to_rgb(opposite_hue / 360.0, 1.0, 1.0)
        chosen = f"#{int(round(opp_rf * 255)):02X}{int(round(opp_gf * 255)):02X}{int(round(opp_bf * 255)):02X}"

        print(f"[color] Analyzed image: Key Hue = {key_hue:.1f}°, Inverted Opp Hue = {opposite_hue:.1f}°, Title Color = {chosen}")
        return chosen
    except Exception as e:
        print(f"[color] Error detecting key color: {e}, falling back to blaze orange", file=sys.stderr)
        return "#FF6600"


detect_harmonious_cmy_color = detect_opposite_key_color


def layout_stacked_justified(draw, lines, w, h, font_path, target_ratio=DEFAULT_TARGET_WIDTH_RATIO, spacing=None, max_scale_ratio=1.75):
    """
    Computes text positions and metrics for stacked, justified typography.
    Each line fills target_w = int(w * target_ratio).
    Anchored at the bottom, where the bottom margin exactly equals the vertical spacing between lines (S_bottom == S_between).
    """
    target_w = int(w * target_ratio)
    margin_x = (w - target_w) // 2

    # Step 1: Measure natural font size for each line to fill target_w
    raw_font_sizes = []
    for line in lines:
        lo, hi = 20, 1200
        while lo < hi:
            mid = (lo + hi + 1) // 2
            f = ImageFont.truetype(font_path, mid) if font_path else ImageFont.load_default()
            bbox = draw.textbbox((0, 0), line, font=f)
            if (bbox[2] - bbox[0]) <= target_w:
                lo = mid
            else:
                hi = mid - 1
        raw_font_sizes.append(lo)

    base_font_size = min(raw_font_sizes)
    # Cap font size for shorter lines so one word doesn't overpower everything
    max_allowed_font_size = int(base_font_size * max_scale_ratio)

    lines_draw_calls = []
    line_heights = []
    line_y_offsets = []

    for idx, line in enumerate(lines):
        chosen_font_size = min(raw_font_sizes[idx], max_allowed_font_size)
        font = ImageFont.truetype(font_path, chosen_font_size) if font_path else ImageFont.load_default()

        # If line contains spaces, justify by word spacing
        words_in_line = [wd for wd in line.split(" ") if wd]
        if len(words_in_line) > 1:
            word_boxes = [draw.textbbox((0, 0), wd, font=font) for wd in words_in_line]
            word_w = [b[2] - b[0] for b in word_boxes]
            word_ox = [b[0] for b in word_boxes]
            tot_word_w = sum(word_w)
            n_gaps = len(words_in_line) - 1
            gap = (target_w - tot_word_w) / n_gaps if n_gaps > 0 else 0
            th = max(b[3] - b[1] for b in word_boxes)
            oy = min(b[1] for b in word_boxes)

            calls = []
            curr_x = margin_x
            for j, wd in enumerate(words_in_line):
                calls.append((curr_x - word_ox[j], wd, font))
                curr_x += word_w[j] + gap
            lines_draw_calls.append(calls)
            line_heights.append(th)
            line_y_offsets.append(oy)
        else:
            # Single word
            bbox = draw.textbbox((0, 0), line, font=font)
            th = bbox[3] - bbox[1]
            oy = bbox[1]
            ox = bbox[0]

            if chosen_font_size < raw_font_sizes[idx] and len(line) > 1:
                # Font size was capped; justify using tracking (letter-spacing)
                char_boxes = [draw.textbbox((0, 0), c, font=font) for c in line]
                char_w = [b[2] - b[0] for b in char_boxes]
                char_ox = [b[0] for b in char_boxes]
                tot_c_w = sum(char_w)
                n_gaps = len(line) - 1
                gap = (target_w - tot_c_w) / n_gaps if n_gaps > 0 else 0
                th = max(b[3] - b[1] for b in char_boxes)
                oy = min(b[1] for b in char_boxes)

                calls = []
                curr_x = margin_x
                for j, c in enumerate(line):
                    calls.append((curr_x - char_ox[j], c, font))
                    curr_x += char_w[j] + gap
                lines_draw_calls.append(calls)
                line_heights.append(th)
                line_y_offsets.append(oy)
            else:
                # Direct word rendering
                lines_draw_calls.append([(margin_x - ox, line, font)])
                line_heights.append(th)
                line_y_offsets.append(oy)

    # Compute vertical gap S
    avg_th = sum(line_heights) / len(line_heights)
    S = spacing if spacing is not None else int(avg_th * 0.22)

    # Position lines bottom-up:
    # Lowest line bottom is at h - S
    y_positions = [0] * len(lines)
    curr_bottom = h - S
    for i in reversed(range(len(lines))):
        th = line_heights[i]
        oy = line_y_offsets[i]
        y_positions[i] = curr_bottom - th - oy
        curr_bottom = y_positions[i] + oy - S

    # Combine into absolute render calls (x, y, text, font)
    final_render_calls = []
    for i, calls in enumerate(lines_draw_calls):
        line_y = y_positions[i]
        for rel_x, text_piece, font in calls:
            final_render_calls.append((rel_x, line_y, text_piece, font))

    return final_render_calls, S


def overlay_title(image_path, title, color_hex=None, output_path=None, glow=True, shadow=True, top=False, bottom=False, auto_color=False, opacity=0.60, stacked=False, spacing=None, target_ratio=DEFAULT_TARGET_WIDTH_RATIO):
    """
    Renders title in VØIDRIDE aesthetic with 60% font fill opacity and crisp black outline/stroke.
    Supports single-line placement or stacked, justified multi-line bottom placement.
    """
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)

    # In stacked mode, text is always anchored at bottom
    if stacked:
        bottom = True
        top = False

    # Resolve color
    if auto_color or not color_hex:
        color_hex = detect_opposite_key_color(image_path, top=top, bottom=bottom)
    elif color_hex in CMY_NEON_PALETTE:
        color_hex = CMY_NEON_PALETTE[color_hex]

    color_hex = color_hex.lstrip("#")
    color = tuple(int(color_hex[i:i + 2], 16) for i in (0, 2, 4))

    font_path = get_best_font_path()

    if stacked:
        if "\n" in title:
            lines = [ln.strip() for ln in title.split("\n") if ln.strip()]
        else:
            lines = [wd.strip() for wd in title.split() if wd.strip()]
        render_calls, S = layout_stacked_justified(draw, lines, w, h, font_path, target_ratio=target_ratio, spacing=spacing)
        print(f"[layout] Stacked justified {len(lines)} lines (S_between = S_bottom = {S}px)")
    else:
        # Single-line mode
        font_size = find_font_size(draw, title, w, font_path, target_ratio=target_ratio)
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

        bbox = draw.textbbox((0, 0), title, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        text_x_offset = bbox[0]
        text_y_offset = bbox[1]

        x = (w - text_w) // 2 - text_x_offset
        if top:
            y = int(h * 0.08) - text_y_offset
        elif bottom:
            y = int(h * 0.92) - text_h - text_y_offset
        else:
            y = (h - text_h) // 2 - text_y_offset

        render_calls = [(x, y, title, font)]

    # Dynamic line metrics based on canvas resolution
    stroke_w = max(3, int(w * 0.0035))
    shadow_offset = max(5, int(w * 0.0055))
    fill_alpha = int(255 * max(0.05, min(1.0, opacity)))

    # 1. Subtle ambient neon halo behind the stroke
    if glow:
        glow_radius = max(6, int(w * 0.005))
        for r, a in [(glow_radius * 2, int(25 * opacity)), (glow_radius, int(60 * opacity))]:
            step = max(2, r // 3)
            for dx in range(-r, r + 1, step):
                for dy in range(-r, r + 1, step):
                    if dx * dx + dy * dy <= r * r:
                        for rx, ry, piece, f in render_calls:
                            draw.text((rx + dx, ry + dy), piece, font=f, fill=(*color, a))

    # 2. Deep solid drop shadow
    if shadow:
        shadow_stroke = stroke_w + max(2, int(w * 0.001))
        for rx, ry, piece, f in render_calls:
            draw.text((rx + shadow_offset, ry + shadow_offset), piece, font=f,
                      fill=(0, 0, 0, int(220 * opacity)), stroke_width=shadow_stroke, stroke_fill=(0, 0, 0, int(220 * opacity)))

    # 3. Text with 60% opacity fill and crisp black outline
    for rx, ry, piece, f in render_calls:
        draw.text((rx, ry), piece, font=f, fill=(*color, fill_alpha),
                  stroke_width=stroke_w, stroke_fill=(0, 0, 0, 230))

    # Composite onto background
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

    print(f"Saved: {output_path} (Color: #{color_hex}, Opacity: {int(opacity*100)}%, Stroke: {stroke_w}px)")

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
    parser.add_argument("--color", default=None, help="Neon color in hex (e.g. #00f0ff, #ff007f, #faff00) or palette name")
    parser.add_argument("--auto-color", action="store_true", help="Automatically select highest-contrast inverted color based on background")
    parser.add_argument("--opacity", type=float, default=0.60, help="Font fill opacity between 0.0 and 1.0 (default: 0.60)")
    parser.add_argument("--output", default=None, help="Output file path (default: <input>-titled.png)")
    parser.add_argument("--no-glow", action="store_true", help="Skip neon glow effect")
    parser.add_argument("--no-shadow", action="store_true", help="Skip drop shadow effect")
    parser.add_argument("--top", action="store_true", help="Position title at top (8%% from top)")
    parser.add_argument("--bottom", action="store_true", help="Position title at bottom (8%% from bottom)")
    parser.add_argument("--stacked", action="store_true", help="Stack words/lines vertically with each line scaled and justified to fill width, anchored at bottom with equal bottom margin and line spacing")
    parser.add_argument("--album", action="store_true", help="Album title mode (stacked, justified, anchored at bottom)")
    parser.add_argument("--spacing", type=int, default=None, help="Explicit vertical pixel spacing between lines and at bottom")

    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"Error: Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    is_stacked = args.stacked or args.album

    overlay_title(
        image_path=args.image,
        title=args.title,
        color_hex=args.color,
        output_path=args.output,
        glow=not args.no_glow,
        shadow=not args.no_shadow,
        top=args.top,
        bottom=args.bottom or is_stacked,
        auto_color=args.auto_color,
        opacity=args.opacity,
        stacked=is_stacked,
        spacing=args.spacing,
    )


if __name__ == "__main__":
    main()