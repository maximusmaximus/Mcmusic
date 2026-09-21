#!/usr/bin/env python3
"""
patch_all_gateway.py — Combined gateway patcher.
Run after every container restart to ensure all callback handlers are present.
"""
import subprocess
import sys

VENV_PYTHON = "/opt/hermes/.venv/bin/python3"
PATCHES = [
    "/opt/data/scripts/patch_gateway.py",      # Original ap: select/skip/love/hate/refine
    "/opt/data/scripts/patch_gateway_v2.py",    # Pipeline phase handlers (songs/art/final/master)
]

for patch in PATCHES:
    try:
        res = subprocess.run([VENV_PYTHON, patch], capture_output=True, text=True)
        print(f"[patch_all] {patch}: {res.stdout.strip()}")
        if res.stderr.strip():
            print(f"  stderr: {res.stderr.strip()}")
    except Exception as e:
        print(f"[patch_all] {patch}: ERROR — {e}")

print("[patch_all] Done.")
