#!/usr/bin/env python3
"""
gen_receipt.py — Generate a production receipt from an Ardour session.
Reads the session XML, extracts tracks/plugins/automation, and produces
a detailed human-readable report of how the song was made.
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

SESSIONS_DIR = os.environ.get("DAWAGENT_SESSIONS", "/opt/data/dawagent/sessions")
EXPORTS_DIR = os.environ.get("DAWAGENT_EXPORTS", "/opt/data/dawagent/exports")

# Common LV2 plugin URI → friendly name mapping
PLUGIN_NAMES = {
    "http://calf.sourceforge.net/plugins/Equalizer5Band": "Calf 5-Band EQ",
    "http://calf.sourceforge.net/plugins/Equalizer8Band": "Calf 8-Band EQ",
    "http://calf.sourceforge.net/plugins/Compressor": "Calf Compressor",
    "http://calf.sourceforge.net/plugins/Limiter": "Calf Limiter",
    "http://calf.sourceforge.net/plugins/Reverb": "Calf Reverb",
    "http://calf.sourceforge.net/plugins/VintageDelay": "Calf Vintage Delay",
    "http://calf.sourceforge.net/plugins/Phaser": "Calf Phaser",
    "http://calf.sourceforge.net/plugins/Flanger": "Calf Flanger",
    "http://calf.sourceforge.net/plugins/Saturator": "Calf Saturator",
    "http://calf.sourceforge.net/plugins/BassEnhancer": "Calf Bass Enhancer",
    "http://calf.sourceforge.net/plugins/StereoTools": "Calf Stereo Tools",
    "http://lsp-plug.in/plugins/lv2/para_equalizer_x16_stereo": "LSP Para EQ x16",
    "http://lsp-plug.in/plugins/lv2/compressor_stereo": "LSP Compressor",
    "http://lsp-plug.in/plugins/lv2/gate_stereo": "LSP Gate",
    "http://lsp-plug.in/plugins/lv2/limiter_stereo": "LSP Limiter",
    "http://lsp-plug.in/plugins/lv2/delay_compensator_stereo": "LSP Delay Comp",
    "urn:ardour:a-eq": "Ardour a-EQ",
    "urn:ardour:a-comp": "Ardour a-Comp",
    "urn:ardour:a-delay": "Ardour a-Delay",
    "urn:ardour:a-reverb": "Ardour a-Reverb",
    "urn:ardour:a-exp": "Ardour a-Expander",
    "http://gareus.org/oss/lv2/fil4": "x42 EQ",
    "http://gareus.org/oss/lv2/meters": "x42 Meters",
    "http://gareus.org/oss/lv2/dpl": "x42 Limiter",
    "https://github.com/michaelwillis/dragonfly-reverb": "Dragonfly Reverb",
}


def friendly_plugin_name(uri):
    """Convert LV2 URI to a friendly name."""
    if uri in PLUGIN_NAMES:
        return PLUGIN_NAMES[uri]
    # Try to extract a reasonable name from the URI
    name = uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    return name.replace("_", " ").replace("-", " ").title()


def parse_session(session_name):
    """Parse an Ardour session XML and extract production data."""
    session_path = os.path.join(SESSIONS_DIR, session_name, f"{session_name}.ardour")
    if not os.path.exists(session_path):
        return None

    tree = ET.parse(session_path)
    root = tree.getroot()

    session_data = {
        "name": root.get("name", session_name),
        "sample_rate": root.get("sample-rate", "48000"),
        "id": root.get("id", "?"),
        "version": root.get("version", "?"),
        "bpm": "120",
        "tracks": [],
        "plugins_used": set(),
        "total_regions": 0,
        "has_automation": False,
    }

    # Extract tempo
    tempo_map = root.find(".//TempoMap")
    if tempo_map is not None:
        tempo = tempo_map.find(".//Tempo")
        if tempo is not None:
            session_data["bpm"] = tempo.get("beats-per-minute", "120")

    # Extract routes (tracks)
    for route in root.findall(".//Route"):
        track_name = route.get("name", "Unknown")
        track_id = route.get("id", "?")
        is_master = route.get("flags", "").find("MasterOut") >= 0 or track_name == "Master"

        # Determine track type
        track_type = "audio"
        if route.find(".//MidiTrack") is not None:
            track_type = "midi"
        # Check for MIDI diskstream
        ds = route.find(".//Diskstream")
        if ds is not None and ds.get("type", "") == "midi":
            track_type = "midi"

        # Extract plugins
        plugins = []
        for proc in route.findall(".//Processor"):
            proc_type = proc.get("type", "")
            if proc_type in ("lv2", "ladspa", "vst", "clap"):
                plugin_uri = proc.get("unique-id", proc.get("uri", "unknown"))
                plugin_name = friendly_plugin_name(plugin_uri)
                active = proc.get("active", "yes") == "yes"
                plugins.append({
                    "name": plugin_name,
                    "uri": plugin_uri,
                    "active": active,
                    "type": proc_type,
                })
                session_data["plugins_used"].add(plugin_name)

        # Extract gain/pan
        gain = "0"
        pan = "center"
        amp = route.find(".//Amp")
        if amp is not None:
            gain_val = amp.get("gain", "1.0")
            try:
                gain_db = 20 * __import__("math").log10(float(gain_val)) if float(gain_val) > 0 else -96
                gain = f"{gain_db:.1f}"
            except (ValueError, ZeroDivisionError):
                gain = "0"

        panner = route.find(".//Panner")
        if panner is not None:
            pan_val = panner.get("position", "0.5")
            try:
                p = float(pan_val)
                if p < 0.4:
                    pan = f"L{int((0.5 - p) * 200)}%"
                elif p > 0.6:
                    pan = f"R{int((p - 0.5) * 200)}%"
                else:
                    pan = "center"
            except ValueError:
                pan = "center"

        # Count regions
        region_count = len(route.findall(".//Region"))
        session_data["total_regions"] += region_count

        # Check for automation
        auto_lists = route.findall(".//AutomationList")
        has_auto = any(len(al.findall(".//AutomationEvent")) > 0 for al in auto_lists)
        if has_auto:
            session_data["has_automation"] = True

        session_data["tracks"].append({
            "name": track_name,
            "id": track_id,
            "type": track_type,
            "is_master": is_master,
            "plugins": plugins,
            "gain_db": gain,
            "pan": pan,
            "regions": region_count,
            "has_automation": has_auto,
        })

    session_data["plugins_used"] = sorted(session_data["plugins_used"])
    return session_data


def check_exports(session_name):
    """Check what exports exist for this session."""
    export_dir = os.path.join(EXPORTS_DIR, session_name)
    if not os.path.exists(export_dir):
        return {"exists": False, "files": []}

    files = []
    for f in sorted(os.listdir(export_dir)):
        if f.startswith("."):
            continue
        full = os.path.join(export_dir, f)
        size = os.path.getsize(full)
        files.append({
            "name": f,
            "size_mb": round(size / (1024 * 1024), 2),
            "type": os.path.splitext(f)[1].lstrip(".").upper() or "unknown",
        })
    return {"exists": True, "files": files, "dir": export_dir}


def generate_receipt_text(session_data, exports, notes=""):
    """Generate a human-readable production receipt."""
    lines = []
    lines.append(f"🎛️ PRODUCTION RECEIPT — {session_data['name']}")
    lines.append("═" * 45)
    lines.append("")
    lines.append(f"📋 Session: {session_data['name']}")
    lines.append(f"🎵 BPM: {session_data['bpm']} | Sample Rate: {session_data['sample_rate']} Hz")
    lines.append(f"📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"🎚️ Tracks: {len([t for t in session_data['tracks'] if not t['is_master']])}")
    lines.append(f"📦 Regions: {session_data['total_regions']}")
    lines.append(f"🔌 Plugins used: {len(session_data['plugins_used'])}")
    lines.append("")

    # Track breakdown
    lines.append("──── TRACK BREAKDOWN ────")
    for i, track in enumerate(session_data["tracks"]):
        if track["is_master"]:
            continue
        lines.append(f"")
        lines.append(f"{i}. {track['name']} ({track['type']})")
        lines.append(f"   └─ Level: {track['gain_db']} dB | Pan: {track['pan']}")
        lines.append(f"   └─ Regions: {track['regions']}")
        if track["plugins"]:
            chain = " → ".join(p["name"] for p in track["plugins"] if p["active"])
            lines.append(f"   └─ Chain: {chain}")
            for p in track["plugins"]:
                status = "✅" if p["active"] else "⏸️"
                lines.append(f"      {status} {p['name']} ({p['type'].upper()})")
        else:
            lines.append(f"   └─ Chain: (clean / no processing)")
        if track["has_automation"]:
            lines.append(f"   └─ 🔄 Has automation curves")

    # Master bus
    master = next((t for t in session_data["tracks"] if t["is_master"]), None)
    if master:
        lines.append("")
        lines.append("──── MASTER BUS ────")
        lines.append(f"Level: {master['gain_db']} dB")
        if master["plugins"]:
            for p in master["plugins"]:
                status = "✅" if p["active"] else "⏸️"
                lines.append(f"   {status} {p['name']}")

    # Plugin inventory
    if session_data["plugins_used"]:
        lines.append("")
        lines.append("──── PLUGIN INVENTORY ────")
        for plugin in session_data["plugins_used"]:
            lines.append(f"• {plugin}")

    # Mix decisions
    lines.append("")
    lines.append("──── MIX PHILOSOPHY ────")
    track_count = len([t for t in session_data["tracks"] if not t["is_master"]])
    has_plugins = any(t["plugins"] for t in session_data["tracks"])
    if has_plugins:
        lines.append("Plugin chains applied per track for targeted processing.")
    else:
        lines.append("Clean session — no processing applied yet.")
    if session_data["has_automation"]:
        lines.append("Automation curves active for dynamic movement.")
    lines.append(f"Session built with {track_count} discrete tracks for clean separation.")

    # Exports
    lines.append("")
    lines.append("──── EXPORT ────")
    if exports["exists"] and exports["files"]:
        for f in exports["files"]:
            lines.append(f"📁 {f['name']} ({f['size_mb']} MB, {f['type']})")
        lines.append(f"📂 Location: {exports['dir']}")
    else:
        lines.append("⚠️ No exports yet — session is ready for mixing/export.")

    # Notes
    if notes:
        lines.append("")
        lines.append("──── PRODUCTION NOTES ────")
        lines.append(notes)

    lines.append("")
    lines.append("═" * 45)

    return "\n".join(lines)


def generate_receipt_json(session_data, exports, notes=""):
    """Generate a JSON receipt."""
    return {
        "session": session_data["name"],
        "bpm": session_data["bpm"],
        "sample_rate": session_data["sample_rate"],
        "generated_at": datetime.now().isoformat(),
        "track_count": len([t for t in session_data["tracks"] if not t["is_master"]]),
        "region_count": session_data["total_regions"],
        "plugins_used": session_data["plugins_used"],
        "has_automation": session_data["has_automation"],
        "tracks": [
            {
                "name": t["name"],
                "type": t["type"],
                "gain_db": t["gain_db"],
                "pan": t["pan"],
                "regions": t["regions"],
                "plugins": [p["name"] for p in t["plugins"] if p["active"]],
                "has_automation": t["has_automation"],
            }
            for t in session_data["tracks"]
            if not t["is_master"]
        ],
        "master": next(
            (
                {
                    "gain_db": t["gain_db"],
                    "plugins": [p["name"] for p in t["plugins"] if p["active"]],
                }
                for t in session_data["tracks"]
                if t["is_master"]
            ),
            None,
        ),
        "exports": exports.get("files", []),
        "notes": notes,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a production receipt for an Ardour session")
    parser.add_argument("--session", required=True, help="Session name")
    parser.add_argument("--source", default="user", help="Who requested: telegram:CHAT_ID, songprocessor, user")
    parser.add_argument("--notes", default="", help="Additional production notes")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    args = parser.parse_args()

    session_data = parse_session(args.session)
    if session_data is None:
        print(json.dumps({"success": False, "error": f"Session '{args.session}' not found in {SESSIONS_DIR}"}))
        sys.exit(1)

    exports = check_exports(args.session)

    if args.format == "json":
        receipt = generate_receipt_json(session_data, exports, args.notes)
        receipt_text = json.dumps(receipt, indent=2)
    else:
        receipt_text = generate_receipt_text(session_data, exports, args.notes)

    # Always save to exports directory
    export_dir = os.path.join(EXPORTS_DIR, args.session)
    os.makedirs(export_dir, exist_ok=True)
    receipt_file = os.path.join(export_dir, "production_receipt.md")
    with open(receipt_file, "w") as f:
        f.write(receipt_text)

    # Print to stdout for the agent to capture and forward
    print(receipt_text)

    # Print metadata to stderr
    print(f"\n[Receipt saved to {receipt_file}]", file=sys.stderr)
    print(f"[Source: {args.source}]", file=sys.stderr)


if __name__ == "__main__":
    main()
