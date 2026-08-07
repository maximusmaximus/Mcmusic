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
    {"direction": "heavy instrumental opener",
     "rules": ["Heavy bass-driven instrumental with massive buildup and drop",
               "Hard-hitting from second one — immediate presence",
               "Big spatial reverb on percussion, wide stereo field"]},
    {"direction": "smooth groove",
     "rules": ["Smooth but menacing groove with evolving percussion",
               "Bass buildup into a heavy sub drop midway",
               "Spatial panning on hi-hats — stereo movement"]},
    {"direction": "different lead instrument",
     "rules": ["Lead NOT 808 bass — use detuned synth lead or spectral plucks",
               "Bass drops with sidechain pumping",
               "Reverb throws on snare — spatial depth"]},
    {"direction": "tempo shift banger",
     "rules": ["Different BPM (±15 from others)",
               "Massive bass buildup with tension release into drop",
               "Wide stereo imaging — sounds that move across the field"]},
    {"direction": "atmospheric closer",
     "rules": ["Cinematic build to a final bass drop climax",
               "Spatial reverb and delay throws throughout",
               "Smooth evolving textures into heavy finale"]},
    {"direction": "experimental wildcard",
     "rules": ["Unexpected instrument choices with heavy bass foundation",
               "Bass drops that hit different from other tracks",
               "Spatial effects — panning, haas effect, reverb throws"]},
    {"direction": "groove-driven",
     "rules": ["Groove and rhythm with bass buildup tension",
               "Live-sounding drums with spatial placement",
               "Drop hits hard after a stripped-back buildup"]},
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", required=True, help="Album concept")
    parser.add_argument("--tracks", type=int, default=5)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--quality", default="quick", choices=["quick", "standard", "premium"])
    parser.add_argument("--target", default="streaming")
    parser.add_argument("--vocals-pct", type=int, default=0, help="Pct of tracks with vocals (0-100)")
    args = parser.parse_args()

    _auto_detect_chat_id()
    profile, slug = load_active_profile()
    profile_name = profile.get("name", "VØIDRIDE") if profile else "VØIDRIDE"

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

    progress_id = tg_send(
        f"⏳ *{args.brief}*\nGenerating {args.tracks} {mode}...")

    completed = []
    track_files = []
    total_cost = 0.0
    failed = 0
    track_times = []  # for ETA calculation
    avg_track_time = 0

    for i in range(args.tracks):
        track_num = i + 1
        variation = VARIATION_TEMPLATES[i % len(VARIATION_TEMPLATES)]
        has_vocals = i in vocal_positions

        if has_vocals:
            variation = {"direction": "subtle vocal texture",
                         "rules": ["Subtle breathy female vocals as background texture only",
                                   "Vocals ~5% of mix — atmosphere, not lead",
                                   "Bass drops still hit hard through the vocal sections"]}

        # Enrich the brief with variation rules for this track
        enriched_brief = (
            f"{args.brief}. "
            f"This track direction: {variation['direction']}. "
            f"Requirements: {'; '.join(variation['rules'])}"
        )

        # Album context
        ctx = {"track_number": track_num, "total_tracks": args.tracks,
               "brief": args.brief, "previous_tracks": completed,
               "variation_rules": variation["rules"]}
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

                info = {"title": f"Track {track_num}", "bpm": None, "key": None,
                        "genre": None, "has_vocals": has_vocals, "cost_usd": cost,
                        "direction": variation["direction"], "production_dir": prod_dir}

                if plan_path and os.path.isfile(plan_path):
                    with open(plan_path) as f:
                        plan = json.load(f)
                    info.update({"title": plan.get("title", info["title"]),
                                 "bpm": plan.get("bpm"), "key": plan.get("key"),
                                 "genre": plan.get("genre")})

                completed.append(info)
                # For full tracks, prefer FLAC; for samples, MP3 only
                send_file = mp3
                if mp3 and os.path.isfile(mp3):
                    track_files.append((info["title"], mp3, flac))
                log(f"    ✅ {info['title']} | {info.get('bpm','')} BPM | ${cost:.2f}")
            except Exception as e:
                log(f"    ✅ done (parse: {e})")
                completed.append({"title": f"Track {track_num}", "direction": variation["direction"]})
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
    unnamed = [t for t in completed if t.get("title", "").startswith("Track ")]
    if unnamed:
        log(f"  Naming {len(unnamed)} unnamed tracks...")
        api_key = os.environ.get("VENICE_API_KEY", "")
        directions = [t.get("direction", "dark phonk") for t in unnamed]
        album_short = args.brief.split(" - ")[0] if " - " in args.brief else args.brief[:30]
        try:
            prompt = (
                f"Generate {len(unnamed)} dark, evocative 1-3 word track names for a "
                f"nightride phonk album called '{album_short}'. "
                f"Track directions: {', '.join(f'{i+1}) {d}' for i, d in enumerate(directions))}. "
                f"Return ONLY a JSON array of strings. Example: [\"MIDNIGHT PULSE\", \"GHOST WIRE\"]"
            )
            payload = json.dumps({
                "model": "qwen-3-7-plus",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.9, "max_tokens": 200,
            }).encode()
            req = urllib.request.Request(
                "https://api.venice.ai/api/v1/chat/completions",
                data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=30)
            raw = json.loads(resp.read())["choices"][0]["message"]["content"]
            import re as _re
            match = _re.search(r'\[.*\]', raw, _re.DOTALL)
            if match:
                names = json.loads(match.group())
                for t, name in zip(unnamed, names):
                    t["title"] = str(name).upper()
                    log(f"    Named: {t['title']}")
        except Exception as e:
            log(f"    Venice naming failed ({e}), using fallback names")
            # Fallback: generate from direction
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
            for t in unnamed:
                t["title"] = FALLBACK_NAMES.get(t.get("direction", ""), f"TRACK {t.get('number', '?')}")
                log(f"    Fallback: {t['title']}")

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
