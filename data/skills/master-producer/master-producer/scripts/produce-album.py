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
    {"direction": "heavy west coast bass opener",
     "rules": ["Massive West Coast 808 sub-bass with aggressive pitch glide curves and tape saturation",
               "Punchy acoustic-sampled transient kick drum with sharp attack and sidechain ducking",
               "Crisp snap snares with wide stereo throws and syncopated trap rolls",
               "Hard-hitting immediate presence — menacing nocturnal cruiser"]},
    {"direction": "melodic nightride groove",
     "rules": ["Melancholic detuned analog brass and minor-pentatonic sine plucks leading the melody",
               "Sliding West Coast 808 sub-bass groove with rhythmic syncopation",
               "Atmospheric nocturnal cruising aura with stereo haas reverb throws",
               "Smooth buildup descending into a heavy, resonant sub drop"]},
    {"direction": "west coast bounce & melodic lead",
     "rules": ["Syncopated West Coast bounce rhythm with rolling triplet hi-hats",
               "Lead detuned synth melody over deep reese and 808 bass foundations",
               "Punchy transient kick drum driving the dynamic groove",
               "Wide stereo imaging on percussion with centered mono bass dominance"]},
    {"direction": "tempo shift nightride banger",
     "rules": ["Different BPM (tempo shift ±10-15 BPM) exploring faster or slower nightride energy",
               "Tension-building filtered buildup with rising nocturnal pads and sub swells",
               "Devastating drop with elongated 808 glide slides and hard transient slap",
               "Dynamic contrast between atmospheric verse and crushing drop"]},
    {"direction": "atmospheric nightride closer",
     "rules": ["Cinematic nocturnal atmosphere with haunting spectral witch house pads",
               "Deep melodic minor chord progressions on detuned analog synths",
               "Heavy sustained sub-bass foundation with expressive pitch portamento",
               "Smooth evolving soundscape building to a final thundering sub-bass climax"]},
    {"direction": "experimental nightride wildcard",
     "rules": ["Unexpected sonic textures layered with dominant West Coast sub-bass slides",
               "Detuned sine plucks and chopped vocal textures in stereo delay space",
               "Bass drops that hit with punchy acoustic transient definition",
               "Menacing, hypnotic nocturnal cruising aura"]},
    {"direction": "sub-heavy melodic groove",
     "rules": ["Deep sub-bass frequencies commanding the low end (40-55Hz fundamental)",
               "Melodic synth hooks playing dark, silky minor-pentatonic lines",
               "Crisp snap snares and tight syncopated percussion groove",
               "Uncompromised volume balance — hard-hitting yet silky and controlled"]},
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
    if not fallback:
        fallback = {
            "direction": f"Auditory interpretation of cover scene embodying '{track_title}'",
            "rules": [
                f"Sub-bass and 808 glide behavior reflecting {cover_visual[:50] or album_theme[:50]}",
                "Transient percussion and acoustic snap matching visual materials",
                "Atmospheric synth leads and pads translating visual lighting and motifs into sound",
                f"Dynamic progression and arrangement embodying '{track_title}'"
            ],
            "bpm": 130,
            "key": "Ebm",
            "stems": {
                "main": f"{album_theme}. Auditory translation of {cover_visual}. Focused on {track_title}. Heavy 808 slides, punchy kicks, atmospheric synth textures.",
                "texture": f"Atmospheric soundscape reflecting {cover_visual[:150]}, subtle background drone.",
                "accent": f"Sharp dynamic impact matching {track_title} and visual scene."
            }
        }

    if not api_key:
        return fallback

    system_prompt = (
        "You are the Creative Director and Master Sound Designer for VØIDRIDE.\n"
        "Your task: Translate the visual album cover art and album theme into an auditory, "
        "compositional interpretation for the specific song title below.\n\n"
        f"ALBUM: {album_name}\n"
        f"ALBUM THEME & SONIC DNA: {album_theme}\n"
        f"COVER ART VISUAL SCENE: {cover_visual}\n"
        f"TRACK {track_num} OF {total_tracks} TITLE: {track_title}\n\n"
        "Translate the visual setting, lighting, materials, and motifs directly into sound:\n"
        "- Visual materials (wet concrete, cold tiles, steel grills, glass) -> reverb acoustics, transient snap, high-frequency reflections.\n"
        "- Atmospheric phenomena (venting steam, drifting fog, fluorescent tube hum) -> sound beds, filtered white-noise sweeps, voltage drone.\n"
        "- Visual motifs (ambulance idle, shadowed man, katana, moon) -> deep sub-bass motor glide, predatory reese undertones, razor transient cuts, pale pad swells.\n"
        f"- Song Title '{track_title}' -> the central musical hook, groove, and narrative of this specific track.\n\n"
        "Return ONLY a valid JSON object (no markdown fences, no commentary):\n"
        "{\n"
        '  "direction": "One-sentence summary of how this track translates the visual cover into sound",\n'
        '  "rules": [\n'
        '    "Rule 1: Sub-bass and 808 glide behavior reflecting the scene",\n'
        '    "Rule 2: Drum and transient textures reflecting visual materials",\n'
        '    "Rule 3: Lead synth/melodic elements reflecting the visual mood",\n'
        '    "Rule 4: Foley and atmospheric textures from the cover scene",\n'
        '    "Rule 5: Pacing and arrangement embodying the song title"\n'
        '  ],\n'
        '  "bpm": 132,\n'
        '  "key": "Ebm",\n'
        '  "main_prompt": "Comprehensive main prompt for elevenlabs-music (60-120 words) detailing genre, BPM, key, instruments, 808 behavior, atmospheric space, and mood",\n'
        '  "texture_prompt": "Prompt for stable-audio-25 (UNDER 450 CHARS) describing atmospheric texture/foley bed with key and BPM",\n'
        '  "accent_prompt": "Prompt for elevenlabs-sound-effects-v2 (UNDER 450 CHARS) describing short transition FX/foley hit from the scene"\n'
        "}"
    )

    for model_name in ["kimi-k3", "llama-3.3-70b"]:
        try:
            payload = json.dumps({
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Generate auditory interpretation for Track {track_num}: '{track_title}' based on the cover art and theme."}
                ],
                "temperature": 0.6,
                "max_tokens": 1500,
                "venice_parameters": {
                    "strip_thinking_response": True
                }
            }).encode('utf-8')

            req = urllib.request.Request(
                "https://api.venice.ai/api/v1/chat/completions",
                data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if "<think>" in raw:
                    raw = raw.split("</think>")[-1].strip()
                if "```" in raw:
                    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
                    if m:
                        raw = m.group(1)
                    else:
                        raw = re.sub(r'```(?:json)?\s*', '', raw)
                        raw = re.sub(r'\s*```', '', raw)

                parsed = json.loads(raw)
                if parsed.get("direction") and parsed.get("rules") and len(parsed["rules"]) >= 3:
                    stems = parsed.get("stems", {})
                    if not stems:
                        stems = {
                            "main": parsed.get("main_prompt", fallback["stems"]["main"]),
                            "texture": parsed.get("texture_prompt", fallback["stems"]["texture"]),
                            "accent": parsed.get("accent_prompt", fallback["stems"]["accent"])
                        }
                    if len(stems.get("texture", "")) > 450:
                        stems["texture"] = stems["texture"][:445]
                    if len(stems.get("accent", "")) > 450:
                        stems["accent"] = stems["accent"][:445]
                    parsed["stems"] = stems
                    return parsed
        except Exception as e:
            log(f"  ⚠️ Cover-to-song inference with {model_name} failed: {e}")
            continue

    return fallback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", required=True, help="Album concept")
    parser.add_argument("--tracks", type=int, default=5)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--mode", default=None, choices=["full", "sample", "samples", "full tracks"])
    parser.add_argument("--no-deliver", action="store_true", help="Skip Telegram delivery and status messages")
    parser.add_argument("--resume-tracks", type=int, default=0, help="Number of tracks already completed")
    parser.add_argument("--quality", default="quick", choices=["quick", "standard", "premium"])
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

    log(f"📀 {args.brief} — {args.tracks} × {args.duration}s {mode}")

    progress_id = None
    if not args.no_deliver:
        progress_id = tg_send(f"⏳ *{args.brief}*\nGenerating {args.tracks} {mode}...")

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

    for i in range(args.resume_tracks, args.tracks):
        track_num = i + 1
        has_vocals = i in vocal_positions

        # Determine track title if pre-defined
        predefined_title = None
        if i < len(track_names) and track_names[i] and not track_names[i].lower().startswith("track "):
            predefined_title = track_names[i].strip().upper()
        current_title = predefined_title or f"Track {track_num}"

        # If cover_visual, album_theme, or predefined_title are present, derive track direction from cover + theme + title
        if cover_visual or predefined_title or args.album_theme:
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

        # Use enriched brief that includes variation direction
        cmd = [sys.executable, PRODUCER,
               "--prompt", enriched_brief,
               "--duration", str(args.duration),
               "--quality", args.quality,
               "--target", args.target,
               "--director", "--no-deliver"]

        if predefined_title:
            cmd.extend(["--title", predefined_title])

        if is_sample:
            cmd.append("--preview")

        if has_vocals:
            cmd.extend(["--lyrics", "[Verse]\nMmm ahh\n(breathy humming)"])

        env = os.environ.copy()
        env["ALBUM_CONTEXT_FILE"] = ctx_file
        env["TRACK_PROGRESS_FILE"] = progress_file

        timeout = 1800 if not is_sample else 600
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)

        # Stop progress thread
        stop_progress.set()
        progress_thread.join(timeout=2)
        track_elapsed = time.time() - track_start
        track_times.append(track_elapsed)
        avg_track_time = sum(track_times) / len(track_times)

        if result.returncode == 0:
            try:
                rj = json.loads(result.stdout.strip().split("\n")[-1])
                cost = rj.get("cost_report", {}).get("total_usd", 0)
                total_cost += cost
                mp3 = rj.get("files", {}).get("mp3", "")
                flac = rj.get("files", {}).get("flac", "")
                meta_path = rj.get("metadata", "")
                plan_path = meta_path.replace("production_metadata.json", "production_plan.json") if meta_path else ""
                prod_dir = os.path.dirname(meta_path) if meta_path else ""

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
                # For full tracks, prefer FLAC; for samples, MP3 only
                send_file = mp3
                if mp3 and os.path.isfile(mp3):
                    track_files.append((info["title"], mp3, flac))
                log(f"    ✅ {info['title']} | {info.get('bpm','')} BPM | ${cost:.2f}")
            except Exception as e:
                log(f"    ✅ done (parse: {e})")
                default_fallback = predefined_title or f"Track {track_num}"
                completed.append({"title": default_fallback, "direction": variation["direction"]})
        else:
            log(f"    ❌ failed")
            stderr_tail = (result.stderr or "").strip().split("\n")[-2:]
            for line in stderr_tail:
                log(f"       {line.strip()}")
            failed += 1

        try:
            os.remove(ctx_file)
            os.remove(progress_file)
        except Exception:
            pass
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
