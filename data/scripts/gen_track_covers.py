#!/usr/bin/env python3
import json, urllib.request, base64, os, subprocess

VENICE_KEY = ""
BOT = ""
try:
    env = open("/proc/1/environ").read().split(chr(0))
    for e in env:
        if e.startswith("VENICE_API_KEY="): VENICE_KEY = e.split("=",1)[1]
        if e.startswith("TELEGRAM_BOT_TOKEN="): BOT = e.split("=",1)[1]
except: pass

CHAT = "8293122782"
out_dir = "/opt/data/music/artwork/covers/PACIFIC-CYCLONE-DRIFT"
os.makedirs(out_dir, exist_ok=True)

tracks = [
    {"title": "EYEWALL", "scene": "the violent center of a massive cyclone tearing through a neon-lit coastal city, debris swirling in spiral patterns, lightning illuminating rain-drenched streets"},
    {"title": "BLACKWATER", "scene": "a flooded underground tunnel with dark water reflecting red emergency lights, a lone car half-submerged, water rushing through broken concrete"},
    {"title": "GLASSWAKE", "scene": "shattered glass suspended mid-air from a collapsing skyscraper facade, refracting neon city lights through torrential rain, frozen moment of destruction"},
    {"title": "FLOODLINE", "scene": "a highway overpass barely above rising black floodwaters at night, distant car headlights cutting through storm haze, water swallowing the city below"},
    {"title": "CRESTFALL", "scene": "the aftermath calm after the cyclone, a wrecked sports car on an empty rain-soaked boulevard at dawn, palm trees bent and broken, first light breaking through storm clouds"},
]

for i, t in enumerate(tracks):
    prompt = t["scene"] + ". Dark cinematic atmosphere, cyber-noir aesthetic, hyperdetailed, moody lighting. NO TEXT, NO LETTERS, NO TYPOGRAPHY"
    print(f"Generating {i+1}/5: {t['title']}...")
    
    payload = json.dumps({
        "model": "grok-imagine-image-quality",
        "prompt": prompt,
        "response_format": "b64_json"
    }).encode()
    
    req = urllib.request.Request(
        "https://api.venice.ai/api/v1/images/generations",
        data=payload,
        headers={"Authorization": f"Bearer {VENICE_KEY}", "Content-Type": "application/json"}
    )
    
    try:
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        b64 = data.get("data", [{}])[0].get("b64_json")
    except Exception as e:
        print(f"  API error: {e}")
        continue
    
    if b64:
        cover_path = os.path.join(out_dir, f"{t['title']}_cover.png")
        with open(cover_path, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"  Saved: {cover_path}")
        
        # Apply title overlay with --bottom flag for track covers
        subprocess.run(["/opt/hermes/.venv/bin/python3",
            "/opt/data/skills/gen-artwork/gen-artwork/scripts/overlay-title.py",
            cover_path, t["title"], "--bottom"], capture_output=True)
        print(f"  Overlay applied")
        
        # Send to Telegram
        cmd = ["curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{BOT}/sendPhoto",
            "-F", f"chat_id={CHAT}",
            "-F", f"photo=@{cover_path}",
            "-F", f"caption=🎨 Track {i+1}: {t['title']}"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            r = json.loads(res.stdout)
            ok = "Sent!" if r.get("ok") else f"Error: {r}"
        except:
            ok = f"curl error: {res.stderr}"
        print(f"  {ok}")
    else:
        print(f"  No image data returned")

print("\nAll track covers done!")
