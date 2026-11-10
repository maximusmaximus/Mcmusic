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
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# Path to the venice-music.py script
VENICE_SCRIPT = "/opt/data/skills/venice-music/venice-music/scripts/venice-music.py"
DEFAULT_OUTPUT_DIR = "/opt/data/music"

for _sd in [os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scripts")), "/opt/data/scripts"]:
    if os.path.isdir(_sd) and _sd not in sys.path:
        sys.path.insert(0, _sd)
try:
    import model_registry as _mr
except Exception:
    _mr = None
_MAIN_MUSIC_MODEL = _mr.get_primary_model("music.main_instrumental", "elevenlabs-music-v2-5") if _mr else "elevenlabs-music-v2-5"
_FOLEY_SFX_MODEL = _mr.get_primary_model("music.foley_sfx", "elevenlabs-sound-effects-v2") if _mr else "elevenlabs-sound-effects-v2"
_DIRECTOR_CHAIN = _mr.get_role_chain("llm.creative_director", ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"]) if _mr else ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"]

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
        "stems": ["main", "texture", "accent", "riser"],
        "description": "Standard 4-stem mix (main + texture + accent impact + tension riser)",
    },
    "premium": {
        "stems": ["main", "texture", "accent", "riser", "foley", "atmosphere"],
        "description": "Premium 6-stem mix (main + texture + accent + riser + narrative foley + atmosphere)",
    },
    "hyperspatial": {
        "stems": ["main", "texture", "accent", "riser", "foley", "atmosphere", "spatial"],
        "description": "Hyperspatial 7-stem dynamic 3D mix (main + texture + accent + riser + foley + atmosphere + 3D orbital spatial field + resampled chops)",
    },
}

# Stem configuration: model selection and prompt derivation
STEM_CONFIG = {
    "main": {
        "model_vocal": "ace-step-15",                # Cheapest vocal ($0.03), structured [Verse]/[Chorus]
        "model_vocal_freeform": "minimax-music-v25", # Structured/freeform vocal ($0.18)
        "model_vocal_premium": "elevenlabs-music-v2-5",  # Flagship v2.5 ($0.69/min)
        "model_instrumental": "elevenlabs-music-v2-5",   # Flagship v2.5 ($0.69/min, 4096-char prompt)
        "model_instrumental_budget": "lyria-3-pro",
        "prompt_template": "{prompt}",
        "mix_volume": 1.0,   # Full volume for main track
        "pan": 0.0,          # Center
    },
    "texture": {
        "model": "demucs-harmonic-synth",
        "fallback_model": "stable-audio-25",
        "prompt_template": "Smooth complementary background layer for: {prompt}. Warm chords, subtle harmonic support, musical pad that blends naturally",
        "duration_override": None,
        "mix_volume": 0.20,  # Subtle chord-locked harmonic warmth
        "pan": 0.0,          # Center (wide)
    },
    "accent": {
        "model": "voidride-sfx-vault",
        "fallback_model": "elevenlabs-sound-effects-v2",
        "prompt_template": "Smooth warm sub-bass swell impact with soft low-passed resonance and lush dark cavernous reverb tail, rounded attack, no harsh transients or sharp clicks, blends seamlessly, 5 seconds",
        "mix_volume": 0.25,  # Tucked smoothly into the mix at transitions
        "pan": 0.0,          # Center for warm low-mid weight
        "placement": "transitions",
        "max_duration": 8,
    },
    "riser": {
        "model": "voidride-sfx-vault",
        "fallback_model": "elevenlabs-sound-effects-v2",
        "prompt_template": "Silky dark analog synth filter sweep and warm reversed reverb swell, gradual smooth crescendo with soft high-frequency roll-off, no harsh white noise or abrupt cutoff, 5 seconds",
        "mix_volume": 0.23,
        "pan": 0.0,
        "placement": "transitions",
        "max_duration": 8,
    },
    "foley": {
        "model": "elevenlabs-sound-effects-v2",
        "prompt_template": "Subtle nocturnal cyber-noir ambient texture: soft distant rain-slicked highway wash, warm low-passed analog hum, and deep velvet reverb reflections, smooth and understated, no sharp clicks, 6 seconds",
        "mix_volume": 0.19,
        "pan": -0.15,
        "placement": "transitions",
        "max_duration": 8,
    },
    "atmosphere": {
        "model": "demucs-harmonic-synth",
        "fallback_model": "stable-audio-25",
        "prompt_template": "Ambient atmospheric music bed, slow evolving reverb texture, subtle harmonic undertone for: {prompt}. Soft, musical, cinematic depth",
        "mix_volume": 0.16,  # Subtle chord-locked depth with Haas/orbital width
        "pan": -0.25,
    },
    "spatial": {
        "model": "demucs-harmonic-synth",
        "fallback_model": "stable-audio-25",
        "prompt_template": "Hyperspatial 3D audio landscape, wide binaural stereo panning, holographic spatial delays, shimmering spectral echoes and dynamic sound design for: {prompt}. Immersive, wide-angle, cinematic depth",
        "mix_volume": 0.19,  # Holographic 3D chord-locked spatial layer
        "pan": 0.35,
    },
    "b_section": {
        "model": "demucs-htdemucs",
        "fallback_model": "stable-audio-25",
        "prompt_template": "Atmospheric minimal breakdown version: {prompt}. Sparse, filtered, spacious",
        "mix_volume": 0.36,  # Audible during breakdown pocket for contrast
        "pan": 0.15,
    },
    "ear_candy_bus": {
        "model": "hybrid-sfx-bus",
        "prompt_template": "Velvet-smooth beat-locked spatial transition bus: gentle S-curve risers, warm low-passed sub swells, recessed ambient foley washes, and lush reverb-drenched harmonic echoes",
        "mix_volume": 0.26,
        "pan": 0.0,
    },
}

# Target mastering profiles
TARGET_PROFILES = {
    "streaming": {
        "description": "Competitive Club/Streaming Hit Master (SoundCloud, Spotify, Apple Music)",
        "lufs": -10.0, "true_peak": -0.8, "lra": 9,
        "hp_freq": 25, "hp_order": 2,
        "mono_fold_below": 90,
        "comp_threshold": -16, "comp_ratio": 2.0, "comp_attack": 18, "comp_release": 180, "comp_makeup": 1.0,
        "eq": [
            {"f": 52, "w": 0.9, "g": 1.4},
            {"f": 270, "w": 1.6, "g": -1.3},
            {"f": 3100, "w": 1.4, "g": 1.5},
            {"f": 10500, "w": 0.9, "g": 1.3},
        ],
        "stereo_mid": 1.0, "stereo_side": 1.12,
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
    "spatial": "highpass=f=250",
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
        "model": "zai-org-glm-5-1",
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
        "model": "zai-org-glm-5-1",
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


def creative_director(user_prompt, quality_tier, duration, lyrics=None, profile=None, album_context=None, title=None):
    """Use Kimi K3 to produce a structured production plan with per-stem, per-model prompts."""
    api_key = os.environ.get("VENICE_API_KEY", "")
    if not api_key:
        log("  ⚠️ No VENICE_API_KEY — skipping creative director")
        return None

    available_models = {
        "elevenlabs-music-v2-5": {
            "type": "full-track", "cost": 2.08, "max_prompt": 4000,
            "strengths": "Flagship hit-grade instrumentals, razor-sharp 808 glides, expressive melodic hooks, responsive section scripting",
            "supports": "duration (max 600s), force_instrumental, time-stamped section scripting. Does NOT support lyrics.",
        },
        "elevenlabs-music": {
            "type": "full-track", "cost": 2.08, "max_prompt": 2000,
            "strengths": "Fallback full-track instrumentals, clear bass, long-form",
            "supports": "duration (max 600s), force_instrumental. Does NOT support lyrics.",
        },
        "ace-step-15": {
            "type": "vocal", "cost": 0.03, "max_prompt": 2000,
            "strengths": "Structured vocals with [Verse]/[Chorus] tags, cheapest vocal",
            "supports": "lyrics (required), duration (only 60/90/120/150/180/210s)",
        },
        "minimax-music-v2": {
            "type": "vocal", "cost": 0.04, "max_prompt": 300,
            "strengths": "Freeform vocals, catchy melodies, breathy/atmospheric vocals",
            "supports": "lyrics (required), prompt max 300 chars. NO duration control.",
        },
        "demucs-harmonic-synth": {
            "type": "harmonic-bed", "cost": 0.0, "max_prompt": 480,
            "strengths": "Zero-cost, 100% chord-locked harmonic texture/atmosphere/spatial beds derived from main stem",
            "supports": "Matches main stem key/BPM/chord progression automatically.",
        },
        "voidride-sfx-vault": {
            "type": "sfx-vault", "cost": 0.0, "max_prompt": 300,
            "strengths": "Zero-cost, warm studio-curated analog risers and rounded sub-drop accents",
            "supports": "Smooth transitions, zero harsh clicks.",
        },
        "elevenlabs-sound-effects-v2": {
            "type": "sfx", "cost": 0.02, "max_prompt": 490,
            "strengths": "Bespoke cover-matched cyber-noir ambient foley",
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
            if c.get("plan") and c["plan"].get("bpm") and int(c["plan"].get("bpm", 130) or 130) >= 120
        ][-5:]

        if recent_plans:
            memory_context += f"\n\nPRODUCTION MEMORY (last {len(recent_plans)} tracks):\n{json.dumps(recent_plans, indent=2)}\n"

        sonic_dna = profile.get("sonic_dna", {})
        if sonic_dna:
            memory_context += f"\nSONIC DNA for this DJ:\n{json.dumps(sonic_dna, indent=2)}\n"
            memory_context += (
                "\nMEMORY INSTRUCTIONS (DYNAMIC HIT ARCHITECTURE):\n"
                "- Preserve the unmistakable VØIDRIDE aesthetic on EVERY track while designing a MEMORABLE HIT SONG with real tension-and-release contrast!\n"
                "- Keep BPM within 122–154 BPM across distinct bounce pockets (124-130 halftime roller, 134-142 West Coast trap bounce, 146-152 drift-phonk club drive)\n"
                "- Always use dark minor keys (Dm, Fm, Cm, Gm, Ebm)\n"
                "- Foreground a NAMED, SINGABLE EARWORM HOOK MOTIF (e.g., portamento analog lead, hypnotic metallic bell/pluck riff, detuned brass call-and-response, or spectral chopped vocal motif) right in the first 12 seconds\n"
                "- Script dynamic section contrast: filtered hook-tease intro (no sub) -> pre-drop breath -> explosive California 808 Drop 1 -> rhythmic switch-up verse -> stripped-back tension bridge -> octave-lifted Climax Drop 2 -> sleek nocturnal outro\n"
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

    # Album variation context — forces differentiation between tracks while locking aesthetic
    album_instructions = ""
    if album_context:
        prev_tracks = album_context.get("previous_tracks", [])
        track_num = album_context.get("track_number", 1)
        total_tracks = album_context.get("total_tracks", 5)
        album_brief = album_context.get("brief", "")
        variation_rules = album_context.get("variation_rules", [])
        cover_visual = album_context.get("cover_visual", "")
        track_title = album_context.get("track_title", "") or title
        album_theme = album_context.get("album_theme", "")
        stem_prompts = album_context.get("stem_prompts", {})

        if cover_visual:
            album_instructions += f"\n\nALBUM COVER ART CONTEXT:\nThe visual scene depicted on the album cover is:\n\"{cover_visual}\"\n"
            album_instructions += (
                "AUDITORY COVER ART INTERPRETATION (MANDATORY):\n"
                "- Every stem of this song MUST be a direct sonic interpretation of the album cover art within the VØIDRIDE aesthetic.\n"
                "- Translate visual textures into VØIDRIDE electronic/industrial synth & drum textures:\n"
                "  * Concrete, steel, glass, tiles → cold metallic plate reverb throws, crisp snap snares, sharp transient kicks\n"
                "  * Fog, steam, sodium/neon glow → filtered white-noise breath risers, spectral witch house choir pads, voltage hum\n"
                "  * Shadowed structures / vehicles → menacing, predatory California 808 pitch glide curves, coiling Reese bass undertones\n"
                "  * NEVER use organic/woodland foley (NO 'snapping twigs', NO 'creaking wooden beams', NO thin whistles, NO deflating/weak bass)\n"
            )
        if track_title:
            album_instructions += f"\nTRACK TITLE REQUIREMENT:\n- The exact track title is \"{track_title}\".\n- Your JSON response MUST set \"title\": \"{track_title}\".\n- Express \"{track_title}\" through heavy West Coast 808 sub-bass glides, synth hook phrasing, and spatial reverb — NEVER by weakening the bass, dropping the drums, or making the track thin/ambient.\n"
        if stem_prompts:
            album_instructions += f"\nDIRECTOR STEM GUIDANCE:\n{json.dumps(stem_prompts, indent=2)}\n"

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
                "\nALBUM COHESION & VARIATION RULES (MANDATORY):\n"
                "- EVERY track on the album (including Track 1 Opener and Track 5 Closer) MUST carry the full VØIDRIDE aesthetic: relentless California 808 sub-bass dominance, slow predatory pitch portamento slides, coiling Reese bass growls, punchy acoustic-sampled transient kicks, crisp snap snares with wide metallic impulse reverb, rolling syncopated hi-hats, detuned analog brass stabs, and melancholic minor-pentatonic sine plucks.\n"
                "- Keep BPM strictly inside the 122–144 BPM nightride pocket (vary by ±4–8 BPM within 122–144 BPM; NEVER drop below 120 BPM).\n"
                "- Vary the musical key across Dm, Fm, Cm, and Ebm and vary the melodic hook phrasing / rhythmic bounce pattern, NOT the core genre or sub-bass dominance.\n"
                "- NEVER make Track 1 or Track 5 a slow-burn drumless/ambient piece, NEVER add thin whistles or vocal hum leads unless lyrics are explicitly requested, and NEVER let the sub-bass deflate or disappear.\n"
            )
        if album_brief:
            album_instructions += f"\nAlbum brief: {album_brief}\n"
        if variation_rules:
            album_instructions += f"\nSpecific variation for this track: {'; '.join(variation_rules)}\n"

    system_prompt = f"""You are an expert music producer and creative director for VØIDRIDE.
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
2. Main stem prompt ("elevenlabs-music-v2-5", 160-320 words): MUST start with genre, BPM (122-154), musical key (Dm/Fm/Cm/Gm/Ebm), a NAMED foreground earworm hook motif, and time-stamped dynamic hit section cues:
   - [0:00-0:14 Haunted Hook Tease]: Filtered earworm lead motif + nocturnal space, sub-bass held back for anticipation
   - [0:14-0:16 Pre-Drop Breath]: Filtered snare roll / brief tension pause
   - [0:16-0:58 Drop 1]: Explosive California 808 sub-bass with predatory pitch portamento slides, punchy transient kicks, crisp snap snares, and full foreground signature hook
   - [0:58-1:32 Verse Switch-Up]: Syncopated pocket shift / halftime or triplet counter-groove, Reese growl accents
   - [1:32-1:58 Tension Bridge]: Drums & deep sub stripped back for breath, wide spectral pads + rising filter tension
   - [1:58-2:38 Climax Drop 2]: Biggest moment of the record — octave-lifted lead hook + double-time hat energy + heaviest West Coast 808 glide variations
   - [2:38-End Nocturnal Outro]: Clean DJ-friendly resolve letting the hook echo out smoothly
3. Supporting harmonic beds (texture, atmosphere, spatial): Set model to "demucs-harmonic-synth" with concise harmonic character notes (<360 chars) in the same key and BPM.
4. Curated transition SFX (accent, riser): Set model to "voidride-sfx-vault" with smooth warm low-passed descriptions (<260 chars).
5. Bespoke foley stem: Set model to "elevenlabs-sound-effects-v2" (<450 chars) — subtle, warm low-passed cyber-noir ambient texture inspired by the album cover scene and track title (smooth, NO harsh clanks/clicks).
6. Model assignment rules:
   - main: "elevenlabs-music-v2-5" (for all instrumental VØIDRIDE tracks)
   - texture: "demucs-harmonic-synth"
   - atmosphere: "demucs-harmonic-synth"
   - spatial: "demucs-harmonic-synth"
   - accent: "voidride-sfx-vault"
   - riser: "voidride-sfx-vault"
   - foley: "elevenlabs-sound-effects-v2"
7. BPM (122-154) and key (Dm/Fm/Cm/Gm/Ebm) MUST appear explicitly in main stem prompt
8. If lyrics are provided, main model MUST support lyrics
9. For instrumental tracks, set "instrumental": true on main stem
10. TITLE must be a unique creative 1-3 word name — NOT the album name, NOT the user's request, NOT generic
11. NEVER use placeholder text like "..." or "etc" in ANY field.
12. NEVER use organic/woodland foley ("snapping twigs", "wooden beams") or thin novelty whistles.

OUTPUT VALID JSON (no markdown, no code fences):
{{
  "title": "UNIQUE CREATIVE NAME",
  "genre": "primary genre / subgenre",
  "bpm": 136,
  "key": "Dm",
  "energy": "description of dynamic arc and signature hook — NOT a placeholder",
  "stems": {{
    "main": {{
      "model": "elevenlabs-music-v2-5",
      "prompt": "DETAILED section-scripted hit prompt with genre, BPM, key, named earworm hook motif, and [Intro]->[Drop 1]->[Switch-Up]->[Bridge]->[Climax Drop 2]->[Outro] arc. 160-320 words.",
      "instrumental": true
    }},
    "foley": {{
      "model": "elevenlabs-sound-effects-v2",
      "prompt": "Warm low-passed cyber-noir scene texture matching the cover visual."
    }}
  }}
}}"""

    user_msg = user_prompt
    if lyrics:
        user_msg += f"\n\nLYRICS:\n{lyrics[:500]}"

    director_model = os.environ.get("DIRECTOR_MODEL", _DIRECTOR_CHAIN[0])

    # Retry loop — fast structured JSON planner with non-thinking fallbacks
    max_retries = 2
    for attempt in range(max_retries + 1):
        raw = ""
        try:
            v_params = {"strip_thinking_response": True}
            if "qwen" in director_model:
                v_params["disable_thinking"] = True
            req_body = {
                "model": director_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 3500,
                "temperature": 0.55,
                "venice_parameters": v_params,
            }
            if director_model == "kimi-k3":
                req_body["reasoning_effort"] = "low"
            payload = json.dumps(req_body).encode()

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
            msg_obj = result.get("choices", [{}])[0].get("message", {}) or {}
            raw = (msg_obj.get("content") or msg_obj.get("reasoning_content") or "").strip()

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

            # Enforce VØIDRIDE BPM pocket (120-156 BPM)
            try:
                plan_bpm = int(plan.get("bpm", 134))
            except Exception:
                plan_bpm = 134
            if plan_bpm < 120 or plan_bpm > 156:
                old_bpm = plan_bpm
                plan_bpm = 126 if old_bpm < 120 else 150
                plan["bpm"] = plan_bpm
                for s_info in plan.get("stems", {}).values():
                    if isinstance(s_info, dict) and s_info.get("prompt"):
                        s_info["prompt"] = re.sub(rf'\b{old_bpm}\s*BPM\b', f'{plan_bpm} BPM', s_info["prompt"], flags=re.IGNORECASE)

            plan_key = plan.get("key", "Dm") or "Dm"
            target_title = None
            if album_context and album_context.get("track_title"):
                target_title = album_context["track_title"].strip().upper()
            elif title:
                target_title = title.strip().upper()
            if target_title:
                plan["title"] = target_title

            # Ensure all requested stems_needed exist in plan["stems"] with zero-cost harmonic/vault defaults
            plan.setdefault("stems", {})
            scene_cue = ""
            if album_context and album_context.get("cover_visual"):
                scene_cue = album_context["cover_visual"][:120].strip()
            title_cue = plan.get("title", "NIGHTRIDE")

            default_stem_builders = {
                "texture": (
                    "demucs-harmonic-synth",
                    f"Warm chord-locked analog synth chorus pad derived from main stem in {plan_key} at {plan_bpm} BPM for {title_cue}."
                ),
                "atmosphere": (
                    "demucs-harmonic-synth",
                    f"Cavernous cyber-noir spectral reverb wash derived from main stem in {plan_key} at {plan_bpm} BPM for {title_cue}."
                ),
                "spatial": (
                    "demucs-harmonic-synth",
                    f"Hyperspatial 3D binaural side-shimmer reflection bed in {plan_key} at {plan_bpm} BPM for {title_cue}."
                ),
                "accent": (
                    "voidride-sfx-vault",
                    f"Warm rounded subterranean sub-bass impact swell with lush dark cavernous reverb tail for {title_cue}."
                ),
                "riser": (
                    "voidride-sfx-vault",
                    f"Silky dark analog synth filter sweep and warm reverse reverb swell into drop for {title_cue}."
                ),
                "foley": (
                    "elevenlabs-sound-effects-v2",
                    f"Subtle low-passed cyber-noir ambient texture for {title_cue}: soft distant nocturnal highway wash, warm analog hum, and deep velvet reverb reflections, smooth and non-intrusive. {scene_cue}"[:480]
                ),
            }
            for req_stem in stems_needed:
                if req_stem not in plan["stems"] or not isinstance(plan["stems"].get(req_stem), dict) or len(plan["stems"][req_stem].get("prompt", "")) < 20:
                    if req_stem in default_stem_builders:
                        def_model, def_prompt = default_stem_builders[req_stem]
                        plan["stems"][req_stem] = {"model": def_model, "prompt": def_prompt[:480]}

            # Enforce musical models & dynamic VØIDRIDE hit anchor
            model_limits = {
                "elevenlabs-music-v2-5": 3950,
                "elevenlabs-music": 1950,
                "stable-audio-25": 490,
                "elevenlabs-sound-effects-v2": 490,
                "minimax-music-v2": 290,
            }
            for stem_name, stem_info in plan.get("stems", {}).items():
                if isinstance(stem_info, dict):
                    if stem_name in ("texture", "atmosphere", "spatial"):
                        if stem_info.get("model") not in ("demucs-harmonic-synth", "stable-audio-25"):
                            stem_info["model"] = "demucs-harmonic-synth"
                    elif stem_name in ("accent", "riser"):
                        stem_info["model"] = "voidride-sfx-vault"
                    elif stem_name == "foley":
                        stem_info["model"] = _FOLEY_SFX_MODEL
                    elif stem_name == "main" and not has_lyrics:
                        stem_info["model"] = _MAIN_MUSIC_MODEL
                        stem_info["instrumental"] = True
                        mp = stem_info.get("prompt", "")
                        for bad_phrase in [
                            "snapping of twigs", "snapping twigs", "creaking of old wooden beams", "wooden beams",
                            "helium-thin", "deflating pitch", "like a leaking tank", "like helium bleeding",
                        ]:
                            mp = re.sub(re.escape(bad_phrase), "predatory West Coast nightride", mp, flags=re.IGNORECASE)
                        if "california bass" not in mp.lower() and "west coast" not in mp.lower():
                            mp = (
                                f"Dynamic hit-arranged hyperspatial West Coast nightride trap & witch house bass, {plan_bpm} BPM, {plan.get('key', 'Dm')}. "
                                f"Filtered haunted earworm synth hook intro building through a brief pre-drop breath into explosive California 808 sub-bass glides "
                                f"with predatory pitch portamento, punchy transient kicks, crisp snap snares, stripped tension bridge, and octave-lifted climax final drop. "
                                + mp
                            )
                        stem_info["prompt"] = mp

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
                wait = 4 * (attempt + 1)
                log(f"  ⚠️ Director attempt {attempt + 1} failed ({e}) — retrying in {wait}s...")
                if director_model == "deepseek-v4-flash":
                    director_model = "qwen3-235b-a22b-instruct-2507"
                elif director_model == "qwen3-235b-a22b-instruct-2507":
                    director_model = "llama-3.3-70b"
                log(f"  🔄 Switching to fallback model: {director_model}")
                time.sleep(wait)
                continue
            log(f"  ⚠️ Creative Director returned invalid JSON after {max_retries + 1} attempts: {e}")
            if raw:
                log(f"  Raw output: {raw[:300]}")
            return None
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < max_retries:
                wait = 6 * (attempt + 1)
                log(f"  ⚠️ Director network error attempt {attempt + 1} ({e}) — retrying in {wait}s...")
                if director_model == "deepseek-v4-flash":
                    director_model = "qwen3-235b-a22b-instruct-2507"
                elif director_model == "qwen3-235b-a22b-instruct-2507":
                    director_model = "llama-3.3-70b"
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
        v_params = {"strip_thinking_response": True}
        if "qwen" in model:
            v_params["disable_thinking"] = True
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.4,
            "venice_parameters": v_params,
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


def upscale_prompt(prompt, stem_name, genre="", bpm=0, key="", max_chars=490, cover_visual="", track_title=""):
    """Pass 1c: Enrich a stem prompt with vivid, specific audio details."""
    visual_context = ""
    if cover_visual or track_title:
        visual_context = (
            f"Visual scene from album cover: \"{cover_visual}\". Track Title: \"{track_title}\". "
            f"Weave subtle auditory cues reflecting this visual scene and title into the {stem_name} prompt. "
        )
    sfx_smooth_rule = ""
    if stem_name in ("accent", "riser", "foley", "spatial", "texture", "atmosphere"):
        sfx_smooth_rule = (
            "CRITICAL FOR VØIDRIDE: Any special effects or supporting textures MUST be described as "
            "velvet-smooth, warm, low-pass filtered on the top end, with gradual fade-ins and lush decaying reverb tails — "
            "NEVER jarring, harsh, piercing, clicky, or abrupt. "
        )
    system = (
        "You are an expert audio prompt engineer. Take the input prompt and make it MORE "
        "vivid, specific, and detailed for an AI audio generation model. Add: specific "
        "frequency descriptions (sub-bass, mid-range, high-end), spatial positioning "
        "(wide stereo, centered, panning), dynamic characteristics (attack, sustain, "
        "release), and textural details (smooth, warm, lush, deep). "
        f"{visual_context}{sfx_smooth_rule}"
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

    preferred_models = {
        stem: Counter(mlist).most_common(1)[0][0]
        for stem, mlist in models_used.items()
        if mlist
    }
    if profile.get("slug") == "vidride":
        preferred_models.update({
            "main": "elevenlabs-music-v2-5",
            "texture": "demucs-harmonic-synth",
            "atmosphere": "demucs-harmonic-synth",
            "spatial": "demucs-harmonic-synth",
            "accent": "voidride-sfx-vault",
            "riser": "voidride-sfx-vault",
            "foley": "elevenlabs-sound-effects-v2",
        })
    elif preferred_models.get("atmosphere") == "mmaudio-v2-text-to-audio":
        preferred_models["atmosphere"] = "stable-audio-25"

    valid_bpms = [b for b in bpms if 120 <= b <= 156]
    bpm_range = [min(valid_bpms), max(valid_bpms)] if valid_bpms else [122, 154]
    if bpm_range[0] == bpm_range[1]:
        bpm_range = [122, 154]

    existing_dna = profile.get("sonic_dna", {})
    profile["sonic_dna"] = {
        "primary_genres": [g for g, _ in Counter(genres).most_common(5)] if genres else [],
        "bpm_range": bpm_range,
        "preferred_keys": [k for k, _ in Counter(keys).most_common(3)] if keys else [],
        "preferred_models": preferred_models,
        "sound_signature": existing_dna.get(
            "sound_signature",
            "Dominant gliding California 808 sub-bass with silky, reverb-washed nocturnal synths and ultra-smooth, deeply blended spatial transitions — special effects are always filtered, gradual, and recessed behind the beat, never jarring or abrupt.",
        ),
        "anti_patterns": existing_dna.get(
            "anti_patterns",
            [
                "NO jarring or abrupt special effects",
                "NO harsh piercing transients or loud unblended SFX",
                "NO choppy glitch stutters that interrupt the nocturnal groove",
                "NO galloping beats",
                "NO static loops",
                "NO silence drops",
            ],
        ),
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
XFADE_SEC = 4.0  # seconds of smooth crossfade between sections (prevent jarring jumps while keeping punch)
MIN_VOLUME_FLOOR = 0.32  # allow genuine tension-and-release dynamic breath between intro/bridge and drops

ARRANGEMENT = {
    # Each section: (start%, end%, {stem: volume_multiplier})
    # Multipliers are applied to STEM_CONFIG base volumes to sculpt real hit macro-dynamics:
    # filtered intro -> rising build -> full Drop 1 -> stripped tension bridge -> Climax Drop 2 (+0.4dB) -> sleek outro.
    "intro":     (0.00, 0.14, {"main": 0.78, "texture": 1.00, "accent": 0.45, "riser": 0.72, "foley": 0.92, "atmosphere": 1.12, "b_section": 0.0, "spatial": 1.12, "ear_candy_bus": 0.85}),
    "build":     (0.14, 0.36, {"main": 0.94, "texture": 0.88, "accent": 0.75, "riser": 0.95, "foley": 0.80, "atmosphere": 0.88, "b_section": 0.0, "spatial": 0.95, "ear_candy_bus": 0.92}),
    "drop":      (0.36, 0.58, {"main": 1.00, "texture": 0.58, "accent": 0.90, "riser": 0.55, "foley": 0.55, "atmosphere": 0.58, "b_section": 0.0, "spatial": 0.72, "ear_candy_bus": 0.88}),
    "breakdown": (0.58, 0.73, {"main": 0.72, "texture": 1.05, "accent": 0.65, "riser": 0.92, "foley": 0.95, "atmosphere": 1.18, "b_section": 1.00, "spatial": 1.22, "ear_candy_bus": 0.96}),
    "drop2":     (0.73, 0.91, {"main": 1.05, "texture": 0.64, "accent": 0.95, "riser": 0.82, "foley": 0.60, "atmosphere": 0.64, "b_section": 0.0, "spatial": 0.85, "ear_candy_bus": 0.92}),
    "outro":     (0.91, 1.00, {"main": 0.76, "texture": 0.92, "accent": 0.55, "riser": 0.45, "foley": 0.88, "atmosphere": 1.05, "b_section": 0.0, "spatial": 1.08, "ear_candy_bus": 0.80}),
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
    xf = min(XFADE_SEC, duration * 0.04)  # cap crossfade at 4% of track

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
            expr = f"if(lt(t\\,{t_boundary:.1f})\\,{vol_before:.3f}\\,{expr})"
        else:
            slope = (vol_after - vol_before) / max(xf, 0.1)
            lerp_expr = f"{vol_before:.3f}+{slope:.4f}*(t-{ramp_start:.1f})"
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
CONTENT_SAFE_REPLACEMENTS = [
    ("violent force", "raw power"),
    ("tears through", "cuts through"),
    ("tear through", "cut through"),
    ("chest-compressing", "chest-rattling"),
    ("chest compressing", "chest rattling"),
    ("never releasing its grip", "maintaining intensity"),
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
        pattern = re.compile(re.escape(unsafe), re.IGNORECASE)
        result = pattern.sub(safe, result)
    return result


# ─── Audio Analysis & Phase-Locked Beat/Key Alignment (Pillar 3) ─────────
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

        # RMS energy & dB
        rms = float(librosa.feature.rms(y=y).mean())
        rms_db = round(20.0 * math.log10(max(rms, 1e-7)), 1)

        return {
            "bpm": bpm,
            "key": key,
            "spectral_centroid_hz": round(centroid),
            "rms_energy": round(rms, 4),
            "rms_db": rms_db,
            "duration": round(len(y) / sr, 1),
        }
    except ImportError:
        log("  ⚠️ librosa not installed — skipping analysis")
        return None
    except Exception as e:
        log(f"  ⚠️ Analysis failed: {e}")
        return None


def compute_deterministic_mix_overrides(stems_analysis):
    """Deterministic spectral & RMS gain-staging (replaces flaky LLM mix guesses at $0.00 cost).
    Ensures supporting beds never mask the main 808 sub or lead hook, while keeping stereo separation clean.
    """
    overrides = {}
    target_bed_rms_db = {
        "texture": -19.5,
        "atmosphere": -20.5,
        "spatial": -21.0,
        "b_section": -18.5,
        "ear_candy_bus": -19.0,
    }
    for role, analysis in (stems_analysis or {}).items():
        if role == "main" or not isinstance(analysis, dict):
            continue
        base_vol = STEM_CONFIG.get(role, {}).get("mix_volume", 0.18)
        rms_db = analysis.get("rms_db")
        centroid = analysis.get("spectral_centroid_hz", 1800)
        vol = base_vol
        if rms_db is not None and role in target_bed_rms_db:
            excess_db = float(rms_db) - target_bed_rms_db[role]
            if excess_db > 1.5:
                atten = 10.0 ** (-min(excess_db * 0.55, 8.0) / 20.0)
                vol = round(max(base_vol * atten, 0.07), 3)
            elif excess_db < -6.0:
                boost = 10.0 ** (min(abs(excess_db) * 0.35, 3.5) / 20.0)
                vol = round(min(base_vol * boost, base_vol * 1.35), 3)

        eq_rule = "none"
        if role in ("texture", "atmosphere") and centroid > 3400:
            eq_rule = "lowpass_3800hz"
        elif role == "spatial":
            eq_rule = "highpass_260hz"

        overrides[role] = {
            "volume": vol,
            "pan": STEM_CONFIG.get(role, {}).get("pan", 0.0),
            "eq": eq_rule,
        }
    return overrides


_PITCH_CLASS_MAP = {
    "C": 0, "B#": 0,
    "C#": 1, "DB": 1,
    "D": 2,
    "D#": 3, "EB": 3,
    "E": 4, "FB": 4,
    "F": 5, "E#": 5,
    "F#": 6, "GB": 6,
    "G": 7,
    "G#": 8, "AB": 8,
    "A": 9,
    "A#": 10, "BB": 10,
    "B": 11, "CB": 11,
}


def parse_musical_key(key_str):
    """Parse a key string like 'Dm', 'Eb minor', 'F#', 'Cm' into (pitch_class 0..11, is_minor bool)."""
    if not key_str or not isinstance(key_str, str):
        return None, True
    s = key_str.strip()
    m = re.match(r'^([A-Ga-g][#b]?)\s*(minor|major|min|maj|m)?$', s, re.IGNORECASE)
    if not m:
        return None, True
    root = m.group(1).upper()
    qual = (m.group(2) or "").lower()
    is_minor = qual.startswith("m") and qual not in ("maj", "major")
    pc = _PITCH_CLASS_MAP.get(root)
    return pc, is_minor


def compute_semitone_shift(src_key, dst_key):
    """Compute minimal harmonic semitone shift in [-3, +3] to align src_key to dst_key (or relative minor/5th)."""
    src_pc, src_min = parse_musical_key(src_key)
    dst_pc, dst_min = parse_musical_key(dst_key)
    if src_pc is None or dst_pc is None:
        return 0.0

    # Convert major key to its relative minor pitch class (-3 semitones) so harmonic comparison is unified
    src_rel_min = src_pc if src_min else (src_pc - 3) % 12
    dst_rel_min = dst_pc if dst_min else (dst_pc - 3) % 12

    # Candidate target pitch classes that are harmonically consonant with dst_rel_min:
    # 1. Exact tonic match (dst_rel_min)
    # 2. Dominant / Perfect 5th ((dst_rel_min + 7) % 12)
    # 3. Subdominant / Perfect 4th ((dst_rel_min + 5) % 12)
    candidates = [dst_rel_min, (dst_rel_min + 7) % 12, (dst_rel_min + 5) % 12]
    best_diff = 12
    for cand in candidates:
        diff = (cand - src_rel_min + 6) % 12 - 6
        if abs(diff) < abs(best_diff):
            best_diff = diff

    # Cap pitch shift to ±6 semitones so supporting stems NEVER remain out-of-key
    if abs(best_diff) > 6:
        return 0.0
    return float(best_diff)


def align_stem_to_main(stem_path, stem_role, stem_analysis, main_bpm, main_key, main_duration):
    """Pillar 3: Phase-lock supporting stem BPM and key to main stem using pedalboard.time_stretch,
    and extend to full main_duration using a bar-aligned equal-power cosine crossfade (eliminating hard 180s loop cuts).
    """
    if stem_role not in ("texture", "atmosphere", "spatial", "b_section"):
        return stem_path
    if not os.path.isfile(stem_path):
        return stem_path

    try:
        import numpy as np
        import pedalboard
        from pedalboard.io import AudioFile

        with AudioFile(stem_path) as f:
            sr = f.samplerate
            audio = f.read(f.frames)  # shape: (channels, frames)

        if audio.shape[1] < sr * 5:
            return stem_path

        # 1. Calculate BPM stretch factor
        stretch_factor = 1.0
        stem_bpm = (stem_analysis or {}).get("bpm")
        if main_bpm and stem_bpm and stem_bpm > 30:
            # Handle half-time / double-time detection differences
            adj_stem_bpm = float(stem_bpm)
            if adj_stem_bpm < main_bpm * 0.68:
                adj_stem_bpm *= 2.0
            elif adj_stem_bpm > main_bpm * 1.45:
                adj_stem_bpm *= 0.5

            raw_ratio = float(main_bpm) / adj_stem_bpm
            if 0.82 <= raw_ratio <= 1.22 and abs(raw_ratio - 1.0) > 0.012:
                stretch_factor = raw_ratio

        # 2. Calculate harmonic key semitone shift
        stem_key = (stem_analysis or {}).get("key")
        pitch_shift = compute_semitone_shift(stem_key, main_key) if (stem_key and main_key) else 0.0

        # Apply high-quality phase-vocoder time-stretch & pitch-shift if needed
        if abs(stretch_factor - 1.0) > 0.012 or abs(pitch_shift) >= 0.5:
            audio = pedalboard.time_stretch(
                audio.astype(np.float32),
                sr,
                stretch_factor=float(stretch_factor),
                pitch_shift_in_semitones=float(pitch_shift),
                high_quality=True,
                transient_mode="smooth",
                preserve_formants=True,
            )
            log(
                f"  🎯 Phase-locked {stem_role}: stretch={stretch_factor:.3f}x "
                f"({stem_bpm}→{main_bpm} BPM), pitch={pitch_shift:+.0f}st ({stem_key}→{main_key})"
            )

        # 3. Seamless Bar-Aligned Equal-Power Cosine Crossfade Loop to main_duration
        if main_duration and main_duration > 10:
            target_frames = int(round(main_duration * sr))
            cur_frames = audio.shape[1]

            if cur_frames < target_frames:
                bpm_val = float(main_bpm) if (main_bpm and main_bpm >= 80) else 132.0
                bar_sec = 4.0 * (60.0 / bpm_val)
                # Use a 2-bar (~7.2s) equal-power crossfade window
                xfade_sec = min(max(bar_sec * 2.0, 4.0), 10.0, (cur_frames / sr) * 0.25)
                xfade_frames = int(round(xfade_sec * sr))

                # Snap usable loop body to an exact 4-bar multiple so musical phrasing stays on-grid
                four_bar_frames = int(round(bar_sec * 4.0 * sr))
                if cur_frames > four_bar_frames * 2 + xfade_frames:
                    n_blocks = (cur_frames - xfade_frames) // four_bar_frames
                    usable_frames = n_blocks * four_bar_frames + xfade_frames
                    audio_body = audio[:, :usable_frames]
                else:
                    audio_body = audio

                t_theta = np.linspace(0.0, np.pi / 2.0, xfade_frames, dtype=np.float32)
                fade_out = np.cos(t_theta)[None, :]  # (1, xfade_frames)
                fade_in = np.sin(t_theta)[None, :]   # (1, xfade_frames)

                out_buf = audio_body.copy()
                while out_buf.shape[1] < target_frames:
                    # Crossfade the tail of out_buf with the head of audio_body
                    tail = out_buf[:, -xfade_frames:] * fade_out
                    head = audio_body[:, :xfade_frames] * fade_in
                    blended = tail + head
                    out_buf = np.concatenate(
                        [out_buf[:, :-xfade_frames], blended, audio_body[:, xfade_frames:]],
                        axis=1,
                    )

                audio = out_buf[:, :target_frames]
                log(f"  🔁 Seamlessly crossfade-looped {stem_role} to {main_duration:.1f}s ({xfade_sec:.1f}s equal-power xfade)")
            elif cur_frames > target_frames:
                audio = audio[:, :target_frames]

        base, _ = os.path.splitext(stem_path)
        aligned_path = f"{base}_aligned.wav"
        with AudioFile(aligned_path, "w", sr, audio.shape[0]) as f:
            f.write(audio)
        return aligned_path

    except Exception as e:
        log(f"  ⚠️ Stem alignment fallback for {stem_role}: {e}")
        return stem_path


def validate_voidride_main_stem(filepath, requested_duration):
    """Validate that a main stem meets dynamic VØIDRIDE hit standards.
    Checks:
      1. Duration completeness (>= 88% of requested_duration when requested >= 60s)
      2. Drop-window 808 sub-bass authority (25-70Hz active in >= 48% of Drop 1 / Drop 2 windows or >= 36% overall —
         allowing dynamic filtered intros and stripped bridges!)
      3. No multi-window dead-air silence dropout (>= 2 consecutive 5s windows < -40 dB RMS mid-track)
    Returns (passed: bool, issues: list[str], metrics: dict)
    """
    issues = []
    metrics = {}
    actual_dur = get_audio_duration(filepath)
    if actual_dur:
        metrics["actual_duration"] = round(actual_dur, 1)
        if requested_duration and requested_duration >= 60 and actual_dur < requested_duration * 0.88:
            issues.append(
                f"Early cutoff: {actual_dur:.1f}s generated vs {requested_duration}s requested"
            )

    try:
        import librosa
        import numpy as np
        from scipy.signal import butter, sosfilt

        y, sr = librosa.load(filepath, sr=22050, mono=True)
        total_sec = len(y) / sr
        metrics["actual_duration"] = round(total_sec, 1)

        # Sub-bass 25-70 Hz bandpass
        sos_sub = butter(4, [25, 70], btype="bandpass", fs=sr, output="sos")
        y_sub = sosfilt(sos_sub, y)

        win = 5 * sr
        n_wins = len(y) // win
        if n_wins >= 4:
            sub_rms_wins = [
                float(np.sqrt(np.mean(y_sub[i * win:(i + 1) * win] ** 2)))
                for i in range(n_wins)
            ]
            full_rms_wins = [
                float(np.sqrt(np.mean(y[i * win:(i + 1) * win] ** 2)))
                for i in range(n_wins)
            ]
            sub_active_pct = 100.0 * sum(1 for r in sub_rms_wins if r > 0.018) / len(sub_rms_wins)
            drop_indices = [
                idx for idx in range(n_wins)
                if (0.15 <= (idx * 5.0 / max(total_sec, 1.0)) <= 0.50)
                or (0.64 <= (idx * 5.0 / max(total_sec, 1.0)) <= 0.89)
            ]
            if drop_indices:
                drop_sub_pct = 100.0 * sum(1 for idx in drop_indices if sub_rms_wins[idx] > 0.018) / len(drop_indices)
            else:
                drop_sub_pct = sub_active_pct

            metrics["sub_active_pct"] = round(sub_active_pct, 1)
            metrics["drop_sub_active_pct"] = round(drop_sub_pct, 1)
            metrics["sub_mean_rms"] = round(float(np.mean(sub_rms_wins)), 4)

            if requested_duration and requested_duration >= 60 and drop_sub_pct < 48.0 and sub_active_pct < 36.0:
                issues.append(
                    f"Weak 808 sub-bass in drops: active in {drop_sub_pct:.1f}% of drop windows ({sub_active_pct:.1f}% overall)"
                )

            # Check genuine multi-window dead-air dropout (>= 2 consecutive 5s windows < -40 dB mid-track)
            consec_dead = 0
            dead_at_sec = None
            for idx, r in enumerate(full_rms_wins):
                t_sec = idx * 5
                if t_sec < 10 or t_sec > total_sec - 15:
                    continue
                db = 20.0 * np.log10(r + 1e-9)
                if db < -40.0:
                    consec_dead += 1
                    if consec_dead >= 2 and dead_at_sec is None:
                        dead_at_sec = t_sec - 5
                else:
                    consec_dead = 0
            if dead_at_sec is not None:
                issues.append(
                    f"Severe mid-track dead-air dropout (< -40 dB for >=10s starting at {dead_at_sec}s)"
                )
    except Exception as e:
        log(f"  ⚠️ VØIDRIDE stem validation warning: {e}")

    return (len(issues) == 0), issues, metrics


# ─── 4-Stem Separation, Stutter Slicer & Ear-Candy Bus (Pillars 1 & 4) ──
def separate_stems(input_path, output_dir):
    """Use Demucs htdemucs to separate main track into 4 stems (drums, bass, other, vocals) + synthesized no_drums."""
    demucs_out = os.path.join(output_dir, "demucs")
    os.makedirs(demucs_out, exist_ok=True)
    log(f"  Running 4-stem Demucs (htdemucs) separation (drums, bass, other, vocals)...")
    cmd = [
        sys.executable, "-m", "demucs",
        "-n", "htdemucs",
        "-j", "8",
        "-o", demucs_out,
        input_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=360)
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

        # Synthesize no_drums.wav from bass + other + vocals so breakdown generators have a drumless stem
        if "no_drums" not in separated and all(k in separated for k in ("bass", "other")):
            try:
                import numpy as np
                from pedalboard.io import AudioFile
                sum_audio = None
                sr_nd = 44100
                for k in ("bass", "other", "vocals"):
                    p = separated.get(k)
                    if p and os.path.isfile(p):
                        with AudioFile(p) as f:
                            sr_nd = f.samplerate
                            a = f.read(f.frames)
                        sum_audio = a if sum_audio is None else (sum_audio[:, :min(sum_audio.shape[1], a.shape[1])] + a[:, :min(sum_audio.shape[1], a.shape[1])])
                if sum_audio is not None:
                    no_drums_path = os.path.join(stems_path, "no_drums.wav")
                    with AudioFile(no_drums_path, "w", sr_nd, sum_audio.shape[0]) as f:
                        f.write(np.clip(sum_audio, -0.99, 0.99))
                    separated["no_drums"] = no_drums_path
            except Exception as nd_err:
                log(f"  ⚠️ Could not synthesize no_drums.wav: {nd_err}")

        log(f"  ✅ Demucs 4-stem separation complete: {list(separated.keys())}")
        return separated
    except subprocess.TimeoutExpired:
        log(f"  ⚠️ Demucs timed out (>360s)")
        return None
    except Exception as e:
        log(f"  ⚠️ Demucs error: {e}")
        return None


def synthesize_harmonic_stem_from_demucs(role, separated_stems, output_dir, duration=None):
    """Synthesize 100% chord-locked, zero-cost harmonic supporting stems ('texture', 'atmosphere', 'spatial')
    directly from Demucs 'other' + 'vocals' stems so supporting layers NEVER clash harmonically with the main hook!
    """
    if not separated_stems:
        return None
    src = separated_stems.get("other") or separated_stems.get("no_drums")
    if not src or not os.path.isfile(src):
        return None

    out_path = os.path.join(output_dir, f"{role}_demucs_harmonic.wav")
    if role == "texture":
        # Warm analog low-mid chord bed: filter transients above 3.4kHz, remove sub rumble <150Hz, add lush chorus warmth
        af_chain = (
            "highpass=f=150,lowpass=f=3400,"
            "chorus=0.65:0.85:42|56:0.35|0.28:0.25|0.32:1.6|2.1,"
            "aecho=0.8:0.82:240|360:0.26|0.20,"
            "stereotools=mlev=0.90:slev=1.22,volume=0.82,"
            "afade=t=in:d=2.5"
        )
    elif role == "atmosphere":
        # Cavernous nocturnal pad wash: time-blurred octave/reverb reflections with dark spectral air
        af_chain = (
            "highpass=f=190,lowpass=f=4200,"
            "aecho=0.75:0.88:410|630|890:0.38|0.30|0.22,"
            "haas=left_delay=8.5:right_delay=2.4:side_gain=1.28,"
            "stereotools=mlev=0.80:slev=1.35,volume=0.78,"
            "afade=t=in:d=3.0"
        )
    elif role == "spatial":
        # Hyperspatial 3D side-channel shimmer reflection bed: clean >280Hz, wide Haas + slow binaural drift
        af_chain = (
            "highpass=f=280,lowpass=f=9500,"
            "aecho=0.8:0.84:185|310:0.30|0.24,"
            "haas=left_delay=2.2:right_delay=11.6:side_gain=1.36,"
            "stereotools=mlev=0.68:slev=1.45,volume=0.76,"
            "afade=t=in:d=2.0"
        )
    else:
        return None

    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-af", af_chain,
        "-ar", "48000", "-ac", "2",
        out_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and os.path.isfile(out_path):
            log(f"  🎹 Synthesized chord-locked '{role}' stem from Demucs harmonic stem ($0.00, zero dissonance)")
            return out_path
    except Exception as e:
        log(f"  ⚠️ Demucs harmonic stem synthesis failed for {role}: {e}")
    return None


def get_or_create_vault_sfx(role, stems_dir, bpm=134, variant_seed=0):
    """Return a studio-curated, warm, click-free VØIDRIDE transition SFX ('riser' or 'accent')
    from /opt/data/music/sfx_vault/voidride/ (synthesizing the 3-variant master vault once if missing).
    Eliminates $0.04/track SFX API calls and guarantees silky smooth transitions!
    """
    if role not in ("riser", "accent"):
        return None
    vault_dir = os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "music", "sfx_vault", "voidride")
    os.makedirs(vault_dir, exist_ok=True)
    idx = (int(variant_seed or 0) % 3) + 1
    vault_file = os.path.join(vault_dir, f"{role}_0{idx}.wav")

    if not os.path.isfile(vault_file):
        try:
            import numpy as np
            from scipy.signal import butter, sosfilt
            from pedalboard.io import AudioFile

            sr = 48000
            dur = 5.5
            n = int(sr * dur)
            t = np.linspace(0.0, dur, n, dtype=np.float32)
            rng = np.random.RandomState(100 + idx * 17 + (1 if role == "riser" else 2))

            if role == "riser":
                # Silky analog detuned saw/triangle sweep + warm filtered pink breath crescendo
                f0 = 75.0 + idx * 12.0
                f1 = 520.0 + idx * 55.0
                phase = 2.0 * np.pi * (f0 * t + 0.5 * ((f1 - f0) / dur) * (t ** 2))
                tone_l = 0.38 * np.sin(phase) + 0.22 * np.sin(phase * 1.006 + 0.4) + 0.14 * np.sin(phase * 1.995)
                tone_r = 0.38 * np.sin(phase * 1.003 + 0.8) + 0.22 * np.sin(phase * 0.996) + 0.14 * np.sin(phase * 2.004 + 1.1)
                white_l = rng.normal(0.0, 0.22, n).astype(np.float32)
                white_r = rng.normal(0.0, 0.22, n).astype(np.float32)
                sos_lp = butter(3, [120, 2600], btype="bandpass", fs=sr, output="sos")
                breath_l = sosfilt(sos_lp, white_l)
                breath_r = sosfilt(sos_lp, white_r)
                # Smooth S-curve swell peaking 0.25s before end + gentle tail
                env = np.power(np.clip(t / (dur - 0.35), 0.0, 1.0), 2.1)
                tail_frames = int(0.35 * sr)
                env[-tail_frames:] = np.linspace(1.0, 0.0, tail_frames, dtype=np.float32) ** 1.6
                env[:int(0.25 * sr)] *= np.linspace(0.0, 1.0, int(0.25 * sr), dtype=np.float32)
                stereo = np.vstack([(tone_l + breath_l * 0.55) * env, (tone_r + breath_r * 0.55) * env]).astype(np.float32)
            else:
                # Warm rounded subterranean 808 sub-impact + velvet dark reverb wash (zero click!)
                f_start = 66.0 + idx * 3.0
                f_end = 33.0
                freq_curve = f_end + (f_start - f_end) * np.exp(-t * 2.6)
                phase = 2.0 * np.pi * np.cumsum(freq_curve) / sr
                sub = 0.62 * np.sin(phase) + 0.18 * np.tanh(1.8 * np.sin(phase * 2.0))
                shimmer_l = sosfilt(butter(2, [160, 1400], btype="bandpass", fs=sr, output="sos"), rng.normal(0.0, 0.16, n).astype(np.float32))
                shimmer_r = sosfilt(butter(2, [160, 1400], btype="bandpass", fs=sr, output="sos"), rng.normal(0.0, 0.16, n).astype(np.float32))
                atk_frames = int(0.035 * sr)  # 35ms rounded attack = zero click
                env = np.exp(-t * 0.85).astype(np.float32)
                env[:atk_frames] *= 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, atk_frames, dtype=np.float32)))
                env[-int(0.6 * sr):] *= np.linspace(1.0, 0.0, int(0.6 * sr), dtype=np.float32)
                shimmer_env = np.exp(-t * 0.62).astype(np.float32) * env
                stereo = np.vstack([sub * env + shimmer_l * shimmer_env, sub * env + shimmer_r * shimmer_env]).astype(np.float32)

            peak = float(np.max(np.abs(stereo))) or 1.0
            stereo = (stereo / peak * 0.78).astype(np.float32)
            with AudioFile(vault_file, "w", sr, 2) as f:
                f.write(stereo)
            log(f"  🏛️ Initialized curated VØIDRIDE SFX vault asset: {os.path.basename(vault_file)}")
        except Exception as e:
            log(f"  ⚠️ SFX vault synth warning ({role}): {e}")
            return None

    dest = os.path.join(stems_dir, f"{role}_vault_0{idx}.wav")
    try:
        shutil.copy2(vault_file, dest)
        return dest
    except Exception:
        return vault_file


def create_demucs_b_section(separated_stems, output_dir, duration=None):
    """Create a holographic B-section from Demucs-separated stems (drums removed, bass + synths spatialized)."""
    no_drums = separated_stems.get("no_drums")
    if not no_drums or not os.path.isfile(no_drums):
        return None

    b_path = os.path.join(output_dir, "b_section_demucs.wav")
    filters = [
        "lowpass=f=3600",
        "haas=left_delay=5.5:right_delay=12.0:side_gain=1.3",
        "aecho=0.8:0.85:375|500:0.32|0.25",
        "volume=0.72",
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
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if r.returncode == 0 and os.path.isfile(b_path):
            log(f"  ✅ Demucs B-section created (drums removed, Haas + echo spatialized)")
            return b_path
        return None
    except Exception:
        return None


def detect_transition_grid(main_path, bpm=132, duration=None):
    """Detect exact 4-bar musical grid transition timestamps on the main stem."""
    dur = duration or get_audio_duration(main_path) or 260.0
    bpm_val = float(bpm) if (bpm and 80 <= float(bpm) <= 180) else 132.0
    beat_sec = 60.0 / bpm_val
    bar_sec = 4.0 * beat_sec
    four_bar_sec = 4.0 * bar_sec

    # Snap nominal arrangement boundaries to the nearest 4-bar downbeat
    def snap_4bar(target_t):
        if four_bar_sec <= 0:
            return target_t
        idx = max(1, int(round(target_t / four_bar_sec)))
        snapped = idx * four_bar_sec
        return min(max(snapped, bar_sec * 2), dur - bar_sec * 2)

    # Refine with librosa beat frames if available
    first_downbeat = 0.0
    try:
        import librosa
        y, sr = librosa.load(main_path, sr=22050, mono=True, duration=min(dur, 90.0))
        _, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        if len(beat_times) >= 4:
            first_downbeat = float(beat_times[0]) % beat_sec
    except Exception:
        pass

    grid = {
        "bpm": bpm_val,
        "beat_sec": round(beat_sec, 4),
        "bar_sec": round(bar_sec, 4),
        "four_bar_sec": round(four_bar_sec, 4),
        "intro_to_build": round(snap_4bar(dur * 0.15) + first_downbeat, 3),
        "drop_1": round(snap_4bar(dur * 0.40) + first_downbeat, 3),
        "breakdown": round(snap_4bar(dur * 0.60) + first_downbeat, 3),
        "drop_2": round(snap_4bar(dur * 0.75) + first_downbeat, 3),
        "outro": round(snap_4bar(dur * 0.92) + first_downbeat, 3),
        "duration": round(dur, 3),
    }
    log(
        f"  📐 Beat Grid ({bpm_val:.0f} BPM, 1 bar={bar_sec:.2f}s): "
        f"Build={grid['intro_to_build']:.1f}s | Drop1={grid['drop_1']:.1f}s | "
        f"Break={grid['breakdown']:.1f}s | Drop2={grid['drop_2']:.1f}s | Outro={grid['outro']:.1f}s"
    )
    return grid


def sculpt_main_with_demucs(main_path, separated_stems, grid, output_dir):
    """Pillar 4: Use 4-stem Demucs separation to sculpt authentic HIT-RECORD macro-dynamics into the main track:
      1. Intro Hook-Tease High-Pass: Gently filter deep <95Hz sub out of the first ~10s ramping smoothly into Beat 1
         so Drop 1 hits with visceral physical contrast.
      2. Breakdown Tension Pocket: Strip drums down to 0.24x (-12 dB) and filter <85Hz sub during the middle of the
         breakdown while widening melodic 'other'/vocals (+12% gain) so Climax Drop 2 explodes back in.
      3. Pre-Drop 2-Beat Vacuum & Dub-Echo Swell + Climax Drop 2 Octave Lift: Smooth 2-beat breath dip right before
         Drop 1 and Drop 2, +1.0 dB Drop 1 slam, and +1.4 dB Climax Drop 2 slam with a subtle -11 dB +12st octave
         shimmer layer on the melodic hook during Drop 2!
    """
    if not separated_stems or not all(k in separated_stems for k in ("drums", "bass", "other")):
        return main_path

    try:
        import numpy as np
        import pedalboard
        from pedalboard.io import AudioFile
        from scipy.signal import butter, sosfilt

        with AudioFile(separated_stems["drums"]) as f:
            sr = f.samplerate
            drums = f.read(f.frames)
        with AudioFile(separated_stems["bass"]) as f:
            bass = f.read(f.frames)
        with AudioFile(separated_stems["other"]) as f:
            other = f.read(f.frames)

        vocals = None
        if separated_stems.get("vocals") and os.path.isfile(separated_stems["vocals"]):
            with AudioFile(separated_stems["vocals"]) as f:
                vocals = f.read(f.frames)

        n_frames = min(drums.shape[1], bass.shape[1], other.shape[1])
        drums = drums[:, :n_frames].copy()
        bass = bass[:, :n_frames].copy()
        other = other[:, :n_frames].copy()
        if vocals is not None:
            vocals = vocals[:, :n_frames].copy()
        else:
            vocals = np.zeros_like(other)

        beat_sec = grid["beat_sec"]
        bar_sec = grid["bar_sec"]

        # 1. Intro Sub-Hold Tease (first min(intro_to_build, 11s)): high-pass bass >95Hz & attenuate drums slightly,
        # ramping smoothly so the first drop lands with chest-rattling authority!
        intro_end = int(min(grid["intro_to_build"], 11.5) * sr)
        if intro_end > int(3.0 * sr) and intro_end < n_frames // 3:
            sos_hp_intro = butter(2, 95, btype="highpass", fs=sr, output="sos")
            bass_hp = sosfilt(sos_hp_intro, bass[:, :intro_end], axis=1)
            ramp = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, intro_end, dtype=np.float32)))
            bass[:, :intro_end] = bass_hp * (1.0 - ramp[None, :]) + bass[:, :intro_end] * ramp[None, :]
            drum_intro_env = 0.62 + 0.38 * ramp
            drums[:, :intro_end] *= drum_intro_env[None, :]
            log(f"  🎚️ Sculpted intro hook-tease sub ramp (0.0s–{intro_end/sr:.1f}s) for explosive first drop contrast")

        # 2. Breakdown Tension Pocket (breakdown + 0.75 bar -> drop_2 - 1.25 bars)
        bd_start = int((grid["breakdown"] + bar_sec * 0.75) * sr)
        bd_end = int((grid["drop_2"] - bar_sec * 1.25) * sr)
        if 0 < bd_start < bd_end < n_frames and (bd_end - bd_start) > int(bar_sec * 2 * sr):
            seg_n = bd_end - bd_start
            fade_len = min(int(bar_sec * 1.5 * sr), seg_n // 3)
            s_curve = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, fade_len, dtype=np.float32)))

            env_drums = np.ones(seg_n, dtype=np.float32) * 0.24  # -12 dB breakdown drum drop
            env_drums[:fade_len] = 1.0 - s_curve * (1.0 - 0.24)
            env_drums[-fade_len:] = 0.24 + s_curve * (1.0 - 0.24)
            drums[:, bd_start:bd_end] *= env_drums[None, :]

            # Pull deep sub back to 0.56x during bridge while keeping mid-Reese warmth so Drop 2 hits harder
            env_bass = np.ones(seg_n, dtype=np.float32) * 0.56
            env_bass[:fade_len] = 1.0 - s_curve * (1.0 - 0.56)
            env_bass[-fade_len:] = 0.56 + s_curve * (1.0 - 0.56)
            bass[:, bd_start:bd_end] *= env_bass[None, :]

            # Lift melodic hook/pads slightly (+1.0 dB) in the open space
            env_other = np.ones(seg_n, dtype=np.float32) * 1.12
            env_other[:fade_len] = 1.0 + s_curve * 0.12
            env_other[-fade_len:] = 1.12 - s_curve * 0.12
            other[:, bd_start:bd_end] *= env_other[None, :]
            log(f"  🥁 Sculpted dynamic tension bridge ({bd_start/sr:.1f}s–{bd_end/sr:.1f}s: drums -12dB, sub breath, melodic lift)")

        # 3. Pre-Drop 2-Beat Tension Vacuum & Band-Passed Dub-Echo Swell + Drop Impact Slam
        sos_bp = butter(2, [240, 4200], btype="bandpass", fs=sr, output="sos")
        for drop_key in ("drop_1", "drop_2"):
            drop_frame = int(grid[drop_key] * sr)
            bar_frames = int(bar_sec * sr)
            beat_frames = int(beat_sec * sr)

            swell_start = drop_frame - bar_frames
            if swell_start > bar_frames and drop_frame < n_frames - bar_frames:
                seg_len = drop_frame - swell_start
                echo_delay = max(1, int(beat_frames * 0.75))
                o_seg = other[:, swell_start:drop_frame].copy()
                o_bp = sosfilt(sos_bp, o_seg, axis=1)
                if seg_len > echo_delay:
                    o_bp[:, echo_delay:] += 0.48 * o_bp[:, :-echo_delay]
                t_norm = np.linspace(0.0, 1.0, seg_len, dtype=np.float32)
                swell_env = (np.sin(np.pi * t_norm) ** 1.15) * 0.30
                other[:, swell_start:drop_frame] = o_seg + o_bp * swell_env[None, :]

                # 1.5-beat smooth pre-drop breath (drums -> 0.22x, bass -> 0.28x) right before Beat 1 slam!
                breath_len = min(max(1, int(beat_frames * 1.5)), seg_len // 2)
                b_curve = 0.5 * (1.0 + np.cos(np.linspace(0.0, 2.0 * np.pi, breath_len, dtype=np.float32)))
                drum_breath = 0.22 + 0.78 * b_curve
                bass_breath = 0.28 + 0.72 * b_curve
                drums[:, drop_frame - breath_len:drop_frame] *= drum_breath[None, :]
                bass[:, drop_frame - breath_len:drop_frame] *= bass_breath[None, :]
                log(f"  🌊 Sculpted pre-drop breath & echo swell at {swell_start/sr:.1f}s → {drop_frame/sr:.1f}s ({drop_key})")

        # 4. Climax Drop 2 Escalation: +1.1 dB bass/drum punch + subtle +12st octave shimmer on melodic hook!
        d2_start = int(grid["drop_2"] * sr)
        d2_end = int(grid["outro"] * sr)
        if 0 < d2_start < d2_end <= n_frames and (d2_end - d2_start) > int(4.0 * sr):
            d2_len = d2_end - d2_start
            ramp_len = min(int(bar_sec * sr), d2_len // 4)
            d2_env = np.ones(d2_len, dtype=np.float32) * 1.12
            if ramp_len > 0:
                rc = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, ramp_len, dtype=np.float32)))
                d2_env[:ramp_len] = 1.0 + 0.12 * rc
                d2_env[-ramp_len:] = 1.12 - 0.12 * rc
            drums[:, d2_start:d2_end] *= d2_env[None, :]
            bass[:, d2_start:d2_end] *= d2_env[None, :]

            try:
                oct_board = pedalboard.Pedalboard([
                    pedalboard.HighpassFilter(cutoff_frequency_hz=320),
                    pedalboard.PitchShift(semitones=12),
                    pedalboard.LowpassFilter(cutoff_frequency_hz=7500),
                    pedalboard.Reverb(room_size=0.65, wet_level=0.45, dry_level=0.55),
                ])
                oct_hook = oct_board(other[:, d2_start:d2_end].copy(), sr)
                other[:, d2_start:d2_end] += oct_hook[:, :d2_len] * 0.24  # -12 dB octave climax lift
                log(f"  🔥 Added Climax Drop 2 +12st octave hook shimmer & low-end lift ({d2_start/sr:.1f}s–{d2_end/sr:.1f}s)")
            except Exception:
                pass

        sculpted = np.clip(drums + bass + other + vocals, -0.98, 0.98).astype(np.float32)
        sculpted_path = os.path.join(output_dir, "main_sculpted.wav")
        with AudioFile(sculpted_path, "w", sr, sculpted.shape[0]) as f:
            f.write(sculpted)
        return sculpted_path

    except Exception as e:
        log(f"  ⚠️ Demucs main sculpting skipped ({e}) — using original main stem")
        return main_path


def build_ear_candy_bus(stems, separated_stems, grid, main_path, output_dir):
    """Pillar 1: Build a full-length, beat-locked Ear-Candy & Narrative Sample Bus ('ear_candy_bus.wav')
    combining:
      - Multi-point 'riser' sweeps ending precisely on Intro->Build, Drop 1, Breakdown, and Drop 2 downbeats
      - Multi-point 'accent' sub-drop impacts firing on Drop 1, Drop 2, Breakdown, and Outro downbeats
      - Sliced 'foley' world-building micro-samples with 3D Doppler pan & filter movement across 6 bar pockets
      - Resampled 'sample_chop' slices (-12st dark formant + +12st crystalline shimmer) extracted from Demucs
        'other'/'vocals' stems and placed on breakdown/intro/outro turnaround bars.
    """
    try:
        import numpy as np
        from pedalboard import (
            Pedalboard, Reverb, Delay, Chorus, Phaser, PitchShift,
            HighpassFilter, LowpassFilter, Compressor, Gain
        )
        from pedalboard.io import AudioFile

        sr = 48000
        dur = grid["duration"]
        total_frames = int(round(dur * sr))
        bus = np.zeros((2, total_frames), dtype=np.float32)

        bar_sec = grid["bar_sec"]
        beat_sec = grid["beat_sec"]

        def _load_stereo_48k(path):
            if not path or not os.path.isfile(path):
                return None
            tmp_wav = path + "_48k_tmp.wav"
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", path, "-ar", str(sr), "-ac", "2", tmp_wav],
                capture_output=True, timeout=30
            )
            target = tmp_wav if (r.returncode == 0 and os.path.isfile(tmp_wav)) else path
            try:
                with AudioFile(target) as f:
                    a = f.read(f.frames)
                if a.shape[0] == 1:
                    a = np.repeat(a, 2, axis=0)
                elif a.shape[0] > 2:
                    a = a[:2, :]
                return a.astype(np.float32)
            finally:
                if os.path.isfile(tmp_wav):
                    try:
                        os.remove(tmp_wav)
                    except OSError:
                        pass

        def _smooth_sfx_clip(clip, lpf_hz=5800, reverb_wet=0.52):
            """Tame spiky transients, roll off harsh highs, and embed SFX in lush dark reverb so it never sounds jarring."""
            if clip is None or clip.shape[1] == 0:
                return None
            c = clip.copy().astype(np.float32)
            # Soft RMS ceiling normalization so loud 0 dBFS SFX clips never poke out above the beat
            rms = float(np.sqrt(np.mean(c ** 2)) + 1e-8)
            target_rms = 0.085
            if rms > target_rms:
                c *= (target_rms / rms)
            # Soft tanh transient rounding before filtering
            c = np.tanh(c * 1.4) / 1.4
            sfx_board = Pedalboard([
                HighpassFilter(cutoff_frequency_hz=95),
                LowpassFilter(cutoff_frequency_hz=float(lpf_hz)),
                Compressor(threshold_db=-22, ratio=4.0, attack_ms=1.5, release_ms=180),
                Chorus(rate_hz=0.24, depth=0.22, mix=0.25),
                Reverb(room_size=0.88, damping=0.55, wet_level=float(reverb_wet), dry_level=1.0 - float(reverb_wet) * 0.65, width=1.0),
            ])
            # Pad with 1.5s tail so reverb decays smoothly without cutoff
            pad = np.zeros((2, int(1.5 * sr)), dtype=np.float32)
            padded = np.concatenate([c, pad], axis=1)
            return sfx_board(padded, sr)

        def _place_clip(clip, start_sec, gain=1.0, pan=0.0, fade_in_s=0.8, fade_out_s=1.4):
            """Place clip using equal-power raised-cosine S-curve fades so SFX enter and exit with zero jarring edges."""
            if clip is None or clip.shape[1] == 0:
                return
            c = clip.copy() * float(gain)
            n = c.shape[1]
            fi = min(int(fade_in_s * sr), int(n * 0.45))
            fo = min(int(fade_out_s * sr), int(n * 0.48))
            if fi > 1:
                s_in = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, fi, dtype=np.float32)))
                c[:, :fi] *= s_in[None, :]
            if fo > 1:
                s_out = 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, fo, dtype=np.float32)))
                c[:, -fo:] *= s_out[None, :]
            # Constant-power stereo pan (gentle range)
            angle = (float(np.clip(pan, -0.65, 0.65)) + 1.0) * (np.pi / 4.0)
            c[0, :] *= np.cos(angle) * 1.414
            c[1, :] *= np.sin(angle) * 1.414

            idx0 = int(round(start_sec * sr))
            if idx0 < 0:
                c = c[:, -idx0:]
                idx0 = 0
            if idx0 >= total_frames or c.shape[1] == 0:
                return
            idx1 = min(total_frames, idx0 + c.shape[1])
            bus[:, idx0:idx1] += c[:, :idx1 - idx0]

        def _apply_doppler_pan(clip, start_pan=-0.40, end_pan=0.40):
            """Smooth, click-free cosine pan movement across the stereo field."""
            if clip is None or clip.shape[1] == 0:
                return clip
            c = clip.copy()
            n = c.shape[1]
            s_curve = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, n, dtype=np.float32)))
            pans = start_pan + (end_pan - start_pan) * s_curve
            angles = (pans + 1.0) * (np.pi / 4.0)
            c[0, :] *= np.cos(angles) * 1.25
            c[1, :] *= np.sin(angles) * 1.25
            return c

        # 1. Place RISER stem before transitions (smoothed with long S-curve fade-in & reverb tail)
        riser_stem = next((s for s in stems if s["role"] == "riser"), None)
        accent_stem = next((s for s in stems if s["role"] == "accent"), None)
        foley_stem = next((s for s in stems if s["role"] == "foley"), None)

        raw_riser = _load_stereo_48k(riser_stem["file"]) if riser_stem else None
        raw_accent = _load_stereo_48k(accent_stem["file"]) if accent_stem else None
        raw_foley = _load_stereo_48k(foley_stem["file"]) if foley_stem else None

        if raw_riser is None and raw_accent is not None:
            raw_riser = raw_accent[:, ::-1].copy()

        riser_audio = _smooth_sfx_clip(raw_riser, lpf_hz=5600, reverb_wet=0.55) if raw_riser is not None else None
        accent_audio = _smooth_sfx_clip(raw_accent, lpf_hz=5200, reverb_wet=0.58) if raw_accent is not None else None
        foley_audio = _smooth_sfx_clip(raw_foley, lpf_hz=4800, reverb_wet=0.60) if raw_foley is not None else None

        events_placed = 0
        if riser_audio is not None:
            # Align so the peak of the riser lands on the transition and the 1.5s reverb tail washes into the new section
            r_body_dur = max(1.0, (riser_audio.shape[1] / sr) - 1.5)
            _place_clip(riser_audio, grid["intro_to_build"] - r_body_dur, gain=0.38, pan=-0.12, fade_in_s=1.8, fade_out_s=1.5)
            _place_clip(riser_audio, grid["drop_1"] - r_body_dur, gain=0.48, pan=0.0, fade_in_s=1.8, fade_out_s=1.5)
            _place_clip(riser_audio[::-1, :], grid["drop_2"] - r_body_dur, gain=0.50, pan=0.0, fade_in_s=1.8, fade_out_s=1.5)
            _place_clip(riser_audio, grid["breakdown"] - r_body_dur, gain=0.35, pan=0.15, fade_in_s=2.0, fade_out_s=1.6)
            events_placed += 4

        # 2. Place ACCENT warm sub-swell impacts on downbeats with soft S-curve attack (no jarring crack)
        if accent_audio is not None:
            tail_board = Pedalboard([
                HighpassFilter(cutoff_frequency_hz=95),
                LowpassFilter(cutoff_frequency_hz=4500),
                Delay(delay_seconds=min(beat_sec * 0.75, 0.9), feedback=0.35, mix=0.40),
                Reverb(room_size=0.92, damping=0.55, wet_level=0.65, dry_level=0.35, width=1.0),
            ])
            accent_washed = tail_board(accent_audio, sr)
            _place_clip(accent_audio, grid["drop_1"] - 0.08, gain=0.46, pan=0.0, fade_in_s=0.22, fade_out_s=1.6)
            _place_clip(accent_audio[::-1, :], grid["drop_2"] - 0.08, gain=0.48, pan=0.0, fade_in_s=0.22, fade_out_s=1.6)
            _place_clip(accent_washed, grid["breakdown"] - 0.10, gain=0.36, pan=-0.18, fade_in_s=0.35, fade_out_s=2.0)
            _place_clip(accent_washed, grid["outro"] - 0.10, gain=0.32, pan=0.18, fade_in_s=0.35, fade_out_s=2.0)
            events_placed += 4

        # 3. Slice & Gently Pan Narrative FOLEY Washes across 6 musical bar pockets
        if foley_audio is not None and foley_audio.shape[1] > sr:
            f_len = foley_audio.shape[1]
            half_f = f_len // 2
            slice_a = foley_audio[:, :half_f] if half_f > sr else foley_audio
            slice_b = foley_audio[:, half_f:] if (f_len - half_f) > sr else foley_audio

            foley_spots = [
                (bar_sec * 1.0, slice_a, -0.38, 0.32, 0.34),
                (grid["intro_to_build"] + bar_sec * 2.0, slice_b, 0.35, -0.35, 0.30),
                (grid["drop_1"] + bar_sec * 4.0, slice_a, -0.32, 0.38, 0.26),
                (grid["breakdown"] + bar_sec * 1.0, slice_b, 0.40, -0.38, 0.38),
                (grid["breakdown"] + bar_sec * 3.0, slice_a, -0.36, 0.36, 0.35),
                (grid["outro"] + bar_sec * 1.0, slice_b, 0.32, -0.32, 0.32),
            ]
            for t_spot, f_slice, p_start, p_end, f_gain in foley_spots:
                if 0 <= t_spot < dur - 2.0:
                    doppler_clip = _apply_doppler_pan(f_slice, p_start, p_end)
                    _place_clip(doppler_clip, t_spot, gain=f_gain, pan=0.0, fade_in_s=1.1, fade_out_s=1.5)
                    events_placed += 1

        # 4. Synthesize Velvet-Smooth Witch-House / Nightride Resampled Melodic Chops
        chop_source_path = None
        if separated_stems:
            chop_source_path = separated_stems.get("other") or separated_stems.get("no_drums")
        if not chop_source_path:
            chop_source_path = main_path

        src_audio = _load_stereo_48k(chop_source_path)
        if src_audio is not None and src_audio.shape[1] > int(bar_sec * 8 * sr):
            hook_start = int(min(dur * 0.45, dur - bar_sec * 4) * sr)
            chop_len = int(bar_sec * sr)
            raw_chop = src_audio[:, hook_start:hook_start + chop_len].copy()
            # Pre-window raw_chop with a 0.5s raised-cosine envelope on both ends so PitchShift/Delay never click
            win_edge = min(int(0.5 * sr), chop_len // 3)
            if win_edge > 4:
                w_in = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, win_edge, dtype=np.float32)))
                w_out = 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, win_edge, dtype=np.float32)))
                raw_chop[:, :win_edge] *= w_in[None, :]
                raw_chop[:, -win_edge:] *= w_out[None, :]

            # Chop A: Deep -12 semitone dark witch-house formant ghost with lush reverb wash
            low_board = Pedalboard([
                HighpassFilter(cutoff_frequency_hz=180),
                PitchShift(semitones=-12),
                LowpassFilter(cutoff_frequency_hz=2600),
                Chorus(rate_hz=0.35, depth=0.32, mix=0.45),
                Delay(delay_seconds=min(beat_sec * 0.75, 0.8), feedback=0.38, mix=0.45),
                Reverb(room_size=0.92, damping=0.50, wet_level=0.65, dry_level=0.35, width=1.0),
            ])
            padded_chop = np.concatenate([raw_chop, np.zeros((2, chop_len * 2), dtype=np.float32)], axis=1)
            chop_low = low_board(padded_chop, sr)

            # Chop B: +12 semitone warm spectral shimmer echo (low-passed at 6200Hz so it's silky, never piercing)
            high_board = Pedalboard([
                HighpassFilter(cutoff_frequency_hz=420),
                PitchShift(semitones=12),
                LowpassFilter(cutoff_frequency_hz=6200),
                Phaser(rate_hz=0.18, depth=0.38, mix=0.40),
                Delay(delay_seconds=min(beat_sec * 0.5, 0.6), feedback=0.38, mix=0.48),
                Reverb(room_size=0.94, damping=0.55, wet_level=0.72, dry_level=0.28, width=1.0),
                Gain(gain_db=-6.5),
            ])
            chop_high = high_board(padded_chop, sr)

            chop_placements = [
                (bar_sec * 2.0, chop_low, 0.32, -0.28),
                (grid["intro_to_build"] - bar_sec * 2.0, chop_high, 0.28, 0.30),
                (grid["breakdown"] + bar_sec * 0.5, chop_low, 0.38, -0.30),
                (grid["breakdown"] + bar_sec * 2.0, chop_high, 0.34, 0.32),
                (grid["breakdown"] + bar_sec * 3.5, chop_low, 0.36, -0.25),
                (grid["outro"] + bar_sec * 0.5, chop_high, 0.30, 0.28),
            ]
            for c_time, c_audio, c_gain, c_pan in chop_placements:
                if 0 <= c_time < dur - bar_sec:
                    _place_clip(c_audio, c_time, gain=c_gain, pan=c_pan, fade_in_s=1.0, fade_out_s=1.8)
                    events_placed += 1

        # Final bus glue: smooth low-pass roll-off (6500Hz) + gentle glue compression + cohesive dark reverb
        bus_glue = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=90),
            LowpassFilter(cutoff_frequency_hz=6500),
            Compressor(threshold_db=-20, ratio=3.0, attack_ms=5.0, release_ms=200),
            Reverb(room_size=0.86, damping=0.52, wet_level=0.28, dry_level=0.72, width=1.0),
        ])
        bus = bus_glue(bus, sr)
        bus = np.clip(bus, -0.95, 0.95).astype(np.float32)
        bus_path = os.path.join(output_dir, "ear_candy_bus.wav")
        with AudioFile(bus_path, "w", sr, 2) as f:
            f.write(bus)

        log(f"  🍬 Built beat-locked Ear-Candy & Sample Chop Bus ({events_placed} spatial/SFX/chop events across {dur:.1f}s)")
        return bus_path

    except Exception as e:
        log(f"  ⚠️ Ear-Candy bus builder error: {e}")
        return None


# ─── Per-Stem 3D Effects Processing (Pillar 2 — Pedalboard) ─────────────
def process_stem_effects(stem_path, stem_role, output_path=None):
    """Apply holographic 3D spatial, shimmer, modulation, and dynamic effects using Spotify's Pedalboard."""
    try:
        from pedalboard import (
            Pedalboard, Reverb, Compressor, LowpassFilter, HighpassFilter,
            Gain, Chorus, Phaser, Delay, PitchShift, PeakFilter, HighShelfFilter, Mix, Chain
        )
        from pedalboard.io import AudioFile
    except ImportError:
        log("  ⚠️ pedalboard not installed — skipping stem effects")
        return stem_path

    STEM_EFFECTS = {
        "main": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=28),
            Compressor(threshold_db=-18, ratio=2.8, attack_ms=12, release_ms=140),
            Gain(gain_db=1.8),
        ]),
        "texture": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=140),
            PeakFilter(cutoff_frequency_hz=310, gain_db=-3.0, q=1.4),  # Unmask low-mid mud for 808 clarity
            Chorus(rate_hz=0.42, depth=0.24, centre_delay_ms=7.0, feedback=0.1, mix=0.28),
            Reverb(room_size=0.58, damping=0.4, wet_level=0.28, dry_level=0.72, width=0.95),
            LowpassFilter(cutoff_frequency_hz=12500),
        ]),
        "atmosphere": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=70),
            PeakFilter(cutoff_frequency_hz=260, gain_db=-2.5, q=1.2),
            Chorus(rate_hz=0.22, depth=0.30, centre_delay_ms=8.5, feedback=0.15, mix=0.32),
            Delay(delay_seconds=0.45, feedback=0.28, mix=0.22),
            Reverb(room_size=0.88, damping=0.32, wet_level=0.44, dry_level=0.56, width=1.0),
            LowpassFilter(cutoff_frequency_hz=11500),
        ]),
        "accent": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=95),
            LowpassFilter(cutoff_frequency_hz=5800),
            Compressor(threshold_db=-18, ratio=4.0, attack_ms=2.0, release_ms=160),
            Reverb(room_size=0.82, damping=0.50, wet_level=0.48, dry_level=0.58, width=1.0),
            Gain(gain_db=-1.5),
        ]),
        "riser": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=110),
            LowpassFilter(cutoff_frequency_hz=6000),
            Phaser(rate_hz=0.25, depth=0.35, mix=0.30),
            Reverb(room_size=0.86, damping=0.52, wet_level=0.50, dry_level=0.55, width=1.0),
            Gain(gain_db=-1.5),
        ]),
        "foley": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=160),
            LowpassFilter(cutoff_frequency_hz=5200),
            Compressor(threshold_db=-20, ratio=3.5, attack_ms=2.5, release_ms=160),
            Reverb(room_size=0.84, damping=0.55, wet_level=0.52, dry_level=0.54, width=1.0),
            Gain(gain_db=-2.0),
        ]),
        "b_section": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=110),
            Chorus(rate_hz=0.28, depth=0.32, mix=0.30),
            Delay(delay_seconds=0.375, feedback=0.32, mix=0.25),
            Reverb(room_size=0.86, wet_level=0.38, dry_level=0.62, width=1.0),
            LowpassFilter(cutoff_frequency_hz=7500),
        ]),
        "spatial": Pedalboard([
            HighpassFilter(cutoff_frequency_hz=175),
            PeakFilter(cutoff_frequency_hz=340, gain_db=-3.5, q=1.3),  # Carve center pocket for main synths & 808
            Mix([
                # Core modulated 3D path
                Chain([
                    Chorus(rate_hz=0.35, depth=0.38, centre_delay_ms=9.0, feedback=0.2, mix=0.42),
                    Phaser(rate_hz=0.14, depth=0.42, feedback=0.15, mix=0.32),
                    Delay(delay_seconds=0.375, feedback=0.35, mix=0.30),
                    Reverb(room_size=0.93, damping=0.25, wet_level=0.50, dry_level=0.50, width=1.0),
                ]),
                # Holographic +12st Shimmer Octave Layer
                Chain([
                    HighpassFilter(cutoff_frequency_hz=380),
                    PitchShift(semitones=12),
                    LowpassFilter(cutoff_frequency_hz=10500),
                    Delay(delay_seconds=0.50, feedback=0.40, mix=0.55),
                    Reverb(room_size=0.96, damping=0.20, wet_level=0.75, dry_level=0.25, width=1.0),
                    Gain(gain_db=-10.5),
                ]),
                # Dark -12st Sub-Octave Spectral Undertow
                Chain([
                    HighpassFilter(cutoff_frequency_hz=150),
                    PitchShift(semitones=-12),
                    LowpassFilter(cutoff_frequency_hz=1900),
                    Reverb(room_size=0.88, wet_level=0.55, dry_level=0.45, width=1.0),
                    Gain(gain_db=-11.5),
                ]),
            ]),
            HighShelfFilter(cutoff_frequency_hz=6500, gain_db=2.0),
            LowpassFilter(cutoff_frequency_hz=15000),
            Gain(gain_db=1.2),
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

        log(f"  🎸 3D Pedalboard FX applied to {stem_role}: {len(board)} stages")
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

    # Never use 5-second mmaudio-v2 foley clips for full-track continuous beds
    if stem_name in ("texture", "atmosphere", "spatial") and model == "mmaudio-v2-text-to-audio":
        model = "stable-audio-25"

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
        if key_context and stem_name in ("texture", "atmosphere", "spatial"):
            stem_prompt = stem_prompt.rstrip() + key_context + "."

    # Truncate prompt to model limits (elevenlabs-music-v2-5 supports up to 4096 chars!)
    MAX_PROMPT_LEN = {
        "elevenlabs-music-v2-5": 3950,
        "elevenlabs-music": 1980,
        "lyria-3-pro": 1950,
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
        if model not in ("minimax-music-v2", "lyria-3-pro"):
            cmd.extend(["--duration", str(duration)])
    elif duration and stem_name in ("texture", "atmosphere", "spatial"):
        # stable-audio-25 max 180s — pass duration for texture, atmosphere, AND spatial
        bed_dur = min(duration, 180)
        cmd.extend(["--duration", str(bed_dur)])
    # accent doesn't support duration (short SFX)

    # Add lyrics for main vocal track
    if lyrics and stem_name == "main":
        cmd.extend(["--lyrics", lyrics])

    # Add instrumental flag if no lyrics or director specified it
    if stem_name == "main" and model in ("elevenlabs-music", "elevenlabs-music-v2-5"):
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

            # Model fallback: if elevenlabs-music-v2-5 hits transient model error, retry on elevenlabs-music
            if model == "elevenlabs-music-v2-5" and ("model" in error_msg.lower() or "not found" in error_msg.lower() or "invalid" in error_msg.lower()):
                log(f"  🔄 Falling back from elevenlabs-music-v2-5 to elevenlabs-music...")
                return generate_stem(
                    stem_name=stem_name, prompt=stem_prompt[:1950], lyrics=lyrics,
                    duration=duration, stems_dir=stems_dir,
                    model_override="elevenlabs-music", force_instrumental=force_instrumental,
                )

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
                simple_prompt += f", heavy West Coast 808 bass glides, dark nocturnal synth hook, dynamic builds and energetic drops"

                retry_cmd = [
                    sys.executable, VENICE_SCRIPT,
                    "--model", model,
                    "--prompt", simple_prompt,
                    "--output", stems_dir,
                ]
                if _CHAT_ID:
                    retry_cmd.extend(["--chat-id", str(_CHAT_ID)])
                if duration and stem_name == "main" and model not in ("minimax-music-v2", "lyria-3-pro"):
                    retry_cmd.extend(["--duration", str(duration)])
                if stem_name == "main" and not lyrics and model in ("elevenlabs-music", "elevenlabs-music-v2-5"):
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
                            stem_prompt = simple_prompt
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
            "prompt": stem_prompt,
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


def export_daw_stems(active_stems, output_dir, main_duration):
    """Export full-length, duration-matched, arrangement-enveloped, 3D-spatialized stems to <output_dir>/daw_stems/
    so DAWAGENT always receives matched-duration discrete stems with 3D movement and mix balance preserved.
    """
    if not active_stems or not main_duration:
        return None
    daw_stems_dir = os.path.join(output_dir, "daw_stems")
    os.makedirs(daw_stems_dir, exist_ok=True)
    exported = []
    role_order = {"main": 1, "texture": 2, "atmosphere": 3, "spatial": 4, "b_section": 5, "ear_candy_bus": 6}

    for idx, stem in enumerate(sorted(active_stems, key=lambda s: role_order.get(s["role"], 99)), 1):
        role = stem["role"]
        src = stem.get("file", "")
        if not src or not os.path.isfile(src):
            continue
        out_wav = os.path.join(daw_stems_dir, f"{idx:02d}_{role}.wav")
        stem_dur = get_audio_duration(src) or main_duration
        config = STEM_CONFIG.get(role, {"mix_volume": 0.3, "pan": 0.0})
        volume = stem.get("mix_volume_override", config["mix_volume"])
        pan = stem.get("mix_pan_override", config.get("pan", 0.0))

        filters = []
        arr_expr = build_arrangement_volume(role, main_duration)
        if arr_expr:
            filters.append(f"volume='{arr_expr}':eval=frame")
        else:
            filters.append(f"volume={volume}")

        if role == "spatial":
            filters.append(
                "haas=left_delay=2.1:right_delay=11.8:side_gain=1.38:middle_phase=0"
                ",apulsator=mode=sine:timing=hz:hz=0.08:amount=0.52:offset_l=0.0:offset_r=0.5"
                ",stereotools=mlev=0.82:slev=1.36"
            )
        elif role == "atmosphere":
            filters.append(
                "haas=left_delay=9.4:right_delay=2.3:side_gain=1.25:middle_phase=0"
                ",apulsator=mode=triangle:timing=hz:hz=0.05:amount=0.42:offset_l=0.25:offset_r=0.75"
                ",stereotools=mlev=0.88:slev=1.25"
            )
        elif role == "texture":
            filters.append(
                "stereotools=mlev=0.92:slev=1.18"
                ",apulsator=mode=sine:timing=hz:hz=0.11:amount=0.26:offset_l=0.1:offset_r=0.6"
            )
        elif role == "b_section":
            filters.append(
                "haas=left_delay=6.0:right_delay=13.2:side_gain=1.30:middle_phase=0"
                ",stereotools=mlev=0.85:slev=1.30"
            )
        elif pan != 0.0:
            filters.append(f"stereotools=balance_out={pan}")

        if stem_dur < main_duration - 0.2:
            if role in ("texture", "atmosphere", "spatial", "b_section") and stem_dur >= 15:
                filters.append("aloop=loop=-1:size=2e+09")
            else:
                filters.append(f"apad=whole_dur={main_duration}")
        filters.append(f"atrim=0:{main_duration}")
        filters.append("asetpts=PTS-STARTPTS")

        cmd = [
            "ffmpeg", "-y", "-i", src,
            "-af", ",".join(filters),
            "-ar", "48000", "-ac", "2",
            out_wav,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and os.path.isfile(out_wav):
                exported.append(out_wav)
        except Exception:
            pass

    if exported:
        log(f"  🎚️ Exported {len(exported)} full-length ({main_duration:.1f}s) 3D-arranged discrete stems to daw_stems/")
    return daw_stems_dir if exported else None


def mix_stems(stems, output_dir, target="streaming"):
    """Mix multiple stems together using 3D Haas/Orbital spatialization and Kick/808 Sidechain Ducking."""
    if not stems:
        fail("No stems to mix")

    if len(stems) == 1:
        return stems[0]["file"]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mix_path = os.path.join(output_dir, f"mix_{timestamp}.wav")

    log("")
    log("=" * 60)
    log("MIXING STEMS (3D Orbital Spatial + 808 Sidechain Ducking)")
    log("=" * 60)

    main_stem = next((s for s in stems if s["role"] == "main"), stems[0])
    main_duration = get_audio_duration(main_stem["file"])
    if main_duration:
        log(f"  Main track duration: {main_duration:.1f}s")

    # If ear_candy_bus was built, exclude raw short clips (accent, riser, foley) from direct ffmpeg mix
    # because they are already beat-locked, multi-placed, and Doppler-panned inside ear_candy_bus!
    has_ear_candy_bus = any(s["role"] == "ear_candy_bus" for s in stems)
    if has_ear_candy_bus:
        active_stems = [s for s in stems if s["role"] not in ("accent", "riser", "foley")]
    else:
        active_stems = list(stems)

    # Export duration-matched discrete stems for DAWAGENT
    export_daw_stems(active_stems, output_dir, main_duration)

    def _build_mix_filter(use_sidechain=True):
        inputs = []
        filter_parts = []
        core_labels = []
        core_weights = []
        bed_labels = []
        bed_weights = []

        for i, stem in enumerate(active_stems):
            role = stem["role"]
            config = STEM_CONFIG.get(role, {"mix_volume": 0.3, "pan": 0.0})
            volume = stem.get("mix_volume_override", config["mix_volume"])
            pan = stem.get("mix_pan_override", config.get("pan", 0.0))

            inputs.extend(["-i", stem["file"]])
            stem_dur = get_audio_duration(stem["file"])

            arr_expr = build_arrangement_volume(role, main_duration)
            if arr_expr:
                stem_filter = f"[{i}:a]volume='{arr_expr}':eval=frame"
            else:
                stem_filter = f"[{i}:a]volume={volume}"

            eq_override = stem.get("mix_eq_override", "")
            if eq_override:
                if eq_override.startswith("lowpass_"):
                    freq = eq_override.split("_")[1].replace("hz", "")
                    stem_filter += f",lowpass=f={freq}"
                elif eq_override.startswith("highpass_"):
                    freq = eq_override.split("_")[1].replace("hz", "")
                    stem_filter += f",highpass=f={freq}"

            # Pillar 2: True 3D Binaural Haas & Orbital LFO Spatial Movement
            if role == "spatial":
                stem_filter += (
                    ",haas=left_delay=2.1:right_delay=11.8:side_gain=1.38:middle_phase=0"
                    ",apulsator=mode=sine:timing=hz:hz=0.08:amount=0.52:offset_l=0.0:offset_r=0.5"
                    ",stereotools=mlev=0.82:slev=1.36"
                )
            elif role == "atmosphere":
                stem_filter += (
                    ",haas=left_delay=9.4:right_delay=2.3:side_gain=1.25:middle_phase=0"
                    ",apulsator=mode=triangle:timing=hz:hz=0.05:amount=0.42:offset_l=0.25:offset_r=0.75"
                    ",stereotools=mlev=0.88:slev=1.25"
                )
            elif role == "texture":
                stem_filter += (
                    ",stereotools=mlev=0.92:slev=1.18"
                    ",apulsator=mode=sine:timing=hz:hz=0.11:amount=0.26:offset_l=0.1:offset_r=0.6"
                )
            elif role == "b_section":
                stem_filter += (
                    ",haas=left_delay=6.0:right_delay=13.2:side_gain=1.30:middle_phase=0"
                    ",stereotools=mlev=0.85:slev=1.30"
                )
            elif pan != 0.0:
                stem_filter += f",stereotools=balance_out={pan}"

            if target in ("l-acoustics", "club"):
                hp = STEM_HP_FILTERS.get(role)
                if hp:
                    stem_filter += f",{hp}"

            is_short_sfx = role in ("accent", "riser", "foley") and config.get("placement") == "transitions"
            if main_duration and stem_dur and role != "main":
                if is_short_sfx and stem_dur < 15:
                    offset_pct = {"riser": 0.36, "accent": 0.40, "foley": 0.62}.get(role, 0.38)
                    sfx_offset = max(0, main_duration * offset_pct)
                    stem_filter += f",adelay={int(sfx_offset * 1000)}|{int(sfx_offset * 1000)}"
                    stem_filter += f",apad=whole_dur={main_duration}"
                elif stem_dur < main_duration - 0.1:
                    if role in ("texture", "atmosphere", "spatial", "b_section") and stem_dur >= 15:
                        stem_filter += ",aloop=loop=-1:size=2e+09"
                    else:
                        pad_dur = main_duration - stem_dur
                        stem_filter += f",apad=pad_dur={pad_dur}"
                stem_filter += f",atrim=0:{main_duration}"

            stem_filter += ",asetpts=PTS-STARTPTS"
            stem_filter += f"[s{i}]"
            filter_parts.append(stem_filter)

            # Keep ONLY 'main' in core_labels so all supporting beds AND special effects (ear_candy_bus, accent, riser, foley)
            # are sidechain-ducked smoothly underneath the main 808 sub and kick transients!
            if role == "main":
                core_labels.append(f"[s{i}]")
                core_weights.append("1.0")
            else:
                bed_labels.append(f"[s{i}]")
                bed_weights.append("1.0")

            if use_sidechain:
                pan_str = f", pan={pan:+.1f}" if pan != 0.0 else ""
                log(f"  Stem {i}: {role:14s} (vol={volume}{pan_str}, model={stem['model']})")

        # Pillar 5: Dynamic Sub/Kick-Triggered Sidechain Compression between Core Bus and 3D Bed Bus
        if use_sidechain and core_labels and bed_labels:
            if len(core_labels) > 1:
                cw = " ".join(core_weights)
                filter_parts.append(
                    f"{''.join(core_labels)}amix=inputs={len(core_labels)}:duration=longest:normalize=0:weights={cw}[core_bus]"
                )
            else:
                filter_parts.append(f"{core_labels[0]}acopy[core_bus]")

            if len(bed_labels) > 1:
                bw = " ".join(bed_weights)
                filter_parts.append(
                    f"{''.join(bed_labels)}amix=inputs={len(bed_labels)}:duration=longest:normalize=0:weights={bw}[bed_bus]"
                )
            else:
                filter_parts.append(f"{bed_labels[0]}acopy[bed_bus]")

            # Split core_bus -> [core_main] and [sc_raw], isolate 30-135Hz sub/kick transients as sidechain key
            filter_parts.append("[core_bus]asplit=2[core_main][sc_raw]")
            filter_parts.append("[sc_raw]lowpass=f=135,highpass=f=30[sc_key]")
            filter_parts.append(
                "[bed_bus][sc_key]sidechaincompress=threshold=0.035:ratio=4.5:attack=4:release=190:detection=peak:mix=0.72[bed_ducked]"
            )
            filter_parts.append(
                "[core_main][bed_ducked]amix=inputs=2:duration=longest:normalize=0:weights=1.0 1.0[mixed]"
            )
        else:
            all_labels = "".join(f"[s{i}]" for i in range(len(active_stems)))
            weights_str = " ".join("1.0" for _ in active_stems)
            filter_parts.append(
                f"{all_labels}amix=inputs={len(active_stems)}:duration=longest:normalize=0:weights={weights_str}[mixed]"
            )

        return inputs, ";".join(filter_parts)

    sr_str = str(TARGET_PROFILES.get(target, TARGET_PROFILES["streaming"])["sample_rate"])
    inputs, filter_complex = _build_mix_filter(use_sidechain=True)
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[mixed]",
        "-ar", sr_str,
        "-ac", "2",
        mix_path,
    ]

    log(f"  Running ffmpeg 3D sidechain mix...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        if result.returncode != 0:
            log(f"  ⚠️ Sidechain mix filter warning ({result.stderr[-180:]}), retrying with standard amix...")
            inputs_fb, fc_fb = _build_mix_filter(use_sidechain=False)
            cmd_fb = ["ffmpeg", "-y", *inputs_fb, "-filter_complex", fc_fb, "-map", "[mixed]", "-ar", sr_str, "-ac", "2", mix_path]
            res_fb = subprocess.run(cmd_fb, capture_output=True, text=True, timeout=120)
            if res_fb.returncode != 0:
                log(f"  ⛔ Mix failed: {res_fb.stderr[-300:]}")
                return main_stem["file"]
        log(f"  ✅ Mix complete: {mix_path}")
        try:
            premaster_copy = os.path.join(output_dir, "premaster_mix.wav")
            shutil.copy2(mix_path, premaster_copy)
            log(f"  💾 Saved unmastered premaster mix for DAWAGENT: {premaster_copy}")
        except Exception:
            pass
        return mix_path
    except Exception as e:
        log(f"  ⛔ Mix error: {e}")
        return main_stem["file"]


def master_audio(input_path, output_dir, skip_master=False, target="streaming",
                 track_title="VØIDRIDE Track", artist="VØIDRIDE", album=None,
                 genre=None, track_num=None, total_tracks=None, comment=None):
    """Apply studio 2-pass linear loudness mastering chain using ffmpeg. Returns dict with primary path and all files."""
    if skip_master:
        log("  Mastering skipped (--skip-master)")
        return {"primary": input_path, "files": {}}

    profile = TARGET_PROFILES.get(target, TARGET_PROFILES["streaming"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    log("")
    log("=" * 60)
    log(f"MASTERING — Target: {target.upper()} (2-Pass Linear Loudnorm + Soft-Clip)")
    log(f"  {profile['description']}")
    log("=" * 60)

    duration = get_audio_duration(input_path)
    fade_out_dur = 4.5  # Clean DJ/streaming fade-out length
    fade_out_start = max(0, (duration or 60) - fade_out_dur)

    # Build pre-loudnorm analog tone & glue stages
    pre_filters = []

    # 1. Subsonic HP filter
    hp_order = min(profile['hp_order'], 2)
    pre_filters.append(f"highpass=f={profile['hp_freq']}:p={hp_order}")

    # 2. Gentle glue compression (slow attack preserves kick/snare punch!)
    pre_filters.append(
        f"acompressor=threshold={profile['comp_threshold']}dB"
        f":ratio={profile['comp_ratio']}"
        f":attack={profile['comp_attack']}"
        f":release={profile['comp_release']}"
        f":makeup={profile['comp_makeup']}dB"
    )

    # 3. EQ bands
    for eq in profile["eq"]:
        pre_filters.append(f"equalizer=f={eq['f']}:t=q:w={eq['w']}:g={eq['g']}")

    # 4. Stereo field optimization
    if profile["stereo_mid"] != 1.0 or profile["stereo_side"] != 1.0:
        pre_filters.append(f"stereotools=mlev={profile['stereo_mid']}:slev={profile['stereo_side']}")

    # 6. Pass 1 Loudness Measurement for transparent 2-pass linear normalization
    loudnorm_stage = f"loudnorm=I={profile['lufs']}:TP={profile['true_peak']}:LRA={profile['lra']}"
    try:
        measure_chain = ",".join(pre_filters + [f"{loudnorm_stage}:print_format=json"])
        m_res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", input_path, "-af", measure_chain, "-f", "null", "-"],
            capture_output=True, text=True, timeout=90,
        )
        j_start = m_res.stderr.rfind("{")
        j_end = m_res.stderr.rfind("}") + 1
        if j_start >= 0 and j_end > j_start:
            ln_stats = json.loads(m_res.stderr[j_start:j_end])
            in_i = ln_stats.get("input_i")
            in_tp = ln_stats.get("input_tp")
            in_lra = ln_stats.get("input_lra")
            in_thresh = ln_stats.get("input_thresh")
            t_off = ln_stats.get("target_offset")
            if all(v is not None and str(v) not in ("-inf", "inf", "nan") for v in (in_i, in_tp, in_lra, in_thresh, t_off)):
                loudnorm_stage = (
                    f"loudnorm=I={profile['lufs']}:TP={profile['true_peak']}:LRA={profile['lra']}"
                    f":measured_I={in_i}:measured_TP={in_tp}:measured_LRA={in_lra}"
                    f":measured_thresh={in_thresh}:offset={t_off}:linear=true"
                )
                log(f"  📐 Pass 1 measured: {in_i} LUFS (TP {in_tp} dBTP, LRA {in_lra} LU) → applying linear Pass 2")
    except Exception as ln_err:
        log(f"  ⚠️ 2-pass measure fallback to single-pass ({ln_err})")

    # 7. Harmonic Soft-Clipper + Brickwall True-Peak Limiter + Fades
    filters = list(pre_filters)
    filters.append(loudnorm_stage)
    filters.append("asoftclip=type=sin:param=0.82")
    filters.append(f"alimiter=limit={profile['true_peak']}dB:level=false")
    filters.append("afade=t=in:ss=0:d=0.4")
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
        "-metadata", f"artist={artist}",
        "-metadata", f"album_artist={artist}",
        "-metadata", "copyright=© 2026 Max Infeld",
        "-metadata", f"publisher={artist}",
    ]
    if album:
        meta += ["-metadata", f"album={album}"]
    if genre:
        meta += ["-metadata", f"genre={genre}"]
    if track_num:
        meta += ["-metadata", f"track={track_num}/{total_tracks}" if total_tracks else f"track={track_num}"]
    if comment:
        meta += ["-metadata", f"comment={comment}"]
    else:
        meta += ["-metadata", f"comment=Mastered by {artist} — {target} target"]

    output_files = {}
    primary_path = None

    try:
        # Step 1: Master to primary format at target sample rate
        primary_fmt = profile["primary_format"]
        primary_file = os.path.join(output_dir, f"master_{timestamp}.{primary_fmt}")

        codec_args = []
        if primary_fmt == "flac":
            codec_args = ["-sample_fmt", "s32"]
        elif primary_fmt == "aiff":
            codec_args = ["-c:a", "pcm_s24be"]
        elif primary_fmt in ("wav",):
            codec_args = ["-c:a", "pcm_s24le"]

        mono_freq = profile.get("mono_fold_below")
        if mono_freq:
            pre_chain_str = ",".join(pre_filters)
            post_chain_str = ",".join([
                loudnorm_stage,
                "asoftclip=type=sin:param=0.82",
                f"alimiter=limit={profile['true_peak']}dB:level=false",
                "afade=t=in:ss=0:d=0.4",
                f"afade=t=out:st={fade_out_start}:d={fade_out_dur}",
            ])
            fc_primary = (
                f"[0:a]{pre_chain_str},acrossover=split={int(mono_freq)}[low][high];"
                f"[low]pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1[lowm];"
                f"[lowm][high]amix=inputs=2:duration=longest:normalize=0:weights=1 1,"
                f"{post_chain_str}[out]"
            )
            cmd_primary = [
                "ffmpeg", "-y", "-i", input_path,
                "-filter_complex", fc_primary,
                "-map", "[out]",
                "-ar", sr, "-ac", "2",
                *codec_args, *meta, primary_file,
            ]
        else:
            cmd_primary = [
                "ffmpeg", "-y", "-i", input_path,
                "-af", mastering_filter,
                "-ar", sr, "-ac", "2",
                *codec_args, *meta, primary_file,
            ]

        result = subprocess.run(cmd_primary, capture_output=True, text=True, timeout=180)
        if result.returncode != 0 or not os.path.isfile(primary_file) or os.path.getsize(primary_file) < 1000:
            log("  ⚠️ Primary filter_complex failed, retrying direct -af chain...")
            if os.path.exists(primary_file):
                try:
                    os.remove(primary_file)
                except OSError:
                    pass
            cmd_fb = [
                "ffmpeg", "-y", "-i", input_path,
                "-af", mastering_filter,
                "-ar", sr, "-ac", "2",
                *codec_args, *meta, primary_file,
            ]
            result = subprocess.run(cmd_fb, capture_output=True, text=True, timeout=180)
            if result.returncode != 0 or not os.path.isfile(primary_file) or os.path.getsize(primary_file) < 1000:
                if os.path.exists(primary_file):
                    try:
                        os.remove(primary_file)
                    except OSError:
                        pass
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


def matchering_master(input_path, output_dir, reference_dir=None, track_title="VØIDRIDE Track",
                      artist="VØIDRIDE", album=None, genre=None, track_num=None, total_tracks=None):
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

        # Also create FLAC with metadata
        meta = [
            "-metadata", f"title={track_title}",
            "-metadata", f"artist={artist}",
            "-metadata", f"album_artist={artist}",
            "-metadata", "copyright=© 2026 Max Infeld",
            "-metadata", f"publisher={artist}",
        ]
        if album:
            meta += ["-metadata", f"album={album}"]
        if genre:
            meta += ["-metadata", f"genre={genre}"]
        if track_num:
            meta += ["-metadata", f"track={track_num}/{total_tracks}" if total_tracks else f"track={track_num}"]

        out_flac = os.path.join(output_dir, f"master_ref_{timestamp}.flac")
        flac_cmd = ["ffmpeg", "-y", "-i", out_wav, "-ar", "48000", "-sample_fmt", "s32", *meta, out_flac]
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

        # Check for severe unmusical glitches (> 15dB single-second cliff, allowing 8-13dB dynamic bridge drops!)
        for i in range(2, max(2, len(rms_db) - 5)):
            drop = rms_db[i - 1] - rms_db[i]  # positive = got quieter
            if drop > 15.0:
                result["drops"].append({
                    "time_sec": i,
                    "drop_db": round(drop, 1),
                    "severity": "severe" if drop > 20 else "moderate",
                })

        # Check for genuine dead-air sections (> 18dB below average mid-track)
        for i, db in enumerate(rms_db):
            if 5 <= i <= max(5, len(rms_db) - 8) and db < avg_db - 18.0:
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
        "spatial": "surround_wide_elevated",
    }
    stem_freq_ranges = {
        "main": "20-20000Hz",
        "texture": "300-16000Hz",
        "accent": "500-16000Hz",
        "atmosphere": "300-16000Hz",
        "spatial": "250-18000Hz",
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
            "prompt": stem.get("prompt") or config["prompt_template"].format(prompt=args.prompt),
            "file": os.path.basename(stem["file"]),
            "generation_time_seconds": stem.get("generation_time", 0),
            "mix_volume": stem.get("mix_volume_override", config["mix_volume"]),
            "pan": stem.get("mix_pan_override", config.get("pan", 0.0)),
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
    parser.add_argument("--quality", default="standard", choices=["quick", "standard", "premium", "hyperspatial"],
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
    parser.add_argument("--title", default=None, help="Track title for metadata")
    parser.add_argument("--artist", default=None, help="Artist name for metadata (default: VØIDRIDE)")
    parser.add_argument("--album", default=None, help="Album name for metadata")
    parser.add_argument("--genre", default=None, help="Genre for metadata")
    parser.add_argument("--track-number", type=int, default=None, help="Track number for metadata")
    parser.add_argument("--total-tracks", type=int, default=None, help="Total track count for metadata")

    args = parser.parse_args()

    # Set up Telegram notifications — auto-detect if --chat-id not passed
    _CHAT_ID = args.chat_id
    _auto_detect_telegram()

    # Mode detection: Sample preview (<=30s) vs Full track
    is_sample_mode = args.preview or (args.preview is None and args.duration <= 30)
    mode_label = "20s SAMPLE PREVIEW (MP3)" if is_sample_mode else f"FULL TRACK ({args.duration}s, Lossless FLAC)"

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
    log(f"Mode:     {mode_label}")
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

    # Creative Director / Showrunner Plan
    original_prompt = args.prompt
    production_plan = None
    album_context = None
    album_context_file = os.environ.get("ALBUM_CONTEXT_FILE")
    if album_context_file and os.path.isfile(album_context_file):
        try:
            with open(album_context_file) as f:
                album_context = json.load(f)
        except Exception:
            album_context = None

    # Plan replay / Showrunner pre-computed plan mode (zero per-track LLM overhead!)
    if args.plan:
        log("")
        log("PHASE 0: LOCKED SHOWRUNNER / PREVIEW PLAN")
        log("-" * 60)
        try:
            with open(args.plan) as f:
                production_plan = json.load(f)
            production_plan.pop("qc", None)
            production_plan.pop("cost", None)
            log(f"  🔒 Locked plan: {production_plan.get('title', '?')}")
            log(f"  Genre: {production_plan.get('genre')} | BPM: {production_plan.get('bpm')} | Key: {production_plan.get('key')}")
            log(f"  Duration override: {args.duration}s")
            production_plan.setdefault("stems", {})
            plan_key_fill = production_plan.get("key", "Dm")
            plan_bpm_fill = production_plan.get("bpm", 134)
            plan_title_fill = production_plan.get("title", "NIGHTRIDE")
            for ms in stem_names:
                if ms not in production_plan["stems"]:
                    if ms in ("texture", "atmosphere", "spatial"):
                        production_plan["stems"][ms] = {
                            "model": "demucs-harmonic-synth",
                            "prompt": f"Chord-locked {ms} harmonic layer derived from main stem in {plan_key_fill} at {plan_bpm_fill} BPM for {plan_title_fill}.",
                        }
                    elif ms in ("accent", "riser"):
                        production_plan["stems"][ms] = {
                            "model": "voidride-sfx-vault",
                            "prompt": f"Warm studio-curated analog {ms} transition for {plan_title_fill}.",
                        }
                    elif ms == "foley":
                        production_plan["stems"][ms] = {
                            "model": "elevenlabs-sound-effects-v2",
                            "prompt": f"Subtle warm low-passed cyber-noir ambient texture for {plan_title_fill}, smooth nocturnal highway air and velvet reflections.",
                        }
            for sn, si in production_plan.get("stems", {}).items():
                if isinstance(si, dict):
                    log(f"  {sn:12s} → {si.get('model', '?'):25s} (locked)")
            telegram_notify(f"🔒 *Executing Showrunner plan: {production_plan.get('title', '?')}*\nDuration: {args.duration}s")
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
        if album_context:
            log(f"  📀 Album mode: track {album_context.get('track_number', '?')}/{album_context.get('total_tracks', '?')}")
            rules = album_context.get("variation_rules", [])
            if rules:
                log(f"  🎲 Variation: {rules[0]}")
        production_plan = creative_director(
            args.prompt, args.quality, args.duration,
            lyrics=args.lyrics, profile=active_profile,
            album_context=album_context,
            title=args.title,
        )
        if production_plan:
            # Upscale ONLY genuinely tiny prompts (< 120 chars) on paid generative stems
            genre = production_plan.get("genre", "")
            bpm = production_plan.get("bpm", 0)
            key = production_plan.get("key", "")
            cov_vis = album_context.get("cover_visual", "") if album_context else ""
            trk_tit = album_context.get("track_title", "") if album_context else (args.title or "")
            for stem_name, stem_info in production_plan.get("stems", {}).items():
                if isinstance(stem_info, dict) and stem_info.get("prompt"):
                    model = stem_info.get("model", "")
                    if model in ("demucs-harmonic-synth", "voidride-sfx-vault"):
                        continue
                    max_chars = 3900 if model == "elevenlabs-music-v2-5" else (1800 if model == "elevenlabs-music" else 480)
                    if len(stem_info["prompt"]) < 120:
                        stem_info["prompt"] = upscale_prompt(
                            stem_info["prompt"], stem_name,
                            genre=genre, bpm=bpm, key=key, max_chars=max_chars,
                            cover_visual=cov_vis, track_title=trk_tit
                        )
            log("")
        else:
            log("  Director failed — injecting sonic DNA for fallback")
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
    stem_labels = {
        "main": "🎤 Main Track",
        "texture": "🌊 Texture Layer",
        "accent": "💥 Sub Impact FX",
        "riser": "🚀 Tension Riser",
        "foley": "🔊 Narrative Foley",
        "atmosphere": "🌌 Atmosphere",
        "spatial": "🌐 3D Spatial Field",
    }

    telegram_notify(
        f"🎵 *Starting {args.quality} production* — `{mode_label}`\n"
        f"🎯 Target: {args.target}\n"
        f"📋 Pipeline: {total_stems} stems → 3D spatial/ear-candy → sidechain mix → master\n"
        f"⏱️ Estimated: {3 * total_stems + 2}-{5 * total_stems + 5} minutes"
    )

    # Step 1: Generate main track + chord-locked Demucs harmonic stems + SFX vault + bespoke foley
    log("PHASE 1: STEM GENERATION & CHORD-LOCKED HARMONIC SYNTHESIS")
    log("-" * 60)
    report_progress("stems")

    separated_demucs = None
    ordered_stem_names = (["main"] + [s for s in stem_names if s != "main"]) if "main" in stem_names else list(stem_names)
    track_seed = int(args.track_number or (album_context.get("track_number") if album_context else 1) or 1)

    for i, stem_name in enumerate(ordered_stem_names, 1):
        label = stem_labels.get(stem_name, stem_name)
        remaining = total_stems - i
        telegram_notify(
            f"{label} ({i}/{total_stems})\n"
            f"{'✅ ' * (i-1)}{'⏳ ' + '⬜ ' * remaining if remaining >= 0 else ''}"
        )

        # Use Showrunner / Creative Director plan if available
        stem_prompt = args.prompt
        stem_model_override = None
        stem_instrumental = None
        if production_plan and stem_name in production_plan.get("stems", {}):
            plan_stem = production_plan["stems"][stem_name]
            stem_prompt = plan_stem.get("prompt", args.prompt)
            stem_model_override = plan_stem.get("model")
            stem_instrumental = plan_stem.get("instrumental")
            log(f"  📋 Plan [{stem_name}]: {stem_model_override} | \"{stem_prompt[:80]}...\"")

        stem_result = None

        # Zero-cost chord-locked harmonic stem synthesis from Demucs 'other' stem
        if stem_name in ("texture", "atmosphere", "spatial") and (
            stem_model_override in (None, "demucs-harmonic-synth")
        ) and separated_demucs:
            synth_file = synthesize_harmonic_stem_from_demucs(stem_name, separated_demucs, stems_dir, args.duration)
            if synth_file and os.path.isfile(synth_file):
                stem_result = {
                    "role": stem_name,
                    "model": "demucs-harmonic-synth",
                    "prompt": stem_prompt,
                    "file": synth_file,
                    "generation_time": 0.5,
                    "cost": {"cost_usd": 0.0, "credits": 0},
                }

        # Zero-cost curated analog riser / rounded sub-impact SFX vault
        elif stem_name in ("accent", "riser") and stem_model_override in (None, "voidride-sfx-vault"):
            vault_file = get_or_create_vault_sfx(
                stem_name, stems_dir,
                bpm=(production_plan.get("bpm", 134) if production_plan else 134),
                variant_seed=track_seed + i,
            )
            if vault_file and os.path.isfile(vault_file):
                log(f"  🏛️ Loaded smooth curated '{stem_name}' from VØIDRIDE SFX vault ($0.00)")
                stem_result = {
                    "role": stem_name,
                    "model": "voidride-sfx-vault",
                    "prompt": stem_prompt,
                    "file": vault_file,
                    "generation_time": 0.1,
                    "cost": {"cost_usd": 0.0, "credits": 0},
                }

        # Generative API stem (main on elevenlabs-music-v2-5, bespoke foley on elevenlabs-sound-effects-v2, or fallback)
        if stem_result is None:
            fallback_override = stem_model_override
            if fallback_override == "demucs-harmonic-synth":
                fallback_override = STEM_CONFIG.get(stem_name, {}).get("fallback_model", "stable-audio-25")
            elif fallback_override == "voidride-sfx-vault":
                fallback_override = STEM_CONFIG.get(stem_name, {}).get("fallback_model", "elevenlabs-sound-effects-v2")

            stem_result = generate_stem(
                stem_name=stem_name,
                prompt=stem_prompt,
                lyrics=args.lyrics if stem_name == "main" else None,
                duration=args.duration,
                stems_dir=stems_dir,
                model_override=fallback_override,
                force_instrumental=stem_instrumental,
            )

        # VØIDRIDE Automated Main-Stem Acoustic QC Gate + Immediate 4-Stem Demucs Separation
        if stem_result and stem_name == "main" and args.duration >= 60:
            qc_passed, qc_issues, qc_metrics = validate_voidride_main_stem(stem_result["file"], args.duration)
            log(
                f"  🔬 VØIDRIDE Main Stem QC: dur={qc_metrics.get('actual_duration', '?')}s, "
                f"drop_sub={qc_metrics.get('drop_sub_active_pct', '?')}%, "
                f"sub_active={qc_metrics.get('sub_active_pct', '?')}%, "
                f"sub_rms={qc_metrics.get('sub_mean_rms', '?')}"
            )
            retry_attempt = 0
            while not qc_passed and retry_attempt < 2:
                retry_attempt += 1
                log(f"  ⚠️ Main stem failed VØIDRIDE acoustic QC (attempt {retry_attempt}/2): {'; '.join(qc_issues)}")
                reinforced_prompt = (
                    "Dynamic hit-arranged West Coast nightride trap & California 808 bass: "
                    "powerful gliding 808 sub-bass dominance throughout Drop 1 and Climax Drop 2, "
                    "punchy transient kicks, memorable foreground synth hook, and full-length energy through the final bar. "
                    + stem_prompt
                )[:3900]
                retry_stem = generate_stem(
                    stem_name="main",
                    prompt=reinforced_prompt,
                    lyrics=args.lyrics,
                    duration=args.duration,
                    stems_dir=stems_dir,
                    model_override=stem_model_override,
                    force_instrumental=stem_instrumental,
                )
                if retry_stem:
                    stem_result = retry_stem
                    qc_passed, qc_issues, qc_metrics = validate_voidride_main_stem(stem_result["file"], args.duration)
                    log(
                        f"  🔬 Retry {retry_attempt} QC: dur={qc_metrics.get('actual_duration', '?')}s, "
                        f"drop_sub={qc_metrics.get('drop_sub_active_pct', '?')}%, "
                        f"passed={qc_passed}"
                    )
                else:
                    break

            # Run 4-stem Demucs immediately after main so chord-locked harmonic stems & B-section share one pass!
            if args.quality in ("standard", "premium", "hyperspatial"):
                log("  🎛️ Running 4-stem Demucs separation on main stem to unlock chord-locked harmonic beds & dynamic sculpting...")
                separated_demucs = separate_stems(stem_result["file"], stems_dir)

        if stem_result:
            generated_stems.append(stem_result)
        else:
            if stem_name == "main":
                try:
                    shutil.rmtree(session_dir, ignore_errors=True)
                except Exception:
                    pass
                fail(f"Main track generation failed — cannot proceed")
            else:
                log(f"  ⚠️ Optional stem '{stem_name}' failed — continuing without it")

    log(f"")
    log(f"Generated {len(generated_stems)}/{total_stems} stems successfully")

    # Step 1b: Build B-Section from already-separated 4-Stem Demucs (zero duplicate Demucs run!)
    if args.quality in ("standard", "premium", "hyperspatial") and len(generated_stems) >= 2:
        log("")
        log("PHASE 1b: DEMUCS HOLOGRAPHIC B-SECTION")
        log("-" * 60)
        report_progress("b_section")
        telegram_notify("🎭 *Building drumless breakdown contrast from 4-stem Demucs...*")
        main_stem_file = next((s["file"] for s in generated_stems if s["role"] == "main"), None)
        demucs_b_path = None
        if main_stem_file and not separated_demucs:
            separated_demucs = separate_stems(main_stem_file, stems_dir)
        if separated_demucs:
            demucs_b_path = create_demucs_b_section(separated_demucs, stems_dir, args.duration)

        if demucs_b_path:
            generated_stems.append({
                "role": "b_section",
                "model": "demucs-htdemucs",
                "file": demucs_b_path,
                "generation_time": 0,
                "cost": {"cost_usd": 0, "credits": 0},
            })
            log(f"  ✅ Demucs B-section: drums removed & Haas-spatialized for breakdown")
            log(f"  Total stems: {len(generated_stems)} (including Demucs B-section)")
        elif main_stem_file:
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

    # ─── Phase 1c: Stem Analysis & Phase-Locked Beat/Key Alignment ───────
    log("")
    log("PHASE 1c: STEM ANALYSIS & BEAT/KEY PHASE-LOCKING")
    log("-" * 60)
    report_progress("analysis")
    detected_key_actual = None
    detected_bpm_actual = None
    target_key, target_bpm = extract_key_bpm(args.prompt)
    if production_plan:
        target_bpm = target_bpm or production_plan.get("bpm")
        target_key = target_key or production_plan.get("key")

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

    main_stem_obj = next((s for s in generated_stems if s["role"] == "main"), generated_stems[0])
    main_dur_actual = get_audio_duration(main_stem_obj["file"]) or float(args.duration)
    master_bpm_ref = detected_bpm_actual or target_bpm or 132.0
    if master_bpm_ref < 95:
        master_bpm_ref = float(target_bpm or 132.0)
    master_key_ref = detected_key_actual or target_key or "Dm"

    # Pillar 4: Detect Beat Grid & Sculpt Main Stem (Breakdown Drum-Drop + Pre-Drop Stutter Slicer)
    transition_grid = detect_transition_grid(main_stem_obj["file"], bpm=master_bpm_ref, duration=main_dur_actual)
    if separated_demucs and main_dur_actual >= 45:
        sculpted_main = sculpt_main_with_demucs(main_stem_obj["file"], separated_demucs, transition_grid, stems_dir)
        if sculpted_main and sculpted_main != main_stem_obj["file"]:
            main_stem_obj["file"] = sculpted_main

    # ─── Phase 1d: Per-Stem 3D Pedalboard Effects & Beat/Key Alignment ───
    log("")
    log("PHASE 1d: 3D STEM EFFECTS (Pedalboard Shimmer/Modulation) & PHASE ALIGNMENT")
    log("-" * 60)
    report_progress("effects")
    for stem in generated_stems:
        original_file = stem["file"]
        processed_file = process_stem_effects(original_file, stem["role"])
        if processed_file != original_file:
            stem["file"] = processed_file
            stem["effects_applied"] = True

        # Pillar 3: Time-stretch, pitch-match, and seamlessly crossfade-loop beds to exact main_dur_actual
        if stem["role"] in ("texture", "atmosphere", "spatial", "b_section"):
            aligned_file = align_stem_to_main(
                stem["file"], stem["role"], stem.get("analysis"),
                main_bpm=master_bpm_ref, main_key=master_key_ref, main_duration=main_dur_actual
            )
            if aligned_file != stem["file"]:
                stem["file"] = aligned_file
                stem["aligned"] = True

    # ─── Phase 1e: Multi-Point Ear-Candy, Foley & Sample-Chop Bus (Pillar 1) ─
    if main_dur_actual >= 45 and any(s["role"] in ("accent", "riser", "foley") for s in generated_stems):
        log("")
        log("PHASE 1e: EAR-CANDY, DOPPLER FOLEY & SAMPLE-CHOP BUS")
        log("-" * 60)
        ear_candy_path = build_ear_candy_bus(
            generated_stems, separated_demucs, transition_grid, main_stem_obj["file"], stems_dir
        )
        if ear_candy_path and os.path.isfile(ear_candy_path):
            generated_stems.append({
                "role": "ear_candy_bus",
                "model": "hybrid-sfx-bus",
                "file": ear_candy_path,
                "generation_time": 0,
                "cost": {"cost_usd": 0, "credits": 0},
            })

    # ─── Pass 2: Deterministic Spectral & RMS Mix Engineer ($0.00) ───────
    log("")
    log("PHASE 2: MIXING (Deterministic Spectral/RMS Gain-Staging)")
    log("-" * 60)
    report_progress("mixing")

    stems_analysis_data = {}
    for stem in generated_stems:
        if stem.get("analysis"):
            stems_analysis_data[stem["role"]] = stem["analysis"]

    mix_overrides = None
    if stems_analysis_data and len(stems_analysis_data) >= 2:
        mix_overrides = compute_deterministic_mix_overrides(stems_analysis_data)

    if mix_overrides:
        for stem in generated_stems:
            override = mix_overrides.get(stem["role"])
            if override and isinstance(override, dict):
                if "volume" in override:
                    stem["mix_volume_override"] = float(override["volume"])
                if "pan" in override:
                    stem["mix_pan_override"] = float(override["pan"])
                if "eq" in override and override["eq"] != "none":
                    stem["mix_eq_override"] = override["eq"]
        log(f"  🎚️ Applied deterministic RMS/spectral gain-staging to {len(mix_overrides)} supporting beds ($0.00)")
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
    # Resolve metadata fields
    resolved_title = args.title or (production_plan.get("title") if production_plan else None) or args.prompt[:60]
    resolved_artist = args.artist or (active_profile.get("name") if active_profile else "VØIDRIDE")
    resolved_album = args.album or (album_context.get("brief") if album_context else None)
    resolved_genre = args.genre or (production_plan.get("genre") if production_plan else None)
    resolved_track_num = args.track_number or (album_context.get("track_number") if album_context else None)
    resolved_total_tracks = args.total_tracks or (album_context.get("total_tracks") if album_context else None)

    master_result = master_audio(
        mix_path, session_dir, skip_master=args.skip_master,
        target=args.target, track_title=resolved_title,
        artist=resolved_artist, album=resolved_album, genre=resolved_genre,
        track_num=resolved_track_num, total_tracks=resolved_total_tracks,
    )
    master_primary = master_result["primary"]
    master_files = master_result["files"]

    # Step 3b: Reference-based mastering (Matchering) — if reference tracks available
    ref_result = matchering_master(
        mix_path, session_dir, track_title=resolved_title,
        artist=resolved_artist, album=resolved_album, genre=resolved_genre,
        track_num=resolved_track_num, total_tracks=resolved_total_tracks,
    )
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
                                     track_title=resolved_title)

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

    # ─── Pass 4: Acoustic QC Verdict (skip redundant LLM call in batch --no-deliver mode) ───
    plan_genre = production_plan.get("genre", "") if production_plan else ""
    qc_verdict = None if args.no_deliver else quality_control(qc_report, genre=plan_genre, profile=active_profile)
    if qc_verdict:
        qc_report["k3_verdict"] = qc_verdict.get("verdict", "unknown")
        qc_report["k3_score"] = qc_verdict.get("score", 0)
        qc_report["k3_issues"] = qc_verdict.get("issues", [])
        qc_report["k3_suggestions"] = qc_verdict.get("suggestions", [])
    else:
        qc_report["k3_verdict"] = "pass" if qc_report.get("overall_pass") else "warn"
        qc_report["k3_score"] = 90 if qc_report.get("overall_pass") else 72

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

