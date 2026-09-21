#!/usr/bin/env python3
import subprocess, sys, time

SC = "/opt/data/skills/music/soundcloud/scripts/soundcloud_api.py"
PY = "/opt/hermes/.venv/bin/python3"
COVER_DIR = "/opt/data/music/artwork/covers/PACIFIC-CYCLONE-DRIFT"

tracks = [
    ("2394155868", "EYEWALL"),
    ("2394155919", "BLACKWATER"),
    ("2394155958", "GLASSWAKE"),
    ("2394156015", "FLOODLINE"),
    ("2394156072", "CRESTFALL"),
]

for tid, title in tracks:
    art = f"{COVER_DIR}/{title}_cover.png"
    print(f"Updating {title} (ID {tid})...")
    r = subprocess.run([PY, SC, "update", "--track-id", tid, "--artwork", art],
                       capture_output=True, text=True)
    print(f"  {r.stdout.strip()}")
    if r.returncode != 0:
        print(f"  ERROR: {r.stderr.strip()}")
    time.sleep(1)

print("Done!")
