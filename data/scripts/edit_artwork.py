import os
import sys
import argparse
import urllib.request
import urllib.error
import urllib.parse
import json
import uuid
import time
import subprocess

def upload_multipart(url, files, fields, headers):
    import io
    boundary = uuid.uuid4().hex
    headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    
    body = io.BytesIO()
    for key, val in fields.items():
        body.write(f'--{boundary}\r\n'.encode())
        body.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.write(f'{val}\r\n'.encode())
    
    for key, file_info in files.items():
        filename = file_info['filename']
        content = file_info['content']
        body.write(f'--{boundary}\r\n'.encode())
        body.write(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode())
        body.write(b'Content-Type: application/octet-stream\r\n\r\n')
        body.write(content)
        body.write(b'\r\n')
        
    body.write(f'--{boundary}--\r\n'.encode())
    
    req = urllib.request.Request(url, data=body.getvalue(), headers=headers, method='POST')
    return req

def make_request(req, max_retries=1):
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < max_retries:
                print(f"Error {e.code}. Retrying in 2 seconds...")
                time.sleep(2)
                continue
            print(f"HTTP Error {e.code}: {e.read().decode('utf-8', errors='replace')}")
            sys.exit(1)
        except Exception as e:
            if attempt < max_retries:
                print(f"Error: {e}. Retrying in 2 seconds...")
                time.sleep(2)
                continue
            print(f"Request failed: {e}")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Edit artwork via Venice AI")
    parser.add_argument("--image", required=True, help="Path to source image")
    parser.add_argument("--prompt", required=True, help="Edit instructions")
    parser.add_argument("--output", required=True, help="Path to save output")
    parser.add_argument("--title", help="Optional title for overlay")
    parser.add_argument("--test", action="store_true", help="Print payload instead of making call")
    args = parser.parse_args()

    api_key = os.environ.get('VENICE_API_KEY')
    if not api_key:
        print("VENICE_API_KEY not set")
        sys.exit(1)
        
    with open(args.image, 'rb') as f:
        image_data = f.read()
        
    headers = {
        'Authorization': f'Bearer {api_key}'
    }
    
    # 1. Edit Request
    edit_url = 'https://api.venice.ai/api/v1/image/edit'
    fields = {
        'prompt': args.prompt,
        'model': 'grok-imagine-image-quality',
        'enhance_prompt': 'true'
    }
    files = {
        'image': {'filename': os.path.basename(args.image), 'content': image_data}
    }
    
    if args.test:
        print(f"--- TEST MODE ---")
        print(f"Edit URL: {edit_url}")
        print(f"Fields: {fields}")
        print(f"Image bytes: {len(image_data)}")
        return
        
    print("Requesting edit...")
    edit_req = upload_multipart(edit_url, files, fields, headers.copy())
    edited_data = make_request(edit_req)
    
    # 2. Upscale Request
    print("Requesting upscale...")
    upscale_url = 'https://api.venice.ai/api/v1/image/upscale'
    upscale_fields = {
        'scale': '4',
        'creativity': '0.01'
    }
    upscale_files = {
        'image': {'filename': 'edited.png', 'content': edited_data}
    }
    
    upscale_req = upload_multipart(upscale_url, upscale_files, upscale_fields, headers.copy())
    final_data = make_request(upscale_req)
    
    # Save output
    with open(args.output, 'wb') as f:
        f.write(final_data)
    print(f"Saved edited and upscaled image to {args.output}")
    
    # 3. Optional Overlay
    if args.title:
        print("Applying text overlay...")
        cmd = [
            "/opt/hermes/.venv/bin/python3",
            "/opt/data/skills/cover-title-overlay/cover-title-overlay/scripts/overlay-title.py",
            "--image", args.output,
            "--title", args.title,
            "--output", args.output
        ]
        try:
            subprocess.run(cmd, check=True)
            print("Overlay applied.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to apply overlay: {e}")

if __name__ == "__main__":
    main()
