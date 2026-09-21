#!/usr/bin/env python3
import json, urllib.request, os, subprocess

VENICE_API_KEY = ""
try:
    for e in open("/proc/1/environ").read().split(chr(0)):
        if e.startswith("VENICE_API_KEY="): VENICE_API_KEY = e.split("=",1)[1]
except: pass

BOT = ""
try:
    for e in open("/proc/1/environ").read().split(chr(0)):
        if e.startswith("TELEGRAM_BOT_TOKEN="): BOT = e.split("=",1)[1]
except: pass

CHAT = "8293122782"
WAVE_DIR = "/opt/data/music/artwork/waveforms/PACIFIC-CYCLONE-DRIFT"
os.makedirs(WAVE_DIR, exist_ok=True)

tracks = [
    ("EYEWALL", "aggressive drift phonk"),
    ("BLACKWATER", "smooth drift phonk"),
    ("GLASSWAKE", "hypnotic drift phonk"),
    ("FLOODLINE", "halftime drift phonk"),
    ("CRESTFALL", "cinematic drift phonk")
]

visual = "A customized twin-turbo sports car powerslides across flooded palm-lined Santa Monica boulevards, neon-drenched retro-futurism"

for title, genre in tracks:
    print(f"Generating clean banner for {title}...")
    prompt = f"{visual}, panoramic scene for track titled {title} — {genre}. Dark cinematic atmosphere, cyber-noir aesthetic, hyperdetailed, moody lighting. NO TEXT, NO LETTERS, NO TYPOGRAPHY"
    
    url = "https://api.venice.ai/api/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "grok-imagine-image-quality",
        "prompt": prompt,
        "response_format": "b64_json"
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        resp = urllib.request.urlopen(req)
        res_data = json.loads(resp.read())
        
        if "data" in res_data and len(res_data["data"]) > 0:
            import base64
            img_data = base64.b64decode(res_data["data"][0]["b64_json"])
            
            # Save raw square
            raw_path = os.path.join(WAVE_DIR, f"{title}_clean_square.png")
            with open(raw_path, "wb") as f:
                f.write(img_data)
                
            print(f"  ✅ Saved square: {raw_path}")
            
            # Extend to waveform using gen_waveform_art.py
            WAVE_SCRIPT = "/opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py"
            subprocess.run([
                "/opt/hermes/.venv/bin/python3", WAVE_SCRIPT,
                "--image", raw_path, "--title", title, "--output-dir", WAVE_DIR
            ])
            
            final_path = os.path.join(WAVE_DIR, f"{title}_waveform.png")
            
            # Send to Telegram
            cmd = ["curl", "-s", "-X", "POST",
                f"https://api.telegram.org/bot{BOT}/sendPhoto",
                "-F", f"chat_id={CHAT}", "-F", f"photo=@{final_path}",
                "-F", f"caption=🖼️ CLEAN Waveform banner for {title}"]
            subprocess.run(cmd)
            
    except Exception as e:
        print(f"  ❌ Error: {e}")

print("Done!")
