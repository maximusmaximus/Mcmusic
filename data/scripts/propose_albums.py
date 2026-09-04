#!/usr/bin/env python3
"""
propose_albums.py — Proposes 5 VOIDRIDE album concepts.

Features:
  - Robust JSON parsing with retry + repair + fallback model
  - Theme injection: --theme, --seed-themes
  - Post-refinement: --refine (refines existing proposals)
  - Preference memory: taste_profile.json (likes/dislikes/notes)

Usage:
    python3 propose_albums.py                                        # Run (cron or manual)
    python3 propose_albums.py --theme "ice and frost"                # Theme-directed
    python3 propose_albums.py --seed-themes "cosmic,underwater"      # Seed anchors
    python3 propose_albums.py --refine "darker, more industrial"     # Refine existing
    python3 propose_albums.py --test                                 # Dry run (no TG send)
    python3 propose_albums.py --force                                # Skip publish gate
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Config ──
VENICE_API_KEY = os.environ.get("VENICE_API_KEY", "")
VENICE_MODEL = "claude-opus-5"
FALLBACK_MODEL = "openai-gpt-55-pro"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")
RELEASES_DIR = Path("/opt/data/music/releases")
EXPORTS_DIR = Path("/opt/data/music/exports")
ARTWORK_DIR = Path("/opt/data/music/artwork/covers")
PROPOSALS_DIR = Path("/opt/data/music/proposals")
TASTE_FILE = PROPOSALS_DIR / "taste_profile.json"

MAX_RETRIES = 3


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[propose-albums {ts}] {msg}", flush=True)


# ── Taste Profile ───────────────────────────────────────────────────────

def load_taste_profile():
    if TASTE_FILE.exists():
        try:
            with open(TASTE_FILE) as f:
                return json.load(f)
        except Exception:
            log("⚠ Corrupt taste_profile.json, starting fresh")
    return {"likes": [], "dislikes": [], "preferred_subgenres": [], "rejected_subgenres": [], "notes": []}


def save_taste_profile(profile):
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    with open(TASTE_FILE, "w") as f:
        json.dump(profile, f, indent=2)


def record_like(album_name, subgenre, visual, source="selected"):
    profile = load_taste_profile()
    entry = {"theme": visual or album_name, "subgenre": subgenre,
             "noted_at": datetime.now().strftime("%Y-%m-%d"), "source": f"{source} {album_name}"}
    existing = {e.get("source") for e in profile["likes"]}
    if entry["source"] not in existing:
        profile["likes"].append(entry)
        if subgenre and subgenre not in profile["preferred_subgenres"]:
            profile["preferred_subgenres"].append(subgenre)
        save_taste_profile(profile)
        log(f"  ❤️ Recorded like: {album_name} ({subgenre})")


def record_dislike(album_name, subgenre, visual, source="rejected"):
    profile = load_taste_profile()
    entry = {"theme": visual or album_name, "subgenre": subgenre,
             "noted_at": datetime.now().strftime("%Y-%m-%d"), "source": f"{source} {album_name}"}
    existing = {e.get("source") for e in profile["dislikes"]}
    if entry["source"] not in existing:
        profile["dislikes"].append(entry)
        if subgenre and subgenre not in profile["rejected_subgenres"]:
            profile["rejected_subgenres"].append(subgenre)
        save_taste_profile(profile)
        log(f"  👎 Recorded dislike: {album_name} ({subgenre})")


def record_skip_all(proposals):
    profile = load_taste_profile()
    for p in proposals:
        entry = {"theme": p.get("visual", p.get("album", "")), "subgenre": p.get("subgenre", ""),
                 "noted_at": datetime.now().strftime("%Y-%m-%d"), "source": f"skipped {p.get('album', '?')}"}
        existing = {e.get("source") for e in profile["dislikes"]}
        if entry["source"] not in existing:
            profile["dislikes"].append(entry)
    save_taste_profile(profile)
    log(f"  ⏭ Recorded skip for {len(proposals)} proposals")


def build_taste_block():
    profile = load_taste_profile()
    lines = []
    if profile.get("likes"):
        themes = [e.get("theme", "") for e in profile["likes"][-10:] if e.get("theme")]
        if themes:
            lines.append(f"USER PREFERENCES (themes they LOVE): {'; '.join(themes[:8])}")
    if profile.get("preferred_subgenres"):
        lines.append(f"PREFERRED SUBGENRES: {', '.join(profile['preferred_subgenres'][:8])}")
    if profile.get("dislikes"):
        themes = [e.get("theme", "") for e in profile["dislikes"][-10:] if e.get("theme")]
        if themes:
            lines.append(f"AVOID THESE THEMES (user dislikes): {'; '.join(themes[:8])}")
    if profile.get("rejected_subgenres"):
        lines.append(f"AVOID THESE SUBGENRES: {', '.join(profile['rejected_subgenres'][:5])}")
    if profile.get("notes"):
        for note in profile["notes"][-5:]:
            lines.append(f"USER NOTE: {note}")

    # Selection intelligence — which album shapes actually get picked
    selected = [e for e in profile.get("likes", []) if "selected" in e.get("source", "")]
    if selected:
        sel_names = [e.get("theme", "")[:60] for e in selected[-5:]]
        lines.append(f"ALBUMS ACTUALLY SELECTED FOR PRODUCTION: {'; '.join(sel_names)}")

    return "\n".join(lines)


# ── Context Blocks for Sophisticated Concept Generation ─────────────────

PROFILE_FILE = Path("/opt/data/music/profiles/vidride/profile.json")


def _load_profile():
    """Load the VØIDRIDE artist profile."""
    if PROFILE_FILE.exists():
        try:
            with open(PROFILE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def build_sonic_identity_block():
    """Block 1: SONIC IDENTITY — genres, keys, BPM range, signature sound."""
    profile = _load_profile()
    if not profile:
        return ""

    lines = ["🧬 SONIC IDENTITY:"]

    dna = profile.get("sonic_dna", {})
    if dna.get("primary_genres"):
        lines.append(f"  Primary genres: {', '.join(dna['primary_genres'])}")
    if dna.get("bpm_range"):
        lines.append(f"  BPM range: {dna['bpm_range'][0]}-{dna['bpm_range'][1]}")
    if dna.get("preferred_keys"):
        lines.append(f"  Preferred keys: {', '.join(dna['preferred_keys'])}")
    if dna.get("preferred_models"):
        models = dna["preferred_models"]
        lines.append(f"  Audio models: {models.get('main', '?')} (main), {models.get('texture', '?')} (texture)")
    if dna.get("total_tracks"):
        lines.append(f"  Total tracks produced: {dna['total_tracks']}")

    style = profile.get("style", {})
    if style.get("mood"):
        lines.append(f"  Mood: {style['mood']}")
    if style.get("influences"):
        lines.append(f"  Influences: {style['influences']}")

    prefix = profile.get("prompt_prefix", "")
    if prefix:
        lines.append(f"  Sonic signature: \"{prefix[:300]}\"")

    return "\n".join(lines) if len(lines) > 1 else ""


def build_production_memory_block():
    """Block 2: PRODUCTION MEMORY — published releases (from releases/ dir), cross-ref with catalog plans."""
    profile = _load_profile()
    catalog = profile.get("catalog", [])

    # Build a lookup: title → plan from catalog
    plan_by_title = {}
    for c in catalog:
        title = c.get("title", "").upper().strip()
        if title and c.get("plan"):
            plan_by_title[title] = c["plan"]

    # Source of truth: releases/ directory = what's actually on SoundCloud
    lines = []
    published_plans = []
    album_count = 0

    if RELEASES_DIR.exists():
        for album_dir in sorted(RELEASES_DIR.iterdir()):
            if not album_dir.is_dir():
                continue
            album_count += 1
            album_name = album_dir.name.upper().replace("-", " ")

            # Get track names from files
            tracks = [f.stem.replace("_MASTER", "").replace("_", " ").upper()
                       for f in sorted(album_dir.glob("*.flac"))]
            if not tracks:
                tracks = [f.stem.replace("_", " ").upper()
                          for f in sorted(album_dir.glob("*.mp3"))]

            # Try to get release.json metadata
            release_json = album_dir / "release.json"
            release_meta = {}
            if release_json.exists():
                try:
                    with open(release_json) as f:
                        release_meta = json.load(f)
                except Exception:
                    pass

            # Cross-reference tracks with catalog plans for BPM/key/genre
            for track in tracks:
                plan = plan_by_title.get(track, {})
                if plan and plan.get("bpm"):
                    published_plans.append(plan)
                    bpm = plan.get("bpm", "?")
                    key = plan.get("key", "?")
                    genre = plan.get("genre", "?")
                    lines.append(f"  ✅ {track} ({album_name}) — {bpm} BPM, {key}, {genre}")
                else:
                    lines.append(f"  ✅ {track} ({album_name})")

    if not lines:
        return ""

    header = [f"📀 PUBLISHED ON SOUNDCLOUD ({album_count} albums, {len(lines)} tracks):"]
    header.extend(lines[-20:])  # Last 20 to avoid bloating prompt

    # Summarize patterns from published tracks that have plans
    bpms = [p["bpm"] for p in published_plans if isinstance(p.get("bpm"), (int, float))]
    keys = [p["key"] for p in published_plans if p.get("key")]
    genres = [p["genre"] for p in published_plans if p.get("genre")]
    if bpms:
        header.append(f"  ⚡ BPM distribution: min={min(bpms)}, max={max(bpms)}, avg={sum(bpms)//len(bpms)}")
    if keys:
        from collections import Counter
        key_counts = Counter(keys).most_common(3)
        header.append(f"  🎹 Most-used keys: {', '.join(f'{k} ({n}x)' for k, n in key_counts)}")
    if genres:
        genre_counts = Counter(genres).most_common(3)
        header.append(f"  🎵 Most-used genres: {', '.join(f'{g} ({n}x)' for g, n in genre_counts)}")

    header.append("  ⚠️ Propose albums that VARY from these patterns — explore gaps in BPM, key, and genre.")

    return "\n".join(header)


def build_visual_identity_block():
    """Block 3: VISUAL IDENTITY — approved cover art concepts from past productions."""
    lines = ["🎨 VISUAL IDENTITY (approved cover art concepts):"]

    # Source 1: taste profile — liked/selected visuals
    taste = load_taste_profile()
    visuals_seen = set()

    selected = [e for e in taste.get("likes", []) if e.get("theme")]
    for entry in selected[-8:]:
        v = entry["theme"]
        if v not in visuals_seen:
            lines.append(f"  ✅ \"{v[:120]}\"")
            visuals_seen.add(v)

    # Source 2: selected proposals from current_proposals.json (if it has a 'selected' field)
    proposals_file = PROPOSALS_DIR / "current_proposals.json"
    if proposals_file.exists():
        try:
            with open(proposals_file) as f:
                pdata = json.load(f)
            if pdata.get("selected"):
                proposals = pdata.get("proposals", [])
                for p in proposals:
                    if p.get("album") == pdata["selected"] and p.get("visual"):
                        v = p["visual"]
                        if v not in visuals_seen:
                            lines.append(f"  🎯 Latest selected: \"{v[:120]}\"")
                            visuals_seen.add(v)
        except Exception:
            pass

    # Source 3: rejected visuals
    rejected_visuals = [e.get("theme", "") for e in taste.get("dislikes", []) if e.get("theme")]
    if rejected_visuals:
        lines.append(f"  ❌ REJECTED visual themes: {'; '.join(v[:60] for v in rejected_visuals[-4:])}")

    if len(lines) <= 1:
        return ""

    lines.append("  New proposals should match this visual language — dark, cinematic, vehicle/tech/urban/cosmic imagery.")
    return "\n".join(lines)


# ── Catalog ─────────────────────────────────────────────────────────────

def gather_catalog():
    catalog = []
    if RELEASES_DIR.exists():
        for album_dir in sorted(RELEASES_DIR.iterdir()):
            if not album_dir.is_dir():
                continue
            tracks = [f.stem.replace("_MASTER", "").replace("_", " ") for f in sorted(album_dir.glob("*.flac"))]
            if tracks:
                catalog.append({"album": album_dir.name, "tracks": tracks, "status": "released"})
    if EXPORTS_DIR.exists():
        released = {a["album"] for a in catalog}
        for d in sorted(EXPORTS_DIR.iterdir()):
            if not d.is_dir() or d.name in released:
                continue
            tracks = [f.stem.replace("_MASTER", "").replace("_", " ") for f in sorted(d.glob("*.flac"))]
            if not tracks:
                tracks = [f.stem.replace("_MASTER", "").replace("_", " ") for f in sorted(d.glob("*.mp3"))]
            if tracks:
                catalog.append({"album": d.name, "tracks": tracks, "status": "exported"})
    cover_themes = set()
    if ARTWORK_DIR.exists():
        for d in ARTWORK_DIR.iterdir():
            if d.is_dir():
                cover_themes.add(d.name)
    return catalog, list(cover_themes)


# ── JSON Repair ─────────────────────────────────────────────────────────

def repair_json(raw):
    """Attempt to repair malformed JSON from LLM output."""
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]

    # Direct parse
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    # Repair 1: Remove trailing commas
    repaired = re.sub(r',\s*([}\]])', r'\1', raw)
    try:
        return json.loads(repaired.strip())
    except json.JSONDecodeError:
        pass

    # Repair 2: Close unclosed brackets/braces
    open_braces = repaired.count("{") - repaired.count("}")
    open_brackets = repaired.count("[") - repaired.count("]")
    if open_braces > 0:
        repaired = repaired.rstrip().rstrip(",") + "}" * open_braces
    if open_brackets > 0:
        repaired = repaired.rstrip().rstrip(",") + "]" * open_brackets
    repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
    try:
        return json.loads(repaired.strip())
    except json.JSONDecodeError:
        pass

    # Repair 3: Extract valid objects from partial array
    objects = []
    depth = 0
    obj_start = None
    for i, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(raw[obj_start:i+1])
                    objects.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None
    if objects:
        log(f"  JSON repair: extracted {len(objects)} valid objects from broken array")
        return objects

    return None


# ── Venice API ──────────────────────────────────────────────────────────

def query_venice(catalog, cover_themes, theme=None, seed_themes=None):
    catalog_text = ""
    for a in catalog:
        catalog_text += f"- {a['album'].upper()}: {', '.join(a['tracks'][:8])}\n"

    theme_block = ""
    if theme:
        theme_block = (
            f"\n🎯 MANDATORY THEME: \"{theme}\"\n"
            f"All 5 albums MUST be inspired by this theme. Interpret it creatively — "
            f"the albums should explore different facets of \"{theme}\" while staying "
            f"within the VØIDRIDE dark electronic aesthetic.\n"
        )

    seed_block = ""
    if seed_themes:
        seeds = [s.strip() for s in seed_themes.split(",")]
        seed_block = (
            f"\n🌱 THEMATIC ANCHORS: {', '.join(seeds)}\n"
            f"At least 2 of the 5 albums MUST explore one of these thematic anchors. "
            f"The remaining albums can explore related or contrasting territory.\n"
        )

    taste_block = build_taste_block()
    taste_section = f"\n📊 USER TASTE PROFILE:\n{taste_block}\n" if taste_block else ""

    # New context blocks
    sonic_block = build_sonic_identity_block()
    sonic_section = f"\n{sonic_block}\n" if sonic_block else ""

    memory_block = build_production_memory_block()
    memory_section = f"\n{memory_block}\n" if memory_block else ""

    visual_block = build_visual_identity_block()
    visual_section = f"\n{visual_block}\n" if visual_block else ""

    prompt = f"""You are a creative director for VØIDRIDE, a dark electronic music project.
Genres: dark trap, witch house, nightride phonk, atmospheric electronic, industrial.
{sonic_section}
Existing catalog:
{catalog_text}

Visual themes: {', '.join(cover_themes[:15]) or 'dark cosmic noir cinematic'}
{visual_section}{theme_block}{seed_block}{taste_section}{memory_section}
Propose exactly 5 NEW album concepts. Each must:
1. Build on the VØIDRIDE aesthetic (dark, cosmic, noir, cinematic) but explore new territory
2. NOT repeat any existing album name or theme
3. Have exactly 5 track titles (ALL CAPS, evocative, 2-3 words, VØIDRIDE style)
4. Include BPM range, key signature, and specific subgenre
5. Include a 1-line visual concept for cover art that fits the VØIDRIDE visual language
6. Include a 50-word production brief that references specific sounds, instruments, and techniques
7. VARY the BPM, key, and subgenre across proposals — not all 5 should be the same style

RESPOND IN THIS EXACT JSON FORMAT ONLY (no markdown fences, no explanation):
[
  {{
    "album": "ALBUM NAME",
    "tracks": ["TRACK 1", "TRACK 2", "TRACK 3", "TRACK 4", "TRACK 5"],
    "bpm": "130-145",
    "key": "Dm",
    "subgenre": "industrial witch house",
    "visual": "Abandoned subway station flooded with bioluminescent water, cracked tiles, fog",
    "brief": "Dark industrial witch house EP. Heavy sub-bass 808s, distorted vocal chops, reversed reverb pads, metallic percussion, glitch transitions. 130-145 BPM, D minor, cinematic darkness."
  }}
]"""

    models = [VENICE_MODEL, VENICE_MODEL, FALLBACK_MODEL]

    for attempt in range(MAX_RETRIES):
        model = models[min(attempt, len(models) - 1)]
        log(f"  Attempt {attempt + 1}/{MAX_RETRIES} (model: {model})")

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
            "max_tokens": 4000,
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
                    log("  Venice API returned empty response")
                    continue
                result = json.loads(raw)
                msg = result["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                content = content.strip()
                log(f"  Venice response length: {len(content)} chars")

                proposals = repair_json(content)
                if proposals and isinstance(proposals, list) and len(proposals) >= 3:
                    valid = [p for p in proposals if isinstance(p, dict) and p.get("album") and p.get("tracks")]
                    if len(valid) >= 3:
                        log(f"  ✓ Parsed {len(valid)} valid proposals")
                        return valid[:5]
                    else:
                        log(f"  ⚠ Only {len(valid)} valid proposals, retrying...")
                else:
                    log(f"  ⚠ JSON repair failed or too few results, retrying...")

        except json.JSONDecodeError as e:
            log(f"  JSON parse error: {e}")
        except Exception as e:
            log(f"  Venice API error: {e}")

        if attempt < MAX_RETRIES - 1:
            time.sleep(3)

    log("✗ All retries exhausted")
    return None


def query_venice_refine(existing_proposals, refinement, catalog, cover_themes):
    existing_text = json.dumps(existing_proposals, indent=2)
    catalog_text = ""
    for a in catalog:
        catalog_text += f"- {a['album'].upper()}: {', '.join(a['tracks'][:5])}\n"

    taste_block = build_taste_block()
    taste_section = f"\n📊 USER TASTE PROFILE:\n{taste_block}\n" if taste_block else ""

    sonic_block = build_sonic_identity_block()
    sonic_section = f"\n{sonic_block}\n" if sonic_block else ""

    memory_block = build_production_memory_block()
    memory_section = f"\n{memory_block}\n" if memory_block else ""

    visual_block = build_visual_identity_block()
    visual_section = f"\n{visual_block}\n" if visual_block else ""

    prompt = f"""You are a creative director for VØIDRIDE, a dark electronic music project.
{sonic_section}

Here are the current 5 album proposals:
{existing_text}

Existing catalog (do NOT repeat):
{catalog_text}
{visual_section}{taste_section}{memory_section}
The user wants these proposals REFINED with this feedback:
🎯 "{refinement}"

Generate 5 REFINED album proposals that incorporate the user's feedback.
Keep proposals the user would likely love, modify or replace ones that don't match.
Maintain the VØIDRIDE aesthetic (dark, cosmic, noir, cinematic).

RESPOND IN THIS EXACT JSON FORMAT ONLY (no markdown fences, no explanation):
[
  {{
    "album": "ALBUM NAME",
    "tracks": ["TRACK 1", "TRACK 2", "TRACK 3", "TRACK 4", "TRACK 5"],
    "bpm": "130-145",
    "key": "Dm",
    "subgenre": "industrial witch house",
    "visual": "Dark visual concept description",
    "brief": "50-word production brief."
  }}
]"""

    models = [VENICE_MODEL, FALLBACK_MODEL]
    for attempt in range(2):
        model = models[min(attempt, len(models) - 1)]
        log(f"  Refine attempt {attempt + 1}/2 (model: {model})")
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.85,
            "max_tokens": 4000,
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
                    continue
                result = json.loads(raw)
                content = result["choices"][0]["message"].get("content", "").strip()
                log(f"  Venice response length: {len(content)} chars")
                proposals = repair_json(content)
                if proposals and isinstance(proposals, list) and len(proposals) >= 3:
                    valid = [p for p in proposals if isinstance(p, dict) and p.get("album")]
                    if len(valid) >= 3:
                        log(f"  ✓ Refined {len(valid)} proposals")
                        return valid[:5]
        except Exception as e:
            log(f"  Refine error: {e}")
        if attempt < 1:
            time.sleep(3)
    return None


# ── Telegram ────────────────────────────────────────────────────────────

def send_proposals(proposals, dry_run=False, theme=None, is_refined=False):
    if not proposals:
        return False

    if is_refined:
        lines = ["🎵 *VØIDRIDE — Refined Proposals*\n"]
    elif theme:
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

    lines.append("\n─────────────────────\n👆 *Tap to produce, ❤️/👎 to train taste*")
    msg = "\n".join(lines)

    buttons = []
    for i, p in enumerate(proposals[:5], 1):
        buttons.append([{"text": f"🚀 {i}. {p['album']}", "callback_data": f"ap:{i}"}])
        buttons.append([
            {"text": "❤️ Love", "callback_data": f"ap:love:{i}"},
            {"text": "👎 Not my vibe", "callback_data": f"ap:hate:{i}"},
        ])
    buttons.append([
        {"text": "⏭ Skip All", "callback_data": "ap:skip"},
        {"text": "🔄 Refine These", "callback_data": "ap:refine"},
    ])

    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    proposals_file = PROPOSALS_DIR / "current_proposals.json"
    with open(proposals_file, "w") as f:
        save_data = {"proposals": proposals, "created_at": datetime.now().isoformat()}
        if theme:
            save_data["theme"] = theme
        json.dump(save_data, f, indent=2)
    log(f"Saved proposals to {proposals_file}")

    if dry_run:
        print(msg)
        print(f"\nButtons: {len(buttons)} rows")
        return True

    if not TELEGRAM_BOT_TOKEN:
        log("No TELEGRAM_BOT_TOKEN, skipping send")
        return False

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


# ── Publish Gate ────────────────────────────────────────────────────────

def check_publish_gate():
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
    if RELEASES_DIR.exists():
        for d in RELEASES_DIR.iterdir():
            if d.is_dir() and (d.name == selected_slug or d.name.startswith(selected_slug + "-")):
                return True, f"{selected} published as {d.name}"
    export_count = 0
    if Path("/opt/data/music/exports").exists():
        for d in Path("/opt/data/music/exports").iterdir():
            if d.is_dir() and d.name.startswith(selected_slug):
                export_count += 1
    if export_count > 0:
        return False, f"{selected} has {export_count} tracks exported but not yet published to releases"
    else:
        selected_at = data.get("selected_at", "")
        return False, f"{selected} was selected at {selected_at[:19]} but not yet produced/published"


# ── Main ────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Propose VØIDRIDE album concepts")
    parser.add_argument("--test", action="store_true", help="Dry run (no TG send)")
    parser.add_argument("--force", action="store_true", help="Skip publish gate")
    parser.add_argument("--theme", type=str, default=None,
                        help="Theme to direct all proposals (e.g. 'ice and frost', 'samurai noir')")
    parser.add_argument("--seed-themes", type=str, default=None,
                        help="Comma-separated thematic anchors (at least 2/5 albums must explore these)")
    parser.add_argument("--refine", type=str, default=None,
                        help="Refine existing proposals with this feedback (e.g. 'darker, more cosmic')")
    args = parser.parse_args()

    log("Starting album proposal generation...")
    if args.theme:
        log(f"Theme: {args.theme}")
    if args.seed_themes:
        log(f"Seed themes: {args.seed_themes}")

    # ── Refine mode ──
    if args.refine:
        log(f"Refine mode: \"{args.refine}\"")
        proposals_file = PROPOSALS_DIR / "current_proposals.json"
        if not proposals_file.exists():
            log("No existing proposals to refine")
            sys.exit(1)
        try:
            existing_data = json.load(open(proposals_file))
            existing = existing_data.get("proposals", [])
        except Exception:
            log("Failed to load existing proposals")
            sys.exit(1)
        if not existing:
            log("No proposals found in current_proposals.json")
            sys.exit(1)
        catalog, cover_themes = gather_catalog()
        proposals = query_venice_refine(existing, args.refine, catalog, cover_themes)
        if not proposals:
            log("Failed to refine proposals")
            sys.exit(1)
        log(f"Got {len(proposals)} refined proposals")
        if send_proposals(proposals, dry_run=args.test, is_refined=True):
            log("Done (refined)")
        else:
            log("Failed to send refined proposals")
            sys.exit(1)
        return

    # ── Normal mode ──
    if not args.force:
        ok, reason = check_publish_gate()
        if not ok:
            log(f"⏸ Skipping proposals: {reason}")
            log("Use --force to override, or publish the album to releases/")
            if TELEGRAM_BOT_TOKEN:
                msg = (f"⏸ *Album proposal skipped*\n\nReason: {reason}\n\n"
                       f"Publish the album to releases/ to unlock next batch, or run with `--force` to override.")
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
    proposals = query_venice(catalog, cover_themes, theme=args.theme, seed_themes=args.seed_themes)
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
