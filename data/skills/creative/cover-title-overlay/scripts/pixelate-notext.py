#!/usr/bin/env python3
"""
Pixelate text regions on cover art with chunky neon-style blocks
colored from the artwork's own palette.

Usage:
    python3 pixelate-notext.py INPUT_PATH OUTPUT_PATH [--pixel-size 32] [--padding 40]

Batch (process all PNGs in a directory):
    python3 pixelate-notext.py --batch INPUT_DIR OUTPUT_DIR [--pixel-size 32]

The script auto-detects text regions via sliding-window brightness analysis,
extracts dominant colors from the artwork, and fills the text area with
art-matched 32px pixel blocks with dark grid lines, depth blocks, and glitch pops.
"""
import argparse
import os
import random
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.path.insert(0, '/opt/hermes/.venv/lib/python3.13/site-packages')
    from PIL import Image, ImageDraw


def find_text_region(img, search_start_pct=0.70, window_height=350, padding=40):
    """Find the text band at bottom of a cover via sliding-window brightness."""
    w, h = img.size
    rgb = img.load()
    gray = img.convert('L').load()

    bg_samples = []
    for x in range(w // 4, w * 3 // 4, 30):
        for y in range(h // 5, h // 4, 30):
            bg_samples.append(gray[x, y])
    bg_median = sorted(bg_samples)[len(bg_samples) // 2]

    search_start = int(h * search_start_pct)
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

    best_start = search_start
    best_total = 0
    for start_y in range(search_start, h - window_height):
        total = sum(score for y, score in row_scores if start_y <= y < start_y + window_height)
        if total > best_total:
            best_total = total
            best_start = start_y

    text_top = max(0, best_start - padding)
    text_bottom = min(h, best_start + window_height + padding)
    return (0, text_top, w, text_bottom - text_top)


def extract_palette(img, n_colors=10):
    """Extract dominant colors from the artwork via weighted bucket quantization."""
    w, h = img.size
    rgb = img.load()

    samples = []
    step = max(1, min(w, h) // 80)
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b = rgb[x, y][:3]
            lum = (r + g + b) / 3
            if lum > 25:
                max_c = max(r, g, b)
                min_c = min(r, g, b)
                sat = max_c - min_c
                weight = 1 + (sat / 255.0) * 3 + (lum / 255.0)
                samples.append(((r, g, b), weight))

    if not samples:
        return [(128, 0, 255), (0, 255, 255), (255, 0, 128)]

    buckets = {}
    for (r, g, b), weight in samples:
        key = ((r // 48) * 48, (g // 48) * 48, (b // 48) * 48)
        if key not in buckets:
            buckets[key] = [0, 0, 0, 0]
        buckets[key][0] += r * weight
        buckets[key][1] += g * weight
        buckets[key][2] += b * weight
        buckets[key][3] += weight

    sorted_buckets = sorted(buckets.items(), key=lambda x: x[1][3], reverse=True)
    palette = []
    for key, (rs, gs, bs, ws) in sorted_buckets[:n_colors * 3]:
        if ws > 0:
            avg_r, avg_g, avg_b = int(rs / ws), int(gs / ws), int(bs / ws)
            max_c = max(avg_r, avg_g, avg_b)
            min_c = min(avg_r, avg_g, avg_b)
            sat = max_c - min_c
            if sat < 50 and max_c > 80:
                avg_r = min(255, int(avg_r * 1.1))
                avg_g = min(255, int(avg_g * 1.05))
                avg_b = min(255, int(avg_b * 1.15))
            palette.append((avg_r, avg_g, avg_b))

    final_palette = []
    for color in palette:
        too_similar = any(
            sum(abs(a - b) for a, b in zip(color, existing)) < 60
            for existing in final_palette
        )
        if not too_similar:
            final_palette.append(color)
        if len(final_palette) >= n_colors:
            break

    while len(final_palette) < 6:
        final_palette.append((128, 0, 255))

    return final_palette


def pixelate_region(img, region, pixel_size=32):
    """Cover the region with chunky art-matched pixel blocks."""
    x, y, w, h_region = region
    img = img.copy()
    draw = ImageDraw.Draw(img)

    palette = extract_palette(img, n_colors=10)
    bright_palette = [
        (min(255, int(c[0] * 1.3 + 30)), min(255, int(c[1] * 1.3 + 30)), min(255, int(c[2] * 1.3 + 30)))
        for c in palette
    ]
    dark_palette = [
        (max(0, int(c[0] * 0.15)), max(0, int(c[1] * 0.15)), max(0, int(c[2] * 0.15)))
        for c in palette
    ]

    rows = h_region // pixel_size + 1
    cols = w // pixel_size + 1
    random.seed(42)

    for row in range(rows):
        for col in range(cols):
            roll = random.random()
            if roll < 0.12:
                base = random.choice(dark_palette)
                brightness = 0.5 + random.random() * 0.5
            elif roll < 0.17:
                base = random.choice(bright_palette)
                brightness = 1.0 + random.random() * 0.4
            else:
                base = random.choice(palette)
                brightness = 0.75 + random.random() * 0.35

            final_r = min(255, max(0, int(base[0] * brightness)))
            final_g = min(255, max(0, int(base[1] * brightness)))
            final_b = min(255, max(0, int(base[2] * brightness)))

            block_x = x + col * pixel_size
            block_y = y + row * pixel_size

            draw.rectangle(
                [block_x, block_y, block_x + pixel_size - 1, block_y + pixel_size - 1],
                fill=(final_r, final_g, final_b),
            )

            # 2px dark grid line on top and left for chunky feel
            dark = (max(0, final_r // 7), max(0, final_g // 7), max(0, final_b // 7))
            draw.rectangle([block_x, block_y, block_x + pixel_size - 1, block_y + 1], fill=dark)
            draw.rectangle([block_x, block_y, block_x + 1, block_y + pixel_size - 1], fill=dark)

    return img


def process_single(input_path, output_path, pixel_size=32, padding=40):
    """Process a single cover image."""
    img = Image.open(input_path).convert('RGB')
    region = find_text_region(img, padding=padding)
    result = pixelate_region(img, region, pixel_size=pixel_size)
    result.save(output_path, 'PNG', optimize=True)
    print(f"OK: {os.path.basename(input_path)} -> {output_path}")


def process_batch(input_dir, output_dir, pixel_size=32):
    """Process all PNG covers in a directory (excluding _space and _sc variants)."""
    os.makedirs(output_dir, exist_ok=True)

    files = sorted(
        f for f in os.listdir(input_dir)
        if f.endswith('.png') and not f.endswith('_space.png') and not f.endswith('_sc.png')
    )

    processed = skipped = failed = 0
    for fname in files:
        input_path = os.path.join(input_dir, fname)
        output_path = os.path.join(output_dir, fname)

        if os.path.exists(output_path):
            print(f"SKIP (exists): {fname}")
            skipped += 1
            continue

        try:
            img = Image.open(input_path).convert('RGB')
            if img.size[0] < 100 or img.size[1] < 100:
                print(f"SKIP (too small): {fname}")
                skipped += 1
                continue
            region = find_text_region(img)
            result = pixelate_region(img, region, pixel_size=pixel_size)
            result.save(output_path, 'PNG', optimize=True)
            print(f"OK: {fname}")
            processed += 1
        except Exception as e:
            print(f"FAIL: {fname} - {e}")
            failed += 1

    print(f"\nDone: {processed} processed, {skipped} skipped, {failed} failed")


def main():
    parser = argparse.ArgumentParser(description='Pixelate text on cover art with art-matched colors')
    parser.add_argument('input', help='Input image path or directory (for --batch)')
    parser.add_argument('output', help='Output image path or directory (for --batch)')
    parser.add_argument('--batch', action='store_true', help='Process all PNGs in input directory')
    parser.add_argument('--pixel-size', type=int, default=32, help='Pixel block size (default: 32, extra chunky)')
    parser.add_argument('--padding', type=int, default=40, help='Padding around detected text region (default: 40)')
    args = parser.parse_args()

    if args.batch:
        process_batch(args.input, args.output, args.pixel_size)
    else:
        process_single(args.input, args.output, args.pixel_size, args.padding)


if __name__ == '__main__':
    main()