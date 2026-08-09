#!/usr/bin/env python3
"""
handoff.py — Bridge between songprocessor and DAWAGENT.
Writes/reads job manifests on the shared volume so one agent
can hand off work to the other with full context.

Shared volume: /opt/data/dawagent/sessions/SESSION_NAME/

Usage:
  # Songprocessor writes a job after generating:
  python3 handoff.py write \
    --session "VOIDRIDE_Samples" \
    --bpm 140 \
    --stems "/path/to/stem1.mp3,/path/to/stem2.mp3" \
    --stem-names "Kick,Snare" \
    --plan "Kick: Calf EQ + LSP Compressor | Snare: Calf EQ + Dragonfly Room" \
    --source "songprocessor" \
    --notes "10 VOIDRIDE samples at 140 BPM, dark industrial style"

  # DAWAGENT reads the job:
  python3 handoff.py read --session "VOIDRIDE_Samples"

  # List all pending jobs:
  python3 handoff.py list

  # DAWAGENT marks job as processed:
  python3 handoff.py done --session "VOIDRIDE_Samples"
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path(os.environ.get("DAWAGENT_SESSIONS", "/opt/data/dawagent/sessions"))
EXPORTS_DIR = Path(os.environ.get("DAWAGENT_EXPORTS", "/opt/data/dawagent/exports"))
MANIFEST_NAME = "handoff.json"


def cmd_write(args):
    """Write a handoff manifest and copy stems to the session directory."""
    session_dir = SESSIONS_DIR / args.session / "interchange"
    session_dir.mkdir(parents=True, exist_ok=True)

    stems = [s.strip() for s in args.stems.split(",") if s.strip()]
    stem_names = [s.strip() for s in args.stem_names.split(",")] if args.stem_names else []

    # Copy stems to the interchange directory
    copied = []
    for i, stem_path in enumerate(stems):
        src = Path(stem_path)
        if not src.exists():
            print(json.dumps({"success": False, "error": f"Stem not found: {stem_path}"}))
            sys.exit(1)
        name = stem_names[i] if i < len(stem_names) else src.stem
        ext = src.suffix or ".mp3"
        dest = session_dir / f"{name}{ext}"
        shutil.copy2(str(src), str(dest))
        copied.append({
            "name": name,
            "file": str(dest),
            "original": str(src),
            "type": "audio"
        })

    # Parse processing plan
    plan = {}
    if args.plan:
        for entry in args.plan.split("|"):
            entry = entry.strip()
            if ":" in entry:
                stem_name, chain = entry.split(":", 1)
                plan[stem_name.strip()] = [p.strip() for p in chain.split("+")]

    manifest = {
        "session": args.session,
        "bpm": int(args.bpm) if args.bpm else 120,
        "source": args.source or "songprocessor",
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "stems": copied,
        "processing_plan": plan,
        "notes": args.notes or "",
        "stem_count": len(copied),
    }

    manifest_path = SESSIONS_DIR / args.session / MANIFEST_NAME
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(json.dumps({
        "success": True,
        "session": args.session,
        "manifest": str(manifest_path),
        "stems_copied": len(copied),
        "interchange_dir": str(session_dir),
        "message": f"Handoff ready: {len(copied)} stems copied to {session_dir}"
    }, indent=2))


def cmd_read(args):
    """Read a handoff manifest."""
    manifest_path = SESSIONS_DIR / args.session / MANIFEST_NAME
    if not manifest_path.exists():
        print(json.dumps({"success": False, "error": f"No handoff found for session '{args.session}'"}))
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    print(json.dumps(manifest, indent=2))


def cmd_list(args):
    """List all sessions with pending handoffs."""
    if not SESSIONS_DIR.exists():
        print(json.dumps({"success": True, "jobs": []}))
        return

    jobs = []
    for session_dir in sorted(SESSIONS_DIR.iterdir()):
        manifest_path = session_dir / MANIFEST_NAME
        if manifest_path.exists():
            with open(manifest_path) as f:
                data = json.load(f)
            jobs.append({
                "session": data.get("session", session_dir.name),
                "status": data.get("status", "unknown"),
                "stems": data.get("stem_count", 0),
                "source": data.get("source", "?"),
                "bpm": data.get("bpm", "?"),
                "created_at": data.get("created_at", "?"),
                "notes": data.get("notes", "")[:80],
            })

    print(json.dumps({"success": True, "jobs": jobs}, indent=2))


def cmd_done(args):
    """Mark a handoff as processed."""
    manifest_path = SESSIONS_DIR / args.session / MANIFEST_NAME
    if not manifest_path.exists():
        print(json.dumps({"success": False, "error": f"No handoff found for session '{args.session}'"}))
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    manifest["status"] = "processed"
    manifest["processed_at"] = datetime.now().isoformat()

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(json.dumps({"success": True, "session": args.session, "status": "processed"}))


def main():
    parser = argparse.ArgumentParser(description="Agent handoff bridge")
    sub = parser.add_subparsers(dest="command")

    # write
    w = sub.add_parser("write", help="Write a handoff manifest")
    w.add_argument("--session", required=True)
    w.add_argument("--bpm", default="120")
    w.add_argument("--stems", required=True, help="Comma-separated file paths")
    w.add_argument("--stem-names", default="", help="Comma-separated stem names")
    w.add_argument("--plan", default="", help="Processing plan: 'Kick: Calf EQ + LSP Comp | Snare: ...'")
    w.add_argument("--source", default="songprocessor")
    w.add_argument("--notes", default="")

    # read
    r = sub.add_parser("read", help="Read a handoff manifest")
    r.add_argument("--session", required=True)

    # list
    sub.add_parser("list", help="List pending handoffs")

    # done
    d = sub.add_parser("done", help="Mark handoff as processed")
    d.add_argument("--session", required=True)

    args = parser.parse_args()
    if args.command == "write":
        cmd_write(args)
    elif args.command == "read":
        cmd_read(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "done":
        cmd_done(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
