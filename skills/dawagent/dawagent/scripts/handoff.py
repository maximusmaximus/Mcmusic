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


def load_production_context(metadata_file=None, production_dir=None):
    """Load enriched production context from metadata/plan files.

    Reads production_metadata.json and production_plan.json to extract
    structured fields that the DAW processor needs: key, genre, mastering
    profile, per-stem volumes/sources, vocal presence, and mix file path.

    Args:
        metadata_file: Explicit path to production_metadata.json
        production_dir: Directory containing both metadata and plan files

    Returns:
        dict with enriched fields, or empty dict if files not found
    """
    context = {}
    meta = {}
    plan = {}

    # Load production_metadata.json
    meta_path = None
    if metadata_file and Path(metadata_file).exists():
        meta_path = Path(metadata_file)
    elif production_dir:
        candidate = Path(production_dir) / "production_metadata.json"
        if candidate.exists():
            meta_path = candidate

    if meta_path:
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Load production_plan.json
    plan_path = None
    if production_dir:
        candidate = Path(production_dir) / "production_plan.json"
        if candidate.exists():
            plan_path = candidate
    elif meta_path:
        candidate = meta_path.parent / "production_plan.json"
        if candidate.exists():
            plan_path = candidate

    if plan_path:
        try:
            with open(plan_path) as f:
                plan = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Extract key & genre from production plan
    if plan.get("key"):
        context["key"] = plan["key"]
    if plan.get("genre"):
        context["genre"] = plan["genre"]
    if plan.get("bpm"):
        context["bpm"] = plan["bpm"]

    # Extract mastering profile from metadata
    mastering = meta.get("mastering_profile")
    if mastering:
        context["mastering_profile"] = {
            "lufs": mastering.get("lufs", -14),
            "true_peak": mastering.get("true_peak", -1),
            "lra": mastering.get("lra", 11),
            "compression": mastering.get("compression", {}),
            "eq_bands": mastering.get("eq_bands", []),
            "stereo": mastering.get("stereo", {}),
        }

    # Extract per-stem volumes and sources from composition data
    composition = meta.get("composition", {})
    stems_meta = composition.get("stems", [])
    if stems_meta:
        volumes = {}
        sources = {}
        for stem in stems_meta:
            role = stem.get("role", "")
            if stem.get("mix_volume") is not None:
                volumes[role] = stem["mix_volume"]
            model = stem.get("model", "")
            if model:
                sources[role] = model
        if volumes:
            context["stem_volumes"] = volumes
        if sources:
            context["stem_sources"] = sources

    # Vocal presence from DJ profile or composition
    dj_profile = meta.get("dj_profile", {})
    if "has_vocals" in dj_profile:
        context["has_vocals"] = dj_profile["has_vocals"]

    # Mix file path (for direct mastering instead of amix re-mix)
    outputs = meta.get("outputs", {})
    if outputs.get("primary_file"):
        session_dir = meta.get("session_dir", "")
        mix_file = os.path.join(session_dir, outputs["primary_file"])
        if os.path.exists(mix_file):
            context["mix_file"] = mix_file

    return context


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

    # Load enriched production context from metadata files
    context = load_production_context(
        metadata_file=getattr(args, "metadata_file", None),
        production_dir=getattr(args, "production_dir", None),
    )

    # CLI overrides take priority over metadata-derived values
    bpm = int(args.bpm) if args.bpm else context.get("bpm", 120)

    manifest = {
        "session": args.session,
        "bpm": bpm,
        "source": args.source or "songprocessor",
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "stems": copied,
        "processing_plan": plan,
        "notes": args.notes or "",
        "stem_count": len(copied),
        "album": getattr(args, "album", "") or "",
        "profile": getattr(args, "profile", "") or "",
    }

    # Merge enriched production context into manifest
    if context.get("key"):
        manifest["key"] = context["key"]
    if context.get("genre"):
        manifest["genre"] = context["genre"]
    if context.get("mastering_profile"):
        manifest["mastering_profile"] = context["mastering_profile"]
    if context.get("stem_volumes"):
        manifest["stem_volumes"] = context["stem_volumes"]
    if context.get("stem_sources"):
        manifest["stem_sources"] = context["stem_sources"]
    if "has_vocals" in context:
        manifest["has_vocals"] = context["has_vocals"]

    # Copy hermes-music mix file to interchange for direct mastering
    mix_file = context.get("mix_file")
    if mix_file and os.path.exists(mix_file):
        mix_dest = session_dir / Path(mix_file).name
        shutil.copy2(mix_file, str(mix_dest))
        manifest["mix_file"] = str(mix_dest)

    manifest_path = SESSIONS_DIR / args.session / MANIFEST_NAME
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    enriched_fields = [k for k in ("key", "genre", "mastering_profile",
                                    "stem_volumes", "stem_sources",
                                    "has_vocals", "mix_file") if k in manifest]

    print(json.dumps({
        "success": True,
        "session": args.session,
        "manifest": str(manifest_path),
        "stems_copied": len(copied),
        "interchange_dir": str(session_dir),
        "enriched_fields": enriched_fields,
        "message": f"Handoff ready: {len(copied)} stems, {len(enriched_fields)} enriched fields"
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
                "key": data.get("key", ""),
                "genre": data.get("genre", ""),
                "has_context": bool(data.get("mastering_profile")),
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
    w.add_argument("--album", default="", help="Album name for metadata tagging")
    w.add_argument("--profile", default="", help="Artist profile name for metadata tagging")
    w.add_argument("--metadata-file", default=None,
                   help="Path to production_metadata.json for enriched handoff context")
    w.add_argument("--production-dir", default=None,
                   help="Production session directory containing metadata and plan files")

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
