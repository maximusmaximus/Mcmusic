#!/usr/bin/env python3
"""
verify_pipeline_environment.py — Automated verification and self-healing for pipeline scripts.
Validates that produce-album.py and master-producer.py contain required flags and that
container entrypoints do not overwrite live skills with stale image files.
"""

import os
import shutil
import subprocess
import sys

SCRIPTS_DIR = "/opt/data/scripts"
SKILLS_DIR = "/opt/data/skills/master-producer/master-producer/scripts"
BUNDLED_DIR = "/opt/hermes/bundled-skills/master-producer/master-producer/scripts"
ENTRYPOINT = "/opt/hermes/entrypoint.sh"
VENV_PYTHON = "/opt/hermes/.venv/bin/python3"


def check_script_args(script_path, required_flags):
    if not os.path.exists(script_path):
        return False, f"File {script_path} does not exist"
    python_bin = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
    try:
        proc = subprocess.run([python_bin, script_path, "--help"], capture_output=True, text=True, timeout=10)
        output = proc.stdout + proc.stderr
        missing = [f for f in required_flags if f not in output]
        if missing:
            return False, f"Missing flags: {', '.join(missing)}"
        return True, "OK"
    except Exception as e:
        return False, str(e)


def audit_and_heal():
    healed = []
    issues = []

    # 1. Check entrypoint.sh patch
    if os.path.exists(ENTRYPOINT):
        try:
            with open(ENTRYPOINT, "r", encoding="utf-8") as f:
                content = f.read()
            if 'rm -rf "$dest"' in content or 'cp -r "$skill_dir" "$dest"' in content:
                patch_script = os.path.join(SCRIPTS_DIR, "patch_entrypoint.py")
                if os.path.exists(patch_script):
                    subprocess.run([sys.executable, patch_script], capture_output=True, timeout=10)
                    healed.append("Patched /opt/hermes/entrypoint.sh to disable destructive bundled-skills sync")
        except Exception as e:
            issues.append(f"Failed to check entrypoint.sh: {e}")

    # 2. Check produce-album.py
    prod_album = os.path.join(SKILLS_DIR, "produce-album.py")
    ok, msg = check_script_args(prod_album, ["--mode", "--no-deliver", "--resume-tracks", "--track-names"])
    if not ok:
        issues.append(f"produce-album.py invalid: {msg}")

    # 3. Check master-producer.py
    master_prod = os.path.join(SKILLS_DIR, "master-producer.py")
    ok, msg = check_script_args(master_prod, ["--title", "--artist", "--album"])
    if not ok:
        issues.append(f"master-producer.py invalid: {msg}")

    # 4. Sync current working scripts to bundled-skills as fallback
    if os.path.exists(BUNDLED_DIR) and os.path.exists(prod_album) and os.path.exists(master_prod):
        try:
            shutil.copy2(prod_album, os.path.join(BUNDLED_DIR, "produce-album.py"))
            shutil.copy2(master_prod, os.path.join(BUNDLED_DIR, "master-producer.py"))
            healed.append("Synced active scripts into container bundled-skills directory")
        except Exception as e:
            issues.append(f"Could not sync bundled-skills: {e}")

    return issues, healed


def main():
    issues, healed = audit_and_heal()
    if healed:
        for h in healed:
            print(f"[env-audit] ✅ Healed: {h}")
    if issues:
        for i in issues:
            print(f"[env-audit] ⚠️ Issue detected: {i}", file=sys.stderr)
        sys.exit(1)
    else:
        print("[env-audit] ✅ All pipeline scripts and container entrypoint guards verified.")
        sys.exit(0)


if __name__ == "__main__":
    main()
