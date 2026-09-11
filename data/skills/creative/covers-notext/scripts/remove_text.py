#!/usr/bin/env python3
"""Remove text from a cover image using Venice AI image edit API.

Usage:
    remove_text.py INPUT_PATH OUTPUT_PATH [MODEL] [RESOLUTION]

    INPUT_PATH:  Path to source image (PNG/JPG/WebP)
    OUTPUT_PATH: Path to save no-text output (PNG)
    MODEL:       Venice edit model (default: gpt-image-2-edit)
    RESOLUTION:  Resolution tier: "1K", "2K", "4K" (default: auto based on model)

Examples:
    # Best quality (gpt-image-2-edit with 4K):
    remove_text.py cover.png cover_notext.png

    # Fast/cheap (firered-image-edit, 1K only):
    remove_text.py cover.png cover_notext.png firered-image-edit

    # Alternative model:
    remove_text.py cover.png cover_notext.png flux-2-max-edit
"""
import os
import sys
import base64
import requests
import time

VENICE_API_KEY = os.environ.get("VENICE_API_KEY", "") or os.environ.get("VENICE_INFERENCE_KEY", "")
if not VENICE_API_KEY:
    print("ERROR: VENICE_API_KEY not set in environment")
    sys.exit(1)

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

INPUT_PATH = sys.argv[1]
OUTPUT_PATH = sys.argv[2]
MODEL = sys.argv[3] if len(sys.argv) > 3 else "gpt-image-2-edit"

if not os.path.exists(INPUT_PATH):
    print(f"ERROR: Input file not found: {INPUT_PATH}")
    sys.exit(1)

# Determine default resolution based on model
# gpt-image-2-edit supports "4K" -> 2880x2880
# firered-image-edit does NOT support resolution param -> 400 error if included
# Other models: omit resolution, let them default
if len(sys.argv) > 4:
    RESOLUTION = sys.argv[4]
elif "gpt-image" in MODEL:
    RESOLUTION = "4K"
else:
    RESOLUTION = None

# Downscale large images before sending (reduces payload, faster upload)
from PIL import Image

MAX_DIM = 2048
img = Image.open(INPUT_PATH).convert("RGB")
w, h = img.size
temp_path = None

if max(w, h) > MAX_DIM:
    print(f"Downscaling from {w}x{h} to {MAX_DIM}px max dim...")
    ratio = MAX_DIM / max(w, h)
    new_w, new_h = int(w * ratio), int(h * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    temp_path = INPUT_PATH + ".resized.png"
    img.save(temp_path, "PNG")
    INPUT_PATH_WORK = temp_path
    print(f"Resized to {new_w}x{new_h}")
else:
    temp_path = INPUT_PATH + ".temp.png"
    img.save(temp_path, "PNG")
    INPUT_PATH_WORK = temp_path

# Read and encode
with open(INPUT_PATH_WORK, "rb") as f:
    img_data = f.read()
    img_b64 = base64.b64encode(img_data).decode("utf-8")

print(f"Image: {len(img_data)} bytes -> {len(img_b64)} chars base64")
print(f"Model: {MODEL}, Resolution: {RESOLUTION or 'default'}")

# Build payload
payload = {
    "model": MODEL,
    "prompt": (
        "Remove all text, letters, typography, and words from this image. "
        "Fill in those areas with the surrounding background artwork and visual "
        "elements so it looks natural and seamless, as if the text was never there. "
        "The result should be a clean image with no text at all — just the artwork."
    ),
    "image": img_b64,
    "aspect_ratio": "1:1",
    "safe_mode": False,  # Dark album art triggers content filters with True
}

# Only add resolution if specified (not all models support it)
if RESOLUTION:
    payload["resolution"] = RESOLUTION

headers = {
    "Authorization": f"Bearer {VENICE_API_KEY}",
    "Content-Type": "application/json"
}

print(f"Sending to Venice API...")
start = time.time()
resp = requests.post(
    "https://api.venice.ai/api/v1/image/edit",
    json=payload,
    headers=headers,
    timeout=300
)
elapsed = time.time() - start

if resp.status_code == 200:
    content_type = resp.headers.get("content-type", "")
    if "image" in content_type:
        os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_PATH)), exist_ok=True)
        with open(OUTPUT_PATH, "wb") as f:
            f.write(resp.content)

        # Check result and upscale to 3000x3000 if needed
        result_img = Image.open(OUTPUT_PATH)
        rw, rh = result_img.size
        print(f"Result: {rw}x{rh} ({len(resp.content)} bytes, {elapsed:.1f}s)")

        if (rw, rh) != (3000, 3000):
            print(f"Scaling from {rw}x{rh} to 3000x3000...")
            result_img = result_img.convert("RGB").resize((3000, 3000), Image.LANCZOS)
            result_img.save(OUTPUT_PATH, "PNG")
            final_size = os.path.getsize(OUTPUT_PATH)
            print(f"Saved: {OUTPUT_PATH} ({final_size/1024/1024:.1f} MB, 3000x3000)")
        else:
            print(f"Saved: {OUTPUT_PATH} ({len(resp.content)} bytes)")
    else:
        print(f"ERROR: Unexpected content-type: {content_type}")
        print(f"Response: {resp.text[:500]}")
        sys.exit(1)
else:
    print(f"ERROR: HTTP {resp.status_code} ({elapsed:.1f}s)")
    print(f"Response: {resp.text[:500]}")
    sys.exit(1)

# Clean up temp files
for path in [INPUT_PATH + ".resized.png", INPUT_PATH + ".temp.png"]:
    if os.path.exists(path):
        os.unlink(path)