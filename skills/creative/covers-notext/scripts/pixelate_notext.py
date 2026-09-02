#!/usr/bin/env python3
"""Pixelate text regions on cover art using colors sampled from the artwork itself.

Offline fallback when Venice AI is unavailable. Detects bright/colored text bands
at the bottom of cover images and replaces them with chunky neon pixel blocks
colored from the image's own palette.

Usage:
    pixelate_notext.py INPUT_PATH OUTPUT_PATH [PIXEL_SIZE]

    INPUT_PATH:  Path to source image (PNG/JPG)
    OUTPUT_PATH:  Path to save pixelated output (PNG)
    PIXEL_SIZE:  Block size in pixels (default: 32)

Examples:
    pixelate_notext.py cover.png cover_notext.png
    pixelate_notext.py cover.png cover_notext.png 24
"""
import sys
import os
import random

sys.path.insert(0, '/opt/hermes/.venv/lib/python3.13/site-packages')
from PIL import Image, ImageDraw


def find_text_region(img, search_start_pct=0.70, window_height=350, padding=40):
    """Find the text band at bottom of cover via sliding window brightness detection.
    
    Scans the bottom 30% of the image for the densest cluster of bright/colored
    pixels. Works well for VØIDRIDE-style covers with neon text at the bottom.
    """
    w, h = img.size
    rgb = img.load()
    gray = img.convert('L').load()
    
    # Get background brightness from top-center (definitely no text there)
    bg_samples = []
    for x in range(w//4, w*3//4, 30):
        for y in range(h//5, h//4, 30):
            bg_samples.append(gray[x, y])
    bg_median = sorted(bg_samples)[len(bg_samples)//2]
    
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
        row_scores.append((y, score, bright, colored))
    
    # Sliding window to find densest region
    best_start = search_start
    best_total = 0
    for start_y in range(search_start, max(search_start, h - window_height)):
        total = sum(score for y, score, b, c in row_scores if start_y <= y < start_y + window_height)
        if total > best_total:
            best_total = total
            best_start = start_y
    
    text_top = max(0, best_start - padding)
    text_bottom = min(h, best_start + window_height + padding)
    
    return (0, text_top, w, text_bottom - text_top)


def extract_palette(img, n_colors=10):
    """Extract dominant colors from the artwork via bucket quantization."""
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
    
    # Bucket quantization
    buckets = {}
    for (r, g, b), weight in samples:
        qr, qg, qb = (r // 48) * 48, (g // 48) * 48, (b // 48) * 48
        key = (qr, qg, qb)
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
            avg_r = int(rs / ws)
            avg_g = int(gs / ws)
            avg_b = int(bs / ws)
            max_c = max(avg_r, avg_g, avg_b)
            min_c = min(avg_r, avg_g, avg_b)
            sat = max_c - min_c
            if sat < 50 and max_c > 80:
                avg_r = min(255, int(avg_r * 1.1))
                avg_g = min(255, int(avg_g * 1.05))
                avg_b = min(255, int(avg_b * 1.15))
            palette.append((avg_r, avg_g, avg_b))
    
    # Deduplicate similar colors
    final_palette = []
    for color in palette:
        if all(sum(abs(a-b) for a, b in zip(color, existing)) >= 60 for existing in final_palette):
            final_palette.append(color)
        if len(final_palette) >= n_colors:
            break
    
    while len(final_palette) < 6:
        final_palette.append((128, 0, 255))
    
    return final_palette


def pixelate_text_region(img, region, pixel_size=32):
    """Cover the text region with chunky pixel blocks using art-matched colors.
    
    Extracts a palette from the whole image, then fills the text region with
    pixel blocks colored from that palette. Includes dark depth blocks (12%),
    bright glitch blocks (5%), and 2px dark grid lines between pixels.
    """
    x, y, w, h_region = region
    img = img.copy()
    draw = ImageDraw.Draw(img)
    
    palette = extract_palette(img, n_colors=10)
    
    # Build bright and dark variants
    bright_palette = [(min(255, int(c[0]*1.3+30)), min(255, int(c[1]*1.3+30)), min(255, int(c[2]*1.3+30))) for c in palette]
    dark_palette = [(max(0, int(c[0]*0.15)), max(0, int(c[1]*0.15)), max(0, int(c[2]*0.15))) for c in palette]
    
    rows = h_region // pixel_size + 1
    cols = w // pixel_size + 1
    
    random.seed(42)  # Deterministic for reproducibility
    
    for row in range(rows):
        for col in range(cols):
            roll = random.random()
            if roll < 0.12:
                # 12% dark depth blocks
                base = random.choice(dark_palette)
                brightness = 0.5 + random.random() * 0.5
            elif roll < 0.17:
                # 5% bright glitch blocks
                base = random.choice(bright_palette)
                brightness = 1.0 + random.random() * 0.4
            else:
                # 83% normal palette blocks
                base = random.choice(palette)
                brightness = 0.75 + random.random() * 0.35
            
            final_r = min(255, max(0, int(base[0] * brightness)))
            final_g = min(255, max(0, int(base[1] * brightness)))
            final_b = min(255, max(0, int(base[2] * brightness)))
            
            block_x = x + col * pixel_size
            block_y = y + row * pixel_size
            
            draw.rectangle(
                [block_x, block_y, block_x + pixel_size - 1, block_y + pixel_size - 1],
                fill=(final_r, final_g, final_b)
            )
            
            # 2px dark grid lines on top and left edges for chunky feel
            dark = (max(0, final_r // 7), max(0, final_g // 7), max(0, final_b // 7))
            draw.rectangle([block_x, block_y, block_x + pixel_size - 1, block_y + 1], fill=dark)
            draw.rectangle([block_x, block_y, block_x + 1, block_y + pixel_size - 1], fill=dark)
    
    return img


def batch_process(input_dir, output_dir, pixel_size=32):
    """Process all PNG files in a directory (skipping _space and _sc variants)."""
    os.makedirs(output_dir, exist_ok=True)
    
    all_files = sorted([f for f in os.listdir(input_dir)
                        if f.endswith('.png')
                        and not f.endswith('_space.png')
                        and not f.endswith('_sc.png')])
    
    processed = 0
    skipped = 0
    failed = 0
    
    for i, fname in enumerate(all_files):
        input_path = os.path.join(input_dir, fname)
        output_path = os.path.join(output_dir, fname)
        
        if os.path.exists(output_path):
            skipped += 1
            continue
        
        try:
            img = Image.open(input_path).convert('RGB')
            w, h = img.size
            if w < 100 or h < 100:
                skipped += 1
                continue
            
            region = find_text_region(img)
            result = pixelate_text_region(img, region, pixel_size)
            result.save(output_path, 'PNG', optimize=True)
            processed += 1
            size_mb = os.path.getsize(output_path) / (1024*1024)
            print(f"[{i+1}/{len(all_files)}] OK: {fname} ({size_mb:.1f}MB)")
        except Exception as e:
            print(f"[{i+1}/{len(all_files)}] FAIL: {fname} - {e}")
            failed += 1
    
    print(f"\nDone: {processed} processed, {skipped} skipped, {failed} failed")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    pixel_size = int(sys.argv[3]) if len(sys.argv) > 3 else 32
    
    img = Image.open(input_path).convert('RGB')
    region = find_text_region(img)
    print(f"Image: {img.size}, Text region: x={region[0]}, y={region[1]}, w={region[2]}, h={region[3]}")
    
    # Extract and show palette
    palette = extract_palette(img)
    print(f"Palette ({len(palette)} colors): " + ", ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in palette))
    
    result = pixelate_text_region(img, region, pixel_size)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    result.save(output_path, 'PNG', optimize=True)
    print(f"Saved: {output_path} ({os.path.getsize(output_path)/1024/1024:.1f}MB)")