#!/usr/bin/env python3
"""
edit_artwork.py — Edit artwork via Venice AI Image Edit inference API (/api/v1/image/edit).
Uses base64 data URL with JSON payload and enhance_prompt=True.
"""

import os
import sys
import argparse
import urllib.request
import urllib.error
import urllib.parse
import json
import base64
import time
import subprocess

def sanitize_prompt_for_venice(prompt, max_len=1450):
    prompt = prompt.strip()
    suffix = " NO TEXT, NO LETTERS, NO TYPOGRAPHY, NO WORDS"
    if "NO TEXT" in prompt.upper():
        suffix = ""
    avail_len = max_len - len(suffix)
    if len(prompt) > avail_len:
        trimmed = prompt[:avail_len]
        last_period = trimmed.rfind('.')
        if last_period > avail_len - 150:
            prompt = trimmed[:last_period + 1]
        else:
            last_space = trimmed.rfind(' ')
            if last_space > 0:
                prompt = trimmed[:last_space]
            else:
                prompt = trimmed
    return (prompt + suffix).strip()

def edit_artwork(image_path, prompt, output_path, api_key, model=None, test=False):
    if not os.path.exists(image_path):
        print(f"Error: Source image not found: {image_path}")
        sys.exit(1)

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    clean_prompt = sanitize_prompt_for_venice(prompt)

    payload = {
        "image": f"data:image/png;base64,{img_b64}",
        "prompt": clean_prompt,
        "enhance_prompt": True
    }
    if model:
        payload["model"] = model

    edit_url = "https://api.venice.ai/api/v1/image/edit"

    if test:
        print("--- TEST MODE ---")
        print(f"Edit URL: {edit_url}")
        print(f"Payload keys: {list(payload.keys())}")
        print(f"Prompt ({len(clean_prompt)} chars): {clean_prompt}")
        print(f"Image base64 length: {len(img_b64)}")
        return True

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(edit_url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    for attempt in range(2):
        try:
            print(f"Requesting image edit from Venice AI (attempt {attempt+1})...")
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
                if len(data) > 1000:
                    with open(output_path, "wb") as f:
                        f.write(data)
                    print(f"Saved edited image to {output_path} ({len(data)} bytes)")
                    return True
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            print(f"HTTP Error {e.code}: {err_body}")
            if e.code >= 500 and attempt < 1:
                time.sleep(2)
                continue
            sys.exit(1)
        except Exception as e:
            print(f"Request failed: {e}")
            if attempt < 1:
                time.sleep(2)
                continue
            sys.exit(1)
    return False

def upscale_artwork(image_path, api_key):
    try:
        from PIL import Image
        img = Image.open(image_path)
        if img.size[0] >= 3000 and img.size[1] >= 3000:
            return True

        with open(image_path, 'rb') as f:
            img_data = f.read()

        boundary = '----VeniceUpscaleBoundary'
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{os.path.basename(image_path)}"\r\n'
            f'Content-Type: image/png\r\n\r\n'.encode() + img_data + b'\r\n' +
            f'--{boundary}\r\nContent-Disposition: form-data; name="scale"\r\n\r\n4\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="creativity"\r\n\r\n0.01\r\n'
            f'--{boundary}--\r\n'.encode()
        )
        url = "https://api.venice.ai/api/v1/image/upscale"
        req = urllib.request.Request(url, data=body, method='POST', headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': f'multipart/form-data; boundary={boundary}',
        })

        with urllib.request.urlopen(req, timeout=120) as response:
            upscaled_data = response.read()

        if len(upscaled_data) > 1000:
            tmp_path = image_path.replace('.png', '_4k.png')
            with open(tmp_path, 'wb') as f:
                f.write(upscaled_data)
            upscaled_img = Image.open(tmp_path)
            final = upscaled_img.resize((3000, 3000), Image.LANCZOS)
            final.save(image_path, 'PNG')
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            print(f"Successfully upscaled {image_path} to 3000x3000")
            return True
    except Exception as e:
        print(f"Upscale warning: {e}")
    return False

def main():
    parser = argparse.ArgumentParser(description="Edit artwork via Venice AI")
    parser.add_argument("--image", required=True, help="Path to source image")
    parser.add_argument("--prompt", required=True, help="Edit instructions")
    parser.add_argument("--output", required=True, help="Path to save output")
    parser.add_argument("--title", help="Optional title for overlay")
    parser.add_argument("--model", help="Optional model override")
    parser.add_argument("--upscale", action="store_true", help="Upscale to 3000x3000 after edit")
    parser.add_argument("--test", action="store_true", help="Print payload instead of making call")
    args = parser.parse_args()

    api_key = os.environ.get('VENICE_API_KEY')
    if not api_key:
        try:
            import yaml
            cfg = yaml.safe_load(open("/opt/data/config.yaml"))
            api_key = cfg.get("venice_api_key") or cfg.get("VENICE_API_KEY")
        except Exception:
            pass

    if not api_key and not args.test:
        print("Error: VENICE_API_KEY not set")
        sys.exit(1)

    ok = edit_artwork(args.image, args.prompt, args.output, api_key, model=args.model, test=args.test)
    if not ok or args.test:
        return

    if args.upscale:
        print("Upscaling edited artwork to 3000x3000...")
        upscale_artwork(args.output, api_key)

    if args.title:
        print(f"Applying text overlay for title '{args.title}'...")
        overlay_script = "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py"
        if not os.path.exists(overlay_script):
            overlay_script = "/opt/data/skills/cover-title-overlay/cover-title-overlay/scripts/overlay-title.py"
        if os.path.exists(overlay_script):
            cmd = [
                "/opt/hermes/.venv/bin/python3",
                overlay_script,
                "--image", args.output,
                "--title", args.title,
                "--auto-color",
                "--output", args.output
            ]
            try:
                subprocess.run(cmd, check=True)
                print("Title overlay applied successfully.")
            except subprocess.CalledProcessError as e:
                print(f"Failed to apply overlay: {e}")

if __name__ == "__main__":
    main()
