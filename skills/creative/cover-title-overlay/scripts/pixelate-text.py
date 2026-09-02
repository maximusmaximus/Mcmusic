#!/usr/bin/env python3
"""
Pixelate text on cover art with art-matched colored mosaic blocks.
Detects the text region (bright/colored text on dark backgrounds) and replaces
it with a chunky pixel grid whose colors are sampled FROM the artwork itself.
Designed for VØIDRIDE-style covers where text is overlaid at the bottom via overlay-title.py.

Style: extra-chunky 32px blocks, colors extracted from the artwork palette
(no rainbow gradient), with dark depth blocks, bright glitch pops, and
2px dark grid lines for a chunky retro-censorship look.

Usage:
    /opt/hermes/.venv/bin/python3 pixelate-text.py \
        --input /path/to/cover.png \
        --output /path/to/output.png \
        [--pixel-size 32] \
        [--padding 40] \
        [--window-height 350] \
        [--palette-colors 10] \
        [--seed 42]

The script auto-detects the text band using a sliding-window brightness/saturation
scoring algorithm. For 3000x3000 covers with --bottom title placement, this finds
the neon text + glow region reliably.
"""

import argparse
import os
import random
import sys

sys.path.insert(0, '/opt/hermes/.venv/lib/python3.13/site-packages')
from PIL import Image, ImageDraw


def find_text_region(img, padding=40, window_height=350):
    """
    Detect text band at the bottom of a dark cover with neon text.
    Uses sliding-window scoring on bright + saturated pixels.
    Returns (x, y, w, h) region to pixelate.
    """
    w, h = img.size
    rgb = img.load()
    gray = img.convert('L').load()

    # Background brightness from top-center
    bg_samples = []
    for x in range(w // 4, w * 3 // 4, 30):
        for y in range(h // 5, h // 4, 30):
            bg_samples.append(gray[x, y])
    bg_median = sorted(bg_samples)[len(bg_samples) // 2]

    # Score each row in bottom 30%
    search_start = int(h * 0.70)
    row_scores = []
    for y in range(search_start, h):
        bright = 0
        colored = 0
        for x in range(0, w, 2):
            r, g, b = rgb[x, y][:3]
            lum = (r + g + b) / 3
            max_c = max(r, g, b)
            min_c = min(r, g, b)
            sat = max_c - min_c
            if lum > bg_median + 50:
                bright += 1
            if sat > 80 and max_c > 140:
                colored += 1
        score = colored * 3 + bright
        row_scores.append((y, score))

    # Sliding window: find densest region
    best_start = search_start
    best_total = 0
    for i in range(len(row_scores)):
        window_total = sum(s for y, s in row_scores[i:i + window_height]) if i + window_height <= len(row_scores) else 0
        if window_total > best_total:
            best_total = window_total
            best_start = row_scores[i][0]

    text_top = max(0, best_start - padding)
    text_bottom = min(h, best_start + window_height + padding)

    return (0, text_top, w, text_bottom - text_top)


def extract_palette(img, n_colors=10):
    """
    Extract dominant colors from the artwork for pixelation.
    Samples the entire image, weights saturated/colored pixels higher,
    then clusters and deduplicates to produce a diverse palette.
    """
    w, h = img.size
    rgb = img.load()

    # Sample pixels across the entire image
    samples = []
    step = max(1, min(w, h) // 80)
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b = rgb[x, y][:3]
            lum = (r + g + b) / 3
            max_c = max(r, g, b)
            min_c = min(r, g, b)
            sat = max_c - min_c
            # Weight: prioritize visible, colored pixels
            weight = 1.0 + (sat / 255.0) * 3.0 + (lum / 255.0)
            samples.append(((r, g, b), weight))

    if not samples:
        return [(128, 0, 255), (0, 255, 255), (255, 0, 128)]

    # Bucketize to reduce color space
    buckets = {}
    for (r, g, b), weight in samples:
        qr = (r // 48) * 48
        qg = (g // 48) * 48
        qb = (b // 48) * 48
        key = (qr, qg, qb)
        if key not in buckets:
            buckets[key] = [0.0, 0.0, 0.0, 0.0]
        buckets[key][0] += r * weight
        buckets[key][1] += g * weight
        buckets[key][2] += b * weight
        buckets[key][3] += weight

    # Sort by weighted count, take top candidates
    sorted_buckets = sorted(buckets.items(), key=lambda x: x[1][3], reverse=True)

    palette = []
    for key, (rs, gs, bs, ws) in sorted_buckets[:n_colors * 3]:
        if ws > 0:
            avg_r = int(rs / ws)
            avg_g = int(gs / ws)
            avg_b = int(bs / ws)
            # Slight saturation boost for depth
            max_c = max(avg_r, avg_g, avg_b)
            min_c = min(avg_r, avg_g, avg_b)
            sat = max_c - min_c
            if sat < 50 and max_c > 80:
                avg_r = min(255, int(avg_r * 1.1))
                avg_g = min(255, int(avg_g * 1.05))
                avg_b = min(255, int(avg_b * 1.15))
            palette.append((avg_r, avg_g, avg_b))

    # Deduplicate: remove colors within 60 units of each other
    final = []
    for color in palette:
        too_similar = False
        for existing in final:
            dist = sum(abs(a - b) for a, b in zip(color, existing))
            if dist < 60:
                too_similar = True
                break
        if not too_similar:
            final.append(color)
        if len(final) >= n_colors:
            break

    # Ensure minimum coverage
    while len(final) < 6:
        final.append(final[0] if final else (128, 0, 255))

    return final


def make_dark_variant(color, factor=0.15):
    """Dark version of a color for depth blocks."""
    return (max(0, int(color[0] * factor)),
            max(0, int(color[1] * factor)),
            max(0, int(color[2] * factor)))


def make_bright_variant(color, factor=1.3):
    """Brighter version of a color for glitch blocks."""
    return (min(255, int(color[0] * factor + 30)),
            min(255, int(color[1] * factor + 30)),
            min(255, int(color[2] * factor + 30)))


def pixelate_region(img, region, pixel_size=32, palette_colors=10, seed=42):
    """
    Cover the region with an art-matched chunky pixel mosaic.
    Colors are extracted from the artwork itself — no rainbow gradient.
    """
    x, y, w, h_region = region
    img = img.copy()
    draw = ImageDraw.Draw(img)

    # Extract palette from the artwork
    palette = extract_palette(img, n_colors=palette_colors)
    print(f"Extracted {len(palette)}-color palette from artwork:")
    for i, c in enumerate(palette):
        print(f"  {i+1}. rgb{c} = #{c[0]:02x}{c[1]:02x}{c[2]:02x}")

    # Build block palettes
    bright_palette = [make_bright_variant(c) for c in palette]
    dark_palette = [make_dark_variant(c) for c in palette]

    rows = h_region // pixel_size + 1
    cols = w // pixel_size + 1
    random.seed(seed)

    for row in range(rows):
        for col in range(cols):
            roll = random.random()
            if roll < 0.12:
                # 12% dark depth blocks for rhythm
                base = random.choice(dark_palette)
                brightness = 0.5 + random.random() * 0.5
            elif roll < 0.17:
                # 5% bright glitch blocks
                base = random.choice(bright_palette)
                brightness = 1.0 + random.random() * 0.4
            else:
                # 83% normal palette blocks (from art)
                base = random.choice(palette)
                brightness = 0.75 + random.random() * 0.35

            final_r = min(255, max(0, int(base[0] * brightness)))
            final_g = min(255, max(0, int(base[1] * brightness)))
            final_b = min(255, max(0, int(base[2] * brightness)))

            block_x = x + col * pixel_size
            block_y = y + row * pixel_size

            # Fill block
            draw.rectangle(
                [block_x, block_y, block_x + pixel_size - 1, block_y + pixel_size - 1],
                fill=(final_r, final_g, final_b)
            )

            # 2px dark grid lines on top and left for chunky grid feel
            dark = (max(0, final_r // 7), max(0, final_g // 7), max(0, final_b // 7))
            draw.rectangle([block_x, block_y, block_x + pixel_size - 1, block_y + 1], fill=dark)
            draw.rectangle([block_x, block_y, block_x + 1, block_y + pixel_size - 1], fill=dark)

    return img


def main():
    parser = argparse.ArgumentParser(
        description='Pixelate text on cover art with art-matched colored mosaic blocks. '
                    'Colors are extracted from the artwork itself — no rainbow.')
    parser.add_argument('--input', required=True, help='Input cover image path')
    parser.add_argument('--output', required=True, help='Output image path')
    parser.add_argument('--pixel-size', type=int, default=32,
                        help='Pixel block size (default: 32). Larger = chunkier.')
    parser.add_argument('--padding', type=int, default=40,
                        help='Padding around detected text region (default: 40)')
    parser.add_argument('--window-height', type=int, default=350,
                        help='Detection window height in pixels (default: 350)')
    parser.add_argument('--palette-colors', type=int, default=10,
                        help='Number of colors to extract from artwork (default: 10)')
    parser.add_argument('--seed', type=int, default=42,
                        help='Random seed for reproducibility (default: 42)')
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    img = Image.open(args.input).convert('RGB')
    print(f"Image size: {img.size}")

    print("Detecting text region...")
    region = find_text_region(img, padding=args.padding, window_height=args.window_height)
    print(f"Text region: x={region[0]}, y={region[1]}, w={region[2]}, h={region[3]}")

    print(f"Applying art-matched pixelation (pixel_size={args.pixel_size})...")
    result = pixelate_region(img, region, pixel_size=args.pixel_size,
                             palette_colors=args.palette_colors, seed=args.seed)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    result.save(args.output, 'PNG', optimize=True)
    print(f"Saved: {args.output} ({os.path.getsize(args.output)} bytes)")


if __name__ == '__main__':
    main()