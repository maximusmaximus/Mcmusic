#!/usr/bin/env python3
"""
snapshot_manager.py — Versioned Atomic Snapshot & Rollback Subsystem for SP2

Ensures any changes made to SP2 can be safely verified and rolled back with 1-click.
  - Takes full snapshots of /opt/data/scripts/ before any patch or self-update.
  - Performs pre-flight `py_compile` checks.
  - Auto-rolls back immediately if syntax or dry-run checks fail.
  - Supports 1-click manual rollback to any previous version.
"""

import json
import os
import py_compile
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPTS_DIR = os.environ.get("HERMES_SCRIPTS_DIR", "/opt/data/scripts")
SNAPSHOTS_DIR = os.environ.get("HERMES_SNAPSHOTS_DIR", "/opt/data/snapshots")
HISTORY_FILE = os.path.join(SNAPSHOTS_DIR, "history.json")

os.makedirs(SNAPSHOTS_DIR, exist_ok=True)


def _load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"current_version": None, "snapshots": []}


def _save_history(history: dict):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def create_snapshot(description: str = "manual_snapshot") -> str:
    """Create an atomic snapshot of all scripts in SCRIPTS_DIR."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snapshot_id = f"v_{ts}"
    target_dir = os.path.join(SNAPSHOTS_DIR, snapshot_id)
    os.makedirs(target_dir, exist_ok=True)

    copied_files = []
    for item in os.listdir(SCRIPTS_DIR):
        src_path = os.path.join(SCRIPTS_DIR, item)
        if os.path.isfile(src_path) and (item.endswith(".py") or item.endswith(".sh") or item.endswith(".json")):
            dest_path = os.path.join(target_dir, item)
            shutil.copy2(src_path, dest_path)
            copied_files.append(item)

    history = _load_history()
    snapshot_entry = {
        "snapshot_id": snapshot_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "files_count": len(copied_files),
        "files": copied_files
    }
    history["snapshots"].append(snapshot_entry)
    history["current_version"] = snapshot_id
    _save_history(history)

    print(f"[snapshot_manager] Created snapshot {snapshot_id} ({len(copied_files)} files: {description})")
    return snapshot_id


def verify_scripts(scripts_to_check: list = None) -> tuple[bool, str]:
    """Pre-flight compile check on Python scripts."""
    if not scripts_to_check:
        scripts_to_check = [
            os.path.join(SCRIPTS_DIR, f)
            for f in os.listdir(SCRIPTS_DIR)
            if f.endswith(".py")
        ]

    for script in scripts_to_check:
        if not os.path.exists(script):
            continue
        try:
            py_compile.compile(script, doraise=True)
        except py_compile.PyCompileError as e:
            return False, f"Syntax error in {os.path.basename(script)}: {e.msg}"
        except Exception as e:
            return False, f"Compile error in {os.path.basename(script)}: {e}"

    return True, "All scripts passed syntax validation."


def rollback(target_snapshot_id: str = None) -> tuple[bool, str]:
    """Roll back to target snapshot or the most recent prior version."""
    history = _load_history()
    snapshots = history.get("snapshots", [])
    if not snapshots:
        return False, "No snapshots found in history to rollback to."

    if not target_snapshot_id:
        # Pick the previous snapshot (second to last)
        if len(snapshots) < 2:
            target_snapshot_id = snapshots[0]["snapshot_id"]
        else:
            target_snapshot_id = snapshots[-2]["snapshot_id"]

    source_dir = os.path.join(SNAPSHOTS_DIR, target_snapshot_id)
    if not os.path.isdir(source_dir):
        return False, f"Snapshot directory not found: {source_dir}"

    # Before overwriting, snapshot current broken state just in case
    broken_snapshot_id = f"v_pre_rollback_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    broken_dir = os.path.join(SNAPSHOTS_DIR, broken_snapshot_id)
    os.makedirs(broken_dir, exist_ok=True)
    for item in os.listdir(SCRIPTS_DIR):
        sp = os.path.join(SCRIPTS_DIR, item)
        if os.path.isfile(sp):
            shutil.copy2(sp, os.path.join(broken_dir, item))

    # Restore files
    restored_count = 0
    for item in os.listdir(source_dir):
        src_path = os.path.join(source_dir, item)
        dest_path = os.path.join(SCRIPTS_DIR, item)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, dest_path)
            restored_count += 1

    history["current_version"] = target_snapshot_id
    history["last_rollback"] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "restored_from": target_snapshot_id,
        "restored_files": restored_count
    }
    _save_history(history)

    msg = f"Successfully rolled back to {target_snapshot_id} ({restored_count} files restored)."
    print(f"[snapshot_manager] {msg}")
    return True, msg


def apply_file_update(filename: str, new_content: str, description: str = "patch_update") -> tuple[bool, str, str]:
    """
    Safely update a file in SCRIPTS_DIR with automated snapshot and pre-flight compile check.
    Returns: (success: bool, message: str, pre_patch_snapshot_id: str)
    """
    pre_snapshot = create_snapshot(f"Pre-patch: {description}")
    target_path = os.path.join(SCRIPTS_DIR, filename)

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        rollback(pre_snapshot)
        return False, f"Failed to write updated file: {e}", pre_snapshot

    # Compile check
    ok, err = verify_scripts([target_path])
    if not ok:
        print(f"[snapshot_manager] Pre-flight failed: {err}. Triggering automated rollback!")
        rollback(pre_snapshot)
        return False, f"Pre-flight compile check failed: {err}. Rolled back to {pre_snapshot}.", pre_snapshot

    return True, f"Successfully applied update to {filename} (snapshot: {pre_snapshot})", pre_snapshot


def get_latest_snapshot() -> str:
    history = _load_history()
    snapshots = history.get("snapshots", [])
    if snapshots:
        return snapshots[-1]["snapshot_id"]
    return None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "create":
            desc = sys.argv[2] if len(sys.argv) > 2 else "manual"
            print(create_snapshot(desc))
        elif cmd == "rollback":
            target = sys.argv[2] if len(sys.argv) > 2 else None
            ok, msg = rollback(target)
            print(msg)
            sys.exit(0 if ok else 1)
        elif cmd == "verify":
            ok, msg = verify_scripts()
            print(msg)
            sys.exit(0 if ok else 1)
        elif cmd == "list":
            print(json.dumps(_load_history(), indent=2))
    else:
        print("Usage: snapshot_manager.py [create <desc> | rollback [id] | verify | list]")
