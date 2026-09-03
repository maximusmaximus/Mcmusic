#!/usr/bin/env python3
import argparse
import json
import sys
import os
import subprocess
import tempfile
from pathlib import Path
from osc_bridge import ArdourOSCClient
from session_manager import SessionManager

LUA_DIR = "/opt/dawagent/lua"

def run_ardour_headless(session_path, lua_script_path, *args):
    # ardour8-lua executes headless, we pass session path as an argument to the script
    cmd = ["ardour8-lua", lua_script_path, session_path]
    cmd.extend(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=os.environ, timeout=60)
        if result.returncode != 0:
            return {"success": False, "error": result.stderr}
        return {"success": True, "output": result.stdout}
    except Exception as e:
        return {"success": False, "error": str(e)}

def output(data):
    print(json.dumps(data, indent=2))
    sys.exit(0 if data.get("success", True) else 1)

def main():
    parser = argparse.ArgumentParser(description="DAWAGENT Control CLI")
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
    
    # track
    parser_track = subparsers.add_parser("track")
    track_subs = parser_track.add_subparsers(dest="track_cmd")
    t_add = track_subs.add_parser("add")
    t_add.add_argument("--session", required=True)
    t_add.add_argument("--name", required=True)
    t_add.add_argument("--type", choices=["audio", "midi"], required=True)
    
    t_list = track_subs.add_parser("list")
    t_list.add_argument("--session", required=True)

    # export
    parser_export = subparsers.add_parser("export")
    export_subs = parser_export.add_subparsers(dest="export_cmd")
    e_all = export_subs.add_parser("all")
    e_all.add_argument("--session", required=True)
    e_all.add_argument("--output-dir", required=True)

    # lua
    parser_lua = subparsers.add_parser("lua")
    parser_lua.add_argument("--session", required=True)
    parser_lua.add_argument("--script", required=True)
    parser_lua.add_argument("--args", nargs="*", default=[])

    args = parser.parse_args()
    sm = SessionManager()

    if args.command == "status":
        jack = subprocess.run(["pgrep", "-x", "jackd"], capture_output=True)
        ardour = subprocess.run(["pgrep", "-x", "ardour8"], capture_output=True)
        output({
            "success": True,
            "jack_running": jack.returncode == 0,
            "ardour_running": ardour.returncode == 0,
            "sessions": sm.list_sessions()
        })
        
    elif args.command == "health":
        output({"success": True, "status": "healthy", "message": "DAWAGENT is operational"})

    elif args.command == "session":
        if args.session_cmd == "create":
            try:
                path = sm.create_session(args.name, args.sr, args.bpm)
                output({"success": True, "session_path": path})
            except Exception as e:
                output({"success": False, "error": str(e)})
        elif args.session_cmd == "list":
            output({"success": True, "sessions": sm.list_sessions()})

    elif args.command == "track":
        if args.track_cmd == "add":
            try:
                tid = sm.add_track_offline(args.session, args.name, args.type)
                output({"success": True, "track_id": tid})
            except Exception as e:
                output({"success": False, "error": str(e)})
        elif args.track_cmd == "list":
            output({"success": True, "tracks": sm.list_tracks(args.session)})

    elif args.command == "lua":
        session_path = sm._get_session_path(args.session)
        if not os.path.exists(session_path):
            output({"success": False, "error": f"Session not found: {session_path}"})
        
        script_path = args.script
        if not script_path.startswith("/"):
            script_path = os.path.join(LUA_DIR, script_path)
            if not script_path.endswith(".lua"):
                script_path += ".lua"
                
        res = run_ardour_headless(session_path, script_path, *args.args)
        output(res)
        
    elif args.command == "export":
        if args.export_cmd == "all":
            session_dir = Path(sm._sessions_dir) / args.session
            interchange = session_dir / "interchange"
            if not interchange.exists():
                output({"success": False, "error": f"No interchange directory for session '{args.session}'"})

            stems = sorted(list(interchange.glob("*.wav")) + list(interchange.glob("*.mp3"))
                          + list(interchange.glob("*.flac")) + list(interchange.glob("*.ogg")))
            if not stems:
                output({"success": False, "error": "No stems found in interchange"})

            out_dir = Path(args.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            flac_out = out_dir / f"{args.session}_MASTER.flac"

            # Build ffmpeg mix command
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            for s in stems:
                cmd.extend(["-i", str(s)])

            n = len(stems)
            filters = []
            for i in range(n):
                filters.append(f"[{i}:a]volume=1.0[s{i}]")
            mix_inputs = "".join(f"[s{i}]" for i in range(n))
            filters.append(f"{mix_inputs}amix=inputs={n}:duration=longest:dropout_transition=3,"
                          f"loudnorm=I=-14:TP=-1:LRA=11[out]")
            cmd.extend(["-filter_complex", ";".join(filters), "-map", "[out]",
                       "-ar", "48000", "-sample_fmt", "s32", str(flac_out)])

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if result.returncode != 0:
                    output({"success": False, "error": result.stderr[-200:]})
                output({"success": True, "output": str(flac_out),
                        "size_mb": round(flac_out.stat().st_size / (1024*1024), 1)})
            except Exception as e:
                output({"success": False, "error": str(e)})
        else:
            output({"success": False, "error": "Unknown export subcommand"})

    else:
        parser.print_help()
        output({"success": False, "error": "Invalid command"})

if __name__ == "__main__":
    main()
