#!/usr/bin/env python3
"""
Venice AI Music Generator — async queue lifecycle handler.

Usage:
    python3 venice-music.py --model MODEL --prompt TEXT [--lyrics TEXT]
                            [--duration SECONDS] [--instrumental]
                            [--output DIR]

Handles the full Venice audio API lifecycle:
  1. POST /audio/queue   → get queue_id
  2. POST /audio/retrieve → poll until complete, download audio
  3. POST /audio/complete → cleanup server storage

Outputs JSON to stdout with the result.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

VENICE_API_BASE = "https://api.venice.ai/api/v1"
DEFAULT_OUTPUT_DIR = "/opt/data/music"
MAX_POLL_TIME = 600  # 10 minutes max wait
POLL_INTERVAL = 5    # seconds between polls

# Telegram progress notifications
_CHAT_ID = None
_BOT_TOKEN = None
_LAST_NOTIFY_TIME = 0
_SILENT_MODE = os.environ.get("HERMES_SILENT", "").lower() in ("1", "true", "yes")


def _auto_detect_telegram():
    """Auto-detect Telegram bot token and chat ID from Hermes environment."""
    global _CHAT_ID, _BOT_TOKEN
    _BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not _BOT_TOKEN:
        return

    # If --chat-id was passed, use it
    if _CHAT_ID:
        return

    # Auto-detect from Hermes sessions.json
    sessions_path = os.path.join(
        os.environ.get("HERMES_HOME", "/opt/data"), "sessions", "sessions.json"
    )
    try:
        with open(sessions_path, "r") as f:
            sessions = json.load(f)
        # Find the most recently active telegram session
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
        pass  # No sessions file or parse error — silent


def telegram_notify(msg, force=False):
    """Send a progress message to the user's Telegram chat."""
    global _LAST_NOTIFY_TIME
    if _SILENT_MODE or not _CHAT_ID or not _BOT_TOKEN:
        return
    # Rate limit: at most one message every 10 seconds unless forced
    now = time.time()
    if not force and (now - _LAST_NOTIFY_TIME) < 10:
        return
    _LAST_NOTIFY_TIME = now
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
        pass  # Don't fail the generation if notification fails

# Model constraints discovered from Venice API errors
MODEL_CONSTRAINTS = {
    "elevenlabs-music": {
        "supports_lyrics": False,       # 400 error if lyrics_prompt is sent
        "requires_lyrics": False,
        "supports_duration": True,
        "supports_instrumental": True,
        "max_duration": 600,
        "output_format": "mp3",
    },
    "minimax-music-v2": {
        "supports_lyrics": True,
        "requires_lyrics": True,        # API requires lyrics_prompt field
        "supports_duration": False,      # 400 error if duration_seconds is sent
        "supports_instrumental": False,
        "output_format": "mp3",
    },
    "ace-step-15": {
        "supports_lyrics": True,
        "requires_lyrics": True,        # API requires lyrics_prompt field
        "supports_duration": True,
        "supports_instrumental": False,
        "valid_durations": [60, 90, 120, 150, 180, 210],
        "output_format": "flac",
    },
    "stable-audio-25": {
        "supports_lyrics": False,
        "requires_lyrics": False,
        "supports_duration": True,
        "supports_instrumental": False,
        "max_duration": 180,
        "output_format": "wav",
    },
    "elevenlabs-sound-effects-v2": {
        "supports_lyrics": False,
        "requires_lyrics": False,
        "supports_duration": False,
        "supports_instrumental": False,
        "output_format": "mp3",
    },
    "mmaudio-v2-text-to-audio": {
        "supports_lyrics": False,
        "requires_lyrics": False,
        "supports_duration": False,
        "supports_instrumental": False,
        "output_format": "mp3",
    },
}

# Models that produce sound effects (not music)
SFX_MODELS = {"elevenlabs-sound-effects-v2", "mmaudio-v2-text-to-audio"}


def slugify(text, max_len=40):
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = text.strip('-')
    if len(text) > max_len:
        text = text[:max_len].rsplit('-', 1)[0]
    return text or 'untitled'


def get_output_subdir(base_dir, model, prompt):
    """Determine organized output subdirectory based on model type."""
    today = datetime.now().strftime("%Y-%m-%d")
    if model in SFX_MODELS:
        subdir = os.path.join(base_dir, "sfx", today)
    else:
        subdir = os.path.join(base_dir, "singles", today)
    os.makedirs(subdir, exist_ok=True)
    return subdir


def get_api_key():
    """Get Venice API key from environment."""
    key = os.environ.get("VENICE_API_KEY", "")
    if not key:
        key = os.environ.get("VENICE_INFERENCE_KEY", "")
    if not key:
        fail("VENICE_API_KEY environment variable is not set")
    return key


def validate_params(model, prompt, lyrics, duration, instrumental):
    """Validate parameters against known model constraints. Auto-fix where possible."""
    constraints = MODEL_CONSTRAINTS.get(model)
    if not constraints:
        log(f"Warning: Unknown model '{model}', skipping parameter validation")
        return prompt, lyrics, duration, instrumental

    # Prompt minimum length (Venice requires >= 10 chars)
    if len(prompt) < 10:
        prompt = prompt + " " + "music audio generation"
        log(f"Warning: prompt too short — padded to: {prompt}")

    # Lyrics: strip if unsupported
    if lyrics and not constraints.get("supports_lyrics", False):
        log(f"Warning: {model} does not support lyrics — removing lyrics_prompt")
        lyrics = None

    # Lyrics: auto-generate placeholder if required but not provided
    if not lyrics and constraints.get("requires_lyrics", False):
        lyrics = "[instrumental]"
        log(f"Warning: {model} requires lyrics_prompt — auto-set to '[instrumental]'")

    # Duration check
    if duration and not constraints.get("supports_duration", False):
        log(f"Warning: {model} does not support duration — removing duration_seconds")
        duration = None

    # Valid durations check (ace-step-15)
    if duration and "valid_durations" in constraints:
        valid = constraints["valid_durations"]
        if duration not in valid:
            nearest = min(valid, key=lambda x: abs(x - duration))
            log(f"Warning: {model} only accepts durations {valid} — snapping {duration}s to {nearest}s")
            duration = nearest

    # Max duration check
    if duration and "max_duration" in constraints:
        max_dur = constraints["max_duration"]
        if duration > max_dur:
            log(f"Warning: {model} max duration is {max_dur}s — capping from {duration}s")
            duration = max_dur

    # Instrumental check
    if instrumental and not constraints.get("supports_instrumental", False):
        log(f"Warning: {model} does not support force_instrumental — removing flag")
        instrumental = False

    return prompt, lyrics, duration, instrumental


def api_request(endpoint, payload, api_key, accept="application/json"):
    """Make a POST request to the Venice API. Returns (response_bytes, content_type)."""
    url = f"{VENICE_API_BASE}{endpoint}"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": accept,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            content_type = resp.headers.get("Content-Type", "application/json")
            body = resp.read()
            return body, content_type
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get("error", error_body)
        except json.JSONDecodeError:
            error_msg = error_body
        fail(f"API error ({e.code}): {error_msg}")
    except urllib.error.URLError as e:
        fail(f"Connection error: {e.reason}")


def quote_audio(api_key, model, duration=None):
    """Get a cost quote from Venice /audio/quote. Returns cost dict."""
    payload = {"model": model}
    # Only add duration if the model supports it
    constraints = MODEL_CONSTRAINTS.get(model, {})
    if duration and constraints.get("supports_duration", True):
        payload["duration_seconds"] = int(duration)

    try:
        body, _ = api_request("/audio/quote", payload, api_key)
        result = json.loads(body)
        cost_usd = result.get("quote", 0)
        credits = int(cost_usd * 100)  # 100 credits = $1 USD
        log(f"Quote: ${cost_usd:.4f} ({credits} credits) for {model}")
        return {"cost_usd": float(cost_usd), "credits": credits, "model": model}
    except Exception as e:
        log(f"Quote failed for {model}: {e}")
        return {"cost_usd": 0, "credits": 0, "model": model, "estimated": True}


def queue_audio(api_key, model, prompt, lyrics=None, duration=None, instrumental=False):
    """Queue an audio generation request. Returns (queue_id, quote)."""
    # Get cost quote first
    quote = quote_audio(api_key, model, duration)

    payload = {
        "model": model,
        "prompt": prompt,
    }

    if lyrics:
        payload["lyrics_prompt"] = lyrics

    if duration:
        payload["duration_seconds"] = int(duration)

    if instrumental:
        payload["force_instrumental"] = True

    log(f"Queuing generation: model={model}")
    if duration:
        log(f"  Duration: {duration}s")
    if lyrics:
        log(f"  Lyrics: {lyrics[:60]}...")
    if instrumental:
        log(f"  Mode: instrumental")
    log(f"  Payload: {json.dumps(payload)}")

    body, _ = api_request("/audio/queue", payload, api_key)
    result = json.loads(body)

    queue_id = result.get("queue_id")
    if not queue_id:
        fail(f"No queue_id in response: {result}")

    log(f"Queued successfully: queue_id={queue_id}")
    return queue_id, quote


def retrieve_audio(api_key, model, queue_id, output_dir, prompt=""):
    """Poll for audio completion and download. Returns output file path."""
    start_time = time.time()
    poll_count = 0

    while True:
        elapsed = time.time() - start_time
        if elapsed > MAX_POLL_TIME:
            fail(f"Timed out after {MAX_POLL_TIME}s waiting for generation")

        poll_count += 1
        payload = {
            "model": model,
            "queue_id": queue_id,
            "delete_media_on_completion": True,
        }

        # Accept both JSON (status) and audio (completed)
        body, content_type = api_request(
            "/audio/retrieve",
            payload,
            api_key,
            accept="audio/mpeg, audio/wav, audio/flac, application/json",
        )

        # If JSON, it's a status update
        if "application/json" in content_type:
            status_data = json.loads(body)
            status = status_data.get("status", "UNKNOWN")

            if status == "PROCESSING":
                avg_time = status_data.get("average_execution_time", 0)
                exec_dur = status_data.get("execution_duration", 0)
                avg_secs = avg_time / 1000 if avg_time else 0
                exec_secs = exec_dur / 1000 if exec_dur else 0
                log(f"Processing... {exec_secs:.0f}s / ~{avg_secs:.0f}s est [poll #{poll_count}]")
                # Send progress update every ~30 seconds
                if avg_secs > 0:
                    pct = min(95, int(exec_secs / avg_secs * 100))
                    bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
                    telegram_notify(f"⏳ Generating... {bar} {pct}%\n⏱️ {exec_secs:.0f}s / ~{avg_secs:.0f}s estimated")
                else:
                    telegram_notify(f"⏳ Generating... {exec_secs:.0f}s elapsed")
                time.sleep(POLL_INTERVAL)
                continue
            elif status == "QUEUED":
                log(f"Queued, waiting... [poll #{poll_count}]")
                telegram_notify(f"🔄 Queued, waiting for server...")
                time.sleep(POLL_INTERVAL)
                continue
            else:
                fail(f"Unexpected status: {status} — {status_data}")

        # Audio data received!
        ext_map = {
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/flac": ".flac",
        }
        # Default based on model constraints
        default_ext = "." + MODEL_CONSTRAINTS.get(model, {}).get("output_format", "mp3")
        ext = default_ext
        for ct, extension in ext_map.items():
            if ct in content_type:
                ext = extension
                break

        # Organize into subdirectories: singles/YYYY-MM-DD/ or sfx/YYYY-MM-DD/
        organized_dir = get_output_subdir(output_dir, model, prompt)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prompt_slug = slugify(prompt)

        # Save raw file first
        raw_filename = f"{timestamp}_{model}_{prompt_slug}{ext}"
        raw_path = os.path.join(organized_dir, raw_filename)
        with open(raw_path, "wb") as f:
            f.write(body)

        gen_time = time.time() - start_time
        size_kb = len(body) / 1024
        log(f"Raw audio saved: {raw_path} ({size_kb:.0f} KB, {gen_time:.1f}s generation)")

        # Convert to FLAC (lossless, 24-bit, 48kHz) as primary output
        flac_filename = f"{timestamp}_{model}_{prompt_slug}.flac"
        flac_path = os.path.join(organized_dir, flac_filename)
        mp3_filename = f"{timestamp}_{model}_{prompt_slug}.mp3"
        mp3_path = os.path.join(organized_dir, mp3_filename)

        try:
            import subprocess
            # FLAC: lossless master copy
            if ext != ".flac":
                cmd_flac = [
                    "ffmpeg", "-y", "-i", raw_path,
                    "-ar", "48000", "-ac", "2", "-sample_fmt", "s32",
                    flac_path,
                ]
                res = subprocess.run(cmd_flac, capture_output=True, text=True, timeout=60)
                if res.returncode == 0:
                    log(f"FLAC master: {flac_path}")
                else:
                    log(f"FLAC conversion failed, using raw: {res.stderr[-150:]}")
                    flac_path = raw_path
            else:
                flac_path = raw_path  # Already FLAC

            # MP3: high-quality portable copy
            if ext != ".mp3":
                cmd_mp3 = [
                    "ffmpeg", "-y", "-i", raw_path,
                    "-b:a", "320k", "-id3v2_version", "3",
                    mp3_path,
                ]
                res = subprocess.run(cmd_mp3, capture_output=True, text=True, timeout=60)
                if res.returncode == 0:
                    log(f"MP3 copy:    {mp3_path}")
                else:
                    log(f"MP3 conversion failed: {res.stderr[-150:]}")
                    mp3_path = None
            else:
                mp3_path = raw_path  # Already MP3, FLAC is the conversion

            # Clean up raw file if we have both conversions and raw isn't one of them
            if raw_path != flac_path and raw_path != mp3_path and os.path.exists(flac_path):
                os.remove(raw_path)
                log(f"Cleaned up raw: {raw_path}")

        except Exception as e:
            log(f"Conversion error (raw file preserved): {e}")
            flac_path = raw_path

        return flac_path, gen_time


def log(msg):
    """Log to stderr so stdout stays clean for JSON output."""
    print(f"[venice-music] {msg}", file=sys.stderr, flush=True)


def fail(msg):
    """Output error JSON and exit."""
    print(json.dumps({"success": False, "error": msg}))
    sys.exit(1)


def main():
    global _CHAT_ID, _BOT_TOKEN
    parser = argparse.ArgumentParser(description="Generate audio via Venice AI")
    parser.add_argument("--model", required=True, help="Venice model ID")
    parser.add_argument("--prompt", required=True, help="Audio description prompt")
    parser.add_argument("--lyrics", default=None, help="Song lyrics (vocal models only)")
    parser.add_argument("--duration", type=int, default=None, help="Duration in seconds")
    parser.add_argument("--instrumental", action="store_true", help="Force instrumental (elevenlabs-music only)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--chat-id", default=None, help="Telegram chat ID for progress updates (auto-detected if omitted)")

    args = parser.parse_args()

    # Set up Telegram notifications — auto-detect if --chat-id not passed
    _CHAT_ID = args.chat_id
    _auto_detect_telegram()
    api_key = get_api_key()

    # Validate and auto-fix parameters based on model constraints
    prompt, lyrics, duration, instrumental = validate_params(
        args.model, args.prompt, args.lyrics, args.duration, args.instrumental
    )

    log(f"Starting generation: {args.model}")
    log(f"Prompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}")

    model_name = args.model.replace('-', ' ').title()
    telegram_notify(f"⏳ *Generating audio...*\n🎛️ Model: {model_name}\n⏱️ This may take 1-5 minutes", force=True)

    # Step 1: Queue
    queue_id, quote = queue_audio(
        api_key=api_key,
        model=args.model,
        prompt=prompt,
        lyrics=lyrics,
        duration=duration,
        instrumental=instrumental,
    )

    # Step 2: Poll + Retrieve
    output_path, gen_time = retrieve_audio(
        api_key=api_key,
        model=args.model,
        queue_id=queue_id,
        output_dir=args.output,
        prompt=prompt,
    )
    # Send completion + cost notification
    model_name = args.model.replace('-', ' ').title()
    cost_usd = quote.get("cost_usd", 0)
    credits = quote.get("credits", 0)
    telegram_notify(
        f"✅ *Audio ready!*\n"
        f"🎛️ Model: {model_name}\n"
        f"⏱️ Generated in {gen_time:.0f}s\n"
        f"💰 Cost: ${cost_usd:.4f} ({credits} credits)\n"
        f"📎 Sending file...",
        force=True,
    )

    # Output result JSON
    result = {
        "success": True,
        "file": output_path,
        "model": args.model,
        "duration_requested": duration,
        "generation_time_seconds": round(gen_time, 1),
        "cost": quote,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
