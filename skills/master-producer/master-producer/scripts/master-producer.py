#!/usr/bin/env python3
"""
Master Producer — Multi-model AI music production pipeline.

Generates multiple audio stems using different Venice AI models,
then mixes and masters them with ffmpeg for studio-quality output.

Pipeline:
  1. Generate stems (main track, texture, accents, atmosphere)
  2. Mix stems with volume balancing and stereo placement
  3. Master with compression, EQ, loudness normalization, limiting
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# Path to the venice-music.py script
VENICE_SCRIPT = "/opt/data/skills/venice-music/venice-music/scripts/venice-music.py"
DEFAULT_OUTPUT_DIR = "/opt/data/music"

# Telegram progress notifications
_CHAT_ID = None
_BOT_TOKEN = None


def _auto_detect_telegram():
    """Auto-detect Telegram bot token and chat ID from Hermes environment."""
    global _CHAT_ID, _BOT_TOKEN
    _BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not _BOT_TOKEN:
        return
    if _CHAT_ID:
        return
    sessions_path = os.path.join(
        os.environ.get("HERMES_HOME", "/opt/data"), "sessions", "sessions.json"
    )
    try:
        with open(sessions_path, "r") as f:
            sessions = json.load(f)
        latest = None
        for key, sess in sessions.items():
            if "telegram" in key:
                origin = sess.get("origin", {})
                chat_id = origin.get("chat_id")
                if chat_id:
                    updated = sess.get("updated_at", "")
                    if not latest or updated > latest[0]:
                        latest = (updated, chat_id)
        if latest:
            _CHAT_ID = latest[1]
            log(f"Auto-detected Telegram chat_id: {_CHAT_ID}")
    except Exception:
        pass
_SILENT_MODE = False  # Set by --no-deliver to suppress Telegram spam


def telegram_notify(msg):
    """Send a progress message to the user's Telegram chat."""
    if _SILENT_MODE or not _CHAT_ID or not _BOT_TOKEN:
        return
    try:
        payload = json.dumps({"chat_id": _CHAT_ID, "text": msg, "parse_mode": "Markdown"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


# ─── Progress Reporting ─────────────────────────────────────────────────
_PROGRESS_FILE = os.environ.get("TRACK_PROGRESS_FILE", "")
_PIPELINE_START = None

PHASE_NAMES = {
    "director": "Creative Director (K3)",
    "research": "Genre Research",
    "compose": "Prompt Composition",
    "stems": "Generating Stems",
    "b_section": "B-Section",
    "analysis": "Stem Analysis",
    "effects": "Stem Effects",
    "mixing": "Mixing",
    "mastering": "Mastering",
    "encoding": "Encoding",
    "delivery": "Delivery",
    "done": "Complete",
}


def report_progress(phase, detail=""):
    """Write current pipeline phase to progress file for upstream consumers."""
    global _PIPELINE_START
    if not _PROGRESS_FILE:
        return
    if _PIPELINE_START is None:
        _PIPELINE_START = time.time()
    try:
        elapsed = time.time() - _PIPELINE_START
        progress = {
            "phase": phase,
            "phase_name": PHASE_NAMES.get(phase, phase),
            "detail": detail,
            "elapsed_s": round(elapsed, 1),
            "timestamp": time.time(),
        }
        with open(_PROGRESS_FILE, "w") as f:
            json.dump(progress, f)
    except Exception:
        pass


def telegram_send_audio(filepath, title="Hermes Music", performer="Hermes", caption=""):
    """Send an audio file to the user's Telegram chat via sendAudio API."""
    if not _CHAT_ID or not _BOT_TOKEN:
        log("  ⚠️ No Telegram credentials — skipping file delivery")
        return False
    try:
        import mimetypes
        boundary = "----HermesBoundary"
        filename = os.path.basename(filepath)

        # Build multipart form data manually (no requests library)
        body = bytearray()
        # chat_id field
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{_CHAT_ID}\r\n".encode())
        # title field
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n{title}\r\n".encode())
        # performer field
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"performer\"\r\n\r\n{performer}\r\n".encode())
        # caption field
        if caption:
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode())
        # audio file
        content_type = mimetypes.guess_type(filename)[0] or "audio/mpeg"
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode())
        with open(filepath, "rb") as f:
            body.extend(f.read())
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendAudio",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read().decode())
        if result.get("ok"):
            log(f"  ✅ Delivered to Telegram: {filename}")
            return True
        else:
            log(f"  ⚠️ Telegram delivery failed: {result}")
            return False
    except Exception as e:
        log(f"  ⚠️ Telegram delivery error: {e}")
        return False

# Quality tier definitions
QUALITY_TIERS = {
    "quick": {
        "stems": ["main", "texture"],
        "description": "Quick 2-stem mix (main + ambient texture)",
    },
    "standard": {
        "stems": ["main", "texture", "accent"],
        "description": "Standard 3-stem mix (main + texture + accent FX)",
    },
    "premium": {
        "stems": ["main", "texture", "accent", "atmosphere"],
        "description": "Premium 4-stem mix (main + texture + accent + atmosphere)",
    },
}

# Stem configuration: model selection and prompt derivation
STEM_CONFIG = {
    "main": {
        "model_vocal": "ace-step-15",           # Cheapest vocal ($0.03), structured [Verse]/[Chorus]
        "model_vocal_freeform": "minimax-music-v26",  # Freeform vocal ($0.04)
        "model_vocal_premium": "elevenlabs-music",   # Premium vocal ($0.69)
        "model_instrumental": "elevenlabs-music",
        "model_instrumental_budget": "ace-step-15",
        "prompt_template": "{prompt}",
        "mix_volume": 1.0,   # Full volume for main track
        "pan": 0.0,          # Center
    },
    "texture": {
        "model": "stable-audio-25",
        "prompt_template": "Smooth complementary background layer for: {prompt}. Warm chords, subtle harmonic support, musical pad that blends naturally",
        "duration_override": None,  # Will match main or cap at 180s
        "mix_volume": 0.22,  # Subtle background (reduced to not compete)
        "pan": 0.0,          # Center (wide)
    },
    "accent": {
        "model": "elevenlabs-sound-effects-v2",
        "prompt_template": "Short musical transition: riser sweep into crisp impact hit, punchy and clean, 5 seconds",
        "mix_volume": 0.45,  # Higher volume since it's only placed at transitions
        "pan": 0.0,          # Center for impact
        "placement": "transitions",  # Only place at detected transitions, not full duration
        "max_duration": 8,           # Accent should be short (seconds)
    },
    "atmosphere": {
        "model": "stable-audio-25",   # Switched from mmaudio — stable-audio makes MUSIC not noise
        "prompt_template": "Ambient atmospheric music bed, slow evolving reverb texture, subtle harmonic undertone for: {prompt}. Soft, musical, cinematic depth",
        "mix_volume": 0.15,  # Very subtle depth
        "pan": -0.25,        # Slightly left for width
    },
    "b_section": {
        "model": "stable-audio-25",
        "prompt_template": "Atmospheric minimal breakdown version: {prompt}. Sparse, filtered, spacious",
        "mix_volume": 0.35,  # Moderate — only audible during breakdown via arrangement
        "pan": 0.15,         # Slightly right for contrast with atmosphere
    },
}

# Target mastering profiles
TARGET_PROFILES = {
    "streaming": {
        "description": "Streaming platforms (Spotify, Apple Music)",
        "lufs": -14, "true_peak": -1, "lra": 11,
        "hp_freq": 30, "hp_order": 2,
        "comp_threshold": -20, "comp_ratio": 4, "comp_attack": 10, "comp_release": 200, "comp_makeup": 2,
        "eq": [
            {"f": 3000, "w": 1.5, "g": 2},
            {"f": 12000, "w": 1.0, "g": 1.5},
            {"f": 80, "w": 0.8, "g": 1},
        ],
        "stereo_mid": 1.0, "stereo_side": 1.0,
        "sample_rate": 48000,
        "primary_format": "flac",
        "outputs": ["flac", "mp3"],
        "export_stems": False,
    },
    "l-acoustics": {
        "description": "L-Acoustics PA systems (K1/K2, KARA, L-ISA)",
        "lufs": -8, "true_peak": -0.3, "lra": 15,
        "hp_freq": 20, "hp_order": 2,  # ffmpeg highpass 'p' only accepts 1 or 2
        "mono_fold_below": 80,
        "comp_threshold": -16, "comp_ratio": 2, "comp_attack": 25, "comp_release": 500, "comp_makeup": 1,
        "eq": [
            {"f": 55, "w": 0.7, "g": 1.5},
            {"f": 275, "w": 2.0, "g": -2.5},
            {"f": 3500, "w": 2.0, "g": -1},
            {"f": 8000, "w": 1.2, "g": 1.5},
            {"f": 14000, "w": 0.8, "g": 1},
            {"f": 16000, "w": 1.0, "g": -0.5},
        ],
        "stereo_mid": 1.12, "stereo_side": 0.89,
        "sample_rate": 96000,
        "primary_format": "aiff",
        "outputs": ["aiff", "wav", "flac", "mp3"],
        "export_stems": True,
    },
    "club": {
        "description": "Club/DJ sound systems",
        "lufs": -10, "true_peak": -0.5, "lra": 13,
        "hp_freq": 25, "hp_order": 2,  # ffmpeg highpass 'p' only accepts 1 or 2
        "mono_fold_below": 80,
        "comp_threshold": -18, "comp_ratio": 3, "comp_attack": 15, "comp_release": 300, "comp_makeup": 1.5,
        "eq": [
            {"f": 55, "w": 0.7, "g": 1},
            {"f": 250, "w": 2.0, "g": -1.5},
            {"f": 3000, "w": 1.5, "g": 1.5},
            {"f": 12000, "w": 1.0, "g": 1},
        ],
        "stereo_mid": 1.06, "stereo_side": 0.95,
        "sample_rate": 48000,
        "primary_format": "wav",
        "outputs": ["wav", "flac", "mp3"],
        "export_stems": False,
    },
    "headphones": {
        "description": "Studio reference headphones",
        "lufs": -16, "true_peak": -1, "lra": 14,
        "hp_freq": 20, "hp_order": 2,
        "comp_threshold": -22, "comp_ratio": 2, "comp_attack": 20, "comp_release": 400, "comp_makeup": 1,
        "eq": [
            {"f": 3000, "w": 1.5, "g": 1},
            {"f": 12000, "w": 1.0, "g": 1},
            {"f": 80, "w": 0.8, "g": 0.5},
        ],
        "stereo_mid": 1.0, "stereo_side": 1.0,
        "sample_rate": 48000,
        "primary_format": "flac",
        "outputs": ["flac", "mp3"],
        "export_stems": False,
    },
}

# Per-stem high-pass filters for L-ISA frequency separation
STEM_HP_FILTERS = {
    "main": None,
    "texture": "highpass=f=300",
    "accent": "highpass=f=500",
    "atmosphere": "highpass=f=300",
}


def log(msg):
    """Log to stderr so stdout stays clean for JSON output."""
    print(f"[master-producer] {msg}", file=sys.stderr, flush=True)


def fail(msg):
    """Output error JSON and exit."""
    print(json.dumps({"success": False, "error": msg}))
    sys.exit(1)


def slugify(text, max_len=30):
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = text.strip('-')
    if len(text) > max_len:
        text = text[:max_len].rsplit('-', 1)[0]
    return text or 'untitled'


def create_session_dir(base_dir, prompt):
    """Create a named session directory under productions/."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify(prompt)
    session_name = f"{timestamp}_{slug}"
    session_dir = os.path.join(base_dir, "productions", session_name)
    stems_dir = os.path.join(session_dir, "stems")
    os.makedirs(stems_dir, exist_ok=True)
    return session_dir, stems_dir


PROFILES_SCRIPT = "/opt/data/skills/producer-profiles/producer-profiles/scripts/profiles.py"


def load_active_profile():
    """Load the active DJ profile by reading the .active file."""
    profiles_dir = os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "music", "profiles")
    active_file = os.path.join(profiles_dir, ".active")
    if not os.path.isfile(active_file):
        return None
    try:
        with open(active_file) as f:
            active_slug = f.read().strip()
        if not active_slug:
            return None
        profile_path = os.path.join(profiles_dir, active_slug, "profile.json")
        if not os.path.isfile(profile_path):
            log(f"  ⚠️ Active profile '{active_slug}' not found on disk")
            return None
        with open(profile_path) as f:
            profile = json.load(f)
        log(f"  Active profile: {profile.get('name', active_slug)}")
        return profile
    except Exception as e:
        log(f"  ⚠️ Failed to load active profile: {e}")
        return None


def compose_prompt(user_prompt, profile=None):
    """Use Venice LLM to enhance a vague prompt into a detailed production brief."""
    api_key = os.environ.get("VENICE_API_KEY", "")
    if not api_key:
        log("  ⚠️ No VENICE_API_KEY — skipping prompt composition")
        return user_prompt

    # Build profile hint (compact, not a list)
    profile_hint = ""
    if profile:
        style = profile.get("style", {})
        parts = []
        if style.get("genres"):
            parts.append(f"genres: {style['genres']}")
        if style.get("mood"):
            parts.append(f"mood: {style['mood']}")
        if style.get("instruments"):
            parts.append(f"instruments: {style['instruments']}")
        if style.get("influences"):
            parts.append(f"influences: {style['influences']}")
        if parts:
            profile_hint = f" Incorporate these style preferences: {', '.join(parts)}."

    system = (
        "You are a music prompt engineer. Transform the input into a single flowing paragraph "
        "that describes a song for an AI music generator. Include genre, BPM as a number, "
        "musical key, specific instruments and sounds, mood, and energy arc. "
        "Write it as one continuous description — NO bullet points, NO lists, NO labels, "
        "NO headers, NO markdown, NO explanations, NO meta-commentary. "
        "Do NOT start with 'Here is' or 'The user wants' or 'Looking at'. "
        "IMPORTANT: Use only music-production language. Avoid violent or aggressive words "
        "like 'assault', 'attack', 'brutal', 'destroy', 'violent', 'weapon', 'war', 'blood'. "
        "Instead use music terms: 'powerful', 'intense', 'heavy', 'massive', 'thundering'. "
        "Include a suggested song structure at the end, like: "
        "'Structure: 8-bar filtered intro, 16-bar main drop, 8-bar minimal breakdown, 16-bar final drop'. "
        "Just output the music description paragraph directly."
        f"{profile_hint}"
    )

    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt[:800]},  # Cap input length
        ],
        "max_tokens": 500,
        "temperature": 0.7,
    }).encode()

    try:
        req = urllib.request.Request(
            "https://api.venice.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode())
        enhanced = result["choices"][0]["message"]["content"].strip()
        # Strip thinking tags
        if "<think>" in enhanced:
            enhanced = enhanced.split("</think>")[-1].strip()
        # Strip meta-commentary — detect if LLM is analyzing instead of prompting
        bad_starts = [
            "The user", "Looking at", "I need to", "Let me", "Here is",
            "Here's", "Based on", "This production", "The request",
            "Given the", "For this",
        ]
        is_meta = any(enhanced.startswith(p) for p in bad_starts)
        has_bullets = "\n-" in enhanced or "\n*" in enhanced or "\n1." in enhanced
        if is_meta or has_bullets:
            # Try to extract actual prompt from after meta-commentary
            if "\n\n" in enhanced:
                paragraphs = [p.strip() for p in enhanced.split("\n\n") if p.strip()]
                # Find longest paragraph without bullets
                clean = [p for p in paragraphs if "\n-" not in p and "\n*" not in p and len(p) > 30]
                if clean:
                    enhanced = max(clean, key=len)
                    log(f"  ⚠️ Stripped meta-commentary, extracted {len(enhanced)} char prompt")
                else:
                    log(f"  ⚠️ Compose returned meta-commentary — using original prompt")
                    return user_prompt
            else:
                log(f"  ⚠️ Compose returned meta-commentary — using original prompt")
                return user_prompt
        if enhanced and len(enhanced) > 20:
            compose_cost = result.get("cost", {}).get("usd", 0)
            log(f"  ✅ Prompt composed ({len(enhanced)} chars, ${compose_cost:.4f})")
            log(f"  Enhanced: {enhanced[:150]}...")
            return enhanced
        else:
            log("  ⚠️ Compose returned empty — using original prompt")
            return user_prompt
    except Exception as e:
        log(f"  ⚠️ Compose failed ({e}) — using original prompt")
        return user_prompt


def research_genre(user_prompt, profile=None):
    """Deep genre research via Venice LLM — produces expert-level production briefs."""
    api_key = os.environ.get("VENICE_API_KEY", "")
    if not api_key:
        log("  ⚠️ No VENICE_API_KEY — skipping genre research")
        return user_prompt

    system = """You are a professional music producer and genre researcher with 20 years of experience.
Given a song request, produce an expert-level production brief.

Your response MUST include ALL of these:
1. EXACT genre classification (main genre + 2-3 subgenres)
2. BPM (exact number, based on genre norms)
3. Musical key (with reasoning, e.g. "Dm is the darkest minor key, standard for dark DnB")
4. DETAILED sound palette (8-10 specific sounds with synthesis/recording descriptions):
   - e.g., "Reese bass: detuned saw waves with slow LFO modulation on filter cutoff"
   - e.g., "Amen break: pitched down -3 semitones, chopped, heavy parallel compression"
5. Song structure with approximate bar counts:
   - e.g., "Intro (8 bars, filtered pad) → Build (8 bars, adding hats+riser) → Drop (16 bars, full energy)"
6. Mix characteristics:
   - Frequency balance (e.g., "sub-heavy below 60Hz, scooped 200-400Hz, crispy 8k+")
   - Stereo image (e.g., "mono bass center, wide reverb tails, stereo percussion")
7. 3 well-known reference tracks in this exact style
8. Production techniques specific to this genre
9. What to AVOID (common mistakes that ruin this genre)

Output ONLY the production brief as flowing text. No markdown headers, no numbered lists, no labels. Write it as a continuous, detailed description that could be fed directly to a music generation AI."""

    if profile:
        style = profile.get("style", {})
        catalog = profile.get("catalog", [])
        profile_ctx = (
            f"\n\nActive DJ Profile: {profile.get('name', 'Unknown')}\n"
            f"Genres: {style.get('genres', '')}\n"
            f"Mood: {style.get('mood', '')}\n"
            f"Instruments: {style.get('instruments', '')}\n"
            f"Influences: {style.get('influences', '')}\n"
        )
        if catalog:
            recent = catalog[-3:]  # Last 3 productions
            profile_ctx += f"Recent productions: {json.dumps([c.get('title','') for c in recent])}\n"
        profile_ctx += "Incorporate the profile's established style while exploring the requested direction."
        system += profile_ctx

    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 800,
        "temperature": 0.6,
    }).encode()

    try:
        req = urllib.request.Request(
            "https://api.venice.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=45)
        result = json.loads(resp.read().decode())
        researched = result["choices"][0]["message"]["content"].strip()
        if "<think>" in researched:
            researched = researched.split("</think>")[-1].strip()
        # Strip meta-commentary
        meta_prefixes = [
            "The user has provided", "Looking at the input", "I need to",
            "Let me", "Here is", "Here's", "Based on",
        ]
        for prefix in meta_prefixes:
            if researched.startswith(prefix):
                for sep in ["\n\n", ". "]:
                    if sep in researched:
                        parts = researched.split(sep)
                        researched = max(parts, key=len).strip()
                        break
                break
        if researched and len(researched) > 50:
            cost = result.get("cost", {}).get("usd", 0)
            log(f"  ✅ Genre research complete ({len(researched)} chars, ${cost:.4f})")
            log(f"  Research: {researched[:200]}...")
            return researched
        else:
            log("  ⚠️ Research returned empty — using original prompt")
            return user_prompt
    except Exception as e:
        log(f"  ⚠️ Research failed ({e}) — using original prompt")
        return user_prompt


def creative_director(user_prompt, quality_tier, duration, lyrics=None, profile=None, album_context=None):
    """Use Kimi K3 to produce a structured production plan with per-stem, per-model prompts."""
    api_key = os.environ.get("VENICE_API_KEY", "")
    if not api_key:
        log("  ⚠️ No VENICE_API_KEY — skipping creative director")
        return None

    available_models = {
        "elevenlabs-music": {
            "type": "full-track", "cost": 0.69, "max_prompt": 2000,
            "strengths": "Premium instrumentals, clear bass, long-form, best overall quality",
            "supports": "duration (max 600s), force_instrumental. Does NOT support lyrics.",
        },
        "ace-step-15": {
            "type": "vocal", "cost": 0.03, "max_prompt": 2000,
            "strengths": "Structured vocals with [Verse]/[Chorus] tags, cheapest vocal",
            "supports": "lyrics (required), duration (only 60/90/120/150/180/210s)",
        },
        "minimax-music-v26": {
            "type": "vocal", "cost": 0.04, "max_prompt": 300,
            "strengths": "Latest MiniMax — tighter rhythm, clearer vocals, atmospheric, breathy textures",
            "supports": "lyrics (required), prompt max 300 chars. NO duration control.",
        },
        "minimax-music-v25": {
            "type": "vocal", "cost": 0.04, "max_prompt": 300,
            "strengths": "Mid-tier MiniMax — reliable freeform vocals, catchy melodies",
            "supports": "lyrics (required), prompt max 300 chars. NO duration control.",
        },
        "stable-audio-25": {
            "type": "instrumental/texture", "cost": 0.19, "max_prompt": 490,
            "strengths": "Textures, ambient, atmospheric pads, breakdowns, long instrumentals",
            "supports": "duration (max 180s). NO lyrics. NO instrumental flag.",
        },
        "elevenlabs-sound-effects-v2": {
            "type": "sfx", "cost": 0.02, "max_prompt": 490,
            "strengths": "Short SFX, risers, impacts, transitions",
            "supports": "NO duration. NO lyrics. Generates short clips.",
        },
        "mmaudio-v2-text-to-audio": {
            "type": "sfx/foley", "cost": 0.01, "max_prompt": 490,
            "strengths": "Environmental sounds, foley, nature ambience",
            "supports": "NO duration. NO lyrics. Generates short clips.",
        },
    }

    stems_needed = QUALITY_TIERS[quality_tier]["stems"]
    has_lyrics = bool(lyrics)

    # Build production memory from profile (compact — full plans bloat K3's context)
    memory_context = ""
    if profile:
        catalog = profile.get("catalog", [])
        # Get last 5 tracks — compact summary only (no full prompts)
        recent_plans = [
            {"title": c.get("title"), "bpm": c["plan"].get("bpm"),
             "key": c["plan"].get("key"), "genre": c["plan"].get("genre"),
             "models": [v.get("model") for v in c["plan"].get("stems", {}).values() if isinstance(v, dict)]}
            for c in catalog[-10:]
            if c.get("plan") and c["plan"].get("bpm")
        ][-5:]

        if recent_plans:
            memory_context += f"\n\nPRODUCTION MEMORY (last {len(recent_plans)} tracks):\n{json.dumps(recent_plans, indent=2)}\n"

        sonic_dna = profile.get("sonic_dna", {})
        if sonic_dna:
            memory_context += f"\nSONIC DNA for this DJ:\n{json.dumps(sonic_dna, indent=2)}\n"
            memory_context += (
                "\nMEMORY INSTRUCTIONS:\n"
                "- Stay within the DJ's aesthetic but VARY the execution\n"
                "- Use the preferred models as a baseline, but switch when the prompt demands it\n"
                "- BPM range and preferred keys are guidelines, not hard limits\n"
                "- Incorporate signature sounds but ALSO introduce new elements\n"
                "- Each track should feel like the same artist but NOT the same song\n"
            )

        style = profile.get("style", {})
        memory_context += (
            f"\nDJ Profile: {profile.get('name', 'Unknown')}\n"
            f"Genres: {style.get('genres', '')}\n"
            f"Mood: {style.get('mood', '')}\n"
            f"Instruments: {style.get('instruments', '')}\n"
            f"Influences: {style.get('influences', '')}\n"
        )

        # SONIC SIGNATURE — the prompt prefix that made the good tracks sound good
        prefix = profile.get("prompt_prefix", "")
        if prefix:
            memory_context += (
                f"\nSONIC SIGNATURE (MUST weave into EVERY main stem prompt):\n"
                f"\"{prefix}\"\n"
                "Every main stem prompt you write MUST incorporate this sonic identity.\n"
            )

        # Reference prompt from best published track
        published = [c for c in profile.get("catalog", [])
                     if (c.get("soundcloud_url") or c.get("published")) and c.get("plan")]
        if published:
            best = published[-1]  # most recent published
            ref_prompt = best["plan"].get("stems", {}).get("main", {}).get("prompt", "")
            if ref_prompt:
                memory_context += (
                    f"\nREFERENCE PROMPT (from published track \"{best.get('title', '?')}\"):\n"
                    f"\"{ref_prompt[:400]}\"\n"
                    "Your main stem prompts should match this level of detail and specificity.\n"
                )

    # Album variation context — forces differentiation between tracks
    album_instructions = ""
    if album_context:
        prev_tracks = album_context.get("previous_tracks", [])
        track_num = album_context.get("track_number", 1)
        total_tracks = album_context.get("total_tracks", 5)
        album_brief = album_context.get("brief", "")
        variation_rules = album_context.get("variation_rules", [])

        if prev_tracks:
            prev_summary = json.dumps([
                {"title": t.get("title"), "bpm": t.get("bpm"), "key": t.get("key"),
                 "genre": t.get("genre"), "has_vocals": t.get("has_vocals", False),
                 "lead_instrument": t.get("lead_instrument", "808 bass")}
                for t in prev_tracks
            ], indent=2)
            album_instructions += f"\n\nALBUM CONTEXT — Track {track_num} of {total_tracks}:\n"
            album_instructions += f"Previous tracks in this album:\n{prev_summary}\n"
            album_instructions += (
                "\nALBUM VARIATION RULES (MANDATORY):\n"
                "- This track MUST be DIFFERENT from the previous tracks listed above\n"
                "- Use a DIFFERENT lead instrument or sound design approach\n"
                "- Use a DIFFERENT BPM (at least ±5 BPM from any previous track)\n"
                "- Use a DIFFERENT musical key from the previous track\n"
                "- If no previous track has vocals, consider adding breathy/humming vocals\n"
                "- If previous tracks are all high-energy, make this one slower or more atmospheric\n"
                "- The album needs DYNAMIC RANGE — not every track can be the same intensity\n"
            )
        if album_brief:
            album_instructions += f"\nAlbum brief: {album_brief}\n"
        if variation_rules:
            album_instructions += f"\nSpecific variation for this track: {'; '.join(variation_rules)}\n"

    system_prompt = f"""You are an expert music producer and creative director.
{memory_context}
{album_instructions}
Given a song request, produce a STRUCTURED PRODUCTION PLAN as valid JSON.

AVAILABLE AUDIO MODELS (you MUST select from these):
{json.dumps(available_models, indent=2)}

STEMS TO PRODUCE: {json.dumps(stems_needed)}
DURATION: {duration} seconds
HAS LYRICS: {has_lyrics}

CRITICAL RULES:
1. Each stem gets its OWN prompt, tailored to that model's max_prompt length
2. Main stem prompt: vivid but CONCISE — genre, BPM as a number, musical key, 3-4 key sounds, mood. 50-200 words. MINIMUM 50 words.
3. Supporting stem prompts (texture, atmosphere, b_section): MUST include the SAME key and BPM as main for coherence. MINIMUM 30 words.
4. stable-audio-25 prompts MUST be under 490 characters total.
5. elevenlabs-sfx prompts: describe a SHORT sound effect (3-8 seconds), not a song. Under 490 characters.
6. Pick the BEST model for each stem based on genre and role:
   - Bass-heavy genres (dubstep, trap, DnB, phonk): elevenlabs-music for main
   - Ambient/chill genres: stable-audio-25 can be main
   - Vocals with [Verse]/[Chorus] tags: ace-step-15
   - Freeform vocals: minimax-music-v2
7. BPM and key MUST appear explicitly in every stem prompt
8. If lyrics are provided, main model MUST support lyrics
9. For instrumental tracks, set "instrumental": true on main stem
10. TITLE must be a unique creative 1-3 word name — NOT the album name, NOT the user's request, NOT generic
11. NEVER use placeholder text like "..." or "etc" in ANY field. Every prompt MUST be a complete, detailed description
12. Every "prompt" value MUST be a FULL audio generation description with specific instruments, mood, and production details

OUTPUT VALID JSON (no markdown, no code fences):
{{
  "title": "UNIQUE CREATIVE NAME",
  "genre": "primary genre / subgenre",
  "bpm": 150,
  "key": "Fm",
  "energy": "description of energy and mood — NOT a placeholder",
  "stems": {{
    "main": {{
      "model": "model-id-from-list",
      "prompt": "DETAILED prompt: genre, BPM, key, instruments, mood, texture, energy. MINIMUM 50 words.",
      "instrumental": true
    }},
    "texture": {{
      "model": "model-id-from-list",
      "prompt": "DETAILED ambient/texture prompt with same key and BPM. MINIMUM 30 words."
    }}
  }}
}}"""

    user_msg = user_prompt
    if lyrics:
        user_msg += f"\n\nLYRICS:\n{lyrics[:500]}"

    director_model = os.environ.get("DIRECTOR_MODEL", "deepseek-v4-pro")

    # Retry loop — K3 sometimes returns empty on rapid successive calls
    max_retries = 2
    for attempt in range(max_retries + 1):
        raw = ""
        try:
            payload = json.dumps({
                "model": director_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 3000,
                "temperature": 0.5,
            }).encode()

            req = urllib.request.Request(
                "https://api.venice.ai/api/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=90)
            result = json.loads(resp.read().decode())
            raw = result["choices"][0]["message"]["content"].strip()

            # ── Robust JSON extraction from thinking models ──────────
            # K3 outputs reasoning text before JSON. We need to find the
            # actual JSON object in the response, ignoring thinking noise.

            # 1) Strip <think>...</think> XML tags
            if "<think>" in raw:
                raw = raw.split("</think>")[-1].strip()
            # 2) Strip markdown code fences
            if "```" in raw:
                fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
                if fence_match:
                    raw = fence_match.group(1)
                else:
                    raw = re.sub(r'```(?:json)?\s*', '', raw)
                    raw = re.sub(r'\s*```', '', raw)

            if not raw:
                raise json.JSONDecodeError("Empty response from K3", "", 0)

            # 3) Try direct parse first (cleanest case)
            try:
                plan = json.loads(raw)
            except json.JSONDecodeError:
                # 4) Find the last complete {...} JSON object using brace depth
                #    This skips thinking text and partial JSON fragments
                last_json = None
                depth = 0
                start_pos = None
                for pos, ch in enumerate(raw):
                    if ch == '{':
                        if depth == 0:
                            start_pos = pos
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0 and start_pos is not None:
                            candidate = raw[start_pos:pos + 1]
                            try:
                                parsed = json.loads(candidate)
                                # Prefer objects that look like production plans
                                if "stems" in parsed or "title" in parsed:
                                    last_json = parsed
                            except json.JSONDecodeError:
                                pass
                            start_pos = None

                if last_json is None:
                    raise json.JSONDecodeError("No valid JSON object found in K3 response", raw[:200], 0)
                plan = last_json

            # Validate prompts — reject lazy/placeholder outputs
            for stem_name, stem_info in plan.get("stems", {}).items():
                if isinstance(stem_info, dict):
                    p = stem_info.get("prompt", "")
                    if len(p) < 30 or p.strip() in ("...", "etc", "placeholder", ""):
                        raise json.JSONDecodeError(
                            f"K3 wrote placeholder prompt for {stem_name}: '{p}' — rejecting plan",
                            "", 0
                        )

            # Enforce prompt length limits per model
            model_limits = {"stable-audio-25": 490, "elevenlabs-sound-effects-v2": 490, "minimax-music-v2": 290}
            for stem_name, stem_info in plan.get("stems", {}).items():
                if isinstance(stem_info, dict):
                    model = stem_info.get("model", "")
                    limit = model_limits.get(model)
                    if limit and len(stem_info.get("prompt", "")) > limit:
                        stem_info["prompt"] = stem_info["prompt"][:limit]

            cost = result.get("cost", {}).get("usd", 0)
            log(f"  ✅ Creative Director plan ready ({director_model}, ${cost:.4f})")
            log(f"  Title: {plan.get('title', '?')}")
            log(f"  Genre: {plan.get('genre', '?')} | BPM: {plan.get('bpm', '?')} | Key: {plan.get('key', '?')}")
            for stem_name, stem_info in plan.get("stems", {}).items():
                prompt_preview = stem_info.get("prompt", "")[:80]
                log(f"  {stem_name:12s} → {stem_info.get('model', '?'):30s} \"{prompt_preview}...\"")
            return plan

        except json.JSONDecodeError as e:
            if attempt < max_retries:
                wait = 5 * (attempt + 1)  # 5s, 10s exponential backoff
                log(f"  ⚠️ K3 attempt {attempt + 1} failed ({e}) — retrying in {wait}s...")
                # Try alternate model on last retry
                if attempt == max_retries - 1 and director_model == "deepseek-v4-pro":
                    director_model = "qwen-3-7-plus"
                    log(f"  🔄 Switching to fallback model: {director_model}")
                time.sleep(wait)
                continue
            log(f"  ⚠️ Creative Director returned invalid JSON after {max_retries + 1} attempts: {e}")
            if raw:
                log(f"  Raw output: {raw[:300]}")
            return None
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            # Network/API errors should also retry — K3 rate limits, timeouts
            if attempt < max_retries:
                wait = 10 * (attempt + 1)  # 10s, 20s — longer for network issues
                log(f"  ⚠️ K3 network error attempt {attempt + 1} ({e}) — retrying in {wait}s...")
                if attempt == max_retries - 1 and director_model == "deepseek-v4-pro":
                    director_model = "qwen-3-7-plus"
                    log(f"  🔄 Switching to fallback model: {director_model}")
                time.sleep(wait)
                continue
            log(f"  ⚠️ Creative Director network error after {max_retries + 1} attempts: {e}")
            return None
        except Exception as e:
            log(f"  ⚠️ Creative Director failed ({e}) — falling back to legacy mode")
            return None


# ─── K3 INFERENCE PASSES ────────────────────────────────────────────────
# These use cheap K3/qwen calls to make adaptive decisions at each
# pipeline stage instead of using hardcoded values.

def _quick_inference(system_prompt, user_prompt, model="deepseek-v4-flash", max_tokens=800):
    """Make a quick inference call for pipeline decisions. Returns parsed JSON or None."""
    api_key = os.environ.get("VENICE_API_KEY", "")
    if not api_key:
        return None
    try:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }).encode()
        req = urllib.request.Request(
            "https://api.venice.ai/api/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        resp = urllib.request.urlopen(req, timeout=45)
        result = json.loads(resp.read().decode())
        raw = result["choices"][0]["message"]["content"].strip()
        # Strip thinking tags
        if "<think>" in raw:
            raw = raw.split("</think>")[-1].strip()
        # Strip code fences
        if "```" in raw:
            m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
            if m:
                raw = m.group(1)
        # Extract JSON
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Brace-depth fallback
            depth = 0
            sp = None
            for pos, ch in enumerate(raw):
                if ch == '{':
                    if depth == 0:
                        sp = pos
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and sp is not None:
                        try:
                            return json.loads(raw[sp:pos + 1])
                        except json.JSONDecodeError:
                            pass
                        sp = None
            return None
    except Exception as e:
        log(f"  ⚠️ Quick inference failed: {e}")
        return None


def upscale_prompt(prompt, stem_name, genre="", bpm=0, key="", max_chars=490):
    """Pass 1c: Enrich a stem prompt with vivid, specific audio details."""
    system = (
        "You are an expert audio prompt engineer. Take the input prompt and make it MORE "
        "vivid, specific, and detailed for an AI audio generation model. Add: specific "
        "frequency descriptions (sub-bass, mid-range, high-end), spatial positioning "
        "(wide stereo, centered, panning), dynamic characteristics (attack, sustain, "
        "release), and textural details (gritty, smooth, crystalline, warm). "
        f"Keep the result under {max_chars} characters. "
        "Return JSON: {\"prompt\": \"enhanced prompt text\"}"
    )
    user = (
        f"Stem: {stem_name} | Genre: {genre} | BPM: {bpm} | Key: {key}\n"
        f"Original prompt: \"{prompt}\"\n"
        f"Enhance this prompt. Make it vivid and specific. Under {max_chars} chars."
    )
    result = _quick_inference(system, user)
    if result and result.get("prompt") and len(result["prompt"]) >= 30:
        enhanced = result["prompt"][:max_chars]
        log(f"  🔬 Upscaled {stem_name} prompt: {len(prompt)} → {len(enhanced)} chars")
        return enhanced
    return prompt  # fallback to original


def infer_mix_params(stems_analysis, genre="", profile=None):
    """Pass 2: K3 Mix Engineer — decide volumes, pan, EQ from stem analysis."""
    analysis_text = ""
    for stem_name, analysis in stems_analysis.items():
        analysis_text += (
            f"  {stem_name}: BPM={analysis.get('bpm', '?')}, Key={analysis.get('key', '?')}, "
            f"centroid={analysis.get('spectral_centroid_hz', '?')}Hz, "
            f"rms={analysis.get('rms_db', '?')}dB\n"
        )

    system = (
        "You are a professional mix engineer for electronic music. "
        "Given stem analysis data, decide optimal mix parameters. "
        "Consider: frequency masking between stems, key clashes, "
        "spatial separation via panning, and genre-appropriate balance. "
        "Return JSON with per-stem parameters:\n"
        "{\"stems\": {\"main\": {\"volume\": 1.0, \"pan\": 0.0, \"eq\": \"none\"}, "
        "\"texture\": {\"volume\": 0.35, \"pan\": 0.1, \"eq\": \"lowpass_1200hz\"}, ...}, "
        "\"reasoning\": \"brief explanation\"}"
    )
    user = f"Genre: {genre}\nStem Analysis:\n{analysis_text}\nDecide mix parameters."

    result = _quick_inference(system, user)
    if result and "stems" in result:
        log(f"  🎛️ K3 Mix Engineer: {result.get('reasoning', 'no reasoning')[:80]}")
        return result["stems"]
    return None  # caller uses hardcoded defaults


def infer_mastering(mix_analysis, genre="", profile=None):
    """Pass 3: K3 Mastering Engineer — decide LUFS target, EQ, limiter from mix analysis."""
    ref_lufs = "-14.0"
    if profile:
        catalog = profile.get("catalog", [])
        published = [c for c in catalog if c.get("soundcloud_url")]
        if published:
            lufs_vals = [c.get("plan", {}).get("qc", {}).get("lufs") for c in published]
            lufs_vals = [l for l in lufs_vals if l]
            if lufs_vals:
                ref_lufs = f"{sum(lufs_vals)/len(lufs_vals):.1f}"

    system = (
        "You are a mastering engineer for electronic music. "
        "Given a mix analysis and genre, decide mastering parameters. "
        "Consider: genre loudness conventions (phonk/trap = -11 to -12 LUFS, "
        "ambient = -16 LUFS, club = -10 LUFS), spectral balance, dynamic range. "
        "Return JSON:\n"
        "{\"lufs_target\": -12.0, \"true_peak_limit\": -0.5, "
        "\"eq\": {\"low_shelf_hz\": 60, \"low_shelf_db\": 1.5, \"high_shelf_hz\": 12000, \"high_shelf_db\": 0.5}, "
        "\"reasoning\": \"brief explanation\"}"
    )
    user = (
        f"Genre: {genre}\n"
        f"Mix Analysis: {json.dumps(mix_analysis)}\n"
        f"DJ's reference LUFS: {ref_lufs}\n"
        f"Decide mastering parameters."
    )

    result = _quick_inference(system, user)
    if result and "lufs_target" in result:
        log(f"  🎚️ K3 Mastering: target {result['lufs_target']} LUFS — {result.get('reasoning', '')[:60]}")
        return result
    return None  # caller uses defaults


def quality_control(qc_report, genre="", profile=None):
    """Pass 4: K3 Quality Controller — evaluate final track against benchmarks."""
    ref_benchmarks = ""
    if profile:
        catalog = profile.get("catalog", [])
        published = [c for c in catalog if c.get("soundcloud_url")]
        if published:
            qc_vals = [c.get("plan", {}).get("qc", {}) for c in published if c.get("plan", {}).get("qc")]
            if qc_vals:
                avg_lufs = sum(q.get("lufs", -14) for q in qc_vals) / len(qc_vals)
                ref_benchmarks = f"Reference: avg LUFS={avg_lufs:.1f} from {len(qc_vals)} published tracks"

    system = (
        "You are a quality controller for an AI music studio. "
        "Evaluate the final mastered track against genre standards. "
        "Return JSON:\n"
        "{\"verdict\": \"pass|marginal|fail\", \"score\": 7.5, "
        "\"issues\": [\"list of specific issues\"], "
        "\"suggestions\": [\"list of improvements for next time\"]}"
    )
    user = (
        f"Genre: {genre}\n"
        f"QC Report: {json.dumps(qc_report)}\n"
        f"{ref_benchmarks}\n"
        f"Evaluate this track."
    )

    result = _quick_inference(system, user)
    if result and "verdict" in result:
        verdict = result["verdict"]
        score = result.get("score", "?")
        icon = {"pass": "✅", "marginal": "⚠️", "fail": "❌"}.get(verdict, "❓")
        log(f"  {icon} QC: {verdict} (score: {score}/10)")
        if result.get("issues"):
            for issue in result["issues"][:3]:
                log(f"     • {issue}")
        return result
    return None


def update_sonic_dna(profile_path):
    """Rebuild a profile's sonic_dna from its catalog history."""
    try:
        with open(profile_path) as f:
            profile = json.load(f)
    except Exception:
        return

    catalog = [c for c in profile.get("catalog", []) if c.get("plan")]
    if not catalog:
        return

    from collections import Counter

    bpms = [c["plan"]["bpm"] for c in catalog if c["plan"].get("bpm")]
    keys = [c["plan"]["key"] for c in catalog if c["plan"].get("key")]
    genres = []
    models_used = {}

    for c in catalog:
        plan = c["plan"]
        if plan.get("genre"):
            for g in plan["genre"].replace("/", ",").split(","):
                genres.append(g.strip())
        for stem, info in plan.get("stems", {}).items():
            if isinstance(info, dict) and info.get("model"):
                models_used.setdefault(stem, []).append(info["model"])

    profile["sonic_dna"] = {
        "primary_genres": [g for g, _ in Counter(genres).most_common(5)] if genres else [],
        "bpm_range": [min(bpms), max(bpms)] if bpms else [120, 140],
        "preferred_keys": [k for k, _ in Counter(keys).most_common(3)] if keys else [],
        "preferred_models": {
            stem: Counter(mlist).most_common(1)[0][0]
            for stem, mlist in models_used.items()
            if mlist
        },
        "total_tracks": len(catalog),
        "last_updated": datetime.utcnow().isoformat() + "Z",
    }

    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2)
    log(f"  📊 Sonic DNA updated ({len(catalog)} tracks in history)")


# ─── Arrangement Sections ───────────────────────────────────────────────
# Define how stem volumes change over time to create song structure.
# Volume floors raised to prevent jarring drops. Crossfade duration (XFADE_SEC)
# smooths transitions between sections instead of hard cuts.
XFADE_SEC = 2.0  # seconds of linear crossfade between sections
MIN_VOLUME_FLOOR = 0.5  # no stem ever drops below 50% of its base volume

ARRANGEMENT = {
    # Each section: (start%, end%, {stem: volume_multiplier})
    # Multipliers are applied to STEM_CONFIG base volumes.
    # Floor: main never below 0.65, supporting stems never below 0.5× base.
    "intro":     (0.00, 0.15, {"main": 0.8,  "texture": 1.0, "accent": 0.0, "atmosphere": 1.1, "b_section": 0.0}),
    "build":     (0.15, 0.40, {"main": 1.0,  "texture": 0.8, "accent": 0.3, "atmosphere": 0.8, "b_section": 0.0}),
    "drop":      (0.40, 0.60, {"main": 1.0,  "texture": 0.5, "accent": 1.0, "atmosphere": 0.5, "b_section": 0.0}),
    "breakdown": (0.60, 0.75, {"main": 0.7,  "texture": 1.0, "accent": 0.0, "atmosphere": 1.2, "b_section": 1.0}),
    "drop2":     (0.75, 0.92, {"main": 1.0,  "texture": 0.6, "accent": 0.5, "atmosphere": 0.5, "b_section": 0.0}),
    "outro":     (0.92, 1.00, {"main": 0.7,  "texture": 0.8, "accent": 0.0, "atmosphere": 1.0, "b_section": 0.0}),
}


def build_arrangement_volume(stem_role, duration):
    """Build an ffmpeg volume expression with smooth crossfades between sections.

    Instead of hard if(lt(t,...)) cuts, uses linear interpolation across
    XFADE_SEC-wide windows at each section boundary so volume changes
    are gradual, not jarring. Enforces MIN_VOLUME_FLOOR.
    """
    if not duration or duration <= 0:
        return None

    base_vol = STEM_CONFIG.get(stem_role, {}).get("mix_volume", 1.0)
    vol_floor = base_vol * MIN_VOLUME_FLOOR  # absolute minimum

    # Collect (time_boundary, target_volume) pairs
    sections = sorted(ARRANGEMENT.values(), key=lambda x: x[0])
    parts = []
    for start_pct, end_pct, vols in sections:
        t_end = duration * end_pct
        mult = vols.get(stem_role, 1.0)
        final_vol = max(base_vol * mult, vol_floor)  # enforce floor
        parts.append((t_end, final_vol))

    # Build expression with linear crossfades between sections.
    # For each boundary, create a ramp: lerp(prev_vol, next_vol) over XFADE_SEC.
    # Expression: if(lt(t, boundary - xf/2), prev_vol,
    #              if(lt(t, boundary + xf/2), lerp(prev_vol, next_vol, (t - start) / xf),
    #               next_vol))
    xf = min(XFADE_SEC, duration * 0.02)  # cap crossfade at 2% of track

    # Simple approach: build nested ifs with linear ramps at boundaries
    # For each pair of consecutive sections, add a ramp zone
    if len(parts) < 2:
        return str(parts[0][1]) if parts else str(base_vol)

    # Build from innermost (last section) outward
    expr = f"{parts[-1][1]:.3f}"  # fallback = last section

    for i in range(len(parts) - 2, -1, -1):
        t_boundary = parts[i][0]
        vol_before = parts[i][1]
        vol_after = parts[i + 1][1] if i + 1 < len(parts) else vol_before

        ramp_start = max(0, t_boundary - xf / 2)
        ramp_end = t_boundary + xf / 2

        if abs(vol_before - vol_after) < 0.01:
            # Same volume — no ramp needed, just a simple threshold
            expr = f"if(lt(t\\,{t_boundary:.1f})\\,{vol_before:.3f}\\,{expr})"
        else:
            # Linear ramp: lerp = vol_before + (vol_after - vol_before) * (t - ramp_start) / xf
            slope = (vol_after - vol_before) / max(xf, 0.1)
            lerp_expr = f"{vol_before:.3f}+{slope:.4f}*(t-{ramp_start:.1f})"
            # Clamp the lerp within the ramp zone
            expr = (
                f"if(lt(t\\,{ramp_start:.1f})\\,{vol_before:.3f}\\,"
                f"if(lt(t\\,{ramp_end:.1f})\\,{lerp_expr}\\,{expr}))"
            )

    return expr


def extract_key_bpm(prompt_text):
    """Extract musical key and BPM from an enhanced prompt string."""
    key = None
    bpm = None

    # Match BPM: "140 BPM" or "at 140bpm" or "tempo: 140"
    bpm_match = re.search(r'(\d{2,3})\s*(?:bpm|BPM)', prompt_text)
    if bpm_match:
        bpm = int(bpm_match.group(1))

    # Match key: "D minor", "Dm", "C# minor", "Am", "F# major"
    key_match = re.search(r'([A-G][#b]?)\s*(minor|major|min|maj|m(?![a-z]))', prompt_text, re.IGNORECASE)
    if key_match:
        root = key_match.group(1)
        quality = key_match.group(2).lower()
        if quality.startswith('m') and quality != 'maj' and quality != 'major':
            key = f"{root} minor"
        else:
            key = f"{root} major"

    return key, bpm


def split_frequency_bands(input_path, output_dir):
    """Split an audio file into bass/mid/high frequency bands using ffmpeg.
    Returns dict with paths to each band file, or None on failure.
    """
    basename = os.path.splitext(os.path.basename(input_path))[0]
    bands = {
        "sub_bass": {"filter": "lowpass=f=120", "file": os.path.join(output_dir, f"{basename}_sub.wav")},
        "bass_mid": {"filter": "highpass=f=120,lowpass=f=2500", "file": os.path.join(output_dir, f"{basename}_mid.wav")},
        "high":     {"filter": "highpass=f=2500", "file": os.path.join(output_dir, f"{basename}_high.wav")},
    }

    result_paths = {}
    for band_name, band_info in bands.items():
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-af", band_info["filter"],
            "-ar", "48000", "-ac", "2",
            band_info["file"],
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                result_paths[band_name] = band_info["file"]
        except Exception:
            pass

    if result_paths:
        log(f"  🔬 Split into {len(result_paths)} frequency bands: {', '.join(result_paths.keys())}")
    return result_paths if result_paths else None


def generate_b_section(prompt, duration, stems_dir):
    """Generate a contrasting B-section stem for the breakdown."""
    b_prompt = (
        f"Atmospheric minimal breakdown version: {prompt[:300]}. "
        f"Sparse, filtered, spacious — stripped-back bridge section. "
        f"Half the energy, focus on texture and space. No heavy bass or drums."
    )
    # stable-audio-25 max 500 chars
    if len(b_prompt) > 490:
        b_prompt = b_prompt[:487].rsplit(' ', 1)[0] + "..."

    b_duration = min(duration, 180)  # stable-audio-25 max
    log("")
    log("=" * 60)
    log("GENERATING B-SECTION (breakdown contrast)")
    log(f"  Prompt: {b_prompt[:100]}...")
    log("=" * 60)

    cmd = [
        sys.executable, VENICE_SCRIPT,
        "--model", "stable-audio-25",
        "--prompt", b_prompt,
        "--output", stems_dir,
        "--duration", str(b_duration),
    ]
    if _CHAT_ID:
        cmd.extend(["--chat-id", str(_CHAT_ID)])

    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env={**os.environ})
        if result.returncode != 0:
            log(f"  ⚠️ B-section API failed — creating LP-filtered main as fallback")
            return None
        output = json.loads(result.stdout)
        if not output.get("success"):
            log(f"  ⚠️ B-section generation failed: {output.get('error')}")
            return None
        filepath = output["file"]
        # Rename
        ext = os.path.splitext(filepath)[1]
        renamed = os.path.join(os.path.dirname(filepath), f"b_section_stable-audio-25{ext}")
        try:
            os.rename(filepath, renamed)
            filepath = renamed
        except OSError:
            pass
        elapsed = time.time() - start
        log(f"  ✅ B-section done: {filepath} ({elapsed:.0f}s)")
        cost = output.get("cost", {"cost_usd": 0, "credits": 0})
        return {
            "role": "b_section",
            "model": "stable-audio-25",
            "file": filepath,
            "generation_time": round(elapsed, 1),
            "cost": cost,
        }
    except Exception as e:
        log(f"  ⚠️ B-section error: {e}")
        return None


# ─── Content Safety ──────────────────────────────────────────────────────
# ElevenLabs rejects prompts with violence-adjacent language even when
# describing music genres (dubstep, metal, etc). Replace with safe synonyms.
CONTENT_SAFE_REPLACEMENTS = [
    # Multi-word phrases first (order matters for longer matches)
    ("violent force", "raw power"),
    ("tears through", "cuts through"),
    ("tear through", "cut through"),
    ("chest-compressing", "chest-rattling"),
    ("chest compressing", "chest rattling"),
    ("never releasing its grip", "maintaining intensity"),
    # Single words
    ("assault", "onslaught"),
    ("violent", "intense"),
    ("violence", "intensity"),
    ("brutal", "massive"),
    ("brutality", "intensity"),
    ("devastating", "earth-shattering"),
    ("destroy", "dominate"),
    ("destruction", "power"),
    ("shredding", "slicing"),
    ("weapon", "force"),
    ("attack", "impact"),
    ("attacking", "hitting"),
    ("killing", "crushing"),
    ("murder", "power"),
    ("punishing", "pounding"),
    ("annihilate", "overwhelm"),
    ("carnage", "chaos"),
    ("slaughter", "mayhem"),
    ("blood", "fire"),
    ("warfare", "storm"),
    ("combat", "clash"),
    ("fight", "clash"),
    ("rage", "fury"),
    ("submission", "surrender"),
    ("tearout", "heavy bass"),
    ("snarl", "growl"),
    ("unleash", "release"),
    ("unleashes", "releases"),
    ("unrelenting", "relentless"),
    ("ferocious", "fierce"),
    ("savagery", "power"),
    ("savage", "fierce"),
    ("ruthless", "relentless"),
    ("merciless", "unyielding"),
    ("havoc", "chaos"),
    ("wreak", "create"),
    ("headbanging", "head-nodding"),
]


def sanitize_prompt(text):
    """Replace violence-adjacent words with content-safe alternatives."""
    result = text
    for unsafe, safe in CONTENT_SAFE_REPLACEMENTS:
        # Case-insensitive replacement preserving boundaries
        pattern = re.compile(re.escape(unsafe), re.IGNORECASE)
        result = pattern.sub(safe, result)
    return result


# ─── Audio Analysis (Phase 1) ────────────────────────────────────────────
def analyze_stem(filepath):
    """Analyze a generated stem for BPM, key, and spectral characteristics using librosa."""
    try:
        import librosa
        import numpy as np
        y, sr = librosa.load(filepath, sr=None, mono=True, duration=60)  # First 60s

        # BPM detection
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = round(float(tempo[0]) if hasattr(tempo, '__len__') else float(tempo), 1)

        # Key detection via chroma + Krumhansl-Schmuckler
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        chroma_mean = chroma.mean(axis=1)
        major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        major_corrs = [np.corrcoef(np.roll(chroma_mean, -i), major_profile)[0, 1] for i in range(12)]
        minor_corrs = [np.corrcoef(np.roll(chroma_mean, -i), minor_profile)[0, 1] for i in range(12)]
        best_major = max(range(12), key=lambda i: major_corrs[i])
        best_minor = max(range(12), key=lambda i: minor_corrs[i])
        if major_corrs[best_major] >= minor_corrs[best_minor]:
            key = key_names[best_major]
        else:
            key = f"{key_names[best_minor]}m"

        # Spectral centroid (brightness)
        centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())

        # RMS energy
        rms = float(librosa.feature.rms(y=y).mean())

        return {
            "bpm": bpm,
            "key": key,
            "spectral_centroid_hz": round(centroid),
            "rms_energy": round(rms, 4),
            "duration": round(len(y) / sr, 1),
        }
    except ImportError:
        log("  ⚠️ librosa not installed — skipping analysis")
        return None
    except Exception as e:
        log(f"  ⚠️ Analysis failed: {e}")
        return None


# ─── Stem Separation (Phase 2) ───────────────────────────────────────────
def separate_stems(input_path, output_dir):
    """Use Demucs to separate a track into drums/no_drums."""
    demucs_out = os.path.join(output_dir, "demucs")
    os.makedirs(demucs_out, exist_ok=True)
    log(f"  Running Demucs stem separation...")
    cmd = [
        sys.executable, "-m", "demucs",
        "-n", "htdemucs",
        "--two-stems", "drums",
        "-o", demucs_out,
        input_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            log(f"  ⚠️ Demucs failed: {result.stderr[-200:] if result.stderr else 'unknown error'}")
            return None

        track_name = os.path.splitext(os.path.basename(input_path))[0]
        stems_path = os.path.join(demucs_out, "htdemucs", track_name)
        if not os.path.isdir(stems_path):
            log(f"  ⚠️ Demucs output dir not found: {stems_path}")
            return None

        separated = {}
        for stem_file in os.listdir(stems_path):
            if stem_file.endswith(".wav"):
                name = os.path.splitext(stem_file)[0]
                separated[name] = os.path.join(stems_path, stem_file)

        log(f"  ✅ Demucs separation complete: {list(separated.keys())}")
        return separated
    except subprocess.TimeoutExpired:
        log(f"  ⚠️ Demucs timed out (>300s)")
        return None
    except Exception as e:
        log(f"  ⚠️ Demucs error: {e}")
        return None


def create_demucs_b_section(separated_stems, output_dir, duration=None):
    """Create a B-section from Demucs-separated stems (drums removed)."""
    no_drums = separated_stems.get("no_drums")
    if not no_drums or not os.path.isfile(no_drums):
        return None

    b_path = os.path.join(output_dir, "b_section_demucs.wav")
    filters = [
        "lowpass=f=3000",
        "volume=0.65",
        "afade=t=in:d=2",
        "areverse,afade=t=in:d=2,areverse",
    ]
    cmd = [
        "ffmpeg", "-y", "-i", no_drums,
        "-af", ",".join(filters),
        "-ar", "48000", "-ac", "2",
        b_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and os.path.isfile(b_path):
            log(f"  ✅ Demucs B-section created (drums removed, LP filtered)")
            return b_path
        return None
    except Exception:
        return None


# ─── Per-Stem Effects Processing (Pedalboard) ───────────────────────────
def process_stem_effects(stem_path, stem_role, output_path=None):
    """Apply genre-appropriate effects to a stem using Spotify's Pedalboard."""
    try:
        from pedalboard import Pedalboard, Reverb, Compressor, LowpassFilter, HighpassFilter, Gain
        from pedalboard.io import AudioFile
    except ImportError:
        log("  ⚠️ pedalboard not installed — skipping stem effects")
        return stem_path

    # Per-role effect chains — with makeup gain on compressors to prevent
    # volume loss, and gentler cuts on supporting stems.
    STEM_EFFECTS = {
        "main": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=30),
            Compressor(threshold_db=-18, ratio=3, attack_ms=10, release_ms=150),
            Gain(gain_db=2),  # Makeup gain to compensate for compression
        ]),
        "texture": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=150),  # Lowered from 200Hz to keep more warmth
            Reverb(room_size=0.55, wet_level=0.25, dry_level=0.75),
            LowpassFilter(cutoff_frequency_hz=12000),  # Raised from 10kHz to keep air
        ]),
        "atmosphere": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=60),  # Lowered from 80Hz
            Reverb(room_size=0.85, wet_level=0.40, dry_level=0.60),
            LowpassFilter(cutoff_frequency_hz=10000),  # Raised from 6kHz — was too dark
            # Removed -2dB Gain cut — was making breakdowns too quiet
        ]),
        "accent": Pedalboard([
            Compressor(threshold_db=-15, ratio=4, attack_ms=5, release_ms=100),
            Gain(gain_db=1.5),  # Makeup gain for compression
            Reverb(room_size=0.25, wet_level=0.15, dry_level=0.85),
        ]),
        "b_section": Pedalboard([
            Reverb(room_size=0.8, wet_level=0.30, dry_level=0.70),
            LowpassFilter(cutoff_frequency_hz=6000),  # Raised from 4kHz — was muffling too much
            # Removed -1dB Gain cut — breakdown already quieter from arrangement
        ]),
    }

    board = STEM_EFFECTS.get(stem_role)
    if not board:
        return stem_path

    base, ext = os.path.splitext(stem_path)
    out = output_path or f"{base}_fx.wav"
    try:
        with AudioFile(stem_path) as f:
            sr = f.samplerate
            audio = f.read(f.frames)

        processed = board(audio, sr)

        with AudioFile(out, "w", sr, processed.shape[0]) as f:
            f.write(processed)

        log(f"  🎸 Pedalboard FX applied to {stem_role}: {len(board)} effects")
        return out
    except Exception as e:
        log(f"  ⚠️ Pedalboard FX failed for {stem_role}: {e}")
        return stem_path


def generate_stem(stem_name, prompt, lyrics=None, duration=None, stems_dir=None,
                  model_override=None, force_instrumental=None):
    """Generate a single stem using venice-music.py. Returns stem file path."""
    config = STEM_CONFIG[stem_name]

    # Select model — use director override if provided, otherwise smart selection
    if model_override:
        model = model_override
    elif stem_name == "main":
        if lyrics:
            # Check if lyrics have structure tags like [Verse], [Chorus]
            has_structure = bool(re.search(r'\[(?:Verse|Chorus|Bridge|Hook|Intro|Outro)', lyrics, re.IGNORECASE))
            if has_structure:
                model = config.get("model_vocal", "ace-step-15")  # ACE-Step handles structure best
            else:
                model = config.get("model_vocal_freeform", config.get("model_vocal", "minimax-music-v2"))
        else:
            model = config.get("model_instrumental", "elevenlabs-music")
    else:
        model = config["model"]

    # Build prompt — use director prompt directly, or wrap with template
    if model_override:
        # Director already crafted a per-stem prompt — use it directly
        stem_prompt = prompt
    else:
        # Legacy mode: inject key/BPM context for supporting stems
        detected_key, detected_bpm = extract_key_bpm(prompt)
        key_context = ""
        if stem_name != "main":
            if detected_key:
                key_context += f" in {detected_key}"
            if detected_bpm:
                key_context += f" at {detected_bpm} BPM"
        stem_prompt = config["prompt_template"].format(prompt=prompt)
        if key_context and stem_name in ("texture", "atmosphere"):
            stem_prompt = stem_prompt.rstrip() + key_context + "."

    # Truncate prompt to model limits (stable-audio-25 max 500 chars)
    MAX_PROMPT_LEN = {
        "stable-audio-25": 490,
        "elevenlabs-sound-effects-v2": 490,
        "mmaudio-v2-text-to-audio": 490,
    }
    max_len = MAX_PROMPT_LEN.get(model, 2000)
    if len(stem_prompt) > max_len:
        stem_prompt = stem_prompt[:max_len - 3].rsplit(' ', 1)[0] + "..."

    # Sanitize for content policy (replace violence-adjacent terms)
    stem_prompt = sanitize_prompt(stem_prompt)

    # Build command
    cmd = [
        sys.executable, VENICE_SCRIPT,
        "--model", model,
        "--prompt", stem_prompt,
        "--output", stems_dir,
    ]

    # Pass chat-id for sub-progress updates
    if _CHAT_ID:
        cmd.extend(["--chat-id", str(_CHAT_ID)])

    # Add duration for models that support it
    if duration and stem_name == "main":
        # minimax-music-v2 doesn't support duration
        if model != "minimax-music-v2":
            cmd.extend(["--duration", str(duration)])
    elif duration and stem_name == "texture":
        # stable-audio-25 max 180s
        tex_dur = min(duration, 180)
        cmd.extend(["--duration", str(tex_dur)])
    elif duration and stem_name == "atmosphere":
        # stable-audio-25 max 180s — atmosphere DOES support duration
        atmo_dur = min(duration, 180)
        cmd.extend(["--duration", str(atmo_dur)])
    # accent doesn't support duration (short SFX)

    # Add lyrics for main vocal track
    if lyrics and stem_name == "main":
        cmd.extend(["--lyrics", lyrics])

    # Add instrumental flag if no lyrics or director specified it
    if stem_name == "main" and model == "elevenlabs-music":
        if force_instrumental or (force_instrumental is None and not lyrics):
            cmd.append("--instrumental")

    log(f"")
    log(f"{'='*60}")
    log(f"GENERATING STEM: {stem_name.upper()}")
    log(f"  Model: {model}")
    log(f"  Prompt: {stem_prompt[:100]}...")
    if lyrics and stem_name == "main":
        log(f"  Lyrics: {lyrics[:60]}...")
    log(f"{'='*60}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ},
        )

        # Log stderr (progress messages)
        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                log(f"  [{stem_name}] {line}")

        if result.returncode != 0:
            log(f"  ⛔ Stem '{stem_name}' failed (exit code {result.returncode})")
            error_msg = ""
            if result.stdout:
                try:
                    err = json.loads(result.stdout)
                    error_msg = err.get('error', 'unknown')
                    log(f"  Error: {error_msg}")
                except json.JSONDecodeError:
                    error_msg = result.stdout[:200]
                    log(f"  Output: {error_msg}")

            # Content policy retry: strip prompt to basics and retry
            if "content policy" in error_msg.lower() or "violates" in error_msg.lower():
                log(f"  🔄 Content policy hit — retrying with simplified prompt...")
                # Extract just genre, BPM, key from prompt
                detected_key, detected_bpm = extract_key_bpm(stem_prompt)
                simple_prompt = f"Instrumental electronic music track"
                if detected_bpm:
                    simple_prompt += f" at {detected_bpm} BPM"
                if detected_key:
                    simple_prompt += f" in {detected_key}"
                simple_prompt += f", heavy bass, dark mood, energetic drops, powerful synths, deep sub frequencies, intense rhythm"

                retry_cmd = [
                    sys.executable, VENICE_SCRIPT,
                    "--model", model,
                    "--prompt", simple_prompt,
                    "--output", stems_dir,
                ]
                if _CHAT_ID:
                    retry_cmd.extend(["--chat-id", str(_CHAT_ID)])
                if duration and stem_name == "main" and model != "minimax-music-v2":
                    retry_cmd.extend(["--duration", str(duration)])
                if stem_name == "main" and not lyrics and model == "elevenlabs-music":
                    retry_cmd.append("--instrumental")

                log(f"  Simplified prompt: {simple_prompt}")
                try:
                    retry_result = subprocess.run(
                        retry_cmd, capture_output=True, text=True, timeout=600, env={**os.environ}
                    )
                    if retry_result.returncode == 0:
                        retry_output = json.loads(retry_result.stdout)
                        if retry_output.get("success"):
                            log(f"  ✅ Retry succeeded with simplified prompt!")
                            # Continue with the successful result
                            result = retry_result
                            # Jump to the success path below
                        else:
                            log(f"  ⛔ Retry also failed: {retry_output.get('error')}")
                            return None
                    else:
                        log(f"  ⛔ Retry also rejected — model too restrictive for this genre")
                        return None
                except Exception as e:
                    log(f"  ⛔ Retry error: {e}")
                    return None
            else:
                return None

        # Parse JSON output
        output = json.loads(result.stdout)
        if not output.get("success"):
            log(f"  ⛔ Stem '{stem_name}' generation failed: {output.get('error')}")
            return None

        elapsed = time.time() - start
        filepath = output["file"]

        # Rename to descriptive role-based filename
        ext = os.path.splitext(filepath)[1]
        clean_name = f"{stem_name}_{model}{ext}"
        renamed_path = os.path.join(os.path.dirname(filepath), clean_name)
        try:
            os.rename(filepath, renamed_path)
            filepath = renamed_path
        except OSError:
            pass  # Keep original name if rename fails

        log(f"  ✅ Stem '{stem_name}' done: {filepath} ({elapsed:.0f}s)")
        stem_cost = output.get("cost", {"cost_usd": 0, "credits": 0})
        return {
            "role": stem_name,
            "model": model,
            "file": filepath,
            "generation_time": round(elapsed, 1),
            "cost": stem_cost,
        }

    except subprocess.TimeoutExpired:
        log(f"  ⛔ Stem '{stem_name}' timed out after 600s")
        return None
    except Exception as e:
        log(f"  ⛔ Stem '{stem_name}' error: {e}")
        return None


def get_audio_duration(filepath):
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", filepath],
            capture_output=True, text=True, timeout=10,
        )
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except Exception:
        return None


def mix_stems(stems, output_dir, target="streaming"):
    """Mix multiple stems together using ffmpeg. Returns mixed file path."""
    if not stems:
        fail("No stems to mix")

    if len(stems) == 1:
        # Only one stem, just copy it
        return stems[0]["file"]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mix_path = os.path.join(output_dir, f"mix_{timestamp}.wav")

    log("")
    log("=" * 60)
    log("MIXING STEMS")
    log("=" * 60)

    # Get main track duration for looping/trimming secondary stems
    main_stem = next((s for s in stems if s["role"] == "main"), stems[0])
    main_duration = get_audio_duration(main_stem["file"])
    if main_duration:
        log(f"  Main track duration: {main_duration:.1f}s")

    # Build ffmpeg filter complex for mixing
    inputs = []
    filter_parts = []

    for i, stem in enumerate(stems):
        config = STEM_CONFIG[stem["role"]]
        # Use K3 Mix Engineer overrides if available, else STEM_CONFIG defaults
        volume = stem.get("mix_volume_override", config["mix_volume"])
        pan = stem.get("mix_pan_override", config.get("pan", 0.0))

        inputs.extend(["-i", stem["file"]])

        # Get this stem's duration
        stem_dur = get_audio_duration(stem["file"])

        # Build per-stem filter: volume adjust + panning + optional pad/trim
        # Use arrangement-based volume if available (creates dynamic sections)
        arr_expr = build_arrangement_volume(stem["role"], main_duration)
        if arr_expr:
            stem_filter = f"[{i}:a]volume='{arr_expr}':eval=frame"
        else:
            stem_filter = f"[{i}:a]volume={volume}"

        # Apply K3 mix EQ override if present
        eq_override = stem.get("mix_eq_override", "")
        if eq_override:
            if eq_override.startswith("lowpass_"):
                freq = eq_override.split("_")[1].replace("hz", "")
                stem_filter += f",lowpass=f={freq}"
            elif eq_override.startswith("highpass_"):
                freq = eq_override.split("_")[1].replace("hz", "")
                stem_filter += f",highpass=f={freq}"

        # Apply panning via stereotools balance
        if pan != 0.0:
            stem_filter += f",stereotools=balance_out={pan}"

        # Apply per-stem HP filter for frequency separation (L-ISA optimization)
        if target in ("l-acoustics", "club"):
            hp = STEM_HP_FILTERS.get(stem["role"])
            if hp:
                stem_filter += f",{hp}"

        # Smart accent placement: don't pad short accents to fill the whole song
        is_accent = stem["role"] == "accent" and config.get("placement") == "transitions"

        if main_duration and stem_dur and stem["role"] != "main":
            if is_accent and stem_dur < 15:
                # Accent is a short SFX — place it at ~38% mark (just before the drop)
                # so it has room to ring out before breakdown at 60%
                accent_offset = max(0, main_duration * 0.38)
                stem_filter += f",adelay={int(accent_offset * 1000)}|{int(accent_offset * 1000)}"
                stem_filter += f",apad=whole_dur={main_duration}"
                log(f"  Accent placed at {accent_offset:.0f}s (pre-drop transition)")
            elif stem_dur < main_duration:
                # Pad with silence to match main track length
                pad_dur = main_duration - stem_dur
                stem_filter += f",apad=pad_dur={pad_dur}"

            # Trim to main track length
            stem_filter += f",atrim=0:{main_duration}"

        stem_filter += f"[s{i}]"
        filter_parts.append(stem_filter)

        pan_str = f", pan={pan:+.1f}" if pan != 0.0 else ""
        log(f"  Stem {i}: {stem['role']} (vol={volume}{pan_str}, model={stem['model']})")

    # Mix all stems together with proper gain compensation
    # amix normalize=0 prevents automatic level reduction but we need manual compensation
    stem_labels = "".join(f"[s{i}]" for i in range(len(stems)))
    # Use a higher weight for main stem to keep it prominent
    if len(stems) > 1:
        # Main gets weight 1.0, others proportional to their mix_volume
        weights = []
        for s in stems:
            w = STEM_CONFIG[s["role"]]["mix_volume"]
            weights.append(str(w))
        weights_str = " ".join(weights)
        filter_parts.append(f"{stem_labels}amix=inputs={len(stems)}:duration=longest:normalize=0:weights={weights_str}[mixed]")
    else:
        filter_parts.append(f"{stem_labels}amix=inputs=1:normalize=0[mixed]")

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[mixed]",
        "-ar", str(TARGET_PROFILES.get(target, TARGET_PROFILES["streaming"])["sample_rate"]),
        "-ac", "2",
        mix_path,
    ]

    log(f"  Running ffmpeg mix...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log(f"  ⛔ Mix failed: {result.stderr[-300:]}")
            # Fallback: just return the main track
            log(f"  Falling back to main track only")
            return main_stem["file"]
        log(f"  ✅ Mix complete: {mix_path}")
        return mix_path
    except Exception as e:
        log(f"  ⛔ Mix error: {e}")
        return main_stem["file"]


def master_audio(input_path, output_dir, skip_master=False, target="streaming", track_title="Hermes Music"):
    """Apply target-specific mastering chain using ffmpeg. Returns dict with primary path and all files."""
    if skip_master:
        log("  Mastering skipped (--skip-master)")
        return {"primary": input_path, "files": {}}

    profile = TARGET_PROFILES.get(target, TARGET_PROFILES["streaming"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    log("")
    log("=" * 60)
    log(f"MASTERING — Target: {target.upper()}")
    log(f"  {profile['description']}")
    log("=" * 60)

    duration = get_audio_duration(input_path)
    fade_out_dur = 5.0  # Professional fade-out length
    fade_out_start = max(0, (duration or 60) - fade_out_dur)

    # Build mastering filter chain from profile
    filters = []

    # 1. Subsonic HP filter
    # ffmpeg highpass 'p' (poles) only accepts 1 or 2
    hp_order = min(profile['hp_order'], 2)
    filters.append(f"highpass=f={profile['hp_freq']}:p={hp_order}")

    # 2. Mono fold below threshold (L-Acoustics/Club)
    if profile.get("mono_fold_below"):
        freq = profile["mono_fold_below"]
        filters.append(f"crossfeed=freq={freq}:slope=1")

    # 3. Compression
    filters.append(
        f"acompressor=threshold={profile['comp_threshold']}dB"
        f":ratio={profile['comp_ratio']}"
        f":attack={profile['comp_attack']}"
        f":release={profile['comp_release']}"
        f":makeup={profile['comp_makeup']}dB"
    )

    # 4. EQ bands
    for eq in profile["eq"]:
        filters.append(f"equalizer=f={eq['f']}:t=q:w={eq['w']}:g={eq['g']}")

    # 5. Stereo field optimization
    if profile["stereo_mid"] != 1.0 or profile["stereo_side"] != 1.0:
        filters.append(f"stereotools=mlev={profile['stereo_mid']}:slev={profile['stereo_side']}")

    # 6. Loudness normalization
    filters.append(f"loudnorm=I={profile['lufs']}:TP={profile['true_peak']}:LRA={profile['lra']}")

    # 7. Limiter
    filters.append(f"alimiter=limit={profile['true_peak']}dB:level=false")

    # 8. Fade in/out
    filters.append("afade=t=in:ss=0:d=0.5")
    filters.append(f"afade=t=out:st={fade_out_start}:d={fade_out_dur}")

    mastering_filter = ",".join(filters)
    sr = str(profile["sample_rate"])

    # Log the chain
    log(f"  Mastering chain ({len(filters)} stages):")
    log(f"    HP: {profile['hp_freq']}Hz ({profile['hp_order']*12}dB/oct)")
    if profile.get("mono_fold_below"):
        log(f"    Mono fold: <{profile['mono_fold_below']}Hz")
    log(f"    Compression: {profile['comp_ratio']}:1, atk={profile['comp_attack']}ms, rel={profile['comp_release']}ms")
    for eq in profile["eq"]:
        sign = "+" if eq["g"] > 0 else ""
        log(f"    EQ: {sign}{eq['g']}dB @ {eq['f']}Hz (Q={eq['w']})")
    if profile["stereo_mid"] != 1.0:
        log(f"    Stereo: mid={profile['stereo_mid']}, side={profile['stereo_side']}")
    log(f"    Loudness: {profile['lufs']} LUFS, TP={profile['true_peak']}dB, LRA={profile['lra']}")
    log(f"    Sample rate: {int(sr)/1000:.0f}kHz / 24-bit")
    log(f"    Formats: {', '.join(f.upper() for f in profile['outputs'])}")

    # Metadata for all outputs
    meta = [
        "-metadata", f"title={track_title}",
        "-metadata", "artist=Hermes Music",
        "-metadata", f"comment=Mastered by Hermes Music — {target} target",
    ]

    output_files = {}
    primary_path = None

    try:
        # Step 1: Master to primary format at target sample rate
        primary_fmt = profile["primary_format"]
        primary_file = os.path.join(output_dir, f"master_{timestamp}.{primary_fmt}")

        cmd_primary = [
            "ffmpeg", "-y", "-i", input_path,
            "-af", mastering_filter,
            "-ar", sr, "-ac", "2",
        ]
        # Codec depends on output format
        if primary_fmt == "flac":
            cmd_primary += ["-sample_fmt", "s32"]  # FLAC uses its own codec
        elif primary_fmt == "aiff":
            cmd_primary += ["-c:a", "pcm_s24be"]   # AIFF needs big-endian
        elif primary_fmt in ("wav",):
            cmd_primary += ["-c:a", "pcm_s24le"]   # WAV uses little-endian
        cmd_primary += [*meta, primary_file]


        result = subprocess.run(cmd_primary, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            # Fallback: try without crossfeed if that caused the error
            if profile.get("mono_fold_below"):
                log(f"  ⚠️ Primary failed, retrying without crossfeed...")
                filters_fallback = [f for f in filters if "crossfeed" not in f]
                mastering_filter_fb = ",".join(filters_fallback)
                cmd_fb = [
                    "ffmpeg", "-y", "-i", input_path,
                    "-af", mastering_filter_fb,
                    "-ar", sr, "-ac", "2", "-c:a", "pcm_s24le",
                    *meta, primary_file,
                ]
                result = subprocess.run(cmd_fb, capture_output=True, text=True, timeout=180)
            if result.returncode != 0:
                log(f"  ⛔ Primary mastering failed: {result.stderr[-300:]}")
                return {"primary": input_path, "files": {}}

        log(f"  ✅ Primary ({primary_fmt.upper()}): {primary_file}")
        output_files[primary_fmt] = primary_file
        primary_path = primary_file

        # Step 2: Generate additional formats from the primary master
        for fmt in profile["outputs"]:
            if fmt == primary_fmt:
                continue

            out_file = os.path.join(output_dir, f"master_{timestamp}.{fmt}")

            if fmt == "mp3":
                cmd = ["ffmpeg", "-y", "-i", primary_file,
                       "-b:a", "320k", "-id3v2_version", "3", *meta, out_file]
            elif fmt == "flac":
                cmd = ["ffmpeg", "-y", "-i", primary_file,
                       "-ar", "48000", "-sample_fmt", "s32", *meta, out_file]
            elif fmt == "wav":
                cmd = ["ffmpeg", "-y", "-i", primary_file,
                       "-ar", sr, "-c:a", "pcm_s24le", *meta, out_file]
            elif fmt == "aiff":
                cmd = ["ffmpeg", "-y", "-i", primary_file,
                       "-ar", sr, "-c:a", "pcm_s24le", *meta, out_file]
            else:
                continue

            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode == 0:
                log(f"  ✅ {fmt.upper()} copy: {out_file}")
                output_files[fmt] = out_file
            else:
                log(f"  ⚠️ {fmt.upper()} failed")

        return {"primary": primary_path, "files": output_files}

    except Exception as e:
        log(f"  ⛔ Mastering error: {e}")
        return {"primary": input_path, "files": {}}


def matchering_master(input_path, output_dir, reference_dir=None, track_title="Hermes Music"):
    """Apply reference-based mastering using Matchering.
    Matches RMS, frequency response, peak amplitude, and stereo width to a reference track."""
    try:
        import matchering as mg
    except ImportError:
        log("  ⚠️ matchering not installed — skipping reference mastering")
        return None

    # Find reference tracks
    ref_dir = reference_dir or os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "music", "references")
    if not os.path.isdir(ref_dir):
        log(f"  ⚠️ No reference directory at {ref_dir} — skipping reference mastering")
        return None

    # Find any .wav/.flac/.mp3 in the references dir
    ref_file = None
    for ext in ("*.wav", "*.flac", "*.mp3"):
        import glob
        matches = glob.glob(os.path.join(ref_dir, "**", ext), recursive=True)
        if matches:
            ref_file = matches[0]
            break

    if not ref_file:
        log(f"  ⚠️ No reference tracks found in {ref_dir}")
        return None

    log(f"  🎯 Reference track: {os.path.basename(ref_file)}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_wav = os.path.join(output_dir, f"master_ref_{timestamp}.wav")
    out_mp3 = os.path.join(output_dir, f"master_ref_{timestamp}.mp3")

    try:
        mg.process(
            target=input_path,
            reference=ref_file,
            results=[
                mg.pcm24(out_wav),
                mg.mp3(out_mp3),
            ],
        )
        log(f"  ✅ Matchering: reference-mastered to {os.path.basename(ref_file)}")
        log(f"    WAV: {out_wav}")
        log(f"    MP3: {out_mp3}")

        # Also create FLAC
        out_flac = os.path.join(output_dir, f"master_ref_{timestamp}.flac")
        flac_cmd = ["ffmpeg", "-y", "-i", out_wav, "-ar", "48000", "-sample_fmt", "s32", out_flac]
        subprocess.run(flac_cmd, capture_output=True, text=True, timeout=60)
        if os.path.isfile(out_flac):
            log(f"    FLAC: {out_flac}")

        return {
            "primary": out_wav,
            "files": {
                "wav": out_wav,
                "mp3": out_mp3,
                "flac": out_flac if os.path.isfile(out_flac) else None,
            },
            "reference": os.path.basename(ref_file),
        }
    except Exception as e:
        log(f"  ⚠️ Matchering failed: {e}")
        return None


def preflight_audio_check(filepath):
    """Scan for sudden volume drops that would sound jarring.

    Measures RMS in 1-second windows and flags any window where:
    - RMS drops > 6dB from the previous window (sudden drop)
    - RMS is > 10dB below the track average (dead section)

    Returns dict with pass/fail, drop timestamps, and severity.
    """
    result = {"pass": True, "drops": [], "dead_sections": []}
    try:
        import numpy as np
        # Use ffmpeg to extract raw PCM and analyze in 1s windows
        cmd = [
            "ffmpeg", "-i", filepath, "-f", "f32le", "-acodec", "pcm_f32le",
            "-ac", "1", "-ar", "22050", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode != 0:
            return result

        samples = np.frombuffer(proc.stdout, dtype=np.float32)
        sr = 22050
        window = sr  # 1 second windows
        n_windows = len(samples) // window
        if n_windows < 3:
            return result

        rms_values = []
        for i in range(n_windows):
            chunk = samples[i * window:(i + 1) * window]
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            rms_values.append(rms)

        # Convert to dB (relative to max RMS)
        max_rms = max(rms_values) if rms_values else 1e-10
        rms_db = [20 * np.log10(max(r, 1e-10) / max(max_rms, 1e-10)) for r in rms_values]
        avg_db = sum(rms_db) / len(rms_db)

        # Check for sudden drops (> 6dB between consecutive windows)
        for i in range(1, len(rms_db)):
            drop = rms_db[i - 1] - rms_db[i]  # positive = got quieter
            if drop > 6.0:
                result["drops"].append({
                    "time_sec": i,
                    "drop_db": round(drop, 1),
                    "severity": "severe" if drop > 10 else "moderate",
                })

        # Check for dead sections (> 10dB below average)
        for i, db in enumerate(rms_db):
            if db < avg_db - 10:
                result["dead_sections"].append({
                    "time_sec": i,
                    "level_db": round(db, 1),
                    "below_avg_db": round(avg_db - db, 1),
                })

        if result["drops"] or result["dead_sections"]:
            result["pass"] = False
            drop_count = len(result["drops"])
            dead_count = len(result["dead_sections"])
            log(f"  ⚠️ Pre-flight: {drop_count} sudden drops, {dead_count} dead sections")
            for d in result["drops"][:3]:  # show first 3
                log(f"    📉 {d['time_sec']}s: -{d['drop_db']}dB drop ({d['severity']})")
        else:
            log(f"  ✅ Pre-flight: no sudden drops or dead sections detected")

    except ImportError:
        log("  ⚠️ numpy not available — skipping pre-flight check")
    except Exception as e:
        log(f"  ⚠️ Pre-flight check error: {e}")

    return result


def analyze_master_qc(filepath, target="streaming"):
    """Run loudness, spectral, and pre-flight analysis on mastered file. Returns QC dict."""
    qc = {"target": target}
    try:
        # Loudness stats via loudnorm in measure mode
        cmd = [
            "ffmpeg", "-i", filepath, "-af",
            "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        # Parse loudnorm JSON from stderr
        stderr = result.stderr
        json_start = stderr.rfind("{")
        json_end = stderr.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            stats = json.loads(stderr[json_start:json_end])
            qc["integrated_lufs"] = float(stats.get("input_i", 0))
            qc["true_peak_db"] = float(stats.get("input_tp", 0))
            qc["lra"] = float(stats.get("input_lra", 0))

        # Determine pass/fail
        profile = TARGET_PROFILES.get(target, TARGET_PROFILES["streaming"])
        target_lufs = profile["lufs"]
        lufs = qc.get("integrated_lufs", -99)
        tp = qc.get("true_peak_db", 0)
        qc["lufs_pass"] = abs(lufs - target_lufs) <= 3
        qc["tp_pass"] = tp <= profile["true_peak"] + 0.5

        # Pre-flight waveform check for sudden drops / dead sections
        preflight = preflight_audio_check(filepath)
        qc["preflight_pass"] = preflight["pass"]
        qc["preflight_drops"] = preflight.get("drops", [])
        qc["preflight_dead_sections"] = preflight.get("dead_sections", [])

        qc["overall_pass"] = qc["lufs_pass"] and qc["tp_pass"] and qc["preflight_pass"]

    except Exception as e:
        log(f"  ⚠️ QC analysis error: {e}")
        qc["error"] = str(e)

    return qc


def export_stems_lisa(stems, output_dir, target, track_title="Hermes Music"):
    """Export individual stems as AIFF files for L-ISA routing."""
    profile = TARGET_PROFILES.get(target, TARGET_PROFILES["streaming"])
    if not profile.get("export_stems"):
        return None

    stems_export_dir = os.path.join(output_dir, "stems_lisa")
    os.makedirs(stems_export_dir, exist_ok=True)
    sr = str(profile["sample_rate"])
    manifest_stems = []

    # L-ISA object position suggestions
    lisa_objects = {
        "main": "center_front",
        "texture": "surround_wide",
        "accent": "overhead_fx",
        "atmosphere": "surround_ambient",
    }
    stem_freq_ranges = {
        "main": "20-20000Hz",
        "texture": "300-16000Hz",
        "accent": "500-16000Hz",
        "atmosphere": "300-16000Hz",
    }

    log("")
    log("L-ISA STEM EXPORT")
    log("-" * 60)

    for i, stem in enumerate(stems):
        role = stem["role"]
        src = stem["file"]
        out_name = f"{i+1:02d}_{role}.aiff"
        out_path = os.path.join(stems_export_dir, out_name)

        cmd = [
            "ffmpeg", "-y", "-i", src,
            "-ar", sr, "-ac", "2", "-sample_fmt", "s32",
            "-metadata", f"title={track_title} — {role}",
            "-metadata", "artist=Hermes Music",
            out_path,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                log(f"  ✅ {out_name} ({lisa_objects.get(role, 'default')})")
                manifest_stems.append({
                    "file": out_name,
                    "role": role,
                    "l_isa_object": lisa_objects.get(role, "default"),
                    "frequency_range": stem_freq_ranges.get(role, "full"),
                    "model": stem["model"],
                })
            else:
                log(f"  ⚠️ {out_name} failed")
        except Exception as e:
            log(f"  ⚠️ {out_name} error: {e}")

    # Write manifest
    manifest = {
        "format": "l-isa-stems-v1",
        "track_title": track_title,
        "target": target,
        "sample_rate": int(sr),
        "bit_depth": 24,
        "stems": manifest_stems,
    }
    manifest_path = os.path.join(stems_export_dir, "stems_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"  ✅ Manifest: {manifest_path}")

    return stems_export_dir


def save_production_metadata(session_dir, args, target_profile, generated_stems,
                              master_result, qc_report, cost_report, pipeline_time, lisa_dir=None):
    """Save detailed production metadata for DJ profile reference and reproducibility."""
    timestamp = datetime.now().isoformat()

    # Build stem details
    stem_details = []
    for stem in generated_stems:
        config = STEM_CONFIG[stem["role"]]
        stem_detail = {
            "role": stem["role"],
            "model": stem["model"],
            "prompt": config["prompt_template"].format(prompt=args.prompt),
            "file": os.path.basename(stem["file"]),
            "generation_time_seconds": stem.get("generation_time", 0),
            "mix_volume": config["mix_volume"],
            "pan": config.get("pan", 0.0),
            "cost": stem.get("cost", {}),
        }
        if stem["role"] == "accent":
            stem_detail["placement"] = config.get("placement", "full")
        if stem["role"] == "main" and args.lyrics:
            stem_detail["lyrics"] = args.lyrics
        stem_details.append(stem_detail)

    # Build the full metadata
    metadata = {
        "version": "2.0",
        "created_at": timestamp,
        "session_dir": session_dir,

        # Input parameters — what was requested
        "request": {
            "prompt": args.prompt,
            "lyrics": args.lyrics,
            "quality_tier": args.quality,
            "target": args.target,
            "duration_requested": args.duration,
            "main_model_override": args.main_model,
        },

        # Composition details — how it was built
        "composition": {
            "quality_tier": args.quality,
            "quality_description": QUALITY_TIERS[args.quality]["description"],
            "stem_count": len(generated_stems),
            "stems": stem_details,
        },

        # Target profile — mastering settings used
        "mastering_profile": {
            "target": args.target,
            "description": target_profile["description"],
            "lufs": target_profile["lufs"],
            "true_peak": target_profile["true_peak"],
            "lra": target_profile["lra"],
            "sample_rate": target_profile["sample_rate"],
            "hp_freq": target_profile["hp_freq"],
            "hp_order": target_profile["hp_order"],
            "mono_fold_below": target_profile.get("mono_fold_below"),
            "compression": {
                "threshold": target_profile["comp_threshold"],
                "ratio": target_profile["comp_ratio"],
                "attack_ms": target_profile["comp_attack"],
                "release_ms": target_profile["comp_release"],
                "makeup_db": target_profile["comp_makeup"],
            },
            "eq_bands": target_profile["eq"],
            "stereo": {
                "mid_level": target_profile["stereo_mid"],
                "side_level": target_profile["stereo_side"],
            },
            "primary_format": target_profile["primary_format"],
            "output_formats": target_profile["outputs"],
        },

        # Output files — what was produced
        "outputs": {
            "primary_file": os.path.basename(master_result.get("primary", "")),
            "all_files": {fmt: os.path.basename(p) for fmt, p in master_result.get("files", {}).items()},
            "lisa_stems_dir": os.path.basename(lisa_dir) if lisa_dir else None,
        },

        # Quality control — measured results
        "qc_report": qc_report,

        # Cost and timing
        "cost_report": cost_report,
        "pipeline_time_seconds": round(pipeline_time, 1),

        # Reproducibility — exact command to recreate
        "reproduce_command": (
            f"python master-producer.py"
            f" --prompt \"{args.prompt}\""
            f" --quality {args.quality}"
            f" --target {args.target}"
            f" --duration {args.duration}"
            + (f" --lyrics \"{args.lyrics}\"" if args.lyrics else "")
            + (f" --main-model {args.main_model}" if args.main_model else "")
        ),

        # DJ profile tags — for finding similar tracks later
        "dj_profile": {
            "prompt_keywords": [w.strip().lower() for w in args.prompt.replace(",", " ").split() if len(w.strip()) > 3],
            "has_vocals": bool(args.lyrics),
            "target_system": args.target,
            "format": target_profile["primary_format"],
            "sample_rate": target_profile["sample_rate"],
            "loudness_lufs": qc_report.get("integrated_lufs"),
            "true_peak_db": qc_report.get("true_peak_db"),
            "pa_ready": qc_report.get("overall_pass", False),
        },
    }

    # Save to session directory
    metadata_path = os.path.join(session_dir, "production_metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    log(f"  📋 Metadata: {metadata_path}")

    return metadata_path


def main():
    global _CHAT_ID, _BOT_TOKEN
    parser = argparse.ArgumentParser(description="Master Producer — Multi-model AI music production")
    parser.add_argument("--prompt", required=True, help="Song/audio description")
    parser.add_argument("--lyrics", default=None, help="Song lyrics (triggers vocal model)")
    parser.add_argument("--quality", default="standard", choices=["quick", "standard", "premium"],
                        help="Production quality tier (default: standard)")
    parser.add_argument("--duration", type=int, default=60, help="Target duration in seconds (default: 60)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--main-model", default=None, help="Override main track model")
    parser.add_argument("--skip-master", action="store_true", help="Skip mastering chain")
    parser.add_argument("--no-deliver", action="store_true",
                        help="Skip Telegram delivery (for batch album mode)")
    parser.add_argument("--target", default="streaming",
                        choices=["streaming", "l-acoustics", "club", "headphones"],
                        help="Mastering target profile (default: streaming)")
    parser.add_argument("--chat-id", default=None, help="Telegram chat ID (auto-detected if omitted)")
    parser.add_argument("--preview", action="store_true", default=None,
                        help="Preview mode: MP3 only to Telegram, no FLAC (auto-on when duration ≤ 30s)")
    parser.add_argument("--compose", action="store_true",
                        help="Auto-enhance prompt via Venice LLM before generating")
    parser.add_argument("--research", action="store_true",
                        help="Deep genre research via Venice LLM before composing")
    parser.add_argument("--director", action="store_true",
                        help="Use Kimi K3 Creative Director for per-stem prompt planning (recommended)")
    parser.add_argument("--director-model", default=None,
                        help="Override director LLM model (default: kimi-k3, budget: kimi-k2-6)")
    parser.add_argument("--plan", default=None,
                        help="Path to a production_plan.json to replay (locks prompts/models from a preview)")
    parser.add_argument("--profile", default=None,
                        help="DJ profile name to load defaults from (auto-detects active if omitted)")

    args = parser.parse_args()

    # Set up Telegram notifications — auto-detect if --chat-id not passed
    _CHAT_ID = args.chat_id
    _auto_detect_telegram()

    # Suppress Telegram spam in batch/album mode
    global _SILENT_MODE
    if args.no_deliver:
        _SILENT_MODE = True
        os.environ["HERMES_SILENT"] = "1"  # Propagate to venice-music.py subprocesses

    tier = QUALITY_TIERS[args.quality]
    stem_names = tier["stems"]
    target_profile = TARGET_PROFILES[args.target]

    log("╔══════════════════════════════════════════════════════════╗")
    log("║          🎵 MASTER PRODUCER — AI STUDIO 🎵              ║")
    log("╚══════════════════════════════════════════════════════════╝")
    log(f"")
    log(f"Quality:  {args.quality} ({tier['description']})")
    log(f"Target:   {args.target} ({target_profile['description']})")
    log(f"Stems:    {', '.join(stem_names)}")
    log(f"Duration: {args.duration}s")
    log(f"Prompt:   {args.prompt[:100]}{'...' if len(args.prompt) > 100 else ''}")
    if args.lyrics:
        log(f"Lyrics:   {args.lyrics[:80]}{'...' if len(args.lyrics) > 80 else ''}")
    log(f"")

    # Override main model if specified
    if args.main_model:
        if args.lyrics:
            STEM_CONFIG["main"]["model_vocal"] = args.main_model
        else:
            STEM_CONFIG["main"]["model_instrumental"] = args.main_model
        log(f"Main model override: {args.main_model}")

    # Load DJ profile (explicit name or auto-detect active)
    active_profile = None
    if args.profile:
        profiles_dir = os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "music", "profiles")
        profile_slug = slugify(args.profile)
        profile_path = os.path.join(profiles_dir, profile_slug, "profile.json")
        if os.path.isfile(profile_path):
            with open(profile_path) as f:
                active_profile = json.load(f)
            log(f"Profile:  {active_profile.get('name', args.profile)}")
        else:
            log(f"⚠️ Profile '{args.profile}' not found — proceeding without")
    else:
        active_profile = load_active_profile()

    # Apply profile defaults (if not explicitly overridden)
    # NOTE: When --director or --plan is used, skip model override — K3 picks per-stem
    if active_profile:
        defaults = active_profile.get("defaults", {})
        use_director = args.plan or args.director or (not args.research and not args.compose)
        if not args.main_model and defaults.get("main_model") and not use_director:
            model_override = defaults["main_model"]
            if args.lyrics:
                STEM_CONFIG["main"]["model_vocal"] = model_override
            else:
                STEM_CONFIG["main"]["model_instrumental"] = model_override
            log(f"  Profile model: {model_override}")
        elif defaults.get("main_model") and use_director:
            log(f"  Profile model skipped (K3 director handles model selection)")
        prefix = active_profile.get("prompt_prefix", "")
        if prefix and prefix not in args.prompt and not use_director:
            args.prompt = f"{prefix}. {args.prompt}"
            log(f"  Profile prefix applied")
        elif prefix and use_director:
            log(f"  Profile prefix skipped (K3 has full profile context)")

    # Creative Director: Kimi K3 produces structured per-stem plan
    original_prompt = args.prompt
    production_plan = None

    # Plan replay mode: lock prompts/models from a preview's production_plan.json
    if args.plan:
        log("")
        log("PHASE 0: PLAN REPLAY (Preview Lock)")
        log("-" * 60)
        try:
            with open(args.plan) as f:
                production_plan = json.load(f)
            # Strip QC/cost from preview — will be recalculated for full track
            production_plan.pop("qc", None)
            production_plan.pop("cost", None)
            log(f"  🔒 Locked plan: {production_plan.get('title', '?')}")
            log(f"  Genre: {production_plan.get('genre')} | BPM: {production_plan.get('bpm')} | Key: {production_plan.get('key')}")
            log(f"  Duration override: {args.duration}s")
            for sn, si in production_plan.get("stems", {}).items():
                if isinstance(si, dict):
                    log(f"  {sn:12s} → {si.get('model', '?'):25s} (locked)")
            # Check if quality tier needs stems not in the plan
            plan_stems = set(production_plan.get("stems", {}).keys())
            needed_stems = set(stem_names)
            missing_stems = needed_stems - plan_stems
            if missing_stems:
                log(f"  📋 Missing stems for {args.quality} tier: {', '.join(missing_stems)}")
                log(f"  Calling K3 to fill missing stems only...")
                fill_plan = creative_director(
                    args.prompt, args.quality, args.duration,
                    lyrics=args.lyrics, profile=active_profile,
                )
                if fill_plan:
                    for ms in missing_stems:
                        if ms in fill_plan.get("stems", {}):
                            production_plan["stems"][ms] = fill_plan["stems"][ms]
                            log(f"  ✅ Filled {ms}: {fill_plan['stems'][ms].get('model', '?')}")
            telegram_notify(f"🔒 *Replaying locked plan: {production_plan.get('title', '?')}*\nDuration: {args.duration}s")
        except Exception as e:
            log(f"  ⚠️ Failed to load plan: {e}")
            production_plan = None
        log("")

    elif args.director or (not args.research and not args.compose):
        log("")
        log("PHASE 0: CREATIVE DIRECTOR")
        log("-" * 60)
        report_progress("director")
        telegram_notify("🎬 *Creative Director planning production...*")
        if args.director_model:
            os.environ["DIRECTOR_MODEL"] = args.director_model
        # Load album context if producing as part of an album
        album_context = None
        album_context_file = os.environ.get("ALBUM_CONTEXT_FILE")
        if album_context_file and os.path.isfile(album_context_file):
            try:
                with open(album_context_file) as f:
                    album_context = json.load(f)
                log(f"  📀 Album mode: track {album_context.get('track_number', '?')}/{album_context.get('total_tracks', '?')}")
                rules = album_context.get("variation_rules", [])
                if rules:
                    log(f"  🎲 Variation: {rules[0]}")
            except Exception:
                pass
        production_plan = creative_director(
            args.prompt, args.quality, args.duration,
            lyrics=args.lyrics, profile=active_profile,
            album_context=album_context,
        )
        if production_plan:
            # Pass 1c: Upscale each stem prompt for richer audio output
            genre = production_plan.get("genre", "")
            bpm = production_plan.get("bpm", 0)
            key = production_plan.get("key", "")
            for stem_name, stem_info in production_plan.get("stems", {}).items():
                if isinstance(stem_info, dict) and stem_info.get("prompt"):
                    model = stem_info.get("model", "")
                    max_chars = {"stable-audio-25": 490, "elevenlabs-sound-effects-v2": 490,
                                 "minimax-music-v2": 290}.get(model, 500)
                    stem_info["prompt"] = upscale_prompt(
                        stem_info["prompt"], stem_name,
                        genre=genre, bpm=bpm, key=key, max_chars=max_chars
                    )
            log("")
        else:
            log("  K3 failed — injecting sonic DNA for fallback")
            # Inject prompt_prefix so fallback prompt has sonic identity
            if active_profile:
                prefix = active_profile.get("prompt_prefix", "")
                if prefix and prefix not in args.prompt:
                    args.prompt = f"{prefix}. {args.prompt}"

    # Legacy fallback: research + compose (if director failed or explicitly requested)
    if not production_plan:
        if args.research:
            log("")
            log("PHASE 0a: GENRE RESEARCH")
            log("-" * 60)
            telegram_notify("🔍 *Researching genre & production techniques...*")
            args.prompt = research_genre(args.prompt, profile=active_profile)
            log("")

        if args.compose:
            log("")
            log("PHASE 0b: PROMPT COMPOSITION")
            log("-" * 60)
            telegram_notify("🧠 *Composing production brief...*")
            args.prompt = compose_prompt(args.prompt, profile=active_profile)
            log("")

    pipeline_start = time.time()
    generated_stems = []

    # Create organized session directory
    session_dir, stems_dir = create_session_dir(args.output, args.prompt)
    log(f"Session:  {session_dir}")
    log(f"")

    total_stems = len(stem_names)
    stem_labels = {"main": "🎤 Main Track", "texture": "🌊 Texture Layer", "accent": "💥 Accent FX", "atmosphere": "🌌 Atmosphere"}

    telegram_notify(
        f"🎵 *Starting {args.quality} production*\n"
        f"🎯 Target: {args.target}\n"
        f"📋 Pipeline: {total_stems} stems → mix → master\n"
        f"⏱️ Estimated: {3 * total_stems + 2}-{5 * total_stems + 5} minutes"
    )

    # Step 1: Generate stems sequentially
    log("PHASE 1: STEM GENERATION")
    log("-" * 60)
    report_progress("stems")

    for i, stem_name in enumerate(stem_names, 1):
        label = stem_labels.get(stem_name, stem_name)
        remaining = total_stems - i
        telegram_notify(
            f"{label} ({i}/{total_stems})\n"
            f"{'✅ ' * (i-1)}{'⏳ ' + '⬜ ' * remaining if remaining >= 0 else ''}"
        )

        # Use Creative Director plan if available
        stem_prompt = args.prompt
        stem_model_override = None
        stem_instrumental = None
        if production_plan and stem_name in production_plan.get("stems", {}):
            plan_stem = production_plan["stems"][stem_name]
            stem_prompt = plan_stem.get("prompt", args.prompt)
            stem_model_override = plan_stem.get("model")
            stem_instrumental = plan_stem.get("instrumental")
            log(f"  📋 Director plan: {stem_model_override} | \"{stem_prompt[:80]}...\"")

        stem_result = generate_stem(
            stem_name=stem_name,
            prompt=stem_prompt,
            lyrics=args.lyrics if stem_name == "main" else None,
            duration=args.duration,
            stems_dir=stems_dir,
            model_override=stem_model_override,
            force_instrumental=stem_instrumental,
        )
        if stem_result:
            generated_stems.append(stem_result)
        else:
            if stem_name == "main":
                fail(f"Main track generation failed — cannot proceed")
            else:
                log(f"  ⚠️ Optional stem '{stem_name}' failed — continuing without it")

    log(f"")
    log(f"Generated {len(generated_stems)}/{total_stems} stems successfully")

    # Step 1b: Generate B-section for breakdown contrast (premium/standard quality)
    if args.quality in ("standard", "premium") and len(generated_stems) >= 2:
        log("")
        log("PHASE 1b: B-SECTION GENERATION")
        log("-" * 60)
        telegram_notify("🎭 *Generating breakdown contrast section...*")
        # Try Demucs-powered B-section first (Phase 2)
        main_stem_file = next((s["file"] for s in generated_stems if s["role"] == "main"), None)
        demucs_b_path = None
        if main_stem_file:
            separated = separate_stems(main_stem_file, stems_dir)
            if separated:
                demucs_b_path = create_demucs_b_section(separated, stems_dir, args.duration)

        if demucs_b_path:
            generated_stems.append({
                "role": "b_section",
                "model": "demucs-htdemucs",
                "file": demucs_b_path,
                "generation_time": 0,
                "cost": {"cost_usd": 0, "credits": 0},
            })
            log(f"  ✅ Demucs B-section: drums removed for breakdown")
            log(f"  Total stems: {len(generated_stems)} (including Demucs B-section)")
        else:
            # Fallback: API-generated B-section
            b_section = generate_b_section(args.prompt, args.duration, stems_dir)
            if b_section:
                generated_stems.append(b_section)
                log(f"  Total stems: {len(generated_stems)} (including B-section)")
            else:
                # Final fallback: LP-filtered main
                if main_stem_file:
                    fallback_path = os.path.join(stems_dir, "b_section_filtered_main.wav")
                    fallback_cmd = [
                        "ffmpeg", "-y", "-i", main_stem_file,
                        "-af", "lowpass=f=800,volume=0.6,areverse,afade=t=in:d=2,areverse,afade=t=in:d=2",
                        "-ar", "48000", "-ac", "2", fallback_path,
                    ]
                    try:
                        r = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=30)
                        if r.returncode == 0:
                            generated_stems.append({
                                "role": "b_section",
                                "model": "ffmpeg-filtered",
                                "file": fallback_path,
                                "generation_time": 0,
                                "cost": {"cost_usd": 0, "credits": 0},
                            })
                            log(f"  ✅ B-section fallback: LP-filtered main created")
                    except Exception:
                        log(f"  ⚠️ B-section fallback also failed")

    # ─── Phase 1c: Stem Analysis ─────────────────────────────────────────
    log("")
    log("PHASE 1c: STEM ANALYSIS")
    log("-" * 60)
    detected_key_actual = None
    detected_bpm_actual = None
    target_key, target_bpm = extract_key_bpm(args.prompt)
    for stem in generated_stems:
        analysis = analyze_stem(stem["file"])
        if analysis:
            stem["analysis"] = analysis
            status_parts = []
            if analysis.get("bpm"):
                status_parts.append(f"BPM={analysis['bpm']}")
            if analysis.get("key"):
                status_parts.append(f"Key={analysis['key']}")
            status_parts.append(f"centroid={analysis.get('spectral_centroid_hz', '?')}Hz")
            if stem["role"] == "main":
                detected_bpm_actual = analysis.get("bpm")
                detected_key_actual = analysis.get("key")
                if target_bpm and detected_bpm_actual:
                    bpm_diff = abs(detected_bpm_actual - float(target_bpm)) / float(target_bpm)
                    if bpm_diff > 0.05:
                        status_parts.append(f"⚠️ BPM off by {bpm_diff*100:.0f}%")
                    else:
                        status_parts.append("✅ BPM match")
            log(f"  {stem['role']:12s} — {', '.join(status_parts)}")
        else:
            log(f"  {stem['role']:12s} — analysis skipped")

    # ─── Phase 1d: Per-Stem Effects ──────────────────────────────────────
    log("")
    log("PHASE 1d: STEM EFFECTS (Pedalboard)")
    log("-" * 60)
    for stem in generated_stems:
        original_file = stem["file"]
        processed_file = process_stem_effects(original_file, stem["role"])
        if processed_file != original_file:
            stem["file"] = processed_file
            stem["effects_applied"] = True

    # ─── Pass 2: K3 Mix Engineer ─────────────────────────────────────────
    log("")
    log("PHASE 2: MIXING")
    log("-" * 60)
    report_progress("mixing")

    # Collect stem analysis for K3 mix inference
    stems_analysis_data = {}
    for stem in generated_stems:
        if stem.get("analysis"):
            stems_analysis_data[stem["role"]] = stem["analysis"]

    mix_overrides = None
    if stems_analysis_data and len(stems_analysis_data) >= 2:
        plan_genre = production_plan.get("genre", "") if production_plan else ""
        mix_overrides = infer_mix_params(stems_analysis_data, genre=plan_genre, profile=active_profile)

    if mix_overrides:
        # Apply K3's mix decisions to STEM_CONFIG overrides
        for stem in generated_stems:
            override = mix_overrides.get(stem["role"])
            if override and isinstance(override, dict):
                if "volume" in override:
                    stem["mix_volume_override"] = float(override["volume"])
                if "pan" in override:
                    stem["mix_pan_override"] = float(override["pan"])
                if "eq" in override and override["eq"] != "none":
                    stem["mix_eq_override"] = override["eq"]
    else:
        log("  Using default mix parameters")

    telegram_notify(f"🎛️ *Mixing {len(generated_stems)} stems together...*")
    mix_path = mix_stems(generated_stems, session_dir, target=args.target)

    # Step 3: Master
    log("")
    log("PHASE 3: MASTERING")
    log("-" * 60)
    report_progress("mastering")
    fmt_str = ', '.join(f.upper() for f in target_profile['outputs'])
    telegram_notify(f"🎚️ *Mastering for {args.target}...* ({fmt_str})")
    master_result = master_audio(mix_path, session_dir, skip_master=args.skip_master,
                                  target=args.target, track_title=args.prompt[:60])
    master_primary = master_result["primary"]
    master_files = master_result["files"]

    # Step 3b: Reference-based mastering (Matchering) — if reference tracks available
    ref_result = matchering_master(mix_path, session_dir, track_title=args.prompt[:60])
    if ref_result:
        log(f"  🎯 Reference master available (matched to: {ref_result.get('reference', 'unknown')})")
        # Use reference master as primary if available
        master_primary = ref_result["primary"]
        master_files = {k: v for k, v in ref_result["files"].items() if v}

    # Step 4: L-ISA stem export (if target supports it)
    lisa_dir = None
    if target_profile.get("export_stems"):
        log("")
        log("PHASE 4: L-ISA EXPORT")
        log("-" * 60)
        telegram_notify("🔊 *Exporting L-ISA stems...*")
        lisa_dir = export_stems_lisa(generated_stems, session_dir, args.target,
                                     track_title=args.prompt[:60])

    pipeline_time = time.time() - pipeline_start

    # Aggregate production costs
    total_cost_usd = 0
    total_credits = 0
    cost_breakdown = []
    for stem in generated_stems:
        sc = stem.get("cost", {})
        stem_usd = sc.get("cost_usd", 0)
        stem_credits = sc.get("credits", 0)
        total_cost_usd += stem_usd
        total_credits += stem_credits
        cost_breakdown.append({
            "stem": stem["role"],
            "model": stem["model"],
            "cost_usd": round(stem_usd, 4),
            "credits": stem_credits,
        })

    cost_report = {
        "total_usd": round(total_cost_usd, 4),
        "total_credits": total_credits,
        "breakdown": cost_breakdown,
    }

    # QC Analysis
    qc_report = analyze_master_qc(master_primary, target=args.target)

    # ─── Pass 4: K3 Quality Controller ───────────────────────────────────
    plan_genre = production_plan.get("genre", "") if production_plan else ""
    qc_verdict = quality_control(qc_report, genre=plan_genre, profile=active_profile)
    if qc_verdict:
        qc_report["k3_verdict"] = qc_verdict.get("verdict", "unknown")
        qc_report["k3_score"] = qc_verdict.get("score", 0)
        qc_report["k3_issues"] = qc_verdict.get("issues", [])
        qc_report["k3_suggestions"] = qc_verdict.get("suggestions", [])

    # Save production plan to session directory
    if production_plan:
        plan_path = os.path.join(session_dir, "production_plan.json")
        production_plan["qc"] = {
            "lufs": qc_report.get("integrated_lufs"),
            "true_peak_db": qc_report.get("true_peak_db"),
            "bpm_actual": next(
                (s.get("analysis", {}).get("bpm") for s in generated_stems if s.get("role") == "main"),
                None,
            ),
            "key_actual": next(
                (s.get("analysis", {}).get("key") for s in generated_stems if s.get("role") == "main"),
                None,
            ),
        }
        production_plan["cost"] = cost_report
        with open(plan_path, "w") as f:
            json.dump(production_plan, f, indent=2)
        log(f"  📋 Production plan: {plan_path}")

    # Save production metadata for DJ profile reference
    metadata_path = save_production_metadata(
        session_dir, args, target_profile, generated_stems,
        master_result, qc_report, cost_report, pipeline_time, lisa_dir
    )

    # Auto-link production to active DJ profile catalog (with plan data)
    if active_profile:
        try:
            # Link via profiles script
            link_cmd = [
                sys.executable, PROFILES_SCRIPT, "link",
                "--name", active_profile.get("name", ""),
                "--file", master_primary,
                "--title", production_plan.get("title", original_prompt[:60]) if production_plan else original_prompt[:60],
            ]
            subprocess.run(link_cmd, capture_output=True, timeout=10)
            log(f"  🔗 Linked to profile: {active_profile.get('name', '')}")

            # Enrich the catalog entry with plan data
            if production_plan:
                profiles_dir = os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "music", "profiles")
                slug = active_profile.get("slug", slugify(active_profile.get("name", "")))
                profile_path = os.path.join(profiles_dir, slug, "profile.json")
                if os.path.isfile(profile_path):
                    with open(profile_path) as f:
                        pdata = json.load(f)
                    # Find the catalog entry we just linked and add plan
                    if pdata.get("catalog"):
                        for entry in reversed(pdata["catalog"]):
                            if entry.get("file") == master_primary or (
                                entry.get("title") == production_plan.get("title")
                            ):
                                entry["plan"] = {
                                    "genre": production_plan.get("genre"),
                                    "bpm": production_plan.get("bpm"),
                                    "key": production_plan.get("key"),
                                    "energy": production_plan.get("energy"),
                                    "stems": {
                                        k: {"model": v.get("model"), "prompt": v.get("prompt")}
                                        for k, v in production_plan.get("stems", {}).items()
                                        if isinstance(v, dict)
                                    },
                                    "qc": production_plan.get("qc", {}),
                                }
                                break
                        with open(profile_path, "w") as f:
                            json.dump(pdata, f, indent=2)
                        log(f"  📊 Plan saved to profile catalog")
                    # Rebuild sonic DNA
                    update_sonic_dna(profile_path)
        except Exception as e:
            log(f"  ⚠️ Profile update: {e}")  # Non-critical

    log("")
    log("╔══════════════════════════════════════════════════════════╗")
    log("║                  ✅ PRODUCTION COMPLETE                  ║")
    log("╚══════════════════════════════════════════════════════════╝")
    log(f"  Target:       {args.target}")
    for fmt, path in master_files.items():
        log(f"  {fmt.upper():12s}: {path}")
    if lisa_dir:
        log(f"  L-ISA stems:  {lisa_dir}")
    log(f"  Total time:   {pipeline_time:.0f}s ({pipeline_time/60:.1f} min)")
    log(f"  Stems used:   {len(generated_stems)}")
    log(f"  Quality:      {args.quality}")
    log(f"  Total cost:   ${total_cost_usd:.4f} ({total_credits} credits)")
    if qc_report.get("integrated_lufs"):
        log(f"  LUFS:         {qc_report['integrated_lufs']:.1f} (target: {target_profile['lufs']})")
        log(f"  True Peak:    {qc_report.get('true_peak_db', 'N/A')} dB")
        log(f"  QC:           {'✅ PASS' if qc_report.get('overall_pass') else '⚠️ CHECK'}")
    log(f"  Metadata:     {metadata_path}")

    # Build cost report lines for Telegram
    cost_lines = []
    for item in cost_breakdown:
        model_short = item["model"].replace("elevenlabs-", "el-").replace("minimax-", "mm-")
        cost_lines.append(f"  {item['stem']}: ${item['cost_usd']:.4f} ({model_short})")
    cost_text = "\n".join(cost_lines)

    # QC lines for Telegram (L-Acoustics/Club targets)
    qc_lines = ""
    if args.target in ("l-acoustics", "club"):
        qc_lines = (
            f"\n🔊 *{args.target.upper()} QC Report*\n"
            f"  LUFS: {qc_report.get('integrated_lufs', 'N/A')}\n"
            f"  True Peak: {qc_report.get('true_peak_db', 'N/A')} dB\n"
            f"  LRA: {qc_report.get('lra', 'N/A')} LU\n"
            f"  Status: {'✅ PA-Ready' if qc_report.get('overall_pass') else '⚠️ Check levels'}\n"
        )

    fmt_list = ', '.join(f.upper() for f in master_files.keys())
    stems_line = f"\n📦 L-ISA stems exported ({len(generated_stems)} stems)" if lisa_dir else ""

    telegram_notify(
        f"✅ *Production complete!*\n"
        f"🎯 Target: {args.target}\n"
        f"⏱️ {pipeline_time/60:.1f} min | {len(generated_stems)} stems | {args.quality}\n"
        f"🎵 Formats: {fmt_list}"
        f"{stems_line}"
        f"{qc_lines}\n"
        f"💰 *Cost Report*\n"
        f"{cost_text}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"  *Total: ${total_cost_usd:.4f}* ({total_credits} credits)\n\n"
        f"📎 Sending your track now..."
    )

    # ─── Deliver audio files to Telegram ─────────────────────────────────
    if args.no_deliver:
        log(f"  📦 Batch mode — skipping individual Telegram delivery")
    else:
        # Determine profile name for performer tag
        profile_name = "Hermes Music"
        if active_profile:
            profile_name = active_profile.get("name", "Hermes Music")

        # Send MP3 first (smaller, plays inline)
        mp3_path = master_files.get("mp3")
        if mp3_path and os.path.isfile(mp3_path):
            telegram_send_audio(
                mp3_path,
                title=original_prompt[:60] if original_prompt else "Hermes Track",
                performer=profile_name,
                caption=f"🔊 {args.target.upper()} master | {qc_report.get('integrated_lufs', 'N/A')} LUFS | {args.quality}",
            )

        # Send FLAC as document — skip in preview mode (MP3 only)
        is_preview = args.preview if args.preview is not None else (args.duration and args.duration <= 30)
        flac_path = master_files.get("flac")
        if flac_path and os.path.isfile(flac_path) and not is_preview:
            try:
                payload = bytearray()
                boundary = "----HermesDoc"
                payload.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{_CHAT_ID}\r\n".encode())
                payload.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n📀 FLAC lossless master (48kHz/24-bit)\r\n".encode())
                flac_name = os.path.basename(flac_path)
                payload.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{flac_name}\"\r\nContent-Type: audio/flac\r\n\r\n".encode())
                with open(flac_path, "rb") as f:
                    payload.extend(f.read())
                payload.extend(f"\r\n--{boundary}--\r\n".encode())
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{_BOT_TOKEN}/sendDocument",
                    data=bytes(payload),
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=120)
                log(f"  ✅ Delivered FLAC to Telegram")
            except Exception as e:
                log(f"  ⚠️ FLAC delivery failed: {e}")
        elif is_preview:
            log(f"  ℹ️ Preview mode — FLAC skipped (MP3 only)")

    # Output result JSON
    result = {
        "success": True,
        "file": master_primary,
        "files": master_files,
        "stems": generated_stems,
        "quality": args.quality,
        "target": args.target,
        "format": target_profile["primary_format"],
        "format_details": f"{target_profile['sample_rate']//1000}kHz / 24-bit {target_profile['primary_format'].upper()}",
        "duration_requested": args.duration,
        "generation_time_seconds": round(pipeline_time, 1),
        "mastering": "skipped" if args.skip_master else "applied",
        "cost_report": cost_report,
        "qc_report": qc_report,
        "lisa_stems": lisa_dir,
        "metadata": metadata_path,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()

