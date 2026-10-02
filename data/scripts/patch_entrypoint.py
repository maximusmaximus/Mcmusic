#!/usr/bin/env python3
"""
patch_entrypoint.py — Prevents /opt/hermes/entrypoint.sh from overwriting live skills
in /opt/data/skills with outdated bundled-skills from the container image.
"""
import os
import sys

ENTRYPOINT = "/opt/hermes/entrypoint.sh"

def patch():
    if not os.path.exists(ENTRYPOINT):
        return
    with open(ENTRYPOINT, "r", encoding="utf-8") as f:
        content = f.read()

    changed = False
    if 'rm -rf "$dest"' in content:
        content = content.replace('rm -rf "$dest"', '# rm -rf "$dest"')
        changed = True
    if 'cp -r "$skill_dir" "$dest"' in content:
        content = content.replace('cp -r "$skill_dir" "$dest"', '# cp -r "$skill_dir" "$dest"')
        changed = True

    if changed:
        with open(ENTRYPOINT, "w", encoding="utf-8") as f:
            f.write(content)
        print("[patch_entrypoint] Successfully disabled destructive bundled-skills sync in entrypoint.sh")
    else:
        print("[patch_entrypoint] entrypoint.sh already patched or does not contain target pattern")

if __name__ == "__main__":
    patch()
