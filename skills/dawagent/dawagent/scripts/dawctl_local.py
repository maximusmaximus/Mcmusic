#!/usr/bin/env python3
"""
dawctl_local.py — Local DAWAGENT controller for hermes-music.
Operates directly on shared volumes (no podman exec needed).
Manages Ardour sessions via XML manipulation on the shared filesystem.
"""
import argparse
import json
import sys
import os

# Add the skill scripts dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from session_manager import SessionManager

SESSIONS_DIR = os.environ.get("DAWAGENT_SESSIONS", "/opt/data/dawagent/sessions")
EXPORTS_DIR = os.environ.get("DAWAGENT_EXPORTS", "/opt/data/dawagent/exports")

def output(data):
    print(json.dumps(data, indent=2))
    sys.exit(0 if data.get("success", True) else 1)

def main():
    parser = argparse.ArgumentParser(description="DAWAGENT Local Control (shared volume)")
    subparsers = parser.add_subparsers(dest="command")

    # status
    subparsers.add_parser("status")

    # health
    subparsers.add_parser("health")

    # session
    parser_session = subparsers.add_parser("session")
    session_subs = parser_session.add_subparsers(dest="session_cmd")

    s_create = session_subs.add_parser("create")
    s_create.add_argument("--name", required=True)
    s_create.add_argument("--sr", type=int, default=48000)
    s_create.add_argument("--bpm", type=int, default=120)

    session_subs.add_parser("list")

    s_info = session_subs.add_parser("info")
    s_info.add_argument("--name", required=True)

    # track
    parser_track = subparsers.add_parser("track")
    track_subs = parser_track.add_subparsers(dest="track_cmd")
    t_add = track_subs.add_parser("add")
    t_add.add_argument("--session", required=True)
    t_add.add_argument("--name", required=True)
    t_add.add_argument("--type", choices=["audio", "midi"], required=True)

    t_list = track_subs.add_parser("list")
    t_list.add_argument("--session", required=True)

    # export list
    parser_exports = subparsers.add_parser("exports")
    exports_subs = parser_exports.add_subparsers(dest="exports_cmd")
    exports_subs.add_parser("list")

    args = parser.parse_args()
    sm = SessionManager(sessions_dir=SESSIONS_DIR)

    if args.command == "status":
        sessions = sm.list_sessions()
        # Check for exports
        exports = []
        if os.path.exists(EXPORTS_DIR):
            for d in os.listdir(EXPORTS_DIR):
                full = os.path.join(EXPORTS_DIR, d)
                if os.path.isdir(full):
                    files = os.listdir(full)
                    exports.append({"name": d, "files": files})
        output({
            "success": True,
            "sessions_dir": SESSIONS_DIR,
            "exports_dir": EXPORTS_DIR,
            "sessions": sessions,
            "exports": exports
        })

    elif args.command == "health":
        sessions_ok = os.path.exists(SESSIONS_DIR)
        exports_ok = os.path.exists(EXPORTS_DIR)
        output({
            "success": sessions_ok,
            "sessions_volume_mounted": sessions_ok,
            "exports_volume_mounted": exports_ok,
            "message": "DAWAGENT shared volumes accessible" if (sessions_ok and exports_ok) else "WARNING: shared volumes not mounted"
        })

    elif args.command == "session":
        if args.session_cmd == "create":
            try:
                path = sm.create_session(args.name, args.sr, args.bpm)
                output({"success": True, "session_path": path, "name": args.name, "sample_rate": args.sr, "bpm": args.bpm})
            except Exception as e:
                output({"success": False, "error": str(e)})
        elif args.session_cmd == "list":
            output({"success": True, "sessions": sm.list_sessions()})
        elif args.session_cmd == "info":
            tracks = sm.list_tracks(args.name)
            output({"success": True, "name": args.name, "tracks": tracks})

    elif args.command == "track":
        if args.track_cmd == "add":
            try:
                tid = sm.add_track_offline(args.session, args.name, args.type)
                output({"success": True, "track_id": tid, "name": args.name, "type": args.type})
            except Exception as e:
                output({"success": False, "error": str(e)})
        elif args.track_cmd == "list":
            output({"success": True, "tracks": sm.list_tracks(args.session)})

    elif args.command == "exports":
        if not os.path.exists(EXPORTS_DIR):
            output({"success": True, "exports": []})
        else:
            exports = []
            for d in os.listdir(EXPORTS_DIR):
                full = os.path.join(EXPORTS_DIR, d)
                if os.path.isdir(full):
                    files = [f for f in os.listdir(full) if not f.startswith('.')]
                    exports.append({"session": d, "files": files})
            output({"success": True, "exports": exports})

    else:
        parser.print_help()
        output({"success": False, "error": "Use: dawctl_local.py {status|health|session|track|exports}"})

if __name__ == "__main__":
    main()
