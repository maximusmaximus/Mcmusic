#!/usr/bin/env python3
"""
propose_albums.py — Proposes 5 VØIDRIDE album concepts.

Features:
  - Robust JSON parsing with retry + repair + fallback model
  - Full discography & proposal history awareness (never repeats produced or recently proposed albums)
  - Hard programmatic deduplication on album titles, track titles, and visual settings
  - Theme injection: --theme, --seed-themes
  - Post-refinement: --refine (refines existing proposals)
  - Preference memory: taste_profile.json (likes/dislikes/notes) + proposal_history.json

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
from collections import Counter
from datetime import datetime
from pathlib import Path

# ── Environment & Cross-Platform Config ──
def _load_dotenv():
    for env_path in ["/opt/data/.env", "/opt/hermes/.env", r"D:\sp2\.env", r"D:\hermes-music\.env"]:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

_load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import model_registry as _mr
except ImportError:
    _mr = None

_PROPOSAL_CHAIN = _mr.get_role_chain("llm.proposals", ["qwen-3-7-plus", "deepseek-v4-flash", "qwen-3-8-flash"]) if _mr else ["qwen-3-7-plus", "deepseek-v4-flash", "qwen-3-8-flash"]
VENICE_API_BASE = os.environ.get("VENICE_API_BASE", "https://api.venice.ai/api/v1")
VENICE_API_KEY = os.environ.get("VENICE_API_KEY", "")
VENICE_MODEL = os.environ.get("PROPOSAL_MODEL", _PROPOSAL_CHAIN[0])
FALLBACK_MODEL = os.environ.get("PROPOSAL_FALLBACK_MODEL", _PROPOSAL_CHAIN[1] if len(_PROPOSAL_CHAIN) > 1 else "deepseek-v4-flash")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")

MUSIC_ROOT = Path("/opt/data/music") if Path("/opt/data/music").exists() else Path("D:/music")
RELEASES_DIR = MUSIC_ROOT / "releases"
ALBUMS_DIR = MUSIC_ROOT / "albums"
EXPORTS_DIR = MUSIC_ROOT / "exports"
ARTWORK_DIR = MUSIC_ROOT / "artwork" / "covers"
PROPOSALS_DIR = MUSIC_ROOT / "proposals"
TASTE_FILE = PROPOSALS_DIR / "taste_profile.json"
HISTORY_FILE = PROPOSALS_DIR / "proposal_history.json"
PROFILE_FILE = MUSIC_ROOT / "profiles" / "vidride" / "profile.json"

MAX_RETRIES = 8
REQUIRED_PROPOSAL_COUNT = 5

# Exhausted title words and visual settings from already-produced albums
EXHAUSTED_TITLE_WORDS = {
    "BASEMENT", "PAWNSHOP", "YARDMASTER", "PRECINCT", "OVERPASS", "SODIUM",
    "MORGUE", "CHROMA", "KATANA", "CHERENKOV", "POSITRON", "SYNAPSE",
    "NECROPOLIS", "CRYOCLASTIC", "ABYSS", "SCRAPLINE", "ORBITAL",
    "ASHFALL", "BLACKOUT", "KINETIC", "NOCTURNE", "OBLIVIAN", "SIGIL",
    "THUNDERVEIL", "INTERIORRENCE", "HELIOS", "GRAVEL", "VELVET"
}

EXHAUSTED_VISUAL_PHRASES = [
    "hospital basement",
    "ambulance",
    "pawnshop",
    "barred storefront",
    "freight locomotive",
    "rail yard",
    "steel couplers",
    "precinct",
    "lattice transmission",
    "radio truck",
    "radio pickup",
    "overpass at 3am",
    "palm silhouettes",
    "underground parking structure",
    "vacancy sign",
    "derelict desert motel",
    "subway train",
    "third rail",
    "drilling rig",
    "lava fissure",
]

STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "of", "to", "and", "or", "through",
    "under", "beneath", "into", "across", "behind", "from", "with", "by",
    "as", "its", "off", "out", "over", "down", "up", "mid", "lone", "empty",
    "black", "matte", "dark", "wet", "cold", "neon", "light", "lights",
    "night", "midnight", "rain", "slicked", "fog", "steam", "haze", "smoke",
    "headlights", "reflections", "glowing", "burning", "cutting", "slicing",
    "photorealistic", "cinematic", "nocturnal", "against", "reflecting",
    "illuminating", "illuminated", "abandoned", "derelict", "single",
    "hovering", "silhouetted", "looming", "darkness", "shadows", "shadowy",
    "shimmering", "view", "scene", "wide", "deep", "high", "rusted",
    "concrete", "steel", "metal", "water", "amber", "blue", "orange", "glow",
    "mist", "swirling", "piercing", "leading", "exposed", "thick", "full"
}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[propose-albums {ts}] {msg}", flush=True)


# ── Taste Profile & Proposal History ────────────────────────────────────

def load_taste_profile():
    if TASTE_FILE.exists():
        try:
            with open(TASTE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log("⚠ Corrupt taste_profile.json, starting fresh")
    return {"likes": [], "dislikes": [], "preferred_subgenres": [], "rejected_subgenres": [], "notes": []}


def save_taste_profile(profile):
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    with open(TASTE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)


def load_proposal_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("history", []) if isinstance(data, dict) else data
        except Exception:
            pass
    return []


def record_proposal_history(proposals):
    if not proposals:
        return
    history = load_proposal_history()
    existing_albums = {h.get("album", "").upper().strip() for h in history}
    now_str = datetime.now().strftime("%Y-%m-%d")
    for p in proposals:
        alb = p.get("album", "").strip()
        if alb and alb.upper() not in existing_albums:
            history.append({
                "album": alb,
                "subgenre": p.get("subgenre", ""),
                "visual": p.get("visual", ""),
                "tracks": p.get("tracks", []),
                "proposed_at": now_str,
            })
            existing_albums.add(alb.upper())
    # Keep last 60 proposals
    history = history[-60:]
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"history": history}, f, indent=2)


def record_like(album_name, subgenre, visual, source="selected"):
    profile = load_taste_profile()
    entry = {
        "album": album_name,
        "theme": visual or album_name,
        "subgenre": subgenre,
        "noted_at": datetime.now().strftime("%Y-%m-%d"),
        "source": f"{source} {album_name}",
    }
    existing = {e.get("source") for e in profile["likes"]}
    if entry["source"] not in existing:
        profile["likes"].append(entry)
        if subgenre and subgenre not in profile["preferred_subgenres"]:
            profile["preferred_subgenres"].append(subgenre)
        save_taste_profile(profile)
        log(f"  ❤️ Recorded like: {album_name} ({subgenre})")


def record_dislike(album_name, subgenre, visual, source="rejected"):
    profile = load_taste_profile()
    entry = {
        "album": album_name,
        "theme": visual or album_name,
        "subgenre": subgenre,
        "noted_at": datetime.now().strftime("%Y-%m-%d"),
        "source": f"{source} {album_name}",
    }
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
        alb = p.get("album", "?")
        entry = {
            "album": alb,
            "theme": p.get("visual", alb),
            "subgenre": p.get("subgenre", ""),
            "noted_at": datetime.now().strftime("%Y-%m-%d"),
            "source": f"skipped {alb}",
        }
        existing = {e.get("source") for e in profile["dislikes"]}
        if entry["source"] not in existing:
            profile["dislikes"].append(entry)
    save_taste_profile(profile)
    record_proposal_history(proposals)
    log(f"  ⏭ Recorded skip for {len(proposals)} proposals")


def _extract_album_from_entry(e):
    if e.get("album"):
        return e["album"].strip()
    src = e.get("source", "")
    for prefix in ("selected ", "loved ", "hated ", "rejected ", "skipped "):
        if src.startswith(prefix):
            return src[len(prefix):].strip()
    return src.strip()


def build_taste_block():
    """
    Build sonic/subgenre preference block WITHOUT feeding already-produced visual scenes
    as 'themes to repeat'. Explicitly marks past selected albums as ALREADY PRODUCED.
    """
    profile = load_taste_profile()
    lines = []

    rejected_subs = set(profile.get("rejected_subgenres", []))
    pref_subs = [s for s in profile.get("preferred_subgenres", []) if s not in rejected_subs]
    if pref_subs:
        # Use MOST RECENT preferred subgenres ([-10:]), not oldest ([:8])
        lines.append(f"PREFERRED SUBGENRES (prioritize these sonic hybrids): {', '.join(pref_subs[-10:])}")

    if profile.get("rejected_subgenres"):
        lines.append(f"AVOID THESE SUBGENRES: {', '.join(profile['rejected_subgenres'][-8:])}")

    if profile.get("dislikes"):
        disliked_themes = [e.get("theme", "") for e in profile["dislikes"][-10:] if e.get("theme")]
        if disliked_themes:
            lines.append(f"AVOID THESE DISLIKED CONCEPTS: {'; '.join(disliked_themes[-8:])}")

    if profile.get("notes"):
        for note in profile["notes"][-5:]:
            lines.append(f"USER NOTE: {note}")

    selected = [e for e in profile.get("likes", []) if "selected" in e.get("source", "")]
    if selected:
        sel_summary = []
        for e in selected[-8:]:
            alb = _extract_album_from_entry(e)
            sub = e.get("subgenre", "")
            if alb:
                sel_summary.append(f"{alb} ({sub})" if sub else alb)
        if sel_summary:
            lines.append(
                f"PAST PRODUCED ALBUMS (match this sonic tier, but NEVER reuse their titles or visual scenes): "
                f"{'; '.join(sel_summary)}"
            )

    return "\n".join(lines)


# ── Context Blocks for Sophisticated Concept Generation ─────────────────

def _load_profile():
    """Load the VØIDRIDE artist profile."""
    if PROFILE_FILE.exists():
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
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

    style = profile.get("style", {})
    if style.get("mood"):
        lines.append(f"  Mood: {style['mood']}")
    if style.get("instruments"):
        lines.append(f"  Core instruments & sound design: {style['instruments']}")
    if style.get("influences"):
        lines.append(f"  Influences: {style['influences']}")

    if dna.get("sound_signature"):
        lines.append(f"  Sound signature: {dna['sound_signature']}")
    if dna.get("anti_patterns"):
        lines.append(f"  Anti-patterns to AVOID: {', '.join(dna['anti_patterns'])}")

    prefix = profile.get("prompt_prefix", "")
    if prefix:
        lines.append(f"  Sonic signature details: \"{prefix[:400]}\"")

    return "\n".join(lines) if len(lines) > 1 else ""


def _clean_track_name(raw_name):
    name = re.sub(r'^\d+[\s_\-]*', '', str(raw_name))
    name = name.replace("_MASTER", "").replace("_", " ").replace("-", " ").strip().upper()
    return name


def gather_catalog():
    """
    Gather ALL released and produced albums from releases/, albums/, taste_profile, and proposal_history.
    Does NOT append single-track export directories that would push actual albums out of prompt slices.
    """
    albums_by_slug = {}

    for base_dir, status_label in [(RELEASES_DIR, "published"), (ALBUMS_DIR, "produced")]:
        if not base_dir.exists():
            continue
        for album_dir in sorted(base_dir.iterdir()):
            if not album_dir.is_dir() or album_dir.name.startswith(".") or album_dir.name == "voidride_v2_covers":
                continue
            slug = album_dir.name.lower().replace("_", "-")
            album_title = album_dir.name.upper().replace("-", " ").replace("_", " ")
            tracks = []
            mtime = album_dir.stat().st_mtime

            rj_path = album_dir / "release.json"
            if rj_path.exists():
                try:
                    with open(rj_path, "r", encoding="utf-8") as f:
                        rj = json.load(f)
                    if rj.get("album"):
                        album_title = rj["album"].upper().strip()
                    elif rj.get("title"):
                        album_title = rj["title"].upper().strip()
                    for t in rj.get("tracks", rj.get("tracklist", [])):
                        if isinstance(t, dict) and t.get("title"):
                            tracks.append(_clean_track_name(t["title"]))
                        elif isinstance(t, str):
                            tracks.append(_clean_track_name(t))
                except Exception:
                    pass

            if not tracks:
                for ext in ("*.flac", "*.mp3"):
                    found = [_clean_track_name(f.stem) for f in sorted(album_dir.glob(ext))]
                    if found:
                        tracks = found
                        break

            if slug not in albums_by_slug or (tracks and not albums_by_slug[slug]["tracks"]):
                albums_by_slug[slug] = {
                    "slug": slug,
                    "album": album_title,
                    "tracks": tracks,
                    "status": status_label,
                    "mtime": mtime,
                }

    # Sort chronologically by mtime (oldest first, newest last)
    catalog = sorted(albums_by_slug.values(), key=lambda x: x.get("mtime", 0))

    cover_themes = set()
    if ARTWORK_DIR.exists():
        for d in ARTWORK_DIR.iterdir():
            if d.is_dir():
                cover_themes.add(d.name)

    return catalog, sorted(cover_themes)


def gather_forbidden_registry(catalog):
    """
    Build comprehensive sets of forbidden album names, forbidden track names,
    and exhausted visual scenes from all releases, albums, taste profile, and proposal history.
    """
    forbidden_albums = set()
    forbidden_tracks = set()
    exhausted_visuals = []

    for c in catalog:
        alb = c.get("album", "").upper().strip()
        if alb:
            forbidden_albums.add(alb)
            forbidden_albums.add(alb.replace("-", " "))
        for t in c.get("tracks", []):
            t_clean = _clean_track_name(t)
            if t_clean and len(t_clean) > 2:
                forbidden_tracks.add(t_clean)

    taste = load_taste_profile()
    for group in ("likes", "dislikes"):
        for e in taste.get(group, []):
            alb = _extract_album_from_entry(e).upper().strip()
            if alb:
                forbidden_albums.add(alb)
                forbidden_albums.add(alb.replace("-", " "))
            vis = e.get("theme", "").strip()
            if vis and len(vis) > 15 and vis not in exhausted_visuals:
                exhausted_visuals.append(vis)

    history = load_proposal_history()
    for h in history:
        alb = h.get("album", "").upper().strip()
        if alb:
            forbidden_albums.add(alb)
            forbidden_albums.add(alb.replace("-", " "))
        vis = h.get("visual", "").strip()
        if vis and len(vis) > 15 and vis not in exhausted_visuals:
            exhausted_visuals.append(vis)
        for t in h.get("tracks", []):
            t_clean = _clean_track_name(t)
            if t_clean:
                forbidden_tracks.add(t_clean)

    # Also include current_proposals.json if it exists
    cur_file = PROPOSALS_DIR / "current_proposals.json"
    if cur_file.exists():
        try:
            with open(cur_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            for p in cdata.get("proposals", []):
                alb = p.get("album", "").upper().strip()
                if alb:
                    forbidden_albums.add(alb)
                    forbidden_albums.add(alb.replace("-", " "))
                vis = p.get("visual", "").strip()
                if vis and len(vis) > 15 and vis not in exhausted_visuals:
                    exhausted_visuals.append(vis)
                for t in p.get("tracks", []):
                    t_clean = _clean_track_name(t)
                    if t_clean:
                        forbidden_tracks.add(t_clean)
        except Exception:
            pass

    return forbidden_albums, forbidden_tracks, exhausted_visuals


def build_production_memory_block(catalog=None):
    """Block 2: PRODUCTION MEMORY — complete album discography + sonic stats."""
    if catalog is None:
        catalog, _ = gather_catalog()

    profile = _load_profile()
    prof_catalog = profile.get("catalog", [])

    bpms = []
    keys = []
    genres = []
    for c in prof_catalog:
        plan = c.get("plan", {})
        if isinstance(plan.get("bpm"), (int, float)):
            bpms.append(plan["bpm"])
        if plan.get("key"):
            keys.append(plan["key"])
        if plan.get("genre"):
            genres.append(plan["genre"])

    lines = [f"📀 COMPLETE PRODUCED DISCOGRAPHY ({len(catalog)} albums — DO NOT REPEAT ANY OF THESE):"]
    for a in catalog:
        t_preview = ", ".join(a["tracks"][:5]) if a.get("tracks") else "5 tracks"
        lines.append(f"  ✅ {a['album']}: {t_preview}")

    if bpms:
        lines.append(f"  ⚡ Catalog BPM distribution: min={min(bpms)}, max={max(bpms)}, avg={sum(bpms)//len(bpms)}")
    if keys:
        key_counts = Counter(keys).most_common(4)
        lines.append(f"  🎹 Most-used keys: {', '.join(f'{k} ({n}x)' for k, n in key_counts)}")
    if genres:
        genre_counts = Counter(genres).most_common(3)
        lines.append(f"  🎵 Most-used genres: {', '.join(f'{g} ({n}x)' for g, n in genre_counts)}")

    lines.append("  ⚠️ Propose 5 BRAND-NEW albums that never repeat any album title or track title above.")
    return "\n".join(lines)


def build_visual_identity_block(exhausted_visuals=None):
    """
    Block 3: VISUAL IDENTITY — defines the VØIDRIDE visual aesthetic while explicitly
    BLACKLISTING already-used cover scenes so the LLM invents brand-new locations/worlds.
    """
    lines = [
        "🎨 VISUAL IDENTITY & SCENE RULES:",
        "  • Aesthetic: Photorealistic 35mm anamorphic nocturne photography, obsidian/matte-black vehicles or",
        "    architectural environments, rain-slicked specular reflections, volumetric fog/mist, stark neon/amber",
        "    chiaroscuro lighting, high-contrast shadow depth.",
        "  • 🚫 EXHAUSTED / ALREADY-USED VISUAL SCENES (STRICTLY FORBIDDEN — DO NOT REUSE THESE SETTINGS):",
        "    - NO hospital basement bays, ambulances, morgues, or medical gurneys (already used in BASEMENT BAY / CHROMA-MORGUE)",
        "    - NO pawnshops, barred storefronts at 4AM, or security grilles (already used in PAWNSHOP ECLIPSE)",
        "    - NO freight locomotives, rail yards, or boxcar steel couplers (already used in NIGHT FREIGHT ZERO / YARDMASTER)",
        "    - NO sedans parked outside rain-slicked police precincts with cigarette smoke (already used in TRENCHCOAT VOLTAGE / PRECINCT)",
        "    - NO radio trucks beneath lattice transmission towers (already used in IONOSPHERE PIRATE / SIGNAL DECAY)",
        "    - NO lowriders on 3AM LA overpasses with sodium haze and palm silhouettes (already used in OVERPASS SODIUM)",
        "    - NO drift cars inside cathedral-sized underground parking structures (already used in SODIUM CATACOMB / TUNNEL VELOCITY)",
        "    - NO flooded subway tunnels with third-rail sparks (already used in TUNNEL VULTURE)",
        "    - NO derelict desert motels with neon VACANCY signs (already used in MOTEL VOID NEON)",
    ]

    if exhausted_visuals:
        recent_vis = exhausted_visuals[-12:]
        lines.append("  • Recently pitched/used scenes (DO NOT copy or paraphrase):")
        for v in recent_vis:
            lines.append(f"    ❌ \"{v[:110]}\"")

    lines.append(
        "  • ✨ REQUIREMENT: Invent 5 COMPLETELY FRESH nocturnal settings, architectural spaces, or coastal/urban/industrial/sci-fi environments never used above!"
    )
    return "\n".join(lines)


# ── Deduplication & Validation ──────────────────────────────────────────

def _significant_words(text):
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return {w for w in words if len(w) > 3 and w not in STOPWORDS}


def validate_proposal(p, forbidden_albums, forbidden_tracks, exhausted_visuals, seen_in_batch):
    """
    Programmatically verify that a proposal is genuinely new:
      - Not matching any existing/past album name or exhausted title keyword
      - Not reusing existing track titles
      - Not reusing exhausted visual settings or high-overlap visual descriptions
    Returns (is_valid, reason).
    """
    if not isinstance(p, dict):
        return False, "not a dict"

    album = str(p.get("album", "")).strip().upper()
    tracks = [str(t).strip().upper() for t in p.get("tracks", []) if str(t).strip()]
    visual = str(p.get("visual", "")).strip()

    if not album or len(tracks) < 5 or not visual:
        return False, f"incomplete fields for '{album}'"

    album_norm = album.replace("-", " ").replace("_", " ").strip()
    if album in forbidden_albums or album_norm in forbidden_albums:
        return False, f"album '{album}' already produced or proposed"

    if album_norm in seen_in_batch["albums"]:
        return False, f"duplicate album '{album}' within current batch"

    album_words = set(re.findall(r"[A-Z0-9]+", album_norm))
    overlap_exhausted = album_words & EXHAUSTED_TITLE_WORDS
    if overlap_exhausted:
        return False, f"album '{album}' reuses exhausted catalog word(s): {', '.join(overlap_exhausted)}"

    overlap_batch_words = album_words & seen_in_batch["title_words"]
    if overlap_batch_words:
        return False, f"album '{album}' shares title word(s) {overlap_batch_words} with another proposal in batch"

    if len(album_norm.split()) != 2:
        return False, f"album '{album_norm}' must be strictly 2 words (got {len(album_norm.split())})"

    for t in tracks[:5]:
        t_clean = _clean_track_name(t)
        if len(t_clean.split()) != 2:
            return False, f"track '{t_clean}' (in '{album}') must be strictly 2 words (got {len(t_clean.split())})"
        if t_clean in forbidden_tracks:
            return False, f"track '{t_clean}' (in '{album}') already exists in catalog/history"
        if t_clean in seen_in_batch["tracks"]:
            return False, f"duplicate track '{t_clean}' in batch"

    vis_lower = visual.lower()
    for phrase in EXHAUSTED_VISUAL_PHRASES:
        if phrase in vis_lower:
            return False, f"visual for '{album}' reuses exhausted setting '{phrase}'"

    vis_words = _significant_words(visual)
    if vis_words:
        for past_vis in exhausted_visuals:
            past_words = _significant_words(past_vis)
            if not past_words:
                continue
            shared = vis_words & past_words
            similarity = len(shared) / max(1, min(len(vis_words), len(past_words)))
            if len(shared) >= 5 or similarity >= 0.45:
                return False, f"visual for '{album}' is too similar to past scene ({len(shared)} shared keywords: {', '.join(sorted(shared)[:5])})"

        for batch_vis in seen_in_batch["visual_words"]:
            shared = vis_words & batch_vis
            if len(shared) >= 4:
                return False, f"visual for '{album}' is too similar to another proposal in batch"

    # Normalize track list to uppercase
    p["album"] = album_norm
    p["tracks"] = [_clean_track_name(t) for t in tracks[:5]]
    return True, "ok"


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

    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    repaired = re.sub(r',\s*([}\]])', r'\1', raw)
    try:
        return json.loads(repaired.strip())
    except json.JSONDecodeError:
        pass

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
    forbidden_albums, forbidden_tracks, exhausted_visuals = gather_forbidden_registry(catalog)

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

    sonic_block = build_sonic_identity_block()
    sonic_section = f"\n{sonic_block}\n" if sonic_block else ""

    memory_block = build_production_memory_block(catalog)
    memory_section = f"\n{memory_block}\n" if memory_block else ""

    visual_block = build_visual_identity_block(exhausted_visuals)
    visual_section = f"\n{visual_block}\n" if visual_block else ""

    forbidden_titles_str = ", ".join(sorted(forbidden_albums))
    forbidden_words_str = ", ".join(sorted(EXHAUSTED_TITLE_WORDS))

    base_prompt = f"""You are the creative director for VØIDRIDE, an elite music project fusing heavy California bass, West Coast bass music, and melodic nightride vibes with dark trap, witch house, and hyperspatial dynamic soundscapes.
Genres: california bass, west coast bass, melodic nightride trap, dark west coast phonk, witch house, cinematic nightride phonk, hyperspatial nightride bass.
{sonic_section}{memory_section}{visual_section}{theme_block}{seed_block}{taste_section}
🚫 STRICT ANTI-DUPLICATION & NOVELTY RULES:
- NEVER propose or paraphrase any of these already-produced/proposed albums: {forbidden_titles_str}
- NEVER use any of these exhausted words in an album title: {forbidden_words_str}
- NEVER reuse any setting listed under EXHAUSTED / ALREADY-USED VISUAL SCENES above (no hospital bays/ambulances, no pawnshops, no rail yards/locomotives, no police precincts, no radio towers/trucks, no 3AM LA overpasses, no underground parking garages, no desert motels, no subway tunnels).

Propose exactly 5 BRAND-NEW, 100% ORIGINAL HIT-RECORD EP concepts (Option 1B format: Tracks 1-4 are punchy ~3m streaming singles with distinct earworm hooks & bounce archetypes; Track 5 is an epic 3m35s extended widescreen closer). Each must:
1. Build on the VØIDRIDE sonic identity (infectious foreground melodic earworm hooks within 10s, dynamic tension-and-release builds/bridges, explosive California 808 sub-bass glides, punchy transient kicks, crisp snap snares, and velvet-smooth reverb-washed transitions)
2. Explore FRESH nocturnal worlds and imagery (e.g., coastal Pacific cliff highways in fog, subterranean flood-control channels, obsidian yachts in dark harbors, derelict aerospace hangars, desert solar-mirror arrays, rooftop helipads in rain, neon botanical conservatories, brutalist hydroelectric dams, shadowy canyon switchbacks, etc.)
3. Have a completely unique 2-word ALL CAPS album title and 5 ALL CAPS track titles (strictly 2 words each, so every album and song title stacks 1 word per line)
4. Include BPM range (within 122-154 BPM), key signature (e.g. Dm, Fm, Cm, Gm, Ebm), and specific hit-ready subgenre
5. Include a 1-line visual concept for cover art (photorealistic, dark, cinematic, zero text)
6. Include a 50-word production brief detailing the signature earworm lead hook motif, dynamic section contrast (filtered hook tease -> explosive 808 Drop 1 -> switch-up -> stripped bridge -> octave-lifted Climax Drop 2), and smooth hyperspatial depth
7. VARY the BPM pocket, key, setting, and hook timbre across all 5 proposals

RESPOND IN THIS EXACT JSON FORMAT ONLY (no markdown fences, no explanation):
[
  {{
    "album": "ALBUM NAME",
    "tracks": ["TRACK 1", "TRACK 2", "TRACK 3", "TRACK 4", "TRACK 5"],
    "bpm": "130-142",
    "key": "Dm",
    "subgenre": "california bass / melodic nightride trap",
    "visual": "Photorealistic 1-line visual scene in a brand-new nocturnal environment",
    "brief": "California bass meets melodic nightride trap with hyperspatial depth. Crushing 808 sub-bass with aggressive pitch slides, punchy acoustic transient kicks, and crisp snap snares. Melancholic detuned analog brass leads, nocturnal sine plucks, and wide 3D spatial delay throws over atmospheric reverb swells. 136 BPM, D minor, thundering West Coast bounce."
  }}
]"""

    models = [
        VENICE_MODEL,
        FALLBACK_MODEL,
        VENICE_MODEL,
        FALLBACK_MODEL,
        VENICE_MODEL,
        FALLBACK_MODEL,
        "qwen-3-8-flash",
        FALLBACK_MODEL,
    ]
    accepted_proposals = []
    seen_in_batch = {
        "albums": set(),
        "title_words": set(),
        "tracks": set(),
        "visual_words": [],
    }
    rejection_feedback = []

    for attempt in range(MAX_RETRIES):
        if len(accepted_proposals) >= REQUIRED_PROPOSAL_COUNT:
            break
        needed = REQUIRED_PROPOSAL_COUNT - len(accepted_proposals)
        ask_count = max(7, needed + 3)
        model = models[min(attempt, len(models) - 1)]
        log(f"  Attempt {attempt + 1}/{MAX_RETRIES} (model: {model}, need {needed} more valid proposals to reach {REQUIRED_PROPOSAL_COUNT}, requesting {ask_count})")

        prompt = base_prompt.replace(
            "Propose exactly 5 BRAND-NEW, 100% ORIGINAL HIT-RECORD EP concepts",
            f"Propose {ask_count} BRAND-NEW, 100% ORIGINAL HIT-RECORD EP concepts (we will select {needed} distinct ones)"
        )
        if seen_in_batch["albums"]:
            prompt += (
                "\n\n🚫 ALREADY ACCEPTED IN CURRENT BATCH (DO NOT REUSE ANY OF THESE ALBUM WORDS, TRACK TITLES, OR SETTINGS):\n"
                f"- Accepted Albums: {', '.join(sorted(seen_in_batch['albums']))}\n"
                f"- Forbidden Title Words (ZERO overlap allowed): {', '.join(sorted(seen_in_batch['title_words']))}\n"
                f"- Forbidden Track Names: {', '.join(sorted(seen_in_batch['tracks']))}\n"
            )
        if rejection_feedback:
            prompt += (
                "\n\n⚠️ PREVIOUS ATTEMPT REJECTED FOR DUPLICATION — DO NOT REPEAT THESE ERRORS:\n"
                + "\n".join(f"- {r}" for r in rejection_feedback[-10:])
            )

        v_params = {"include_venice_system_prompt": False, "strip_thinking_response": True}
        if "qwen" in model:
            v_params["disable_thinking"] = True
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
            "max_tokens": 4800,
            "venice_parameters": v_params,
        }

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{VENICE_API_BASE}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {VENICE_API_KEY}"}
        )

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
                if not raw:
                    log("  Venice API returned empty response")
                    continue
                result = json.loads(raw)
                msg = result["choices"][0]["message"]
                content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                log(f"  Venice response length: {len(content)} chars")

                proposals = repair_json(content)
                if proposals and isinstance(proposals, list):
                    for p in proposals:
                        if len(accepted_proposals) >= REQUIRED_PROPOSAL_COUNT:
                            break
                        ok, reason = validate_proposal(
                            p,
                            forbidden_albums,
                            forbidden_tracks,
                            exhausted_visuals,
                            seen_in_batch,
                        )
                        if ok:
                            accepted_proposals.append(p)
                            alb_norm = p["album"]
                            seen_in_batch["albums"].add(alb_norm)
                            seen_in_batch["title_words"].update(re.findall(r"[A-Z0-9]+", alb_norm))
                            seen_in_batch["tracks"].update(p["tracks"])
                            seen_in_batch["visual_words"].append(_significant_words(p["visual"]))
                            log(f"    ✓ Accepted ({len(accepted_proposals)}/{REQUIRED_PROPOSAL_COUNT}): {p['album']} ({p.get('subgenre', '?')})")
                        else:
                            log(f"    ✗ Rejected duplicate/exhausted proposal: {reason}")
                            rejection_feedback.append(reason)
                else:
                    log("  ⚠ JSON repair failed, retrying...")

        except json.JSONDecodeError as e:
            log(f"  JSON parse error: {e}")
        except Exception as e:
            log(f"  Venice API error: {e}")

        if len(accepted_proposals) < REQUIRED_PROPOSAL_COUNT and attempt < MAX_RETRIES - 1:
            time.sleep(2)

    if len(accepted_proposals) >= REQUIRED_PROPOSAL_COUNT:
        log(f"  ✓ Validated {REQUIRED_PROPOSAL_COUNT} brand-new proposals")
        return accepted_proposals[:REQUIRED_PROPOSAL_COUNT]

    log(f"✗ All retries exhausted with only {len(accepted_proposals)}/{REQUIRED_PROPOSAL_COUNT} valid proposals (strictly require {REQUIRED_PROPOSAL_COUNT})")
    return None


def query_venice_refine(existing_proposals, refinement, catalog, cover_themes):
    forbidden_albums, forbidden_tracks, exhausted_visuals = gather_forbidden_registry(catalog)
    # Remove current batch titles from forbidden only if user asks to keep some, but still block produced albums
    produced_albums = {c["album"].upper().replace("-", " ") for c in catalog}

    existing_text = json.dumps(existing_proposals, indent=2)
    taste_block = build_taste_block()
    taste_section = f"\n📊 USER TASTE PROFILE:\n{taste_block}\n" if taste_block else ""
    sonic_block = build_sonic_identity_block()
    sonic_section = f"\n{sonic_block}\n" if sonic_block else ""
    memory_block = build_production_memory_block(catalog)
    memory_section = f"\n{memory_block}\n" if memory_block else ""
    visual_block = build_visual_identity_block(exhausted_visuals)
    visual_section = f"\n{visual_block}\n" if visual_block else ""

    prompt = f"""You are the creative director for VØIDRIDE, an elite music project fusing heavy California bass and West Coast bass with melodic nightride vibes, dark trap, witch house, and hyperspatial nightride phonk.
{sonic_section}

Here are the current 5 album proposals:
{existing_text}

{memory_section}{visual_section}{taste_section}
The user wants these proposals REFINED with this feedback:
🎯 "{refinement}"

Generate 5 REFINED album proposals that incorporate the user's feedback.
NEVER reuse any already-produced album title ({', '.join(sorted(produced_albums))}) or exhausted setting.
Ensure all proposals maintain the VØIDRIDE aesthetic: heavy California / West Coast 808 sub-bass slides, punchy transient acoustic kicks, crisp snap snares, and melodic nocturnal nightride atmospheres.

RESPOND IN THIS EXACT JSON FORMAT ONLY (no markdown fences, no explanation):
[
  {{
    "album": "ALBUM NAME",
    "tracks": ["TRACK 1", "TRACK 2", "TRACK 3", "TRACK 4", "TRACK 5"],
    "bpm": "130-145",
    "key": "Dm",
    "subgenre": "california bass / melodic nightride trap",
    "visual": "Dark cinematic visual concept description",
    "brief": "50-word production brief detailing heavy California / West Coast bass, sliding 808s, transient kicks, and melodic nightride synth hooks."
  }}
]"""

    models = [VENICE_MODEL, FALLBACK_MODEL, "deepseek-v4-flash", "llama-3.3-70b", "qwen-3-7-plus", "deepseek-v4-flash"]
    accepted_refined = []
    seen_refined_albums = set()
    for attempt in range(len(models)):
        if len(accepted_refined) >= REQUIRED_PROPOSAL_COUNT:
            break
        needed = REQUIRED_PROPOSAL_COUNT - len(accepted_refined)
        model = models[min(attempt, len(models) - 1)]
        log(f"  Refine attempt {attempt + 1}/{len(models)} (model: {model}, need {needed} more to reach {REQUIRED_PROPOSAL_COUNT})")
        cur_prompt = prompt
        if seen_refined_albums:
            cur_prompt += f"\n\nAlready refined in this batch (do not duplicate): {', '.join(sorted(seen_refined_albums))}"
        v_params = {"include_venice_system_prompt": False, "strip_thinking_response": True}
        if "qwen" in model:
            v_params["disable_thinking"] = True
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": cur_prompt}],
            "temperature": 0.85,
            "max_tokens": 4500,
            "venice_parameters": v_params,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{VENICE_API_BASE}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {VENICE_API_KEY}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
                if not raw:
                    continue
                result = json.loads(raw)
                msg_obj = result["choices"][0]["message"]
                content = (msg_obj.get("content") or msg_obj.get("reasoning_content") or "").strip()
                log(f"  Venice response length: {len(content)} chars")
                proposals = repair_json(content)
                if proposals and isinstance(proposals, list):
                    for p in proposals:
                        if len(accepted_refined) >= REQUIRED_PROPOSAL_COUNT:
                            break
                        if not isinstance(p, dict) or not p.get("album"):
                            continue
                        alb_u = str(p["album"]).strip().upper().replace("-", " ")
                        tracks_u = [str(t).strip().upper() for t in p.get("tracks", []) if str(t).strip()]
                        if len(tracks_u) < 5 or alb_u in produced_albums or alb_u in seen_refined_albums:
                            continue
                        p["album"] = alb_u
                        p["tracks"] = tracks_u[:5]
                        accepted_refined.append(p)
                        seen_refined_albums.add(alb_u)
                    if len(accepted_refined) >= REQUIRED_PROPOSAL_COUNT:
                        log(f"  ✓ Refined {REQUIRED_PROPOSAL_COUNT} proposals")
                        return accepted_refined[:REQUIRED_PROPOSAL_COUNT]
        except Exception as e:
            log(f"  Refine error: {e}")
        if attempt < len(models) - 1:
            time.sleep(2)
    log(f"✗ Refine failed to reach {REQUIRED_PROPOSAL_COUNT} proposals (got {len(accepted_refined)})")
    return None


# ── Venice Credit Check & Telegram (Option 1B Hit-Song & Demucs Harmonic Synth Budget) ──

AVG_TRACK_COST_USD = 2.24      # Avg across 4 singles @ $2.10 ($2.08 elevenlabs-music-v2-5 <=180s + $0.02 foley) + 1 closer @ $2.78 (215s)
AVG_TRACKS_TOTAL_USD = 11.18   # 4 × $2.10 + 1 × $2.78 = $11.18 (Demucs harmonic beds & SFX vault = $0.00!)
AVG_COVERS_COST_USD = 0.52     # 6 covers ($0.24) + 6 post-approval upscales ($0.12) + $0.00 local 3K waveforms + ~$0.16 buffer
AVG_ALBUM_COST_USD = 11.70     # Average total full album cost (~$11.70 USD — 47% savings vs prior $21.97!)


def check_venice_album_budget():
    """
    Query live Venice AI balance via /api/v1/api_keys/rate_limits and compare
    against the average full 5-track VØIDRIDE album cost (~$21.97 USD).
    """
    if not VENICE_API_KEY:
        return {
            "ok": False,
            "usd": 0.0,
            "diem": 0.0,
            "bundled": 0.0,
            "total_usd": 0.0,
            "avg_track_cost": AVG_TRACK_COST_USD,
            "avg_tracks_total": AVG_TRACKS_TOTAL_USD,
            "avg_covers_cost": AVG_COVERS_COST_USD,
            "avg_album_cost": AVG_ALBUM_COST_USD,
            "completable_tracks": 5,
            "shortfall": 0.0,
            "sufficient": True,
            "error": "No VENICE_API_KEY",
        }

    req = urllib.request.Request(
        f"{VENICE_API_BASE}/api_keys/rate_limits",
        headers={
            "Authorization": f"Bearer {VENICE_API_KEY}",
            "User-Agent": "Mozilla/5.0",
        },
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            data = payload.get("data", {})
            balances = data.get("balances", {})
            usd = float(balances.get("USD", 0.0) or 0.0)
            diem = float(balances.get("DIEM", 0.0) or 0.0)
            bundled = float(balances.get("BUNDLED_CREDITS", 0.0) or 0.0)
            total_usd = round(usd + diem + bundled, 2)
            completable_tracks = min(5, int(total_usd // AVG_TRACK_COST_USD))
            shortfall = round(max(0.0, AVG_ALBUM_COST_USD - total_usd), 2)
            sufficient = total_usd >= AVG_ALBUM_COST_USD

            report = {
                "timestamp": datetime.now().isoformat(),
                "ok": True,
                "usd": round(usd, 2),
                "diem": round(diem, 2),
                "bundled": round(bundled, 2),
                "total_usd": total_usd,
                "avg_track_cost": AVG_TRACK_COST_USD,
                "avg_tracks_total": AVG_TRACKS_TOTAL_USD,
                "avg_covers_cost": AVG_COVERS_COST_USD,
                "avg_album_cost": AVG_ALBUM_COST_USD,
                "completable_tracks": completable_tracks,
                "shortfall": shortfall,
                "sufficient": sufficient,
            }
            for status_path in ("/tmp/venice_balance_status.json", "/opt/data/music/venice_balance_status.json"):
                try:
                    Path(status_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(status_path, "w", encoding="utf-8") as sf:
                        json.dump(report, sf, indent=2)
                except Exception:
                    pass
            return report
        except Exception as e:
            if attempt == 1:
                log(f"  ⚠ Venice balance check failed: {e}")
                return {
                    "ok": False,
                    "usd": 0.0,
                    "diem": 0.0,
                    "bundled": 0.0,
                    "total_usd": 0.0,
                    "avg_track_cost": AVG_TRACK_COST_USD,
                    "avg_tracks_total": AVG_TRACKS_TOTAL_USD,
                    "avg_covers_cost": AVG_COVERS_COST_USD,
                    "avg_album_cost": AVG_ALBUM_COST_USD,
                    "completable_tracks": 5,
                    "shortfall": 0.0,
                    "sufficient": True,
                    "error": str(e),
                }
            time.sleep(1.0)


def send_proposals(proposals, dry_run=False, theme=None, is_refined=False):
    if not proposals or len(proposals) < REQUIRED_PROPOSAL_COUNT:
        log(f"✗ Refusing to send incomplete proposal batch ({len(proposals) if proposals else 0}/{REQUIRED_PROPOSAL_COUNT} — strictly require {REQUIRED_PROPOSAL_COUNT})")
        return False
    proposals = proposals[:REQUIRED_PROPOSAL_COUNT]

    budget = check_venice_album_budget()
    low_credits = bool(budget.get("ok") and not budget.get("sufficient"))
    if budget.get("ok"):
        status_tag = "SUFFICIENT" if budget["sufficient"] else f"SHORTFALL ${budget['shortfall']:.2f}"
        log(
            f"Venice balance check: ${budget['total_usd']:.2f} USD available "
            f"(avg full album cost: ~${budget['avg_album_cost']:.2f} USD | "
            f"can complete {budget['completable_tracks']}/5 tracks | {status_tag})"
        )

    if is_refined:
        lines = ["🎵 *VØIDRIDE — Refined Proposals*\n"]
    elif theme:
        lines = [f"🎵 *VØIDRIDE — Album Proposals*\n🎯 Theme: _{theme}_\n"]
    else:
        lines = ["🎵 *VØIDRIDE — Fresh Album Proposals*\n"]

    if low_credits:
        lines.append(
            f"⚠️ *INSUFFICIENT VENICE CREDITS FOR FULL ALBUM*\n"
            f"• *Available Credits:* ${budget['total_usd']:.2f} USD (${budget['usd']:.2f} USD / {budget['diem']:.2f} DIEM)\n"
            f"• *Avg Full Album Cost:* ~${budget['avg_album_cost']:.2f} USD (${budget['avg_tracks_total']:.2f} for 5 tracks + ${budget['avg_covers_cost']:.2f} artwork)\n"
            f"• *Current Capacity:* Only *{budget['completable_tracks']}/5 tracks* can be completed (*${budget['shortfall']:.2f} USD needed*)\n"
            f"👉 _Top up Venice credits and tap_ *💳 Credit Added* _below, or tap_ *⏸ Pause* _to hold._\n"
            f"─────────────────────\n"
        )
    elif budget.get("ok"):
        lines.append(
            f"💳 *Venice Credits:* ${budget['total_usd']:.2f} USD _(Avg Album: ~${budget['avg_album_cost']:.2f} — ✅ 5/5 tracks funded)_\n"
        )

    for i, p in enumerate(proposals[:5], 1):
        tracks = " · ".join(p.get("tracks", [])[:5])
        lines.append(
            f"*{i}️⃣  {p['album']}*\n"
            f"    _{p.get('subgenre', '?')}_ · {p.get('bpm', '?')} BPM · {p.get('key', '?')}\n"
            f"    🎨 {p.get('visual', '')}\n"
            f"    🎶 {tracks}\n"
        )

    if low_credits:
        lines.append(
            f"\n─────────────────────\n"
            f"⚠️ *Low Credits:* Need *+${budget['shortfall']:.2f} USD* to reach ~${budget['avg_album_cost']:.2f} avg album cost.\n"
            f"👆 *Tap 💳 Credit Added after topping up, ⏸ Pause, or select an album below*"
        )
    else:
        lines.append("\n─────────────────────\n👆 *Tap to produce, ❤️/👎 to train taste*")
    msg = "\n".join(lines)

    buttons = []
    if low_credits:
        buttons.append([
            {"text": "💳 Credit Added", "callback_data": "ap:credit:added"},
            {"text": "⏸ Pause", "callback_data": "ap:credit:pause"},
        ])
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
    if low_credits:
        buttons.append([
            {"text": "💳 Credit Added", "callback_data": "ap:credit:added"},
            {"text": "⏸ Pause", "callback_data": "ap:credit:pause"},
        ])

    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    proposals_file = PROPOSALS_DIR / "current_proposals.json"

    # Archive previous current_proposals into proposal_history before overwriting
    if proposals_file.exists():
        try:
            with open(proposals_file, "r", encoding="utf-8") as pf:
                old_data = json.load(pf)
            if old_data.get("proposals"):
                record_proposal_history(old_data["proposals"])
        except Exception:
            pass

    with open(proposals_file, "w", encoding="utf-8") as f:
        save_data = {
            "proposals": proposals[:5],
            "created_at": datetime.now().isoformat(),
            "venice_budget": budget,
        }
        if theme:
            save_data["theme"] = theme
        json.dump(save_data, f, indent=2)
    log(f"Saved proposals to {proposals_file}")

    # Also record the newly generated proposals into proposal_history
    record_proposal_history(proposals[:5])

    if dry_run:
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "replace").decode("ascii"))
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
        with open(proposals_file, "r", encoding="utf-8") as f:
            data = json.load(f)
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
    if EXPORTS_DIR.exists():
        for d in EXPORTS_DIR.iterdir():
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
            with open(proposals_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
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
    log(f"Found {len(catalog)} produced albums, {len(cover_themes)} cover themes")
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
