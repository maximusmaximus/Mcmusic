#!/usr/bin/env python3
"""
propose_albums.py — Proposes 5 VOIDRIDE album concepts.

Analyzes existing catalog, queries Venice AI for fresh ideas,
sends formatted proposals to Telegram with inline buttons.
Saves proposals to disk so the agent can load them when the user picks one.

Usage:
    python3 propose_albums.py                          # Run (cron or manual)
    python3 propose_albums.py --theme "ice and frost"  # Theme-directed proposals
    python3 propose_albums.py --test                   # Dry run (no TG send)
    python3 propose_albums.py --force                  # Skip publish gate
"""

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Config ──
VENICE_API_KEY = os.environ.get("VENICE_API_KEY", "")
VENICE_MODEL = "gemini-3-7-flash"  # 1M context, fast, no thinking/reasoning split
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")
RELEASES_DIR = Path("/opt/data/music/releases")
EXPORTS_DIR = Path("/opt/data/music/exports")
ARTWORK_DIR = Path("/opt/data/music/artwork/covers")
PROPOSALS_DIR = Path("/opt/data/music/proposals")


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[propose-albums {ts}] {msg}", flush=True)


def gather_catalog():
    """Collect all existing album/track names and themes."""
    catalog = []

    if RELEASES_DIR.exists():
        for album_dir in sorted(RELEASES_DIR.iterdir()):
            if not album_dir.is_dir():
                continue
            tracks = [f.stem.replace("_MASTER", "").replace("_", " ")
                      for f in sorted(album_dir.glob("*.flac"))]
            if tracks:
                catalog.append({"album": album_dir.name, "tracks": tracks, "status": "released"})

    if EXPORTS_DIR.exists():
        released = {a["album"] for a in catalog}
        for d in sorted(EXPORTS_DIR.iterdir()):
            if not d.is_dir() or d.name in released:
                continue
            tracks = [f.stem.replace("_MASTER", "").replace("_", " ")
                      for f in sorted(d.glob("*.flac"))]
            if not tracks:
                tracks = [f.stem.replace("_MASTER", "").replace("_", " ")
                          for f in sorted(d.glob("*.mp3"))]
            if tracks:
                catalog.append({"album": d.name, "tracks": tracks, "status": "exported"})

    cover_themes = set()
    if ARTWORK_DIR.exists():
        for d in ARTWORK_DIR.iterdir():
            if d.is_dir():
                cover_themes.add(d.name)

    return catalog, list(cover_themes)


def query_venice(catalog, cover_themes, theme=None):
    """Ask Venice AI for 5 album proposals, optionally themed."""
    catalog_text = ""
    for a in catalog:
        catalog_text += f"- {a['album'].upper()}: {', '.join(a['tracks'][:8])}\n"

    # Theme injection
    theme_block = ""
    if theme:
        theme_block = (
            f"\n🎯 MANDATORY THEME: \"{theme}\"\n"
            f"All 5 albums MUST be inspired by this theme. Interpret it creatively — "
            f"the albums should explore different facets of \"{theme}\" while staying "
            f"within the VØIDRIDE dark electronic aesthetic. Track titles, visuals, "
            f"and production briefs should all reflect this theme.\n"
        )

    prompt = f"""You are a creative director for VØIDRIDE, a dark electronic music project.
Genres: dark trap, witch house, nightride phonk, atmospheric electronic, industrial.

Existing catalog:
{catalog_text}

Visual themes: {', '.join(cover_themes[:15]) or 'dark cosmic noir cinematic'}
{theme_block}
Propose exactly 5 NEW album concepts. Each must:
1. Build on the VØIDRIDE aesthetic (dark, cosmic, noir, cinematic) but explore new territory
2. NOT repeat any existing album name or theme
3. Have exactly 5 track titles (ALL CAPS, evocative, 2-3 words, VØIDRIDE style)
4. Include BPM range, key signature, and specific subgenre
5. Include a 1-line visual concept for cover art
6. Include a 50-word production brief

RESPOND IN THIS EXACT JSON FORMAT ONLY (no markdown fences, no explanation):
[
  {{
    "album": "ALBUM NAME",
    "tracks": ["TRACK 1", "TRACK 2", "TRACK 3", "TRACK 4", "TRACK 5"],
    "bpm": "130-145",
    "key": "Dm",
    "subgenre": "industrial witch house",
    "visual": "Abandoned subway station flooded with bioluminescent water, cracked tiles, fog",
    "brief": "Dark industrial witch house EP. Heavy sub-bass 808s, distorted vocal chops, reversed reverb pads, metallic percussion, glitch transitions. Starts claustrophobic, builds to crushing crescendo. 130-145 BPM, D minor, cinematic darkness."
  }}
]"""

    payload = {
        "model": VENICE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
        "max_tokens": 3000,
        "venice_parameters": {"include_venice_system_prompt": False, "strip_thinking_response": True}
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.venice.ai/api/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {VENICE_API_KEY}"}
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
            if not raw:
                log("Venice API returned empty response")
                return None
            result = json.loads(raw)
            msg = result["choices"][0]["message"]
            content = msg.get("content") or msg.get("reasoning_content") or ""
            content = content.strip()
            log(f"Venice response length: {len(content)} chars")
            # Strip markdown fences
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            # Find the JSON array
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                content = content[start:end]
            return json.loads(content.strip())
    except json.JSONDecodeError as e:
        log(f"JSON parse error: {e}")
        log(f"Raw content snippet: {content[:300] if 'content' in locals() else 'N/A'}")
        return None
    except Exception as e:
        log(f"Venice API error: {e}")
        return None


def send_proposals(proposals, dry_run=False, theme=None):
    """Send proposals to Telegram as a formatted message."""
    if not proposals:
        return False

    # Build message
    if theme:
        lines = [f"🎵 *VØIDRIDE — Album Proposals*\n🎯 Theme: _{theme}_\n"]
    else:
        lines = ["🎵 *VØIDRIDE — Fresh Album Proposals*\n"]

    for i, p in enumerate(proposals[:5], 1):
        tracks = " · ".join(p.get("tracks", [])[:5])
        lines.append(
            f"*{i}️⃣  {p['album']}*\n"
            f"    _{p.get('subgenre', '?')}_ · {p.get('bpm', '?')} BPM · {p.get('key', '?')}\n"
            f"    🎨 {p.get('visual', '')}\n"
            f"    🎶 {tracks}\n"
        )

    lines.append("\n─────────────────────\n"
                 "👆 *Tap a button to produce that album*")

    msg = "\n".join(lines)

    # Build inline keyboard buttons
    buttons = []
    for i, p in enumerate(proposals[:5], 1):
        buttons.append([{"text": f"🚀 {i}. {p['album']}", "callback_data": f"ap:{i}"}])
    buttons.append([{"text": "⏭ Skip All", "callback_data": "ap:skip"}])

    # Save to disk
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    proposals_file = PROPOSALS_DIR / "current_proposals.json"
    with open(proposals_file, "w") as f:
        save_data = {
            "proposals": proposals,
            "created_at": datetime.now().isoformat(),
        }
        if theme:
            save_data["theme"] = theme
        json.dump(save_data, f, indent=2)
    log(f"Saved proposals to {proposals_file}")

    if dry_run:
        print(msg)
        return True

    if not TELEGRAM_BOT_TOKEN:
        log("No TELEGRAM_BOT_TOKEN, skipping send")
        return False

    # Send via Telegram with inline keyboard
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": buttons},
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log("✓ Proposals sent to Telegram")
                return True
            log(f"Telegram error: {result}")
            return False
    except Exception as e:
        log(f"Telegram send error: {e}")
        return False


def check_publish_gate():
    """Check if the last selected album has been published. Returns (ok, reason)."""
    proposals_file = PROPOSALS_DIR / "current_proposals.json"
    if not proposals_file.exists():
        return True, "no previous proposals"

    try:
        data = json.load(open(proposals_file))
    except Exception:
        return True, "corrupt proposals file"

    selected = data.get("selected")
    if not selected:
        return True, "no album selected from last batch"

    selected_slug = data.get("selected_slug", selected.lower().replace(" ", "-"))

    # Check if it's been published (exists in releases)
    if RELEASES_DIR.exists():
        for d in RELEASES_DIR.iterdir():
            if d.is_dir() and (d.name == selected_slug or d.name.startswith(selected_slug + "-")):
                return True, f"{selected} published as {d.name}"

    # Check if production has started (exists in exports)
    export_count = 0
    if Path("/opt/data/music/exports").exists():
        for d in Path("/opt/data/music/exports").iterdir():
            if d.is_dir() and d.name.startswith(selected_slug):
                export_count += 1

    if export_count > 0:
        return False, f"{selected} has {export_count} tracks exported but not yet published to releases"
    else:
        # Selected but never produced — still gate it
        selected_at = data.get("selected_at", "")
        return False, f"{selected} was selected at {selected_at[:19]} but not yet produced/published"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Propose VØIDRIDE album concepts")
    parser.add_argument("--test", action="store_true", help="Dry run (no TG send)")
    parser.add_argument("--force", action="store_true", help="Skip publish gate")
    parser.add_argument("--theme", type=str, default=None,
                        help="Theme to direct all proposals (e.g. 'ice and frost', 'samurai noir')")
    args = parser.parse_args()

    log("Starting album proposal generation...")
    if args.theme:
        log(f"Theme: {args.theme}")

    # Gate: don't propose if last selected album isn't published
    if not args.force:
        ok, reason = check_publish_gate()
        if not ok:
            log(f"⏸ Skipping proposals: {reason}")
            log("Use --force to override, or publish the album to releases/")

            # Notify via Telegram
            if TELEGRAM_BOT_TOKEN:
                msg = (f"⏸ *Album proposal skipped*\n\n"
                       f"Reason: {reason}\n\n"
                       f"Publish the album to releases/ to unlock next batch, "
                       f"or run with `--force` to override.")
                payload = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}).encode()
                try:
                    req = urllib.request.Request(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        data=payload, headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=10)
                except Exception:
                    pass
            return
        log(f"✓ Gate passed: {reason}")

    catalog, cover_themes = gather_catalog()
    log(f"Found {len(catalog)} albums, {len(cover_themes)} cover themes")

    proposals = query_venice(catalog, cover_themes, theme=args.theme)
    if not proposals:
        log("Failed to get proposals from Venice AI")
        sys.exit(1)

    log(f"Got {len(proposals)} proposals")

    if send_proposals(proposals, dry_run=args.test, theme=args.theme):
        log("Done")
    else:
        log("Failed to send proposals")
        sys.exit(1)


if __name__ == "__main__":
    main()
