#!/usr/bin/env python3
import os
import sys
import json
import time
import logging
import argparse
import urllib.request
import urllib.parse
import subprocess
import shutil
import base64

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('album_pipeline')

# Constants
FLAGS_DIR = "/tmp/pipeline_flags/"
PROPOSALS_FILE = "/opt/data/music/proposals/current_proposals.json"
PROFILE_FILE = "/opt/data/music/profiles/vidride/profile.json"
ARTWORK_DIR = "/opt/data/music/artwork/covers/"
LOCK_FILE = "/tmp/album_pipeline.lock"
STATE_FILE = "/opt/data/music/pipeline_state.json"

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            pid = int(open(LOCK_FILE).read().strip())
            if os.path.exists(f"/proc/{pid}"):
                logger.error(f"Pipeline already running (PID {pid})")
                sys.exit(1)
        except Exception:
            pass
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

def save_state(state_data):
    with open(STATE_FILE, "w") as f:
        json.dump(state_data, f, indent=2)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}
# Scripts
PRODUCE_SCRIPT = "/opt/data/skills/master-producer/master-producer/scripts/produce-album.py"
SHARE_SCRIPT = "/opt/data/skills/secure-share/scripts/share.py"
PUBLISH_SCRIPT = "/opt/data/skills/music/soundcloud/scripts/publish_release.py"
GEN_ARTWORK_SCRIPT = "/opt/data/skills/gen-artwork/gen-artwork/scripts/gen_artwork.py"
OVERLAY_TITLE_SCRIPT = "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py"
GEN_WAVEFORM_SCRIPT = "/opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py"
STYLIZE_SCRIPT = "/opt/data/scripts/stylize_title.py"
DAWCTL_SCRIPT = "/opt/data/skills/dawagent/dawagent/scripts/dawctl_local.py"
HANDOFF_SCRIPT = "/opt/data/skills/dawagent/dawagent/scripts/handoff.py"

def get_env_var(name, default=None, required=True):
    """Get env var with PID 1 fallback and config.yaml fallback."""
    val = os.environ.get(name)
    if not val:
        # Try PID 1 environment (gateway process)
        try:
            env = open("/proc/1/environ").read().split(chr(0))
            for e in env:
                if e.startswith(f"{name}="):
                    val = e.split("=", 1)[1]
                    break
        except: pass
    if not val:
        # Try config.yaml
        try:
            import yaml
            cfg = yaml.safe_load(open("/opt/data/config.yaml"))
            val = cfg.get(name, cfg.get(name.lower()))
        except: pass
    if not val and required:
        logger.error(f"Missing required environment variable: {name}")
        sys.exit(1)
    return val or default

TELEGRAM_BOT_TOKEN = get_env_var('TELEGRAM_BOT_TOKEN', '', required=False)
TELEGRAM_CHAT_ID = get_env_var('TELEGRAM_CHAT_ID', '8293122782', required=False)
VENICE_API_KEY = get_env_var('VENICE_API_KEY', required=False)

def _send_tg_request(method, data=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    headers = {'Content-Type': 'application/json'}
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8') if data else None, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        logger.error(f"Telegram API error ({method}): {e}")
        return None

def send_message(text, reply_markup=None):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _send_tg_request("sendMessage", payload)

def send_agent_notification(text):
    return send_message(f"[pipeline] {text}")

def send_audio(audio_path, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio"
    cmd = ['curl', '-s', '-X', 'POST', url, '-F', f'chat_id={TELEGRAM_CHAT_ID}', '-F', f'audio=@{audio_path}']
    if caption:
        cmd.extend(['-F', f'caption={caption}'])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        return json.loads(res.stdout) if res.stdout.strip() else None
    except Exception as e:
        logger.error(f"send_audio failed for {audio_path}: {e}")
        return None

def send_photo(photo_path, caption=None, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    cmd = ['curl', '-s', '-X', 'POST', url, '-F', f'chat_id={TELEGRAM_CHAT_ID}', '-F', f'photo=@{photo_path}']
    if caption:
        cmd.extend(['-F', f'caption={caption}'])
    if reply_markup:
        cmd.extend(['-F', f'reply_markup={json.dumps(reply_markup)}'])
    res = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(res.stdout)

def stylize_title(title):
    """Convert plain title to VØIDRIDE Unicode aesthetic."""
    try:
        res = subprocess.run(
            ["/opt/hermes/.venv/bin/python3", STYLIZE_SCRIPT, title],
            capture_output=True, text=True
        )
        if res.returncode == 0 and '->' in res.stdout:
            return res.stdout.strip().split('-> ')[-1]
    except Exception:
        pass
    return title  # fallback to plain

def clear_flags():
    if os.path.exists(FLAGS_DIR):
        shutil.rmtree(FLAGS_DIR)
    os.makedirs(FLAGS_DIR, exist_ok=True)

def poll_flags(timeout_hours=24):
    logger.info("Polling for user decisions...")
    start_time = time.time()
    timeout_seconds = timeout_hours * 3600

    while True:
        if time.time() - start_time > timeout_seconds:
            send_agent_notification("Timeout waiting for user input. Pipeline aborting.")
            sys.exit(1)

        for f in os.listdir(FLAGS_DIR):
            path = os.path.join(FLAGS_DIR, f)
            if not os.path.isfile(path):
                continue
            
            try:
                with open(path, 'r', encoding='utf-8') as fp:
                    content = fp.read().strip()
                os.remove(path)
                logger.info(f"Received flag: {f}")
                return f, content
            except Exception as e:
                logger.error(f"Error reading flag {f}: {e}")
        
        time.sleep(5)

def run_test_mode(proposal_index):
    print(f"--- PIPELINE TEST MODE (Proposal {proposal_index}) ---")
    
    try:
        with open(PROPOSALS_FILE, 'r') as f:
            raw = json.load(f)
            proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
            proposal = proposals[proposal_index]
    except Exception as e:
        print(f"Error loading proposal: {e}")
        return

    try:
        with open(PROFILE_FILE, 'r') as f:
            profile = json.load(f)
    except Exception as e:
        print(f"Error loading profile: {e}")
        return

    brief = f"Title: {proposal.get('album', 'Unknown')}\n"
    brief += f"Direction: {proposal.get('brief', '')}\n"
    brief += "\n--- VØIDRIDE IDENTITY ---\n"
    dna = profile.get("sonic_dna", {})
    brief += f"Genres: {', '.join(dna.get('primary_genres', []))} + dark nightride trap, witch house, cinematic nightride phonk\n"
    brief += f"Keys: {', '.join(dna.get('preferred_keys', ['Fm', 'Cm', 'Dm']))}\n"
    brief += "Anti-patterns: NO galloping, static loops, booming, anthems, helicopter noise, TTS vocals, silence drops\n"
    brief += "Sound: dominant 808 bass with aggressive slides, spectral witch house pads, cyber-noir haze, relentless nocturnal cruising energy\n"

    print("\n[PHASE 1] PRODUCE")
    print(f"Enriched Brief:\n{brief}\n")
    
    print("[PHASE 2] SONG REVIEW")
    print("Sending Audio files...")
    buttons = [
        [{"text": "✅ Approve All", "callback_data": "ap:songs:approve"}],
        [{"text": "📥 Download FLACs", "callback_data": "ap:songs:flac"}],
        [{"text": "🔄 Redo Track 1", "callback_data": "ap:songs:redo:1"}],
        [{"text": "❌ Reject Album", "callback_data": "ap:songs:reject"}]
    ]
    print(f"Buttons:\n{json.dumps({'inline_keyboard': buttons}, indent=2)}\n")
    
    print("[PHASE 3] DAW HANDOFF & MASTERING")
    print(f"  dawctl_local.py session create --name {proposal.get('album', '').replace(' ', '_')} --sr 48000 --bpm <from tracklist>")
    print(f"  handoff.py write --session ... --stems <flacs> --stem-names <titles>")
    print("  Polling /opt/data/dawagent/exports/ for _MASTER.flac files...")
    master_buttons = [
        [{"text": "✅ Approve Masters", "callback_data": "ap:master:approve"}],
        [{"text": "🔄 Wait for Re-export", "callback_data": "ap:master:wait"}]
    ]
    print(f"Buttons:\n{json.dumps({'inline_keyboard': master_buttons}, indent=2)}\n")
    
    print("[PHASE 4] ARTWORK")
    print(f"Visual Prompt: {proposal.get('visual', '')} + NO TEXT, NO LETTERS, NO TYPOGRAPHY")
    art_buttons = [
        [{"text": "✅ Approve Artwork", "callback_data": "ap:art:approve"}],
        [{"text": "✏️ Edit Cover", "callback_data": "ap:art:edit"}],
        [{"text": "🔄 Regenerate", "callback_data": "ap:art:regen"}]
    ]
    print(f"Buttons:\n{json.dumps({'inline_keyboard': art_buttons}, indent=2)}\n")
    
    print("[PHASE 5] FINAL REVIEW")
    print("Packaging mastered release...")
    final_buttons = [
        [{"text": "🚀 Publish to SoundCloud", "callback_data": "ap:final:publish"}],
        [{"text": "↩️ Go Back", "callback_data": "ap:final:back"}]
    ]
    print(f"Buttons:\n{json.dumps({'inline_keyboard': final_buttons}, indent=2)}\n")
    
    print("[PHASE 6] PUBLISH")
    print("Publishing mastered release to SoundCloud...")

def phase_1_redo_single(proposal, profile, tracklist, track_num, feedback=None):
    """Re-produce a single track and swap it into the existing tracklist."""
    album_name = proposal.get('album', 'Unknown Album')
    subgenre = proposal.get('subgenre', 'dark nightride trap')
    
    # Find the original track info
    original = None
    track_idx = None
    for idx, t in enumerate(tracklist):
        if t.get('track') == track_num:
            original = t
            track_idx = idx
            break
    
    if original is None:
        send_message(f"❌ Track {track_num} not found in tracklist")
        return tracklist
    
    title = original.get('title', f'Track {track_num}')
    bpm = original.get('bpm', '130')
    key = original.get('key', 'Cm')
    
    # Build single-track brief
    brief = f"{album_name} - {subgenre}. "
    brief += f"Track {track_num}: {title}. "
    brief += f"{proposal.get('brief', '')} "
    brief += f"{bpm} BPM, {key}. "
    
    # Add sonic identity block
    if profile:
        sonic = profile.get('sonic_dna', {})
        brief += "\n--- VØIDRIDE IDENTITY ---\n"
        brief += f"Primary genres: {', '.join(sonic.get('primary_genres', []))}\n"
        models = sonic.get('preferred_models', {})
        brief += f"Preferred models: {models.get('main', 'elevenlabs-music')} (main), "
        brief += f"{models.get('texture', 'stable-audio-25')} (texture), "
        brief += f"{models.get('accent', 'elevenlabs-sound-effects-v2')} (accent)\n"
        brief += f"Preferred keys: {', '.join(sonic.get('preferred_keys', []))}\n"
        anti = sonic.get('anti_patterns', [])
        if anti:
            brief += f"Anti-patterns: {', '.join(anti)}\n"
        brief += f"The VØIDRIDE sound: {profile.get('prompt_prefix', '')}\n"
    
    if feedback:
        brief += f"\n[REDO FEEDBACK]: {feedback}\n"
    
    send_message(f"🔄 Redoing track {track_num}: {title}...")
    send_agent_notification(f"Redoing track {track_num}: {title}")
    
    # Run master-producer for single track
    cmd = [
        "/opt/hermes/.venv/bin/python3",
        MASTER_PRODUCER_SCRIPT,
        "--prompt", brief,
        "--duration", "260",
        "--quality", "standard",
        "--target", "streaming",
        "--director",
        "--profile", "vidride",
    ]
    
    logger.info(f"Redo track {track_num}: {' '.join(cmd[:6])}...")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    for line in iter(process.stdout.readline, ''):
        line = line.strip()
        if line:
            logger.info(f"Redo output: {line}")
    
    process.wait()
    if process.returncode != 0:
        send_message(f"❌ Track {track_num} redo failed")
        return tracklist
    
    # Find the new production dir — search all recent dirs, not just album slug
    import glob
    album_slug = album_name.lower().replace(' ', '-').replace('_', '-')
    
    # Try album-slug match first, then fall back to most recent of all
    prod_dirs = sorted(glob.glob(f"/opt/data/music/productions/*{album_slug}*"))
    if not prod_dirs:
        all_dirs = sorted(glob.glob("/opt/data/music/productions/2026*"))
        prod_dirs = all_dirs[-3:] if all_dirs else []  # check last 3
    
    if prod_dirs:
        new_dir = prod_dirs[-1]  # latest one
        mp3s = glob.glob(os.path.join(new_dir, "*.mp3"))
        flacs = glob.glob(os.path.join(new_dir, "master_*.flac")) or glob.glob(os.path.join(new_dir, "*.flac"))
        wavs = glob.glob(os.path.join(new_dir, "mix_*.wav"))
        
        # Get title from new production plan
        plan_file = os.path.join(new_dir, "production_plan.json")
        new_title = title
        new_bpm = bpm
        new_key = key
        if os.path.exists(plan_file):
            try:
                with open(plan_file) as f:
                    plan = json.load(f)
                new_title = plan.get("title", title)
                new_bpm = plan.get("bpm", bpm)
                new_key = plan.get("key", key)
            except:
                pass
        
        # Update tracklist entry
        new_track = {
            "track": track_num,
            "title": new_title,
            "bpm": new_bpm,
            "key": new_key,
            "production_dir": new_dir,
        }
        if mp3s:
            new_track["mp3_path"] = mp3s[0]
        if flacs:
            new_track["flac_path"] = flacs[0]
        
        tracklist[track_idx] = new_track
        
        # ── Check for DAWAGENT mastered version (preferred over raw) ──
        daw_slug = new_title.lower().replace(' ', '-').replace('_', '-')
        daw_export_dir = f"/opt/data/dawagent/exports/{daw_slug}"
        daw_session_dir = f"/opt/data/dawagent/sessions/{daw_slug}"
        daw_mp3 = os.path.join(daw_export_dir, f"{daw_slug}_MASTER.mp3")
        daw_flac = os.path.join(daw_export_dir, f"{daw_slug}_MASTER.flac")
        
        # If DAWAGENT session exists but no master yet, wait for it
        if os.path.isdir(daw_session_dir) and not os.path.exists(daw_mp3):
            send_message(f"⏳ Waiting for DAWAGENT mastering of {new_title}...")
            import time
            for _wait in range(18):  # up to 90 seconds
                time.sleep(5)
                if os.path.exists(daw_mp3):
                    break
        
        # Send the best available audio: DAWAGENT master → production MP3 → FLAC → WAV
        audio_to_send = None
        audio_label = ""
        
        if os.path.exists(daw_mp3):
            audio_to_send = daw_mp3
            audio_label = "DAWAGENT Mastered"
            new_track["master_mp3"] = daw_mp3
            logger.info(f"Using DAWAGENT master: {daw_mp3}")
        elif os.path.exists(daw_flac):
            mp3_path = daw_flac.replace('.flac', '.mp3')
            subprocess.run(["ffmpeg", "-y", "-i", daw_flac, "-b:a", "320k", mp3_path], capture_output=True)
            if os.path.exists(mp3_path):
                audio_to_send = mp3_path
                audio_label = "DAWAGENT Mastered"
        elif mp3s and os.path.exists(mp3s[0]):
            audio_to_send = mp3s[0]
            audio_label = "Pre-Master"
        elif flacs and os.path.exists(flacs[0]):
            mp3_path = flacs[0].replace('.flac', '.mp3')
            logger.info(f"Converting FLAC to MP3 for redo send: {flacs[0]}")
            subprocess.run(["ffmpeg", "-y", "-i", flacs[0], "-b:a", "320k", "-map_metadata", "0", mp3_path],
                           capture_output=True)
            if os.path.exists(mp3_path):
                audio_to_send = mp3_path
                audio_label = "Pre-Master"
                new_track["mp3_path"] = mp3_path
        elif wavs and os.path.exists(wavs[0]):
            mp3_path = wavs[0].replace('.wav', '.mp3')
            logger.info(f"Converting WAV to MP3 for redo send: {wavs[0]}")
            subprocess.run(["ffmpeg", "-y", "-i", wavs[0], "-b:a", "320k", mp3_path],
                           capture_output=True)
            if os.path.exists(mp3_path):
                audio_to_send = mp3_path
                audio_label = "Raw Mix"
                new_track["mp3_path"] = mp3_path
        
        if audio_to_send:
            send_audio(audio_to_send, caption=f"🔄 Track {track_num}: {new_title} ({audio_label}) — {new_bpm} BPM, {new_key}")
            logger.info(f"Sent redo audio ({audio_label}): {audio_to_send}")
        else:
            send_message(f"⚠️ Track {track_num} redone but no audio file found to send")
            logger.error(f"No MP3, FLAC, or WAV found in {new_dir} or DAWAGENT exports")
        
        send_message(f"✅ Track {track_num} redone: {new_title} — {new_bpm} BPM, {new_key}")
        send_agent_notification(f"Track {track_num} redone: {new_title} — {new_bpm} BPM, {new_key}")
        
        # ── Also regenerate the track cover ──
        visual = proposal.get('visual', '')
        direction = new_track.get('direction', new_track.get('genre', subgenre))
        send_message(f"🎨 Regenerating cover for redone track {track_num}: {new_title}...")
        
        scene = _build_varied_scene(visual, new_title, direction, track_idx, len(tracklist))
        cover_path = generate_artwork_venice(scene, f"{album_name}/{new_title}")
        
        if cover_path and os.path.exists(cover_path):
            track_art_dir = os.path.join(ARTWORK_DIR, album_name.replace(' ', '-'))
            os.makedirs(track_art_dir, exist_ok=True)
            final_path = os.path.join(track_art_dir, f"{new_title}_cover.png")
            if cover_path != final_path:
                import shutil
                shutil.move(cover_path, final_path)
                cover_path = final_path
            
            # Title overlay
            if os.path.exists(OVERLAY_TITLE_SCRIPT):
                styled_title = stylize_title(new_title)
                subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                    "--image", cover_path, "--title", styled_title,
                    "--bottom", "--auto-color", "--output", cover_path], capture_output=True)
            
            track_btn = [[{"text": f"🔄 Regen Track {track_num}", "callback_data": f"ap:art:redo:{track_num}"}]]
            send_photo(cover_path, caption=f"🎨 Track {track_num}: {new_title} (new cover)", reply_markup={"inline_keyboard": track_btn})
            logger.info(f"Sent new cover for redone track {track_num}: {cover_path}")
            
            # Update SoundCloud artwork if track ID is known
            sc_track_id = new_track.get('soundcloud_track_id') or original.get('soundcloud_track_id')
            if sc_track_id:
                try:
                    SC_SCRIPT = "/opt/data/skills/music/soundcloud/scripts/soundcloud_api.py"
                    subprocess.run(["/opt/hermes/.venv/bin/python3", SC_SCRIPT, "update",
                        "--track-id", str(sc_track_id), "--artwork", cover_path],
                        capture_output=True, timeout=60)
                    logger.info(f"Updated SoundCloud artwork for track {sc_track_id}")
                except Exception as e:
                    logger.error(f"Failed to update SC artwork: {e}")
        else:
            send_message(f"⚠️ Could not regenerate cover for {new_title}")
    else:
        send_message(f"⚠️ Track {track_num} redo completed but couldn't find output")
    
    return tracklist

MASTER_PRODUCER_SCRIPT = "/opt/data/skills/master-producer/master-producer/scripts/master-producer.py"

def phase_1_produce(proposal, profile, redo_track=None, redo_feedback=None):
    album_name = proposal.get('album', 'Unknown Album')
    
    brief = f"{album_name} - {proposal.get('subgenre', 'dark nightride trap')}. "
    brief += f"{proposal.get('brief', '')} "
    if redo_track and redo_feedback:
        brief += f"\n[REDO FEEDBACK FOR TRACK {redo_track}]: {redo_feedback}\n"
        
    brief += "\n--- VØIDRIDE IDENTITY ---\n"
    brief += "Primary genres: dark nightride trap, witch house, cinematic nightride phonk\n"
    brief += "Preferred models: elevenlabs-music (main), stable-audio-25 (texture), elevenlabs-sound-effects-v2 (accent)\n"
    brief += "Preferred keys: Fm, Cm, Dm\n"
    brief += "Anti-patterns: NO galloping, static loops, booming, anthems, helicopter noise, TTS vocals, silence drops\n"
    brief += "The VØIDRIDE sound: dominant 808 bass with aggressive slides, spectral witch house pads, cyber-noir haze, relentless nocturnal cruising energy\n"

    send_agent_notification(f"{album_name} production started (5 tracks)")
    
    cmd = [
        "/opt/hermes/.venv/bin/python3", PRODUCE_SCRIPT,
        "--brief", brief,
        "--tracks", "5",
        "--duration", "260",
        "--quality", "standard"
    ]
    
    logger.info(f"Calling master-producer: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    tracklist = []
    track_num = 0
    for line in iter(process.stdout.readline, ''):
        line = line.strip()
        if not line:
            continue
        logger.info(f"Produce output: {line}")
        
        # Try JSON first
        try:
            data = json.loads(line)
            if "track" in data and "title" in data:
                t_num = data.get("track")
                t_title = data.get("title")
                t_bpm = data.get("bpm", "Unknown")
                t_key = data.get("key", "Unknown")
                mp3_path = data.get("mp3_path")
                msg = f"✅ Track {t_num}/5 {t_title} — {t_bpm} BPM, {t_key}"
                send_message(msg)
                send_agent_notification(f"Track {t_num}/5 {t_title} complete — {t_bpm} BPM, {t_key}")
                tracklist.append(data)
            continue
        except (ValueError, json.JSONDecodeError):
            pass
        
        # Parse text format: "[produce-album]     ✅ EYEWALL | 160 BPM | $3.85"
        import re
        match = re.match(r'\[produce-album\]\s+✅\s+(.+?)\s*\|\s*(\d+)\s*BPM\s*\|\s*\$?([\d.]+)', line)
        if match:
            track_num += 1
            t_title = match.group(1).strip()
            t_bpm = match.group(2)
            t_cost = match.group(3)
            msg = f"✅ Track {track_num}/5 {t_title} — {t_bpm} BPM (${t_cost})"
            send_message(msg)
            send_agent_notification(f"Track {track_num}/5 {t_title} complete — {t_bpm} BPM")
            tracklist.append({"track": track_num, "title": t_title, "bpm": t_bpm, "cost": t_cost})
            
    process.wait()
    if process.returncode != 0:
        send_agent_notification(f"Production failed with code {process.returncode}")
        send_message("❌ Production script failed.")
        sys.exit(1)
    
    # Find production dirs to get actual MP3/FLAC paths
    import glob
    album_slug = proposal.get('album', '').lower().replace(' ', '-').replace('_', '-')
    prod_dirs = sorted(glob.glob(f"/opt/data/music/productions/*{album_slug}*"))
    for i, t in enumerate(tracklist):
        if i < len(prod_dirs):
            d = prod_dirs[-(len(tracklist)-i)]  # latest N dirs
            mp3s = glob.glob(os.path.join(d, "*.mp3"))
            flacs = glob.glob(os.path.join(d, "*.flac"))
            if mp3s:
                t["mp3_path"] = mp3s[0]
            if flacs:
                t["flac_path"] = flacs[0]
            t["production_dir"] = d
        
    send_agent_notification("All tracks complete, sent for user review")
    return tracklist

def phase_2_song_review(tracklist):
    for t in tracklist:
        mp3 = t.get('mp3_path')
        if mp3 and os.path.exists(mp3):
            send_audio(mp3, caption=f"Track {t.get('track')}: {t.get('title')}")
            
    # Send Buttons
    buttons = [
        [{"text": "✅ Approve All", "callback_data": "ap:songs:approve"}],
        [{"text": "📥 Download FLACs", "callback_data": "ap:songs:flac"}]
    ]
    for t in tracklist:
        n = t.get('track')
        buttons.append([{"text": f"🔄 Redo Track {n}", "callback_data": f"ap:songs:redo:{n}"}])
    buttons.append([{"text": "❌ Reject Album", "callback_data": "ap:songs:reject"}])
    
    reply_markup = {"inline_keyboard": buttons}
    send_message("Please review the generated tracks:", reply_markup=reply_markup)
    
    while True:
        flag, content = poll_flags()
        if flag == "songs_approved":
            return "approved", None
        elif flag == "songs_flac_requested":
            # Package FLACs + playlist, share via Cloudflare tunnel
            send_message("📦 Packaging FLACs + playlist...")
            try:
                import tempfile
                album_name = proposal.get("album", "ALBUM").replace(" ", "-")
                pack_dir = os.path.join(tempfile.gettempdir(), f"flac-{album_name}")
                os.makedirs(pack_dir, exist_ok=True)

                # Collect FLACs into pack dir
                flac_files = []
                for idx, t in enumerate(tracklist):
                    flac = t.get("flac_path")
                    if flac and os.path.exists(flac):
                        title = t.get("title", f"Track_{idx+1}")
                        dest_name = f"{(idx+1):02d}-{title.replace(' ', '-')}.flac"
                        dest = os.path.join(pack_dir, dest_name)
                        shutil.copy2(flac, dest)
                        flac_files.append(dest_name)
                    elif t.get("mp3_path") and os.path.exists(t["mp3_path"]):
                        title = t.get("title", f"Track_{idx+1}")
                        dest_name = f"{(idx+1):02d}-{title.replace(' ', '-')}.mp3"
                        dest = os.path.join(pack_dir, dest_name)
                        shutil.copy2(t["mp3_path"], dest)
                        flac_files.append(dest_name)

                # Generate M3U playlist
                if flac_files:
                    playlist_path = os.path.join(pack_dir, f"{album_name}.m3u")
                    with open(playlist_path, "w") as pf:
                        pf.write("#EXTM3U\n")
                        for fname in flac_files:
                            title_clean = os.path.splitext(fname)[0].split("-", 1)[-1].replace("-", " ")
                            pf.write(f"#EXTINF:-1,{title_clean}\n")
                            pf.write(f"{fname}\n")

                # Share via secure-share → Cloudflare tunnel
                res = subprocess.run(
                    ["/opt/hermes/.venv/bin/python3", SHARE_SCRIPT, "--path", pack_dir],
                    capture_output=True, text=True, timeout=120
                )
                # Parse output for the external link
                external_link = None
                for line in res.stdout.splitlines():
                    if "[EXTERNAL LINK]" in line:
                        external_link = line.split("[EXTERNAL LINK]")[-1].strip()
                        break

                if external_link:
                    send_message(
                        f"📥 *{album_name}* — {len(flac_files)} tracks + playlist\n"
                        f"🔗 [Download ZIP]({external_link})"
                    )
                elif res.returncode == 0:
                    # Fallback: no tunnel running, show local link
                    local_link = None
                    for line in res.stdout.splitlines():
                        if "[LOCAL LINK]" in line:
                            local_link = line.split("[LOCAL LINK]")[-1].strip()
                            break
                    send_message(f"📥 FLACs packaged ({len(flac_files)} tracks)\n🔗 {local_link or res.stdout.strip()}")
                else:
                    send_message(f"❌ Failed to package FLACs: {res.stderr[:200]}")

                # Cleanup temp dir
                shutil.rmtree(pack_dir, ignore_errors=True)
            except Exception as e:
                send_message(f"❌ FLAC packaging error: {e}")
            continue # keep polling
        elif flag.startswith("songs_redo_"):
            try:
                track_num = int(flag.split('_')[-1])
                return "redo_track", (track_num, content)
            except:
                continue
        elif flag == "songs_rejected":
            return "reject", content

def generate_artwork_venice(prompt, album_name):
    out_path = os.path.join(ARTWORK_DIR, f"{album_name.replace(' ', '_')}_cover.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    if not VENICE_API_KEY:
        logger.error("VENICE_API_KEY missing, skipping raw API call.")
        return None
        
    url = "https://api.venice.ai/api/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {VENICE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "grok-imagine-image-quality",
        "prompt": f"{prompt} NO TEXT, NO LETTERS, NO TYPOGRAPHY",
        "response_format": "b64_json"
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            b64 = data.get('data', [{}])[0].get('b64_json')
            if b64:
                with open(out_path, 'wb') as f:
                    f.write(base64.b64decode(b64))
                return out_path
    except Exception as e:
        logger.error(f"Venice API generation failed: {e}")
    return None


def phase_3_daw_handoff(proposal, tracklist):
    album_name = proposal.get('album', 'release').replace(' ', '_').replace('-', '_')
    send_message(f"🎛️ Creating DAWAGENT session for <b>{proposal.get('album')}</b>...")
    
    # 1. Create session — use BPM from first track if available
    bpm = str(tracklist[0].get('bpm', '130')) if tracklist else '130'
    subprocess.run(["/opt/hermes/.venv/bin/python3", DAWCTL_SCRIPT, "session", "create", "--name", album_name, "--sr", "48000", "--bpm", bpm])
    
    # 2. Write Handoff
    stems = []
    stem_names = []
    for t in tracklist:
        if t.get('flac_path') and os.path.exists(t.get('flac_path')):
            stems.append(t['flac_path'])
        elif t.get('mp3_path') and os.path.exists(t.get('mp3_path')):
            stems.append(t['mp3_path'])
        stem_names.append(t.get('title', f"Track_{t.get('track')}"))
        
    if not stems:
        send_message("❌ No stems found for DAW handoff!")
        return
        
    subprocess.run([
        "/opt/hermes/.venv/bin/python3", HANDOFF_SCRIPT, "write",
        "--session", album_name,
        "--stems", ",".join(stems),
        "--stem-names", ",".join(stem_names),
        "--notes", f"Mastering for {proposal.get('album')}"
    ])
    
    send_message(f"✅ DAW Session `{album_name}` created and populated. Waiting for DAWAGENT masters (polling `/opt/data/dawagent/exports/{album_name}`)...")
    send_agent_notification("Waiting for DAW masters")
    
    # 3. Poll for masters
    exports_dir = f"/opt/data/dawagent/exports/{album_name}"
    poll_start = time.time()
    max_wait = 48 * 3600  # 48 hours
    last_status = time.time()
    while True:
        elapsed = time.time() - poll_start
        if elapsed > max_wait:
            send_message("⏰ Master polling timed out after 48 hours. Pipeline paused — use --resume to continue.")
            save_state({"phase": 3, "tracklist": tracklist, "proposal": proposal})
            return
        # Send status every 30 minutes
        if time.time() - last_status > 1800:
            hours = int(elapsed // 3600)
            mins = int((elapsed % 3600) // 60)
            send_message(f"⏳ Still waiting for masters… {hours}h {mins}m elapsed")
            last_status = time.time()
        time.sleep(10)
        if os.path.exists(exports_dir):
            masters = [f for f in os.listdir(exports_dir) if f.endswith("_MASTER.flac")]
            if len(masters) >= len(tracklist):
                break
    
    send_message(f"🎚️ Master FLACs detected! Sending for final audio approval...")
    
    # 4. Send audio
    for t in tracklist:
        title = t.get('title')
        master_path = os.path.join(exports_dir, f"{title}_MASTER.flac")
        if os.path.exists(master_path):
            t['master_path'] = master_path
            send_audio(master_path, caption=f"💿 MASTER: {title}")
            
    # 5. Wait for approval
    buttons = [
        [{"text": "✅ Approve Masters", "callback_data": "ap:master:approve"}],
        [{"text": "🔄 Wait for Re-export", "callback_data": "ap:master:wait"}]
    ]
    send_message("Please review the final masters:", reply_markup={"inline_keyboard": buttons})
    
    while True:
        flag, content = poll_flags()
        if flag == "master_approved":
            break
        elif flag == "master_wait":
            send_message("Waiting for re-export... (Replace files in exports dir and click Approve when ready)")
            # Only remove specific flag, not all flags
            try:
                os.remove(os.path.join(FLAGS_DIR, "master_wait"))
            except FileNotFoundError:
                pass

def phase_4_artwork(proposal, tracklist):
    send_agent_notification("User approved songs, generating artwork")
    send_message("🎨 Generating album cover + all track covers...")
    
    album_name = proposal.get('album', 'Unknown Album')
    visual = proposal.get('visual', '')
    track_names = ",".join([t.get('title', '') for t in tracklist])
    
    while True:
        # ── 1. Generate album cover ──
        cover_path = generate_artwork_venice(visual, album_name)
        if not cover_path:
            cmd = [
                "/opt/hermes/.venv/bin/python3", GEN_ARTWORK_SCRIPT,
                "--prompt", f"{visual} NO TEXT, NO LETTERS, NO TYPOGRAPHY",
                "--model", "grok-imagine-image-quality",
                "--album", album_name,
                "--tracks", track_names
            ]
            subprocess.run(cmd)
            cover_path = os.path.join(ARTWORK_DIR, f"{album_name.replace(' ', '_')}_cover.png")
            
        # Optional title overlay on album cover
        if os.path.exists(OVERLAY_TITLE_SCRIPT) and cover_path and os.path.exists(cover_path):
            styled_album = stylize_title(album_name)
            subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                "--image", cover_path, "--title", styled_album, "--auto-color", "--output", cover_path])
        
        if cover_path and os.path.exists(cover_path):
            album_art_buttons = [[{"text": "🔄 Regen Album Cover", "callback_data": "ap:art:regen_album"}]]
            send_photo(cover_path, caption=f"🎨 Album Cover: {album_name}", reply_markup={"inline_keyboard": album_art_buttons})
        else:
            send_message("❌ Failed to generate album cover.")
            return
        
        # ── 2. Generate all track covers (each with its own regen button) ──
        track_cover_paths = _generate_all_track_covers(proposal, tracklist, visual)
        
        # ── 3. Final buttons after ALL covers shown ──
        buttons = [
            [{"text": "✅ Approve All Artwork", "callback_data": "ap:art:approve"}],
            [{"text": "🔄 Regenerate Everything", "callback_data": "ap:art:regen"}],
            [{"text": "✏️ Edit Direction", "callback_data": "ap:art:edit"}]
        ]
        send_message("👆 <b>Review all covers above. Tap 🔄 on any individual cover to redo it, or:</b>", reply_markup={"inline_keyboard": buttons})
        
        # ── 4. Poll — handle per-track redos or full approve/regen ──
        while True:
            flag, content = poll_flags()
            if flag == "art_approved":
                return
            elif flag == "art_edit":
                send_message(f"✏️ Regenerating with new direction: {content}")
                visual += f" {content}"
                break  # break inner loop → outer while regenerates everything
            elif flag == "art_regen":
                send_message("🔄 Regenerating all artwork from scratch...")
                break  # break inner loop → outer while regenerates everything
            elif flag == "art_regen_album":
                send_message("🔄 Regenerating album cover...")
                new_cover = generate_artwork_venice(visual, album_name)
                if new_cover and os.path.exists(new_cover):
                    if os.path.exists(OVERLAY_TITLE_SCRIPT):
                        styled_album = stylize_title(album_name)
                        subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                            "--image", new_cover, "--title", styled_album, "--auto-color", "--output", new_cover])
                    regen_btns = [[{"text": "🔄 Regen Album Cover", "callback_data": "ap:art:regen_album"}]]
                    send_photo(new_cover, caption=f"🎨 Album Cover (new): {album_name}", reply_markup={"inline_keyboard": regen_btns})
                else:
                    send_message("❌ Album cover regen failed")
                continue  # keep polling
            elif flag and flag.startswith("art_redo_"):
                try:
                    track_num = int(flag.split("_")[-1])
                except ValueError:
                    continue
                _redo_single_track_cover(proposal, tracklist, track_num, visual)
                continue  # keep polling

def _build_varied_scene(visual, title, direction, track_idx, total_tracks):
    """Build a varied but cohesive scene prompt for each track cover.
    
    Creates visual continuity through shared style/palette while varying:
    - Environment/setting
    - Weather/atmospheric effects
    - Camera angle/composition
    - Time of day / lighting
    - Color accent
    """
    # ── Environment progression (tells a visual story across tracks) ──
    environments = [
        "desolate volcanic wasteland with cracked obsidian ground and distant eruptions",
        "flooded industrial ruins with water reflecting burning sky, submerged machinery",
        "lightning-struck highway overpass above a sea of molten lava and ash clouds",
        "hurricane-ravaged cityscape with buildings torn apart, debris spiraling upward",
        "aftermath crater landscape under clearing skies, embers floating like fireflies",
    ]
    
    # ── Weather / atmospheric FX (each track gets a unique weather system) ──
    weather = [
        "raining molten fire droplets from a volcanic sky, pyroclastic flow in background",
        "torrential acid rain with neon reflections in puddles, thick fog rolling in",
        "massive lightning storm with forked bolts illuminating everything in purple-white",
        "category 5 hurricane winds with horizontal rain and swirling fire tornados",
        "ash snow falling gently through shafts of golden light breaking through dark clouds",
    ]
    
    # ── Camera angle / composition ──
    cameras = [
        "extreme wide shot, figure silhouetted against massive explosion",
        "low angle shot looking up through rain, reflections on wet ground",
        "aerial drone view looking down at destruction pattern, geometric chaos",
        "dutch angle close-up with debris flying past camera, motion blur",
        "symmetrical centered composition, long perspective vanishing into distance",
    ]
    
    # ── Time of day / lighting ──
    lighting = [
        "blood-red twilight, sky cracked with orange fissures",
        "deep midnight blue with bioluminescent accents and distant fires",
        "overcast bruised-purple sky with sickly green underlighting",
        "stark chiaroscuro with single harsh spotlight from above",
        "golden hour through smoke haze, long dramatic shadows",
    ]
    
    # ── Color accent (consistent series palette but each track has a hero color) ──
    color_accents = [
        "dominant crimson red and charcoal black",
        "deep ocean teal and rusted copper",
        "electric violet and ash grey",
        "molten amber-orange and obsidian",
        "ghostly silver-white and burnt umber",
    ]
    
    # Cycle through variations (wraps for albums > 5 tracks)
    env = environments[track_idx % len(environments)]
    wthr = weather[track_idx % len(weather)]
    cam = cameras[track_idx % len(cameras)]
    light = lighting[track_idx % len(lighting)]
    color = color_accents[track_idx % len(color_accents)]
    
    # Build the full scene prompt
    scene = (
        f"{visual}. "
        f"UNIQUE SCENE FOR THIS TRACK: {env}. "
        f"WEATHER: {wthr}. "
        f"CAMERA: {cam}. "
        f"LIGHTING: {light}. "
        f"COLOR PALETTE: {color}. "
        f"Track mood: {title} — {direction}. "
        f"IMPORTANT: This is track {track_idx + 1} of {total_tracks} in a cohesive album art series. "
        f"Same dark cinematic style and hyperdetailed quality throughout, but each cover must have "
        f"a DISTINCTLY DIFFERENT environment and atmosphere. "
        f"NO TEXT, NO LETTERS, NO TYPOGRAPHY, NO WORDS"
    )
    return scene

def _generate_all_track_covers(proposal, tracklist, visual):
    """Generate all track covers, each sent with its own regen button."""
    album_name = proposal.get('album', 'Unknown Album')
    track_art_dir = os.path.join(ARTWORK_DIR, album_name.replace(' ', '-'))
    os.makedirs(track_art_dir, exist_ok=True)
    
    send_message("🎨 Generating track covers with scene variation...")
    track_cover_paths = []
    
    for i, t in enumerate(tracklist):
        title = t.get('title', f'Track {i+1}')
        direction = t.get('direction', t.get('genre', ''))
        scene = _build_varied_scene(visual, title, direction, i, len(tracklist))
        
        send_agent_notification(f"Generating cover {i+1}/{len(tracklist)}: {title}")
        
        cover_path = generate_artwork_venice(scene, f"{album_name}/{title}")
        if cover_path and os.path.exists(cover_path):
            final_path = os.path.join(track_art_dir, f"{title}_cover.png")
            if cover_path != final_path:
                import shutil
                shutil.move(cover_path, final_path)
                cover_path = final_path
            
            # Waveform banner
            if os.path.exists(GEN_WAVEFORM_SCRIPT):
                subprocess.run(["/opt/hermes/.venv/bin/python3", GEN_WAVEFORM_SCRIPT,
                    "--image", cover_path, "--title", title,
                    "--output-dir", os.path.join(ARTWORK_DIR, "..", "waveforms", album_name.replace(' ', '-'))], capture_output=True)
            
            # Title overlay
            if os.path.exists(OVERLAY_TITLE_SCRIPT):
                styled_title = stylize_title(title)
                subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                    "--image", cover_path, "--title", styled_title,
                    "--bottom", "--auto-color", "--output", cover_path], capture_output=True)
            
            # Send with per-track regen button
            track_btn = [[{"text": f"🔄 Regen Track {i+1}", "callback_data": f"ap:art:redo:{i+1}"}]]
            send_photo(cover_path, caption=f"🎨 Track {i+1}: {title}", reply_markup={"inline_keyboard": track_btn})
            track_cover_paths.append(cover_path)
        else:
            send_message(f"⚠️ Failed to generate cover for {title}")
    
    send_message(f"✅ All {len(tracklist)} track covers generated!")
    return track_cover_paths

def _redo_single_track_cover(proposal, tracklist, track_num, visual):
    """Regenerate a single track cover and send the new one."""
    album_name = proposal.get('album', 'Unknown Album')
    track_art_dir = os.path.join(ARTWORK_DIR, album_name.replace(' ', '-'))
    
    idx = track_num - 1
    if idx < 0 or idx >= len(tracklist):
        send_message(f"❌ Track {track_num} not found")
        return
    
    t = tracklist[idx]
    title = t.get('title', f'Track {track_num}')
    direction = t.get('direction', t.get('genre', ''))
    scene = _build_varied_scene(visual, title, direction, idx, len(tracklist))
    
    send_message(f"🔄 Regenerating cover for Track {track_num}: {title}...")
    
    cover_path = generate_artwork_venice(scene, f"{album_name}/{title}")
    if cover_path and os.path.exists(cover_path):
        final_path = os.path.join(track_art_dir, f"{title}_cover.png")
        if cover_path != final_path:
            import shutil
            shutil.move(cover_path, final_path)
            cover_path = final_path
        
        if os.path.exists(OVERLAY_TITLE_SCRIPT):
            styled_title = stylize_title(title)
            subprocess.run(["/opt/hermes/.venv/bin/python3", OVERLAY_TITLE_SCRIPT,
                "--image", cover_path, "--title", styled_title,
                "--bottom", "--auto-color", "--output", cover_path], capture_output=True)
        
        track_btn = [[{"text": f"🔄 Regen Track {track_num}", "callback_data": f"ap:art:redo:{track_num}"}]]
        send_photo(cover_path, caption=f"🎨 Track {track_num}: {title} (NEW)", reply_markup={"inline_keyboard": track_btn})
    else:
        send_message(f"❌ Failed to regenerate cover for {title}")

def phase_5_final_review(tracklist, proposal):
    send_message("📦 Packaging final release files...")
    
    album_name = proposal.get('album', 'release')
    album_slug = album_name.lower().replace(' ', '-').replace('_', '-')
    release_dir = f"/opt/data/music/releases/{album_slug}"
    os.makedirs(release_dir, exist_ok=True)
    
    # Generate release.json
    release_json = {
        "title": album_name,
        "genre": proposal.get("subgenre", "Electronic"),
        "label": "VØIDRIDE",
        "release_date": time.strftime("%Y-%m-%d"),
        "description": proposal.get("description", proposal.get("brief", ""))
    }
    with open(os.path.join(release_dir, "release.json"), "w") as f:
        json.dump(release_json, f, indent=2)
        
    # Generate tracks_meta.json & copy masters
    tracks_meta = []
    import shutil
    for idx, t in enumerate(tracklist):
        title = t.get("title", f"Track_{idx+1}")
        tracks_meta.append({
            "title": title,
            "bpm": t.get("bpm"),
            "key": t.get("key"),
            "genre": proposal.get("subgenre", "Electronic")
        })
        # Copy master FLAC if it exists, otherwise fall back to raw audio
        master_path = t.get("master_path")
        if not master_path or not os.path.exists(master_path):
            # Fallback: try raw FLAC, then MP3
            master_path = t.get("flac_path") or t.get("mp3_path")
            if master_path:
                logger.warning(f"No master for {title}, using raw: {master_path}")
        if master_path and os.path.exists(master_path):
            ext = os.path.splitext(master_path)[1]
            flac_dest = os.path.join(release_dir, f"{(idx+1):02d}-{title.replace(' ', '-')}{ext}")
            shutil.copy2(master_path, flac_dest)
            
    with open(os.path.join(release_dir, "tracks_meta.json"), "w") as f:
        json.dump(tracks_meta, f, indent=2)
    
    res = subprocess.run(["/opt/hermes/.venv/bin/python3", SHARE_SCRIPT, "--path", release_dir], capture_output=True, text=True)
    if res.returncode == 0:
        link = res.stdout.strip()
        buttons = [
            [{"text": "🚀 Publish to SoundCloud", "callback_data": "ap:final:publish"}],
            [{"text": "↩️ Go Back", "callback_data": "ap:final:back"}]
        ]
        send_message(f"✅ Final Mastered Package Ready: {link}", reply_markup={"inline_keyboard": buttons})
    else:
        send_message("❌ Failed to package final release.")
        return "back"
        
    while True:
        flag, content = poll_flags()
        if flag == "final_publish":
            return "publish"
        elif flag == "final_back":
            return "back"

def phase_6_publish(proposal):
    album_slug = proposal.get('album', 'release').lower().replace(' ', '-')
    send_message("🚀 Publishing to SoundCloud...")
    
    cmd = ["/opt/hermes/.venv/bin/python3", PUBLISH_SCRIPT, "--release", album_slug, "--confirm", "--force"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    if res.returncode == 0:
        send_message(f"✅ {proposal.get('album')} is live on SoundCloud!")
        send_agent_notification("Published to SoundCloud")
    else:
        send_message(f"❌ Publish failed:\n{res.stderr}")

def main():
    parser = argparse.ArgumentParser(description="Album Production Pipeline")
    parser.add_argument("--proposal-index", type=int, default=0, help="Index of the proposal to produce")
    parser.add_argument("--resume", action="store_true", help="Resume from saved state")
    parser.add_argument("--test", action="store_true", help="Run in test mode (no execution)")
    args = parser.parse_args()

    if args.test:
        run_test_mode(args.proposal_index)
        return

    clear_flags()

    # Load state first for resume
    state = load_state()
    
    if args.resume and state.get("proposal"):
        logger.info(f"Resuming from phase {state.get('phase', 1)}")
        proposal = state["proposal"]
        profile = {}
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, 'r') as f:
                profile = json.load(f)
    else:
        # Load Proposal
        if not os.path.exists(PROPOSALS_FILE):
            logger.error(f"Proposals file not found: {PROPOSALS_FILE}")
            sys.exit(1)
        
        with open(PROPOSALS_FILE, 'r') as f:
            raw = json.load(f)
            proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
            if args.proposal_index >= len(proposals):
                logger.error(f"Invalid proposal index {args.proposal_index}")
                sys.exit(1)
            proposal = proposals[args.proposal_index]

        # Load Profile
        if not os.path.exists(PROFILE_FILE):
            logger.error(f"Profile file not found: {PROFILE_FILE}")
            sys.exit(1)
        with open(PROFILE_FILE, 'r') as f:
            profile = json.load(f)

    # Pipeline Loop
    tracklist = None
    redo_track, redo_feedback = None, None
    
    current_phase = state.get("phase", 1)
    if args.resume:
        tracklist = state.get("tracklist")
    else:
        current_phase = 1
        
    acquire_lock()
    
    try:
        while True:
            # Phase 1: Produce
            if current_phase <= 1:
                if not tracklist or redo_track or redo_feedback:
                    tracklist = phase_1_produce(proposal, profile, redo_track, redo_feedback)
                    redo_track, redo_feedback = None, None
                    state["tracklist"] = tracklist
                    state["proposal"] = proposal
                    state["phase"] = 2
                    save_state(state)
                current_phase = 2
                
            # Phase 2: Song Review
            if current_phase == 2:
                decision, payload = phase_2_song_review(tracklist)
                if decision == "reject":
                    send_message(f"Album rejected. Restarting production with new direction: {payload}")
                    proposal['description'] += f"\n[USER REVISION]: {payload}"
                    current_phase = 1
                    continue
                elif decision == "redo_track":
                    track_num = payload[0]
                    feedback = payload[1]
                    send_message(f"🔄 Redoing only track {track_num}...")
                    tracklist = phase_1_redo_single(proposal, profile, tracklist, track_num, feedback)
                    state["tracklist"] = tracklist
                    save_state(state)
                    # Stay in phase 2 for review — don't re-produce everything
                    continue
                elif decision == "approved":
                    send_message("✅ All songs approved! Moving to DAW Handoff & Mastering.")
                    state["phase"] = 3
                    save_state(state)
                    current_phase = 3
                    
            # Phase 3: DAW Handoff & Mastering
            if current_phase == 3:
                phase_3_daw_handoff(proposal, tracklist)
                state["tracklist"] = tracklist  # Update with master_paths
                state["phase"] = 4
                save_state(state)
                current_phase = 4

            # Phase 4: Artwork
            if current_phase == 4:
                art_decision = phase_4_artwork(proposal, tracklist)
                if art_decision == "publish":
                    state["phase"] = 6
                    save_state(state)
                    current_phase = 6
                else:
                    state["phase"] = 5
                    save_state(state)
                    current_phase = 5
                
            # Phase 5: Final Review (Packaging)
            if current_phase == 5:
                fin_decision = phase_5_final_review(tracklist, proposal)
                if fin_decision == "publish":
                    state["phase"] = 6
                    save_state(state)
                    current_phase = 6
                elif fin_decision == "back":
                    current_phase = 4
                    continue
                    
            # Phase 6: Publish
            if current_phase == 6:
                phase_6_publish(proposal)
                # Pipeline complete, clear state
                if os.path.exists(STATE_FILE):
                    os.remove(STATE_FILE)
                break
    finally:
        release_lock()
        clear_flags()
        
    logger.info("Pipeline complete.")

if __name__ == "__main__":
    main()
