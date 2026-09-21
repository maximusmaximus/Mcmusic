#!/usr/bin/env python3
"""List all playlists and fix hyphenated titles."""
import sys, subprocess, json

SC = "/opt/data/skills/music/soundcloud/scripts/soundcloud_api.py"
PY = "/opt/hermes/.venv/bin/python3"

sys.path.insert(0, '/opt/data/skills/music/soundcloud/scripts')
from soundcloud_api import get_auth_headers

import urllib.request
headers = get_auth_headers()
req = urllib.request.Request(
    'https://api.soundcloud.com/me/playlists?limit=20',
    headers=headers
)
resp = urllib.request.urlopen(req)
playlists = json.loads(resp.read())

for p in playlists:
    title = p['title']
    pid = p['id']
    has_hyphen = '-' in title
    print(f"{'FIX' if has_hyphen else 'OK '} {pid} | {title}")
    
    if has_hyphen:
        new_title = title.replace('-', ' ')
        print(f"    -> {new_title}")
        r = subprocess.run([PY, SC, "update-playlist",
            "--playlist-id", str(pid), "--title", new_title],
            capture_output=True, text=True)
        if r.returncode == 0:
            print(f"    DONE")
        else:
            print(f"    ERROR: {r.stderr[:200]}")

print("\nAll playlists checked!")
