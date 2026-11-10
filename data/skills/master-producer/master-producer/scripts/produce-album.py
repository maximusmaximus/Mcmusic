#!/usr/bin/env python3
"""
produce-album.py — Produce varied album tracks with batch delivery + batch tracking.

Telegram flow:
  1. One message: "Generating N tracks..."
  2. Updates that message with track progress
  3. All audio files sent at the end as a batch
  4. Final message: tracklist + total cost

Batch tracking:
  Saves production batch to profile catalog:
    profiles/<slug>/batches/<batch_id>.json

Usage:
    python3 produce-album.py --brief "McNightrideTM" --tracks 5
    python3 produce-album.py --brief "dark EP" --tracks 5 --duration 180 --vocals-pct 20
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCER = os.path.join(SCRIPT_DIR, "master-producer.py")
PROFILES_DIR = os.environ.get("HERMES_HOME", "/opt/data") + "/music/profiles"


def log(msg):
    print(f"[produce-album] {msg}", flush=True)


# ─── Telegram ───────────────────────────────────────────────────────────

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def _auto_detect_chat_id():
    global _CHAT_ID
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
            _CHAT_ID = str(latest[1])
    except Exception:
        pass


def tg_send(text):
    if not _BOT_TOKEN or not _CHAT_ID:
        return None
    try:
        payload = json.dumps({"chat_id": _CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
            data=payload, headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read()).get("result", {}).get("message_id")
    except Exception:
        return None


def tg_edit(msg_id, text):
    if not _BOT_TOKEN or not _CHAT_ID or not msg_id:
        return
    try:
        payload = json.dumps({
            "chat_id": _CHAT_ID, "message_id": msg_id,
            "text": text, "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/editMessageText",
            data=payload, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


def tg_send_audio(file_path, title="", performer=""):
    if not _BOT_TOKEN or not _CHAT_ID:
        return False
    if not os.path.isfile(file_path):
        return False
    try:
        boundary = "----HermesAlbum"
        body = bytearray()
        for name, val in [("chat_id", _CHAT_ID), ("title", title), ("performer", performer)]:
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n".encode())
        fname = os.path.basename(file_path)
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{fname}\"\r\nContent-Type: audio/mpeg\r\n\r\n".encode())
        with open(file_path, "rb") as f:
            body.extend(f.read())
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendAudio",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        log(f"  ⚠️ Audio send failed: {e}")
        return False


# ─── Variation templates ────────────────────────────────────────────────

VARIATION_TEMPLATES = [
    {"direction": "heavy california bass opener",
     "rules": ["Massive California 808 sub-bass with aggressive pitch glide curves and lowrider low-end saturation",
               "Punchy acoustic-sampled transient kick drum with sharp attack and sidechain ducking",
               "Crisp snap snares with wide stereo throws and rolling West Coast syncopated bounce",
               "Hyperspatial 3D soundstage with holographic delay throws and centered mono sub authority"]},
    {"direction": "melodic nightride west coast groove",
     "rules": ["Melancholic detuned analog brass and minor-pentatonic sine plucks leading the melody",
               "Sliding California 808 sub-bass groove with syncopated rhythmic bounce",
               "Atmospheric nocturnal cruising aura with stereo haas reverb throws and wide spectral pads",
               "Smooth buildup descending into a heavy, resonant West Coast sub drop"]},
    {"direction": "west coast bounce & hyperspatial synth lead",
     "rules": ["Syncopated West Coast bounce rhythm with rolling triplet hi-hats and snapping claps",
               "Lead detuned synth melody over deep reese and 808 bass foundations",
               "Punchy transient kick drum driving the dynamic groove",
               "Wide binaural hyperspatial imaging on ambient textures and delays"]},
    {"direction": "tempo shift california nightride banger",
     "rules": ["Different BPM (tempo shift ±10-15 BPM) exploring faster or slower nightride cruising energy",
               "Tension-building filtered buildup with rising nocturnal pads, sub swells, and spatial risers",
               "Devastating drop with elongated California 808 glide slides and hard transient slap",
               "Dynamic contrast between atmospheric verse and crushing drop"]},
    {"direction": "atmospheric hyperspatial nightride closer",
     "rules": ["Cinematic nocturnal atmosphere with haunting spectral witch house pads and 3D spatial field",
               "Deep melodic minor chord progressions on detuned analog synths",
               "Heavy sustained California sub-bass foundation with expressive pitch portamento",
               "Smooth evolving soundscape building to a final thundering sub-bass climax"]},
    {"direction": "experimental nightride bass wildcard",
     "rules": ["Unexpected sonic textures layered with dominant California sub-bass slides",
               "Detuned sine plucks and chopped vocal textures in wide stereo delay space",
               "Bass drops that hit with punchy acoustic transient definition",
               "Menacing, hypnotic nocturnal cruising aura with hyperspatial depth"]},
    {"direction": "sub-heavy california melodic groove",
     "rules": ["Deep sub-bass frequencies commanding the low end (40-55Hz fundamental)",
               "Melodic synth hooks playing dark, silky minor-pentatonic lines",
               "Crisp snap snares and tight syncopated West Coast percussion groove",
               "Uncompromised volume balance — hard-hitting yet silky, controlled, and expansive"]},
]


def load_active_profile():
    active_file = os.path.join(PROFILES_DIR, ".active")
    if not os.path.isfile(active_file):
        return None, None
    try:
        with open(active_file) as f:
            slug = f.read().strip()
        with open(os.path.join(PROFILES_DIR, slug, "profile.json")) as f:
            return json.load(f), slug
    except Exception:
        return None, None


def save_batch(slug, batch_data):
    """Save production batch to profile's batches directory."""
    batches_dir = os.path.join(PROFILES_DIR, slug, "batches")
    os.makedirs(batches_dir, exist_ok=True)
    batch_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    batch_path = os.path.join(batches_dir, f"{batch_id}.json")
    with open(batch_path, "w") as f:
        json.dump(batch_data, f, indent=2)
    log(f"  📁 Batch saved: batches/{batch_id}.json")
    return batch_path


def interpret_track_from_cover_and_theme(album_name, album_theme, cover_visual, track_title, track_num, total_tracks, sonic_dna=None):
    """
    Derive a bespoke musical interpretation of a song from:
      1. The Album Cover Art (lighting, materials, motifs, setting)
      2. The Album Theme & Sonic DNA (subgenre, tempo, key, mood)
      3. The Track Title (the song's distinct narrative hook)
    Uses Venice AI (kimi-k3 with fallback to llama-3.3-70b) and rich deterministic fallbacks.
    """
    api_key = os.environ.get("VENICE_API_KEY", "")

    # Domain fallbacks tailored for BASEMENT BAY
    base_fallbacks = {
        "TILE FEVER": {
            "direction": "Subterranean wet tile reverb and feverish syncopated 808 slides with sterile high-frequency medical clicks",
            "rules": [
                "Massive 808 sub-bass with aggressive pitch glide curves sliding between Eb1 and Bb0",
                "Sterile transient snap snares with cold ceramic plate reverb reflections matching hospital basement tiles",
                "Detuned minor sine plucks creating a dizzying, feverish medical melody in Eb minor",
                "Foley layer of flickering fluorescent tube voltage hum and hydraulic ambulance idling",
                "Dynamic contrast between claustrophobic verse and wide stereo sub drops"
            ],
            "bpm": 132,
            "key": "Ebm",
            "stems": {
                "main": "Clinical witch house trap, 132 BPM, Eb minor. Hypnotic sterile dread. Glazed tile reverberation, aggressive West Coast 808 sub-bass slides, punchy acoustic transient kicks, crisp snap snares with cold gated reflections. Detuned sine plucks, high-voltage fluorescent buzz, reese undertones, menacing nocturnal cruising groove.",
                "texture": "Cold ceramic tile acoustic space, subtle fluorescent light hum, distant echoing hospital basement drone, 132 BPM, key of Eb minor, dark ambient pad.",
                "accent": "Sterile medical snap click into heavy subterranean sub drop impact with metallic tile ring, crisp transient."
            }
        },
        "CYAN DRIP": {
            "direction": "Gated cyan neon synth bleeds and hypnotic dripping foley percussion echoing across cold concrete",
            "rules": [
                "Deep sliding West Coast 808 sub-bass with rounded saturation and long decay",
                "Hypnotic foley percussion incorporating rhythmic water drips echoing in an underground bay",
                "Cyan-lit analog synthesizer stabs with stereo chorus and haas delay bleed",
                "Subtle pitch-dropped vocal breath textures echoing across the wet floor",
                "Silky nocturnal groove balancing cold precision with heavy low-end authority"
            ],
            "bpm": 130,
            "key": "Ebm",
            "stems": {
                "main": "Neon-noir medical phonk, 130 BPM, Eb minor. Cyan tube light aesthetic. Subterranean water drips echoing off wet concrete, deep sliding West Coast 808 bass, punchy tight kicks, syncopated trap hi-hats. Gated cyan synth stabs, detuned sine plucks, sterile hypnotic atmosphere.",
                "texture": "Rhythmic water drips echoing on wet concrete in an underground garage, faint cyan neon electrical buzz, dark spacious pad in Eb minor, 130 BPM.",
                "accent": "Single resonant cyan water drop falling on concrete with long sterile reverb tail and sub sweep."
            }
        },
        "VENT STEAM": {
            "direction": "Pressurized industrial exhaust, filtered white noise steam sweeps, and thundering sub-bass impacts",
            "rules": [
                "Devastating 808 sub drops hitting at 45Hz with long portamento glide releases",
                "Percussive white-noise bursts and pressurized steam hiss used as syncopated risers",
                "Haunting spectral witch house pads evoking cold mist rolling across concrete",
                "Heavy acoustic transient kicks sidechained aggressively to the sub-bass",
                "Menacing, relentless industrial cruising energy with sudden pressure drop mutes"
            ],
            "bpm": 134,
            "key": "Ebm",
            "stems": {
                "main": "Dark nightride trap and industrial witch house, 134 BPM, Eb minor. Heavy steam pouring from underground vents. Devastating West Coast 808 sub-bass slides, punchy transient kicks, crisp snap snares. White noise steam hiss risers, spectral cold pads, reese bass growl, atmospheric pressure releases.",
                "texture": "Continuous atmospheric steam hiss escaping industrial pipe vents, deep low-frequency ventilation rumble, Eb minor nocturnal drone, 134 BPM.",
                "accent": "High-pressure steam release burst with metallic pipe valve clank and sudden stereo sub drop impact."
            }
        },
        "CODE BLUE": {
            "direction": "Urgent cardiac telemetry arpeggios, defibrillator sub-drop surge, and cold clinical emergency pulse",
            "rules": [
                "Rapid cardiac monitor telemetry beeps integrated directly into syncopated percussion",
                "High-energy half-time trap bounce driven by punchy transient kicks and crisp snap snares",
                "Aggressive sliding 808 sub-bass with sudden defibrillator style transient charge-up sweeps",
                "Urgent detuned arpeggiated synths cutting through dense witch house reverb haze",
                "Tension-building filtered builds exploding into crushing, high-octane sub drops"
            ],
            "bpm": 136,
            "key": "Ebm",
            "stems": {
                "main": "High-intensity clinical medical phonk and nightride trap, 136 BPM, Eb minor. Heart-monitor telemetry blips as syncopated percussion, defibrillator sub-bass charge sweeps, aggressive sliding 808s, punchy transient acoustic kicks, urgent detuned arpeggios, sterile emergency dread.",
                "texture": "Rhythmic hospital telemetry heart monitor blips, soft sterile ventilation hum, tense low Eb minor drone, 136 BPM.",
                "accent": "Defibrillator charge-up riser into flatline tone and massive crushing 808 bass impact."
            }
        },
        "QUIET SIREN": {
            "direction": "Distant pitched-down emergency wails filtered through concrete, doppler synths, and haunting spectral outro",
            "rules": [
                "Distant, pitched-down emergency siren harmonics filtered through subterranean concrete walls",
                "Hypnotic half-speed nightride cruiser groove with deep 808 sub portamento",
                "Ethereal witch house choral pads and detuned analog strings dissolving into mist",
                "Razor-sharp katana transient texture echoing in the breakdown",
                "Expansive, lingering outro fading into cold nocturnal silence and pale moonlight"
            ],
            "bpm": 128,
            "key": "Ebm",
            "stems": {
                "main": "Cinematic nightride witch house trap, 128 BPM, Eb minor. Distant pitched-down emergency siren echoes filtered through hospital basement concrete, slow devastating 808 sub-bass slides, punchy kicks, ethereal spectral choir pads, razor transient accents, melancholic nocturnal closure.",
                "texture": "Distant muffled emergency siren echoing from above ground through thick concrete, soft rain and mist on metal, Eb minor pad, 128 BPM.",
                "accent": "Razor-sharp metallic katana draw resonance transitioning into a deep sub-bass fade and filtered siren doppler."
            }
        }
    }

    norm_title = track_title.strip().upper()
    fallback = base_fallbacks.get(norm_title)
    default_bpms = [134, 128, 140, 124, 132]
    default_keys = ["Dm", "Fm", "Cm", "Dm", "Fm"]
    fb_bpm = default_bpms[(track_num - 1) % len(default_bpms)]
    fb_key = default_keys[(track_num - 1) % len(default_keys)]
    if not fallback:
        fallback = {
            "direction": (
                f"Hyperspatial West Coast nightride bass and witch house gravity translating '{track_title}' "
                f"into relentless California 808 sub-bass glides, predatory Reese undertones, punchy transient kicks, "
                f"and detuned analog brass/sine hooks ({fb_bpm} BPM, {fb_key})"
            ),
            "rules": [
                f"Rule 1: Continuous California 808 sub-bass dominance ({fb_bpm} BPM, {fb_key}) with slow predatory pitch portamento glides and centered low-end authority",
                "Rule 2: Punchy acoustic-sampled transient kicks, crisp snap snares thrown wide into metallic impulse reverb, and rolling syncopated West Coast hi-hats",
                "Rule 3: Melancholic detuned analog brass stabs and dark minor-pentatonic sine plucks carrying a hypnotic nocturnal cruising melody",
                "Rule 4: Spectral pitched-down witch house choir pads and holographic 3D binaural delay throws supporting (never overpowering) the 808 sub",
                f"Rule 5: Smooth psychological buildup dropping early into full-force West Coast bass weight embodying '{track_title}' — no dead air, no weak/thin leads"
            ],
            "bpm": fb_bpm,
            "key": fb_key,
            "stems": {
                "main": (
                    f"Hyperspatial nightride bass with witch house gravity, {fb_bpm} BPM, {fb_key}. "
                    f"California bass and heavy West Coast bass mixed with melodic nightride vibes, nocturnal cruising atmosphere. "
                    f"Massive continuous sub-bass dominance: gliding West Coast 808 slides with slow predatory pitch portamento, "
                    f"always centered and thundering. Punchy acoustic-sampled transient kicks, crisp snap snares thrown wide into "
                    f"metallic impulse reverb, rolling syncopated hi-hats. Detuned analog brass stabs and melancholic sine plucks "
                    f"trace dark minor-pentatonic hooks over predatory Reese bass growls and spectral pitched-down choir pads. "
                    f"Hyperspatial 3D binaural delay throws surround the listener while the 808 stays dominant. "
                    f"NO four-on-the-floor, NO EDM festival drops, NO cheerful G-funk, NO static loops, NO silence drops."
                ),
                "texture": (
                    f"Dark witch house atmospheric texture, {fb_bpm} BPM, {fb_key}: spectral detuned analog pads, "
                    f"cold metallic reverb haze, subtle sub swells, nocturnal industrial stillness. Supporting role only, no drums."
                )[:445],
                "accent": (
                    f"Warm rounded sub-bass swell impact in {fb_key} ({fb_bpm} BPM): soft low-passed resonance "
                    f"with lush dark cavernous plate reverb tail, smooth attack, no harsh transients."
                )[:445],
                "riser": (
                    f"Silky dark cyber-noir filter sweep in {fb_key} ({fb_bpm} BPM): gradual spectral pitch-bend swell "
                    f"and warm reversed reverb wash with smooth high-end roll-off, no harsh noise or sudden cutoff."
                )[:445],
                "foley": (
                    f"Subtle low-passed nocturnal ambient texture for '{track_title}': soft distant rain-slicked highway "
                    f"wash, warm analog hum, and deep velvet stereo reverb reflections, smooth and understated."
                )[:445],
                "atmosphere": (
                    f"Deep sub-bass drone and cavernous witch house ambient wash in {fb_key} at {fb_bpm} BPM: "
                    f"distant nocturnal rain haze, stereo depth, warm analog darkness. No drums, no melody."
                )[:445],
                "spatial": (
                    f"Hyperspatial 3D audio layer, {fb_bpm} BPM, {fb_key}: wide binaural stereo panning sweeps, "
                    f"holographic ping-pong delay throws, ghostly spectral reflections orbiting the listener, no drums."
                )[:445]
            }
        }

    if not api_key:
        return fallback

    dna_str = json.dumps(sonic_dna, indent=2) if sonic_dna else "California West Coast nightride bass, witch house, dark nightride trap (122-144 BPM, Dm/Fm/Cm)"

    system_prompt = (
        "You are the Creative Director and Master Sound Designer for VØIDRIDE.\n"
        "Your task: Translate the visual album cover art and album theme into an auditory, "
        "compositional interpretation for the specific song title below while STRICTLY preserving the core VØIDRIDE sonic aesthetic.\n\n"
        f"ALBUM: {album_name}\n"
        f"ALBUM THEME & SONIC DNA: {album_theme}\n"
        f"VØIDRIDE SONIC DNA PROFILE: {dna_str}\n"
        f"COVER ART VISUAL SCENE: {cover_visual}\n"
        f"TRACK {track_num} OF {total_tracks} TITLE: {track_title}\n\n"
        "MANDATORY VØIDRIDE AESTHETIC GUARDRAILS (NEVER VIOLATE):\n"
        "1. EVERY track (including Track 1 Opener and Track 5 Closer) MUST be a heavy California West Coast nightride bass / witch house track.\n"
        "2. BPM MUST be strictly between 122 and 144 BPM (NEVER drop below 120 BPM; slow 110 BPM tempos kill the West Coast trap bounce).\n"
        "3. KEY MUST be a dark minor key from: Dm, Fm, Cm, Ebm.\n"
        "4. CORE INSTRUMENTS (REQUIRED ON ALL TRACKS): Dominant continuous California 808 sub-bass with predatory pitch portamento slides, coiling Reese bass undertones, punchy acoustic-sampled transient kicks, crisp snap snares thrown wide into metallic reverb, rolling syncopated hi-hats, detuned analog brass stabs, melancholic minor-pentatonic sine plucks, and pitched-down spectral witch house choir pads.\n"
        "5. FORBIDDEN TROPES (STRICT BAN):\n"
        "   - NEVER use organic/woodland foley (NO 'snapping twigs', NO 'creaking wooden beams', NO acoustic folk/rock percussion).\n"
        "   - NEVER interpret words like 'HELIUM', 'BLEED', 'COLD', or 'SILENCE' as weak, thin, deflating, or drumless audio (NO 'helium-thin whistles', NO 'deflating bass', NO 'airy drumless verses', NO 'slow-burn ambient closer').\n"
        "   - Track 1 and Track 5 MUST hit with the same heavy sub-bass authority and nocturnal cruising groove as Tracks 2, 3, and 4.\n"
        "6. SMOOTH SPECIAL EFFECTS RULE (CRITICAL FOR VØIDRIDE):\n"
        "   - Any special effects (`accent_prompt`, `riser_prompt`, `foley_prompt`, or transition FX in `main_prompt`) MUST be velvet-smooth, warm, low-pass filtered on the high end, and drenched in lush dark reverb with gradual fade-ins and long decaying tails.\n"
        "   - NEVER ask for jarring, harsh, piercing, clicky, clanky, or abrupt sound effects that poke out of the mix.\n"
        "7. MAIN PROMPT FORMULA: `main_prompt` MUST begin with the genre, BPM, key, and the exact anchor phrase: 'California bass and heavy West Coast bass mixed with melodic nightride vibes — massive continuous sub-bass dominance, gliding West Coast 808 slides with slow predatory pitch portamento...'\n\n"
        "Return ONLY a valid JSON object (no markdown fences, no commentary):\n"
        "{\n"
        '  "direction": "One-sentence summary of how this track translates the visual cover into VØIDRIDE heavy nightride bass",\n'
        '  "rules": [\n'
        '    "Rule 1: Continuous California 808 sub-bass and predatory pitch glide behavior",\n'
        '    "Rule 2: Punchy acoustic transient kicks, crisp snap snares with metallic reverb throws, and rolling syncopated hi-hats",\n'
        '    "Rule 3: Detuned analog brass stabs, melancholic minor-pentatonic sine plucks, and Reese bass growls",\n'
        '    "Rule 4: Spectral witch house choir pads and smooth reverb-washed nocturnal atmosphere supporting the sub-bass",\n'
        '    "Rule 5: Relentless nocturnal cruising groove with seamless, non-jarring special effects embodying the song title"\n'
        '  ],\n'
        f'  "bpm": {fb_bpm},\n'
        f'  "key": "{fb_key}",\n'
        '  "main_prompt": "Comprehensive main prompt for elevenlabs-music (90-150 words) starting with genre, BPM, key, and California bass / heavy West Coast bass mixed with melodic nightride vibes",\n'
        '  "texture_prompt": "Prompt for stable-audio-25 (UNDER 450 CHARS) describing dark witch house spectral pad & atmospheric texture bed with key and BPM (no drums, supporting role)",\n'
        '  "accent_prompt": "Prompt for elevenlabs-sound-effects-v2 (UNDER 450 CHARS) describing warm, rounded sub-bass swell impact with soft low-passed resonance and lush dark reverb tail (no harsh clicks)",\n'
        '  "riser_prompt": "Prompt for elevenlabs-sound-effects-v2 (UNDER 450 CHARS) describing silky pre-drop filter sweep with warm reverse reverb swell and gradual crescendo (no harsh noise or sudden cutoff)",\n'
        '  "foley_prompt": "Prompt for elevenlabs-sound-effects-v2 (UNDER 450 CHARS) describing a subtle, warm low-passed cyber-noir ambient wash inspired by the cover art scene (smooth and deeply recessed, no sharp clicks)",\n'
        '  "atmosphere_prompt": "Prompt for stable-audio-25 (UNDER 450 CHARS) describing deep cavernous sub-bass ambient drone and nocturnal rain haze in the track key and BPM (no drums)",\n'
        '  "spatial_prompt": "Prompt for stable-audio-25 (UNDER 450 CHARS) describing hyperspatial 3D audio layer, wide binaural stereo panning, and holographic delays with key and BPM"\n'
        "}"
    )

    _sr_chain = ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"]
    for _sd in [os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scripts")), "/opt/data/scripts"]:
        if os.path.isdir(_sd) and _sd not in sys.path:
            sys.path.insert(0, _sd)
    try:
        import model_registry as _mr
        _sr_chain = _mr.get_role_chain("llm.showrunner", _sr_chain)
    except Exception:
        pass

    for model_name in _sr_chain:
        try:
            v_params = {"strip_thinking_response": True}
            if "qwen" in model_name:
                v_params["disable_thinking"] = True
            req_body = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Generate dynamic VØIDRIDE hit-record interpretation for Track {track_num}: '{track_title}' based on the cover art and theme."}
                ],
                "temperature": 0.55,
                "max_tokens": 2800,
                "venice_parameters": v_params,
            }
            payload = json.dumps(req_body).encode('utf-8')

            req = urllib.request.Request(
                "https://api.venice.ai/api/v1/chat/completions",
                data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                msg_obj = data.get("choices", [{}])[0].get("message", {}) or {}
                raw = (msg_obj.get("content") or msg_obj.get("reasoning_content") or "").strip()
                if "<think>" in raw:
                    raw = raw.split("</think>")[-1].strip()
                if "```" in raw:
                    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
                    if m:
                        raw = m.group(1)
                    else:
                        raw = re.sub(r'```(?:json)?\s*', '', raw)
                        raw = re.sub(r'\s*```', '', raw)

                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    # Brace-depth fallback extraction
                    parsed = None
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
                                try:
                                    cand = json.loads(raw[start_pos:pos + 1])
                                    if "direction" in cand or "main_prompt" in cand:
                                        parsed = cand
                                except json.JSONDecodeError:
                                    pass
                                start_pos = None
                    if not parsed:
                        raise ValueError("No valid JSON object in response")

                if parsed.get("direction") and parsed.get("rules") and len(parsed["rules"]) >= 3:
                    # Clamp BPM strictly into VØIDRIDE nightride range (122-144 BPM)
                    try:
                        raw_bpm = int(parsed.get("bpm", fb_bpm))
                    except Exception:
                        raw_bpm = fb_bpm
                    if raw_bpm < 120 or raw_bpm > 148:
                        raw_bpm = fb_bpm
                    parsed["bpm"] = raw_bpm

                    stems = parsed.get("stems", {})
                    if not stems:
                        stems = {
                            "main": parsed.get("main_prompt", fallback["stems"]["main"]),
                            "texture": parsed.get("texture_prompt", fallback["stems"]["texture"]),
                            "accent": parsed.get("accent_prompt", fallback["stems"]["accent"]),
                            "riser": parsed.get("riser_prompt", fallback["stems"]["riser"]),
                            "foley": parsed.get("foley_prompt", fallback["stems"]["foley"]),
                            "atmosphere": parsed.get("atmosphere_prompt", fallback["stems"]["atmosphere"]),
                            "spatial": parsed.get("spatial_prompt", fallback["stems"]["spatial"])
                        }
                    else:
                        for k in ("main", "texture", "accent", "riser", "foley", "atmosphere", "spatial"):
                            if not stems.get(k):
                                stems[k] = parsed.get(f"{k}_prompt") or fallback["stems"][k]
                    # Ensure main prompt contains the mandatory California West Coast nightride bass anchor
                    if "california bass" not in stems.get("main", "").lower():
                        stems["main"] = (
                            f"California bass and heavy West Coast bass mixed with melodic nightride vibes, "
                            f"massive continuous sub-bass dominance, gliding West Coast 808 slides with slow predatory pitch portamento. "
                            f"{stems.get('main', '')}"
                        )
                    for k in ("texture", "accent", "riser", "foley", "atmosphere", "spatial"):
                        if len(stems.get(k, "")) > 450:
                            stems[k] = stems[k][:445]
                    parsed["stems"] = stems
                    return parsed
        except Exception as e:
            log(f"  ⚠️ Cover-to-song inference with {model_name} failed: {e}")
            continue

    return fallback


GROOVE_ARCHETYPES = [
    {
        "slot": 1, "bpm": 138, "key": "Dm",
        "archetype": "Lead Single West Coast Bounce",
        "brief": "Immediate within-10s earworm synth/pluck hook, infectious syncopated California 808 lowrider bounce, crisp snap claps, high-replay chorus drop",
    },
    {
        "slot": 2, "bpm": 150, "key": "Cm",
        "archetype": "High-Octane Drift-Phonk Club Weapon",
        "brief": "Aggressive nocturnal metallic bell/brass hook motif, driving double-time hi-hat velocity, predatory 808 portamento slides, explosive climax second drop",
    },
    {
        "slot": 3, "bpm": 126, "key": "Fm",
        "archetype": "Hypnotic Halftime Reese & Witch-House Roller",
        "brief": "Spacious halftime pocket, coiling Reese bass growl trading phrases with haunting spectral vocal/synth lead motif, deep cavernous tension bridge",
    },
    {
        "slot": 4, "bpm": 134, "key": "Gm",
        "archetype": "Minimalist Negative-Space Sub-Bounce Single",
        "brief": "Surgical pocket percussion, bold rhythmic pauses where gliding West Coast 808 sub commands the room, catchy call-and-response minor pluck hook",
    },
    {
        "slot": 5, "bpm": 124, "key": "Ebm",
        "archetype": "Extended Widescreen Darkwave-Trap Anthem Closer",
        "brief": "Emotional minor chord progression, soaring detuned analog lead melody, stripped atmospheric middle bridge, towering octave-lifted finale drop",
    },
]


def plan_album_showrunner(album_name, album_theme, cover_visual, track_names, total_tracks, track_durations, sonic_dna=None):
    """Single-Pass Album Showrunner: plans all N tracks in ONE cohesive LLM call ($0.005 on qwen-3-7-plus),
    assigning contrasting BPM pockets, distinct minor keys, named foreground earworm hooks, and time-stamped
    section-scripted prompts for elevenlabs-music-v2-5!
    Returns dict {track_num (1..N): plan_dict} or {} on failure.
    """
    api_key = os.environ.get("VENICE_API_KEY", "")
    if not api_key:
        return {}

    slots_desc = []
    for idx in range(total_tracks):
        t_num = idx + 1
        t_title = track_names[idx].strip().upper() if idx < len(track_names) and track_names[idx] else f"TRACK {t_num}"
        arch = GROOVE_ARCHETYPES[idx % len(GROOVE_ARCHETYPES)]
        dur_s = track_durations[idx] if idx < len(track_durations) else 175
        m_end = f"{dur_s // 60}:{dur_s % 60:02d}"
        slots_desc.append(
            f"- Track {t_num}: title=\"{t_title}\", duration={dur_s}s ({m_end}), target_bpm={arch['bpm']}, "
            f"target_key=\"{arch['key']}\", archetype=\"{arch['archetype']}\" ({arch['brief']})"
        )

    dna_summary = json.dumps(sonic_dna, indent=2) if sonic_dna else "VØIDRIDE: California 808 nightride bass, witch house & dark trap"
    sys_prompt = (
        "You are the Executive Hit-Record Showrunner for VØIDRIDE.\n"
        "Plan an entire cohesive yet dynamically varied EP in ONE JSON response.\n\n"
        f"ALBUM TITLE: {album_name}\n"
        f"ALBUM THEME: {album_theme}\n"
        f"COVER ART VISUAL SCENE: {cover_visual}\n"
        f"VØIDRIDE SONIC DNA: {dna_summary}\n\n"
        "TRACK SLOTS TO DESIGN (MANDATORY CONTRAST — NO TWO TRACKS MAY SHARE THE SAME BPM OR HOOK INSTRUMENT):\n"
        + "\n".join(slots_desc)
        + "\n\nHIT-SONG ARRANGEMENT RULES FOR EVERY `main_prompt` (160–280 words each, for `elevenlabs-music-v2-5`):\n"
        "1. Start with exact subgenre, BPM, minor key, and VØIDRIDE West Coast 808 + nocturnal nightride identity.\n"
        "2. Define ONE unmistakable, singable FOREGROUND HOOK MOTIF (specific lead synth/pluck/brass/bell/chopped-vocal timbre + rhythmic phrasing) introduced within the first 10 seconds.\n"
        "3. Include explicit time-stamped dynamic section cues scaled to the track's duration:\n"
        "   [0:00-0:14 Haunted Hook Tease, filtered motif, sub held back] -> [0:14-0:16 Pre-Drop Breath] -> "
        "[0:16-0:58 Drop 1: Explosive California 808 glides + punchy transient kicks + full signature hook] -> "
        "[0:58-1:30 Verse Switch-Up: syncopated counter-groove & Reese growls] -> "
        "[1:30-1:56 Tension Bridge: drums & sub stripped back, atmospheric suspense] -> "
        "[1:56-2:36 Climax Drop 2: octave-lifted hook + double-time hat energy + heaviest 808 glides] -> "
        "[Outro: sleek nocturnal resolve]. (Extend timestamps proportionally for Track 5's 3:35 closer arc!)\n"
        "4. All special effects / transitions MUST be smooth, warm, low-passed, and reverb-washed — NEVER harsh, clicky, or jarring. NEVER use woodland/organic foley.\n"
        "5. Also write a bespoke `foley_prompt` (<380 chars) for `elevenlabs-sound-effects-v2` capturing subtle warm cyber-noir scene air from the cover visual.\n\n"
        "Return ONLY valid JSON matching this exact structure (no markdown fences):\n"
        "{\n"
        '  "tracks": [\n'
        "    {\n"
        '      "track_number": 1,\n'
        '      "title": "EXACT TRACK TITLE",\n'
        '      "genre": "West Coast Nightride Trap / Witch House Bass",\n'
        '      "bpm": 138,\n'
        '      "key": "Dm",\n'
        '      "hook_motif": "Short description of signature earworm lead hook",\n'
        '      "direction": "One-sentence sonic direction",\n'
        '      "rules": ["Rule 1", "Rule 2", "Rule 3"],\n'
        '      "main_prompt": "Full 160-280 word section-scripted prompt for elevenlabs-music-v2-5...",\n'
        '      "foley_prompt": "Warm low-passed cyber-noir ambient texture (<380 chars)..."\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    _sr_chain = ["deepseek-v4-flash", "qwen-3-7-plus", "qwen-3-8-flash"]
    for _sd in [os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scripts")), "/opt/data/scripts"]:
        if os.path.isdir(_sd) and _sd not in sys.path:
            sys.path.insert(0, _sd)
    try:
        import model_registry as _mr
        _sr_chain = _mr.get_role_chain("llm.showrunner", _sr_chain)
    except Exception:
        pass

    for model_name in _sr_chain:
        try:
            v_params = {"strip_thinking_response": True}
            if "qwen" in model_name:
                v_params["disable_thinking"] = True
            req_body = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Design all {total_tracks} contrasting hit tracks for '{album_name}' now."},
                ],
                "temperature": 0.6,
                "max_tokens": 5500,
                "venice_parameters": v_params,
            }
            req = urllib.request.Request(
                "https://api.venice.ai/api/v1/chat/completions",
                data=json.dumps(req_body).encode("utf-8"),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=95) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            msg_obj = data.get("choices", [{}])[0].get("message", {}) or {}
            raw = (msg_obj.get("content") or msg_obj.get("reasoning_content") or "").strip()
            if "<think>" in raw:
                raw = raw.split("</think>")[-1].strip()
            if "```" in raw:
                m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
                raw = m.group(1) if m else re.sub(r"```(?:json)?|```", "", raw).strip()

            parsed = json.loads(raw)
            tracks_arr = parsed.get("tracks", [])
            if not isinstance(tracks_arr, list) or len(tracks_arr) < total_tracks:
                raise ValueError(f"Expected {total_tracks} tracks, got {len(tracks_arr) if isinstance(tracks_arr, list) else 0}")

            plans_by_num = {}
            for idx, item in enumerate(tracks_arr[:total_tracks]):
                t_num = int(item.get("track_number") or (idx + 1))
                arch = GROOVE_ARCHETYPES[idx % len(GROOVE_ARCHETYPES)]
                t_title = (
                    track_names[idx].strip().upper()
                    if idx < len(track_names) and track_names[idx]
                    else str(item.get("title", f"TRACK {t_num}")).strip().upper()
                )
                try:
                    bpm_val = int(item.get("bpm") or arch["bpm"])
                except Exception:
                    bpm_val = arch["bpm"]
                if bpm_val < 120 or bpm_val > 156:
                    bpm_val = arch["bpm"]
                key_val = str(item.get("key") or arch["key"]).strip()
                mp = str(item.get("main_prompt") or "").strip()
                if len(mp) < 120:
                    raise ValueError(f"Track {t_num} main_prompt too short ({len(mp)} chars)")
                if "california" not in mp.lower() and "west coast" not in mp.lower():
                    mp = (
                        f"Dynamic hit-arranged West Coast nightride trap & California 808 bass, {bpm_val} BPM, {key_val}. "
                        + mp
                    )
                fp = str(item.get("foley_prompt") or f"Subtle warm low-passed cyber-noir nocturnal highway wash and velvet reflections for {t_title}.")[:440]

                plans_by_num[t_num] = {
                    "title": t_title,
                    "genre": str(item.get("genre") or "Hyperspatial West Coast Nightride Bass"),
                    "bpm": bpm_val,
                    "key": key_val,
                    "energy": str(item.get("hook_motif") or item.get("direction") or arch["archetype"]),
                    "direction": str(item.get("direction") or f"{arch['archetype']}: {item.get('hook_motif', '')}"),
                    "rules": list(item.get("rules") or [arch["brief"]]),
                    "stems": {
                        "main": {
                            "model": "elevenlabs-music-v2-5",
                            "prompt": mp[:3900],
                            "instrumental": True,
                        },
                        "texture": {
                            "model": "demucs-harmonic-synth",
                            "prompt": f"Warm chord-locked analog chorus pad in {key_val} at {bpm_val} BPM for {t_title}.",
                        },
                        "atmosphere": {
                            "model": "demucs-harmonic-synth",
                            "prompt": f"Cavernous cyber-noir spectral reverb wash in {key_val} at {bpm_val} BPM for {t_title}.",
                        },
                        "spatial": {
                            "model": "demucs-harmonic-synth",
                            "prompt": f"Hyperspatial 3D binaural side-shimmer reflections in {key_val} at {bpm_val} BPM for {t_title}.",
                        },
                        "accent": {
                            "model": "voidride-sfx-vault",
                            "prompt": f"Warm rounded subterranean sub-bass impact swell for {t_title}.",
                        },
                        "riser": {
                            "model": "voidride-sfx-vault",
                            "prompt": f"Silky dark analog synth filter sweep into drop for {t_title}.",
                        },
                        "foley": {
                            "model": "elevenlabs-sound-effects-v2",
                            "prompt": fp,
                        },
                    },
                }

            log(f"  🎬 Showrunner planned all {len(plans_by_num)} contrasting hit tracks in 1 pass ({model_name})")
            return plans_by_num
        except Exception as e:
            log(f"  ⚠️ Showrunner pass on {model_name} failed ({e}) — trying next model...")
            continue

    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", required=True, help="Album concept")
    parser.add_argument("--tracks", type=int, default=5)
    parser.add_argument("--duration", type=int, default=175)
    parser.add_argument("--closer-duration", type=int, default=215, help="Extended closer duration for final track (Option 1B)")
    parser.add_argument("--mode", default=None, choices=["full", "sample", "samples", "full tracks"])
    parser.add_argument("--no-deliver", action="store_true", help="Skip Telegram delivery and status messages")
    parser.add_argument("--resume-tracks", type=int, default=0, help="Number of tracks already completed")
    parser.add_argument("--quality", default="quick", choices=["quick", "standard", "premium", "hyperspatial"])
    parser.add_argument("--target", default="streaming")
    parser.add_argument("--vocals-pct", type=int, default=0, help="Pct of tracks with vocals (0-100)")
    parser.add_argument("--track-names", nargs="*", default=None, help="Pre-defined track names")
    parser.add_argument("--album-name", default=None, help="Album name")
    parser.add_argument("--album-theme", default=None, help="Album theme / musical brief")
    parser.add_argument("--cover-visual", default=None, help="Album cover visual description")
    args = parser.parse_args()

    _auto_detect_chat_id()
    profile, slug = load_active_profile()
    profile_name = profile.get("name", "VØIDRIDE") if profile else "VØIDRIDE"
    track_names = [t.strip() for t in args.track_names] if args.track_names else []

    if args.mode in ["sample", "samples"]:
        is_sample = True
    elif args.mode in ["full", "full tracks"]:
        is_sample = False
    else:
        is_sample = args.duration <= 30
    mode = "samples" if is_sample else "full tracks"

    # Which tracks get vocals
    vocal_count = max(0, round(args.tracks * args.vocals_pct / 100))
    vocal_positions = set()
    if vocal_count > 0:
        step = args.tracks / vocal_count
        for i in range(vocal_count):
            vocal_positions.add(min(int(round(step * i + step / 2)), args.tracks - 1))

    # Option 1B Hit Duration Architecture:
    # Tracks 1..(N-1) run at punchy streaming-hit durations (170-178s -> $2.08 Venice <=180s bucket),
    # while Track N (Closer) runs as an extended 215s (3m35s -> $2.76 bucket) widescreen anthem!
    single_pockets = [174, 170, 178, 172]
    track_durations = []
    for idx in range(args.tracks):
        if is_sample:
            track_durations.append(args.duration)
        elif idx == args.tracks - 1 and args.tracks >= 2:
            track_durations.append(max(args.closer_duration, args.duration))
        elif args.duration <= 190:
            track_durations.append(single_pockets[idx % len(single_pockets)])
        else:
            track_durations.append(args.duration)

    dur_summary = (
        f"{args.tracks} × {args.duration}s samples"
        if is_sample
        else f"Option 1B ({args.tracks - 1} singles @ ~{args.duration}s + Closer @ {track_durations[-1]}s)"
    )
    log(f"📀 {args.brief} — {dur_summary}")

    progress_id = None
    if not args.no_deliver:
        progress_id = tg_send(f"⏳ *{args.brief}*\nGenerating {dur_summary}...")

    completed = []
    track_files = []
    total_cost = 0.0
    failed = 0
    track_times = []  # for ETA calculation
    avg_track_time = 0

    # Load any prior completed tracks if resuming
    if args.resume_tracks > 0 and os.path.exists("/tmp/completed_tracks.json"):
        try:
            with open("/tmp/completed_tracks.json") as cf:
                cdata = json.load(cf)
                completed = cdata.get("completed", [])
                total_cost = float(cdata.get("total_cost", 0.0))
                for ct in completed:
                    mp3 = ct.get("mp3_path") or ct.get("files", {}).get("mp3")
                    flac = ct.get("flac_path") or ct.get("files", {}).get("flac")
                    if mp3 and os.path.exists(mp3):
                        track_files.append((ct.get("title", f"Track {ct.get('track', len(track_files)+1)}"), mp3, flac or ""))
        except Exception:
            pass

    album_name = args.album_name or (args.brief.split(" - ")[0] if " - " in args.brief else args.brief[:30])
    album_theme = args.album_theme or args.brief
    cover_visual = args.cover_visual or ""

    def _track_est_cost(dur_sec):
        if is_sample:
            return 0.48
        # elevenlabs-music-v2-5 ($2.08 <=180s, $2.76 <=240s) + $0.02 bespoke foley + $0.00 Demucs harmonic beds & vault SFX
        return 2.10 if dur_sec <= 180 else (2.78 if dur_sec <= 240 else 3.45)

    def _query_venice_budget(start_idx):
        api_key = os.environ.get("VENICE_API_KEY", "")
        rem_durs = track_durations[start_idx:]
        next_cost = _track_est_cost(rem_durs[0]) if rem_durs else 2.10
        rem_total_cost = round(sum(_track_est_cost(d) for d in rem_durs), 2)
        avg_cost = round(rem_total_cost / max(len(rem_durs), 1), 2)
        if not api_key:
            return {"ok": False, "total_usd": 0.0, "cost_per_track": next_cost, "completable_tracks": len(rem_durs)}
        try:
            req = urllib.request.Request(
                "https://api.venice.ai/api/v1/api_keys/rate_limits",
                headers={"Authorization": f"Bearer {api_key}", "User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                bdata = json.loads(resp.read().decode("utf-8")).get("data", {}).get("balances", {})
            usd = float(bdata.get("USD", 0.0) or 0.0)
            diem = float(bdata.get("DIEM", 0.0) or 0.0)
            bundled = float(bdata.get("BUNDLED_CREDITS", 0.0) or 0.0)
            tot = usd + diem + bundled
            running = 0.0
            comp = 0
            for d in rem_durs:
                c = _track_est_cost(d)
                if running + c <= tot + 0.05:
                    running += c
                    comp += 1
                else:
                    break
            return {
                "ok": True,
                "usd": usd,
                "diem": diem,
                "total_usd": tot,
                "cost_per_track": next_cost,
                "avg_cost_per_track": avg_cost,
                "completable_tracks": comp,
                "needed_for_remaining": rem_total_cost,
                "shortfall": round(max(0.0, rem_total_cost - tot), 2),
            }
        except Exception:
            return {"ok": False, "total_usd": 0.0, "cost_per_track": next_cost, "completable_tracks": len(rem_durs)}

    # Single-Pass Album Showrunner: plan all tracks up front in 1 cohesive LLM call
    showrunner_plans = {}
    if not is_sample and (cover_visual or track_names or args.album_theme):
        showrunner_plans = plan_album_showrunner(
            album_name=album_name,
            album_theme=album_theme,
            cover_visual=cover_visual,
            track_names=track_names,
            total_tracks=args.tracks,
            track_durations=track_durations,
            sonic_dna=profile.get("sonic_dna") if profile else None,
        )

    for i in range(args.resume_tracks, args.tracks):
        track_num = i + 1
        has_vocals = i in vocal_positions
        this_duration = track_durations[i]

        # Determine track title if pre-defined
        predefined_title = None
        if i < len(track_names) and track_names[i] and not track_names[i].lower().startswith("track "):
            predefined_title = track_names[i].strip().upper()
        current_title = predefined_title or f"Track {track_num}"

        # Live Venice balance check before starting track
        rem_tracks = args.tracks - i
        v_budget = _query_venice_budget(i)
        if v_budget.get("ok"):
            cap_t = min(v_budget["completable_tracks"], rem_tracks)
            log(
                f"  💳 Venice Balance: ${v_budget['total_usd']:.2f} USD | "
                f"Track {track_num}/{args.tracks} ({this_duration}s) est. ~${v_budget['cost_per_track']:.2f} | "
                f"Capacity: {cap_t}/{rem_tracks} remaining track(s)"
            )
            if v_budget["total_usd"] < v_budget["cost_per_track"] * 0.85:
                log(
                    f"    ⛔ Venice AI balance (${v_budget['total_usd']:.2f} USD) insufficient to complete "
                    f"Track {track_num} '{current_title}' (~${v_budget['cost_per_track']:.2f} needed; "
                    f"can complete 0/{rem_tracks} remaining tracks; shortfall ${v_budget['shortfall']:.2f} USD) — halting cleanly before stem generation."
                )
                balance_depleted = True
                break

        locked_plan_file = None
        sr_plan = showrunner_plans.get(track_num)
        if sr_plan and not has_vocals:
            variation = {
                "direction": sr_plan.get("direction", f"Showrunner hit plan for {current_title}"),
                "rules": list(sr_plan.get("rules", [])),
                "bpm": sr_plan.get("bpm"),
                "key": sr_plan.get("key"),
                "stems": {k: v.get("prompt", "") for k, v in sr_plan.get("stems", {}).items() if isinstance(v, dict)},
            }
            locked_plan_file = f"/tmp/showrunner_plan_{track_num}.json"
            with open(locked_plan_file, "w") as pf:
                json.dump(sr_plan, pf, indent=2)
        elif cover_visual or predefined_title or args.album_theme:
            log(f"  🎨 Interpreting Track {track_num} '{current_title}' from cover scene & album theme...")
            interp = interpret_track_from_cover_and_theme(
                album_name=album_name,
                album_theme=album_theme,
                cover_visual=cover_visual,
                track_title=current_title,
                track_num=track_num,
                total_tracks=args.tracks,
                sonic_dna=profile.get("sonic_dna") if profile else None
            )
            variation = {
                "direction": interp.get("direction", f"Interpretation of {current_title}"),
                "rules": list(interp.get("rules", VARIATION_TEMPLATES[i % len(VARIATION_TEMPLATES)]["rules"])),
                "bpm": interp.get("bpm"),
                "key": interp.get("key"),
                "stems": interp.get("stems", {})
            }
        else:
            variation = dict(VARIATION_TEMPLATES[i % len(VARIATION_TEMPLATES)])
            variation["rules"] = list(variation.get("rules", []))

        if has_vocals:
            variation["direction"] += " (subtle vocal texture)"
            variation["rules"].append("Subtle breathy female vocals as background texture only (~5% of mix)")

        # Enrich the brief with variation rules for this track
        enriched_brief = (
            f"{args.brief}. "
            f"Track {track_num}: {current_title}. "
            f"This track direction: {variation['direction']}. "
            f"Requirements: {'; '.join(variation['rules'])}"
        )

        # Album context
        ctx = {
            "track_number": track_num,
            "total_tracks": args.tracks,
            "album_name": album_name,
            "album_theme": album_theme,
            "cover_visual": cover_visual,
            "track_title": current_title,
            "track_interpretation": variation["direction"],
            "brief": args.brief,
            "previous_tracks": completed,
            "variation_rules": variation["rules"],
            "stem_prompts": variation.get("stems", {})
        }
        ctx_file = f"/tmp/album_ctx_{track_num}.json"
        with open(ctx_file, "w") as f:
            json.dump(ctx, f)

        tg_edit(progress_id,
                f"⏳ *{args.brief}*\n"
                f"Track {track_num}/{args.tracks} — {variation['direction']}...")

        log(f"  [{track_num}/{args.tracks}] {variation['direction']}")

        # Progress file for this track
        progress_file = f"/tmp/track_progress_{track_num}.json"

        # Background progress updater
        stop_progress = threading.Event()
        track_start = time.time()

        def _update_progress():
            while not stop_progress.is_set():
                stop_progress.wait(10)
                if stop_progress.is_set():
                    break
                elapsed = time.time() - track_start
                phase_info = ""
                try:
                    with open(progress_file) as pf:
                        prog = json.load(pf)
                    phase_info = f"  Phase: {prog.get('phase_name', '?')}"
                    # Update pipeline_progress.json for album_pipeline LiveStatusDashboard
                    with open("/tmp/pipeline_progress.json", "w") as ppf:
                        json.dump({
                            "track_num": track_num,
                            "elapsed_sec": int(elapsed),
                            "phase_name": prog.get("phase_name", "Generating stems"),
                            "total_cost": round(total_cost, 2)
                        }, ppf)
                except Exception:
                    pass

                # ETA based on average of completed tracks
                eta = ""
                if avg_track_time > 0:
                    remaining = avg_track_time - elapsed
                    if remaining > 0:
                        eta = f" | ~{int(remaining)}s left"

                completed_list = ""
                for j, ct in enumerate(completed, 1):
                    completed_list += f"\n  {j}. ✅ {ct.get('title', '?')}"

                if not args.no_deliver and progress_id:
                    tg_edit(progress_id,
                        f"⏳ *{args.brief}*\n\n"
                        f"Track {track_num}/{args.tracks} — {variation['direction']}\n"
                        f"{phase_info} | ⏱ {int(elapsed)}s{eta}\n"
                        f"💰 ${total_cost:.2f} so far"
                        f"{completed_list}")

        progress_thread = threading.Thread(target=_update_progress, daemon=True)
        progress_thread.start()

        # Use Showrunner locked plan when available (zero per-track LLM calls!), else --director
        cmd = [sys.executable, PRODUCER,
               "--prompt", enriched_brief,
               "--duration", str(this_duration),
               "--quality", args.quality,
               "--target", args.target,
               "--track-number", str(track_num),
               "--total-tracks", str(args.tracks),
               "--no-deliver"]
        if locked_plan_file and os.path.isfile(locked_plan_file):
            cmd.extend(["--plan", locked_plan_file])
        else:
            cmd.append("--director")

        if predefined_title:
            cmd.extend(["--title", predefined_title])

        if is_sample:
            cmd.append("--preview")

        if has_vocals:
            cmd.extend(["--lyrics", "[Verse]\nMmm ahh\n(breathy humming)"])

        env = os.environ.copy()
        env["ALBUM_CONTEXT_FILE"] = ctx_file
        env["TRACK_PROGRESS_FILE"] = progress_file

        max_retries = 3
        track_success = False

        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                log(f"  🔄 Retrying Track {track_num} (attempt {attempt}/{max_retries}) after backoff...")
                time.sleep(5 * attempt)

            timeout = 1800 if not is_sample else 600
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)

            if result.returncode == 0:
                try:
                    rj = json.loads(result.stdout.strip().split("\n")[-1])
                    cost = rj.get("cost_report", {}).get("total_usd", 0)
                    mp3 = rj.get("files", {}).get("mp3", "")
                    flac = rj.get("files", {}).get("flac", "")
                    meta_path = rj.get("metadata", "")
                    plan_path = meta_path.replace("production_metadata.json", "production_plan.json") if meta_path else ""
                    prod_dir = os.path.dirname(meta_path) if meta_path else ""

                    # Verify that audio file actually exists and is non-empty
                    if not (mp3 and os.path.isfile(mp3) and os.path.getsize(mp3) > 1000):
                        log(f"    ⚠️ Attempt {attempt}: Audio file missing or empty, retrying...")
                        continue

                    total_cost += cost
                    default_title = predefined_title or f"Track {track_num}"
                    info = {"title": default_title, "bpm": None, "key": None,
                            "genre": None, "has_vocals": has_vocals, "cost_usd": cost,
                            "direction": variation["direction"], "production_dir": prod_dir}

                    if plan_path and os.path.isfile(plan_path):
                        with open(plan_path) as f:
                            plan = json.load(f)
                        if predefined_title:
                            info["title"] = predefined_title
                        else:
                            plan_title = plan.get("title")
                            if plan_title and not plan_title.lower().startswith("track "):
                                info["title"] = plan_title
                        info.update({"bpm": plan.get("bpm"), "key": plan.get("key"),
                                     "genre": plan.get("genre")})
                    elif predefined_title:
                        info["title"] = predefined_title

                    if not info.get("bpm") and variation.get("bpm"):
                        info["bpm"] = str(variation.get("bpm"))
                    if not info.get("key") and variation.get("key"):
                        info["key"] = str(variation.get("key"))

                    completed.append(info)
                    track_files.append((info["title"], mp3, flac))
                    log(f"    ✅ {info['title']} | {info.get('bpm','')} BPM | ${cost:.2f}")
                    track_success = True
                    break
                except Exception as e:
                    log(f"    ⚠️ Parse error on attempt {attempt}: {e}")
                    if attempt == max_retries:
                        default_fallback = predefined_title or f"Track {track_num}"
                        completed.append({"title": default_fallback, "direction": variation["direction"]})
                        track_success = True
            else:
                stderr_tail = (result.stderr or "").strip().split("\n")[-2:]
                err_msg = " | ".join(l.strip() for l in stderr_tail if l.strip())
                log(f"    ❌ Attempt {attempt} failed: {err_msg}")
                if any(k in err_msg.lower() for k in ("402", "insufficient usd", "insufficient balance", "payment required")):
                    v_post = _query_venice_budget(args.tracks - i)
                    bal_str = (
                        f"Remaining balance: ${v_post['total_usd']:.2f} USD | "
                        f"Can complete: {min(v_post['completable_tracks'], args.tracks - i)}/{args.tracks - i} remaining tracks | "
                        f"Shortfall: ${v_post.get('shortfall', 0.0):.2f} USD"
                        if v_post.get("ok") else "Insufficient USD/DIEM balance"
                    )
                    log(f"    ⛔ Venice AI balance depleted (HTTP 402) — {bal_str} — halting retries until credits are added.")
                    balance_depleted = True
                    break

        # Stop progress thread
        stop_progress.set()
        progress_thread.join(timeout=2)
        track_elapsed = time.time() - track_start
        track_times.append(track_elapsed)
        avg_track_time = sum(track_times) / len(track_times)

        if not track_success:
            failed += 1
            log(f"    ❌ Track {track_num} failed after {attempt} attempt(s).")

        for tmp_f in (ctx_file, progress_file, locked_plan_file):
            if tmp_f:
                try:
                    os.remove(tmp_f)
                except Exception:
                    pass
        if locals().get("balance_depleted"):
            break
        if track_num < args.tracks:
            time.sleep(5)

    # ─── POST-HOC NAMING ────────────────────────────────────────────────
    # Generate names for any tracks where K3 failed to provide one
    unnamed = [t for t in completed if t.get("title", "").lower().startswith("track ") or t.get("title") in ("?", "Unknown", "")]
    if unnamed:
        log(f"  Naming {len(unnamed)} unnamed tracks...")
        # Check predefined track names first
        still_unnamed = []
        for t in unnamed:
            t_num = t.get("number", 0)
            t_idx = (t_num - 1) if t_num > 0 else completed.index(t)
            if t_idx < len(track_names) and track_names[t_idx] and not track_names[t_idx].lower().startswith("track "):
                t["title"] = track_names[t_idx].strip().upper()
                log(f"    Named from proposal track list: {t['title']}")
            else:
                still_unnamed.append(t)
        unnamed = still_unnamed

    if unnamed:
        api_key = os.environ.get("VENICE_API_KEY", "")
        directions = [t.get("direction", "dark phonk") for t in unnamed]
        album_short = args.brief.split(" - ")[0] if " - " in args.brief else args.brief[:30]

        FALLBACK_NAMES = {
            "heavy instrumental opener": "IGNITION POINT",
            "smooth groove": "VELVET UNDERTOW",
            "different lead instrument": "CHROME SPECTRE",
            "tempo shift banger": "REDLINE SHIFT",
            "atmospheric closer": "DAWN EVAPORATE",
            "subtle vocal texture": "PHANTOM WHISPER",
            "experimental wildcard": "VOID FRACTURE",
            "groove-driven": "NEON DRIFT",
        }
        CURATED_FALLBACKS = [
            "MIDNIGHT RECKONING", "PHANTOM VOLTAGE", "SHADOW RUNNER",
            "OBSIDIAN DRIFT", "STATIC VEIL", "NEON CATALYST",
            "BLACK CHROME", "VOID SEQUENCE", "ECLIPSE DRIFT"
        ]

        names = []
        if api_key:
            try:
                prompt = (
                    f"Generate {len(unnamed)} dark, evocative 1-3 word track names for a "
                    f"nightride phonk album called '{album_short}'. "
                    f"Track directions: {', '.join(f'{i+1}) {d}' for i, d in enumerate(directions))}. "
                    f"Return ONLY a JSON array of strings. Example: [\"MIDNIGHT PULSE\", \"GHOST WIRE\"]"
                )
                for model_cand in ["llama-3.3-70b", "deepseek-v4-flash"]:
                    try:
                        payload = json.dumps({
                            "model": model_cand,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.8, "max_tokens": 200,
                        }).encode()
                        req = urllib.request.Request(
                            "https://api.venice.ai/api/v1/chat/completions",
                            data=payload,
                            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        )
                        resp = urllib.request.urlopen(req, timeout=15)
                        raw = json.loads(resp.read().decode())["choices"][0]["message"].get("content") or ""
                        import re as _re
                        match = _re.search(r'\[.*\]', raw, _re.DOTALL)
                        if match:
                            parsed_names = json.loads(match.group())
                            if isinstance(parsed_names, list) and len(parsed_names) >= len(unnamed):
                                valid = [str(n).strip().upper() for n in parsed_names if str(n).strip() and not str(n).lower().startswith("track ")]
                                if len(valid) >= len(unnamed):
                                    names = valid
                                    break
                    except Exception as me:
                        log(f"    Model {model_cand} naming attempt failed: {me}")
            except Exception as e:
                log(f"    Venice naming failed ({e}), using fallback names")

        for idx_u, t in enumerate(unnamed):
            if idx_u < len(names) and names[idx_u] and not names[idx_u].lower().startswith("track "):
                t["title"] = names[idx_u]
                log(f"    Named via AI: {t['title']}")
            else:
                fallback = FALLBACK_NAMES.get(t.get("direction", ""))
                existing_titles = [c.get("title") for c in completed if c.get("title")]
                if not fallback or fallback in existing_titles:
                    for cand in CURATED_FALLBACKS:
                        if cand not in existing_titles:
                            fallback = cand
                            break
                t["title"] = (fallback or f"PHANTOM SEQUENCE {idx_u+1}").upper()
                log(f"    Fallback Name: {t['title']}")

        # Update track_files with new names
        new_files = []
        for title, mp3, flac in track_files:
            match_track = next((t for t in completed if mp3 and t.get("production_dir", "") in mp3), None)
            if match_track and match_track["title"] != title:
                new_files.append((match_track["title"], mp3, flac))
            else:
                new_files.append((title, mp3, flac))
        track_files = new_files

    # ─── BATCH TRACKING ─────────────────────────────────────────────────
    batch_data = {
        "album": args.brief,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
        "profile": profile_name,
        "tracks_requested": args.tracks,
        "tracks_completed": args.tracks - failed,
        "duration_per_track": args.duration,
        "mode": mode,
        "quality": args.quality,
        "target": args.target,
        "vocals_pct": args.vocals_pct,
        "total_cost_usd": round(total_cost, 2),
        "tracklist": [
            {"number": j + 1, "title": t.get("title", "?"), "bpm": t.get("bpm"),
             "key": t.get("key"), "genre": t.get("genre"),
             "direction": t.get("direction", ""),
             "has_vocals": t.get("has_vocals", False),
             "cost_usd": t.get("cost_usd", 0),
             "production_dir": t.get("production_dir", "")}
            for j, t in enumerate(completed)
        ],
    }

    if slug:
        save_batch(slug, batch_data)

    # ─── BATCH DELIVERY ─────────────────────────────────────────────────
    log(f"\n📀 COMPLETE — {len(track_files)}/{args.tracks} tracks, ${total_cost:.2f}")

    tracklist = ""
    for j, t in enumerate(completed, 1):
        tracklist += f"{j}. {t.get('title', '?')}"
        if t.get("bpm"):
            tracklist += f" ({t['bpm']} BPM, {t.get('key', '?')})"
        tracklist += "\n"

    if not args.no_deliver and progress_id:
        tg_edit(progress_id,
                f"📀 *{args.brief}*\n\n"
                f"{tracklist}\n"
                f"💰 ${total_cost:.2f} | Delivering {len(track_files)} {mode}...")

        sent = 0
        for j, (title, mp3, flac) in enumerate(track_files, 1):
            ok = tg_send_audio(mp3, title=f"{j}. {title}", performer=profile_name)
            if ok:
                sent += 1
                log(f"  📤 {j}/{len(track_files)}: {title}")
            time.sleep(1)

        tg_edit(progress_id,
                f"📀 *{args.brief}*\n\n"
                f"{tracklist}\n"
                f"💰 ${total_cost:.2f} | ✅ {sent} {mode} delivered")

        log(f"✅ {sent}/{len(track_files)} delivered to Telegram")

    # Output batch JSON for upstream consumers
    print(json.dumps(batch_data))


if __name__ == "__main__":
    main()
