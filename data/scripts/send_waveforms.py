#!/usr/bin/env python3
import os, subprocess, json

BOT = ""
try:
    for e in open("/proc/1/environ").read().split(chr(0)):
        if e.startswith("TELEGRAM_BOT_TOKEN="): BOT = e.split("=",1)[1]
except: pass

CHAT = "8293122782"
WAVE_DIR = "/opt/data/music/artwork/waveforms/PACIFIC-CYCLONE-DRIFT"

print(f"Sending waveforms from {WAVE_DIR}...")
for f in sorted(os.listdir(WAVE_DIR)):
    if f.endswith("_waveform.png"):
        path = os.path.join(WAVE_DIR, f)
        title = f.replace("_waveform.png", "")
        print(f"Sending {title}...")
        cmd = ["curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{BOT}/sendPhoto",
            "-F", f"chat_id={CHAT}", "-F", f"photo=@{path}",
            "-F", f"caption=🖼️ Waveform banner for {title}"]
        subprocess.run(cmd)

print("Done!")
