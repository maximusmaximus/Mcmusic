#!/usr/bin/env python3
"""Re-overlay existing track covers with Unicode-styled titles."""
import json, os, subprocess

BOT = ""
try:
    env = open("/proc/1/environ").read().split(chr(0))
    for e in env:
        if e.startswith("TELEGRAM_BOT_TOKEN="): BOT = e.split("=",1)[1]
except: pass

CHAT = "8293122782"
OVERLAY = "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py"
STYLIZE = "/opt/data/scripts/stylize_title.py"
COVER_DIR = "/opt/data/music/artwork/covers/PACIFIC-CYCLONE-DRIFT"
ALBUM_COVER = "/opt/data/music/artwork/covers/PACIFIC-CYCLONE-DRIFT_cover.png"

def stylize(title):
    res = subprocess.run(["/opt/hermes/.venv/bin/python3", STYLIZE, title],
                         capture_output=True, text=True)
    if res.returncode == 0 and '-> ' in res.stdout:
        return res.stdout.strip().split('-> ')[-1]
    return title

# Re-overlay album cover
album_styled = stylize("PACIFIC-CYCLONE-DRIFT")
print(f"Album: PACIFIC-CYCLONE-DRIFT -> {album_styled}")
if os.path.exists(ALBUM_COVER):
    subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY,
        "--image", ALBUM_COVER, "--title", album_styled,
        "--auto-color", "--output", ALBUM_COVER])
    # Send
    cmd = ["curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{BOT}/sendPhoto",
        "-F", f"chat_id={CHAT}", "-F", f"photo=@{ALBUM_COVER}",
        "-F", f"caption=🎨 Album: {album_styled}"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    r = json.loads(res.stdout)
    print(f"  Album cover: {'Sent!' if r.get('ok') else r}")

# Re-overlay track covers
tracks = ["EYEWALL", "BLACKWATER", "GLASSWAKE", "FLOODLINE", "CRESTFALL"]
for i, title in enumerate(tracks):
    styled = stylize(title)
    cover = os.path.join(COVER_DIR, f"{title}_cover.png")
    print(f"\n{i+1}. {title} -> {styled}")
    
    if not os.path.exists(cover):
        print(f"  SKIP: {cover} not found")
        continue
    
    # Overlay with --bottom and --auto-color
    subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY,
        "--image", cover, "--title", styled,
        "--bottom", "--auto-color", "--output", cover])
    
    # Send to Telegram
    cmd = ["curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{BOT}/sendPhoto",
        "-F", f"chat_id={CHAT}", "-F", f"photo=@{cover}",
        "-F", f"caption=🎨 Track {i+1}: {title} ({styled})"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    r = json.loads(res.stdout)
    print(f"  {'Sent!' if r.get('ok') else r}")

print("\nDone! All covers re-overlaid with Unicode titles.")
