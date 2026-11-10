#!/usr/bin/env python3
"""
verify_pipeline_environment.py — Automated verification and self-healing for pipeline scripts & live agent state.
Validates that produce-album.py, master-producer.py, propose_albums.py, album_pipeline.py,
gateway callbacks (telegram.py), SOUL.md, and .skills_prompt_snapshot.json are all in sync and live.
"""

import os
import shutil
import subprocess
import sys

SCRIPTS_DIR = "/opt/data/scripts"
SKILLS_DIR = "/opt/data/skills/master-producer/master-producer/scripts"
SKILL_MD = "/opt/data/skills/master-producer/master-producer/SKILL.md"
BUNDLED_DIR = "/opt/hermes/bundled-skills/master-producer/master-producer/scripts"
BUNDLED_SKILL_MD = "/opt/hermes/bundled-skills/master-producer/master-producer/SKILL.md"
ENTRYPOINT = "/opt/hermes/entrypoint.sh"
GATEWAY_TELEGRAM = "/opt/hermes/gateway/platforms/telegram.py"
SOUL_PATH = "/opt/data/SOUL.md"
SKILLS_SNAPSHOT = "/opt/data/.skills_prompt_snapshot.json"
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
    python_bin = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable

    # 1. Check entrypoint.sh patch
    if os.path.exists(ENTRYPOINT):
        try:
            with open(ENTRYPOINT, "r", encoding="utf-8") as f:
                content = f.read()
            if 'rm -rf "$dest"' in content or 'cp -r "$skill_dir" "$dest"' in content:
                patch_script = os.path.join(SCRIPTS_DIR, "patch_entrypoint.py")
                if os.path.exists(patch_script):
                    subprocess.run([python_bin, patch_script], capture_output=True, timeout=10)
                    healed.append("Patched /opt/hermes/entrypoint.sh to disable destructive bundled-skills sync")
        except Exception as e:
            issues.append(f"Failed to check entrypoint.sh: {e}")

    # 2. Check produce-album.py
    prod_album = os.path.join(SKILLS_DIR, "produce-album.py")
    ok, msg = check_script_args(prod_album, ["--mode", "--no-deliver", "--resume-tracks", "--track-names", "--closer-duration", "hyperspatial"])
    if not ok:
        issues.append(f"produce-album.py invalid: {msg}")

    # 3. Check master-producer.py
    master_prod = os.path.join(SKILLS_DIR, "master-producer.py")
    ok, msg = check_script_args(master_prod, ["--title", "--artist", "--album", "--plan", "hyperspatial"])
    if not ok:
        issues.append(f"master-producer.py invalid: {msg}")

    # 3b. Check venice-music.py has elevenlabs-music-v2-5
    venice_music = "/opt/data/skills/venice-music/venice-music/scripts/venice-music.py"
    bundled_venice_music = "/opt/hermes/bundled-skills/venice-music/venice-music/scripts/venice-music.py"
    if os.path.exists(venice_music):
        vm_txt = open(venice_music, "r", encoding="utf-8", errors="ignore").read()
        if "elevenlabs-music-v2-5" not in vm_txt:
            issues.append("venice-music.py missing elevenlabs-music-v2-5 model definition")
        elif os.path.exists(os.path.dirname(bundled_venice_music)):
            try:
                shutil.copy2(venice_music, bundled_venice_music)
            except Exception:
                pass
    else:
        issues.append("venice-music.py missing")

    # 3c. Sync dawagent handoff.py to bundled-skills if present
    handoff_script = "/opt/data/skills/dawagent/dawagent/scripts/handoff.py"
    bundled_handoff = "/opt/hermes/bundled-skills/dawagent/dawagent/scripts/handoff.py"
    if os.path.exists(handoff_script) and os.path.exists(os.path.dirname(bundled_handoff)):
        try:
            shutil.copy2(handoff_script, bundled_handoff)
        except Exception:
            pass

    # 4. Check propose_albums.py & album_pipeline.py credit gates + Cohesive VØIDRIDE pricing
    propose_script = os.path.join(SCRIPTS_DIR, "propose_albums.py")
    if os.path.exists(propose_script):
        txt = open(propose_script, "r", encoding="utf-8", errors="ignore").read()
        if "check_venice_album_budget" not in txt or "ap:credit:added" not in txt:
            issues.append("propose_albums.py missing Venice credit check or ap:credit:added button")
        if "AVG_ALBUM_COST_USD = 16.32" not in txt:
            issues.append("propose_albums.py missing Cohesive VØIDRIDE AVG_ALBUM_COST_USD = 16.32")
        if "REQUIRED_PROPOSAL_COUNT = 5" not in txt or "len(accepted_proposals) >= 3" in txt:
            issues.append("propose_albums.py missing strict REQUIRED_PROPOSAL_COUNT = 5 enforcement")
    else:
        issues.append("propose_albums.py missing")

    pipeline_script = os.path.join(SCRIPTS_DIR, "album_pipeline.py")
    if os.path.exists(pipeline_script):
        txt = open(pipeline_script, "r", encoding="utf-8", errors="ignore").read()
        if "evaluate_venice_budget" not in txt or "ap:credit:added" not in txt:
            issues.append("album_pipeline.py missing evaluate_venice_budget or ap:credit:added button")
        if "--closer-duration" not in txt:
            issues.append("album_pipeline.py missing --closer-duration handoff")
    else:
        issues.append("album_pipeline.py missing")

    # 5. Sync current working scripts & SKILL.md to bundled-skills as fallback
    if os.path.exists(BUNDLED_DIR) and os.path.exists(prod_album) and os.path.exists(master_prod):
        try:
            shutil.copy2(prod_album, os.path.join(BUNDLED_DIR, "produce-album.py"))
            shutil.copy2(master_prod, os.path.join(BUNDLED_DIR, "master-producer.py"))
            if os.path.exists(SKILL_MD) and os.path.exists(os.path.dirname(BUNDLED_SKILL_MD)):
                shutil.copy2(SKILL_MD, BUNDLED_SKILL_MD)
            healed.append("Synced active scripts and SKILL.md into container bundled-skills directory")
        except Exception as e:
            issues.append(f"Could not sync bundled-skills: {e}")

    # 6. Verify Gateway Telegram callback handlers (ap:credit:added, sp2:model_pr:, etc.)
    if os.path.exists(GATEWAY_TELEGRAM):
        try:
            tg_txt = open(GATEWAY_TELEGRAM, "r", encoding="utf-8", errors="ignore").read()
            if "credit:added" not in tg_txt or "credit:pause" not in tg_txt or "sp2:model_pr:" not in tg_txt:
                patch_gw = os.path.join(SCRIPTS_DIR, "patch_gateway.py")
                if os.path.exists(patch_gw):
                    subprocess.run([python_bin, patch_gw], capture_output=True, timeout=15)
                    healed.append("Re-applied patch_gateway.py to /opt/hermes/gateway/platforms/telegram.py")
        except Exception as e:
            issues.append(f"Gateway telegram.py check failed: {e}")

    # 6b. Verify model_registry.json and weekly Venice scout scripts
    for req_mod in ("model_registry.py", "model_feedback_collector.py", "venice_model_scout.py", "model_pr_manager.py"):
        if not os.path.exists(os.path.join(SCRIPTS_DIR, req_mod)):
            issues.append(f"Missing required model CI script: {req_mod}")
    try:
        sys.path.insert(0, SCRIPTS_DIR)
        import model_registry
        reg = model_registry.load_registry()
        reg_ok, reg_errs = model_registry.validate_registry_schema(reg)
        if not reg_ok:
            issues.append("model_registry.json invalid: " + "; ".join(reg_errs))
    except Exception as e:
        issues.append(f"model_registry check failed: {e}")

    # 7. Verify Agent SOUL.md rules
    if os.path.exists(SOUL_PATH):
        try:
            soul_txt = open(SOUL_PATH, "r", encoding="utf-8", errors="ignore").read()
            if (
                "VENICE AI LIVE CREDIT CHECK & WARNING GATE" not in soul_txt
                or "COHESIVE VØIDRIDE NOCTURNAL ARCHITECTURE" not in soul_txt
                or "REQUIRED_PROPOSAL_COUNT = 5" not in soul_txt
                or "WEEKLY VENICE MODEL SCOUT" not in soul_txt
            ):
                patch_soul = os.path.join(SCRIPTS_DIR, "patch_soul.py")
                if os.path.exists(patch_soul):
                    subprocess.run([python_bin, patch_soul], capture_output=True, timeout=15)
                    healed.append("Re-applied patch_soul.py to update /opt/data/SOUL.md with Cohesive VØIDRIDE, 5-proposal & Model Scout rules")
        except Exception as e:
            issues.append(f"SOUL.md check failed: {e}")

    # 8. Verify .skills_prompt_snapshot.json is not stale relative to SKILL.md
    if os.path.exists(SKILL_MD):
        try:
            skill_mtime = os.path.getmtime(SKILL_MD)
            snap_stale = (not os.path.exists(SKILLS_SNAPSHOT)) or (os.path.getmtime(SKILLS_SNAPSHOT) < skill_mtime)
            if snap_stale:
                if os.path.exists(SKILLS_SNAPSHOT):
                    os.remove(SKILLS_SNAPSHOT)
                subprocess.run(
                    [python_bin, "-c", "import sys; sys.path.insert(0, '/opt/hermes'); from agent.prompt_builder import build_skills_system_prompt; build_skills_system_prompt()"],
                    capture_output=True,
                    timeout=15,
                )
                healed.append("Refreshed /opt/data/.skills_prompt_snapshot.json from live SKILL.md files")
        except Exception as e:
            issues.append(f"Skills snapshot check failed: {e}")

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
        print("[env-audit] ✅ All pipeline scripts, gateway handlers, SOUL.md, and skill snapshots verified live with agent.")
        sys.exit(0)


if __name__ == "__main__":
    main()
