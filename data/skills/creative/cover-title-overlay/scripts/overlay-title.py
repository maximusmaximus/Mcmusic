#!/usr/bin/env python3
"""
Overlay a Unicode-styled song title onto a cover art image.

Usage:
    python3 overlay-title.py --image <bg_image> --title "<TITLE>" --color <hex> [--output <path>] [--no-glow] [--no-shadow]

The title is centered vertically and scaled horizontally to fill ~90% of the image width.
Font: Open Sans Bold.

Examples:
    # Basic overlay with neon glow + drop shadow
    python3 overlay-title.py --image cover_bg.png --title "Ɇ₦†Ʀɏ₩ØɄ₦Đ" --color "#ff00ff"

    # Without glow/shadow (flat text only)
    python3 overlay-title.py --image cover_bg.png --title "₩ƦΔł†Ⱨ" --color "#00ff88" --no-glow --no-shadow

    # Custom output path
    python3 overlay-title.py --image cover_bg.png --title "฿ⱠΔϾҞ†ØƤ" --color "#ff3366" --output /tmp/final_cover.png
"""

import argparse
import os
import shutil
import sys
import math

from PIL import Image, ImageDraw, ImageFont

# Validated font paths with complete native Unicode glyph coverage (31/31 chars)
FONT_CANDIDATES = [
    "/opt/data/.fonts/SegoeUI-Bold.ttf",
    "/opt/data/.fonts/SegoeUI-Black.ttf",
    "/opt/data/.fonts/Calibri-Bold.ttf",
    "/opt/data/.fonts/Arial-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/seguibl.ttf",
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


def detect_harmonious_cmy_color(image_path):
    """Analyze background image lighting and return highest-contrast CMY neon color."""
    try:
        img = Image.open(image_path).convert("RGB")
        thumb = img.resize((64, 64))
        pixels = list(thumb.getdata())
        avg_r = sum(p[0] for p in pixels) / len(pixels)
        avg_g = sum(p[1] for p in pixels) / len(pixels)
        avg_b = sum(p[2] for p in pixels) / len(pixels)

        if avg_r > avg_g + 15 and avg_r > avg_b + 15:
            return CMY_NEON_PALETTE["electric_cyan"]
        elif avg_b > avg_r + 15:
            return CMY_NEON_PALETTE["acid_yellow"]
        elif avg_g > avg_r and avg_g > avg_b:
            return CMY_NEON_PALETTE["hyper_magenta"]
        else:
            return CMY_NEON_PALETTE["hyper_magenta"]
    except Exception:
        return CMY_NEON_PALETTE["hyper_magenta"]


def draw_neon_glow(draw, x, y, title, font, color, glow_layers=None):
    """Draw a smooth neon glow around the title."""
    if glow_layers is None:
        glow_layers = [(6, 25), (4, 55), (2, 95)]

    for radius, alpha in glow_layers:
        for dx in range(-radius, radius + 1, 2):
            for dy in range(-radius, radius + 1, 2):
                dist = math.sqrt(dx * dx + dy * dy)
                if dist <= radius:
                    draw.text((x + dx, y + dy), title, font=font, fill=(*color, alpha))


def draw_drop_shadow(draw, x, y, title, font, shadow_layers=None):
    """Draw an angled drop shadow."""
    if shadow_layers is None:
        shadow_layers = [(10, 10, 80), (8, 8, 150), (6, 6, 220)]

    for ldx, ldy, alpha in shadow_layers:
        draw.text((x + ldx, y + ldy), title, font=font, fill=(0, 0, 0, alpha))


def overlay_title(image_path, title, color_hex=None, output_path=None, glow=True, shadow=True, top=False, bottom=False, auto_color=False):
    """Main overlay function with multi-font fallback and expanded CMY palette."""

    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)

    # Resolve color
    if auto_color or not color_hex:
        color_hex = detect_harmonious_cmy_color(image_path)
    elif color_hex in CMY_NEON_PALETTE:
        color_hex = CMY_NEON_PALETTE[color_hex]

    color_hex = color_hex.lstrip("#")
    color = tuple(int(color_hex[i:i + 2], 16) for i in (0, 2, 4))

    # Font resolution
    font_path = get_best_font_path()
    font_size = find_font_size(draw, title, w, font_path)
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    # Measure text bounding box
    bbox = draw.textbbox((0, 0), title, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x_offset = bbox[0]
    text_y_offset = bbox[1]

    # Center horizontally; position vertically
    x = (w - text_w) // 2 - text_x_offset
    if top:
        y = int(h * 0.08) - text_y_offset
    elif bottom:
        y = int(h * 0.92) - text_h - text_y_offset
    else:
        y = (h - text_h) // 2 - text_y_offset

    # 1. Drop shadow (behind everything)
    if shadow:
        draw_drop_shadow(draw, x, y, title, font)

    # 2. Neon glow
    if glow:
        draw_neon_glow(draw, x, y, title, font, color)

    # 3. Main text (max saturation)
    draw.text((x, y), title, font=font, fill=(*color, 255))

    # 4. White-hot core highlight (slightly brighter, offset -1px)
    bright_core = tuple(min(255, c + 130) for c in color) + (130,)
    draw.text((x - 1, y - 1), title, font=font, fill=bright_core)

    # Composite
    result = Image.alpha_composite(img, text_layer)

    if output_path is None:
        base, ext = os.path.splitext(image_path)
        output_path = f"{base}-titled{ext}"

    if not output_path.lower().endswith(".png"):
        output_path = os.path.splitext(output_path)[0] + ".png"

    result.save(output_path, "PNG")
    print(f"Saved: {output_path} (Color: #{color_hex})")

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
    parser.add_argument("--title", required=True, help="Unicode-styled track title to overlay")
    parser.add_argument("--color", default=None, help="Neon color in hex (e.g. #00f0ff, #ff007f, #faff00) or palette name (e.g. electric_cyan, hyper_magenta, acid_yellow)")
    parser.add_argument("--auto-color", action="store_true", help="Automatically select highest-contrast CMY neon color based on background")
    parser.add_argument("--output", default=None, help="Output file path (default: <input>-titled.png)")
    parser.add_argument("--no-glow", action="store_true", help="Skip neon glow effect")
    parser.add_argument("--no-shadow", action="store_true", help="Skip drop shadow effect")
    parser.add_argument("--top", action="store_true", help="Position title at top (8%% from top)")
    parser.add_argument("--bottom", action="store_true", help="Position title at bottom (8%% from bottom)")

    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"Error: Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    overlay_title(
        image_path=args.image,
        title=args.title,
        color_hex=args.color,
        output_path=args.output,
        glow=not args.no_glow,
        shadow=not args.no_shadow,
        top=args.top,
        bottom=args.bottom,
        auto_color=args.auto_color,
    )


if __name__ == "__main__":
    main()