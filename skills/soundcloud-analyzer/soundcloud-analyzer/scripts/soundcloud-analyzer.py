#!/usr/bin/env python3
"""SoundCloud Playlist Analyzer — AI-powered music tagging and vector search.

Fetches public playlist metadata via yt-dlp, uses Venice AI for intelligent
tagging and description, and stores everything in a SQLite-backed vector
database for semantic search.

Commands:
    analyze   - Analyze a SoundCloud playlist URL
    search    - Semantic search across analyzed tracks
    describe  - Show detailed report for a playlist
    list      - List all analyzed playlists
"""

import argparse
import json
import math
import os
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VENICE_API_BASE = "https://api.venice.ai/api/v1"
ANALYSIS_MODEL = "zai-org-glm-5-2"  # Best for detailed analysis (1M context)
EMBEDDING_MODEL = "text-embedding-bge-m3"
DB_PATH = "/opt/data/soundcloud-analyzer/vectors.db"
DATA_DIR = "/opt/data/soundcloud-analyzer"

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds

# ---------------------------------------------------------------------------
# Logging helpers — all non-JSON output goes to stderr
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    """Print a progress/debug message to stderr."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


def emit_json(obj: dict) -> None:
    """Write a JSON object to stdout (the only thing that should go there)."""
    print(json.dumps(obj, indent=2, ensure_ascii=False), flush=True)


def emit_error(message: str) -> None:
    """Emit a structured error and exit."""
    emit_json({"success": False, "error": message})
    sys.exit(1)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    """Initialise SQLite database and return a connection."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS playlists (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        url             TEXT UNIQUE,
        title           TEXT,
        description     TEXT,
        analyzed_at     TEXT,
        track_count     INTEGER,
        commonalities_json TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS tracks (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        playlist_id       INTEGER,
        title             TEXT,
        artist            TEXT,
        url               TEXT,
        genre             TEXT,
        duration_ms       INTEGER,
        artwork_url       TEXT,
        raw_metadata_json TEXT,
        ai_analysis_json  TEXT,
        embedding_blob    BLOB,
        analyzed_at       TEXT,
        FOREIGN KEY (playlist_id) REFERENCES playlists(id)
    )""")
    conn.commit()
    return conn

# ---------------------------------------------------------------------------
# Embedding pack / unpack
# ---------------------------------------------------------------------------

def pack_embedding(vec: list) -> bytes:
    """Pack a list of floats into a compact binary blob."""
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob: bytes) -> list:
    """Unpack a binary blob back into a list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))

# ---------------------------------------------------------------------------
# Cosine similarity (pure-Python, no numpy)
# ---------------------------------------------------------------------------

def cosine_similarity(a: list, b: list) -> float:
    """Compute cosine similarity between two float vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

# ---------------------------------------------------------------------------
# Venice AI helpers
# ---------------------------------------------------------------------------

def venice_api_call(endpoint: str, payload: dict, timeout: int = 120) -> dict:
    """Make an authenticated call to the Venice AI API with retries."""
    api_key = os.environ.get("VENICE_API_KEY", "")
    if not api_key:
        emit_error("VENICE_API_KEY environment variable is not set.")

    url = f"{VENICE_API_BASE}/{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
            last_err = exc
            wait = RETRY_BACKOFF_BASE ** attempt
            log(f"Venice API attempt {attempt}/{MAX_RETRIES} failed: {exc}. "
                f"Retrying in {wait}s …")
            time.sleep(wait)

    emit_error(f"Venice API call failed after {MAX_RETRIES} retries: {last_err}")
    return {}  # unreachable but keeps linters happy


def venice_chat(system_prompt: str, user_prompt: str) -> str:
    """Send a chat completion request and return the assistant message."""
    payload = {
        "model": ANALYSIS_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    resp = venice_api_call("chat/completions", payload)
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        emit_error(f"Unexpected Venice chat response structure: {exc}")
        return ""


def venice_embed(text: str) -> list:
    """Return the embedding vector for *text*."""
    payload = {
        "model": EMBEDDING_MODEL,
        "input": text,
        "encoding_format": "float",
    }
    resp = venice_api_call("embeddings", payload)
    try:
        return resp["data"][0]["embedding"]
    except (KeyError, IndexError) as exc:
        emit_error(f"Unexpected Venice embedding response structure: {exc}")
        return []

# ---------------------------------------------------------------------------
# Telegram notifications
# ---------------------------------------------------------------------------

def send_telegram(chat_id: str, text: str) -> None:
    """Send a Markdown-formatted Telegram message. Silently ignores errors."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        log("Telegram notification failed (non-fatal).")

# ---------------------------------------------------------------------------
# yt-dlp helpers
# ---------------------------------------------------------------------------

def fetch_playlist_metadata(url: str) -> dict:
    """Use yt-dlp --flat-playlist to grab high-level playlist metadata."""
    log(f"Fetching playlist metadata for: {url}")
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-single-json", url],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        emit_error("yt-dlp is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        emit_error("yt-dlp timed out fetching playlist metadata.")

    if result.returncode != 0:
        stderr_msg = result.stderr.strip() if result.stderr else "unknown error"
        emit_error(f"yt-dlp failed: {stderr_msg}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        emit_error("yt-dlp returned invalid JSON for the playlist.")
    return {}


def fetch_track_metadata(track_url: str) -> dict:
    """Fetch detailed metadata for a single track via yt-dlp."""
    log(f"  Fetching track detail: {track_url}")
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-single-json", "--skip-download", track_url],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        log(f"  ⚠ yt-dlp timed out for {track_url}, using flat data only.")
        return {}
    except FileNotFoundError:
        emit_error("yt-dlp is not installed or not on PATH.")

    if result.returncode != 0:
        log(f"  ⚠ yt-dlp returned non-zero for {track_url}, using flat data only.")
        return {}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        log(f"  ⚠ Invalid JSON for {track_url}, using flat data only.")
        return {}

# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def validate_soundcloud_url(url: str) -> None:
    """Ensure *url* looks like a SoundCloud playlist/set URL."""
    if not url:
        emit_error("No URL provided.")
    if "soundcloud.com" not in url.lower():
        emit_error(f"URL does not appear to be a SoundCloud link: {url}")

# ---------------------------------------------------------------------------
# Track analysis prompt
# ---------------------------------------------------------------------------

TRACK_SYSTEM_PROMPT = """\
You are a professional music analyst and curator.  Given metadata about a music \
track, produce a detailed analytical profile.  Respond ONLY with valid JSON using \
the exact schema below.  Do not add commentary outside the JSON.

Required JSON schema:
{
  "description": "2-3 sentence detailed description of the track",
  "genre": {
    "primary": "primary genre",
    "subgenres": ["subgenre1", "subgenre2"]
  },
  "mood_tags": ["tag1", "tag2", "tag3"],
  "energy_level": 7,
  "instrumentation": ["instrument1", "instrument2"],
  "production_style": ["tag1", "tag2"],
  "similar_artists": ["artist1", "artist2"],
  "bpm_estimate": 120,
  "key_signature_estimate": "C minor",
  "lyrical_themes": ["theme1", "theme2"],
  "sonic_palette": ["descriptor1", "descriptor2"],
  "danceability": 6,
  "emotional_arc": "Brief description of the emotional arc"
}

Guidelines:
- energy_level and danceability are integers 1-10
- bpm_estimate is an integer
- If information is unknown, make your best educated guess based on genre/context
- mood_tags should have 3-5 entries
- similar_artists should have 2-3 entries
- Provide thoughtful, nuanced analysis\
"""

PLAYLIST_SYSTEM_PROMPT = """\
You are a professional music curator.  Given a list of track analyses from a \
playlist, produce an overall playlist-level analysis.  Respond ONLY with valid \
JSON using the exact schema below.

Required JSON schema:
{
  "description": "3-5 sentence description of the playlist as a whole",
  "common_themes": ["theme1", "theme2"],
  "genre_distribution": {"genre1": 0.4, "genre2": 0.3, "genre3": 0.3},
  "mood_progression": "Description of the mood progression / emotional journey",
  "production_patterns": ["pattern1", "pattern2"],
  "unifying_elements": "What ties these tracks together",
  "recommended_context": ["context1", "context2"]
}

Guidelines:
- genre_distribution values should sum to ~1.0
- recommended_context examples: "late-night drive", "morning workout", "deep focus"
- Be insightful and specific, not generic\
"""

# ---------------------------------------------------------------------------
# Core: analyze command
# ---------------------------------------------------------------------------

def cmd_analyze(args) -> None:
    """Analyze a SoundCloud playlist."""
    url = args.url
    telegram_chat = getattr(args, "telegram_chat", None)

    validate_soundcloud_url(url)

    # 1. Fetch playlist ----------------------------------------------------------
    playlist_data = fetch_playlist_metadata(url)
    playlist_title = playlist_data.get("title", "Unknown Playlist")
    entries = playlist_data.get("entries") or []

    if not entries:
        emit_error("Playlist has no tracks or could not be parsed.")

    log(f"Playlist: {playlist_title} ({len(entries)} tracks)")
    send_telegram(
        telegram_chat or "",
        f"🎵 *Analyzing playlist:* {playlist_title}\n"
        f"Tracks: {len(entries)}",
    )

    conn = init_db()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Upsert playlist row -------------------------------------------------------
    existing = conn.execute(
        "SELECT id FROM playlists WHERE url = ?", (url,)
    ).fetchone()
    if existing:
        playlist_id = existing["id"]
        # Delete old tracks so we re-analyze cleanly
        conn.execute("DELETE FROM tracks WHERE playlist_id = ?", (playlist_id,))
        conn.execute(
            "UPDATE playlists SET title=?, analyzed_at=?, track_count=? WHERE id=?",
            (playlist_title, now_iso, len(entries), playlist_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO playlists (url, title, description, analyzed_at, track_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (url, playlist_title, playlist_data.get("description", ""), now_iso, len(entries)),
        )
        playlist_id = cur.lastrowid
    conn.commit()

    # 2. Per-track analysis ------------------------------------------------------
    track_analyses = []
    total = len(entries)

    for idx, entry in enumerate(entries, 1):
        track_title = entry.get("title") or "Unknown"
        track_url = entry.get("url") or entry.get("webpage_url") or ""
        artist = entry.get("uploader") or entry.get("channel") or "Unknown"

        log(f"[{idx}/{total}] Analyzing: {track_title} by {artist}")
        send_telegram(
            telegram_chat or "",
            f"🔍 [{idx}/{total}] Analyzing: _{track_title}_ by {artist}",
        )

        # Fetch richer metadata if the flat entry is sparse ----------------------
        meta = dict(entry)
        needs_detail = not meta.get("genre") and not meta.get("description")
        if needs_detail and track_url:
            detailed = fetch_track_metadata(track_url)
            if detailed:
                # Merge detailed into meta, preferring detailed values
                for k, v in detailed.items():
                    if v and (not meta.get(k)):
                        meta[k] = v

        # Build user prompt for Venice AI ----------------------------------------
        meta_summary = _build_track_summary(meta)
        user_prompt = (
            f"Analyze this track based on the following metadata:\n\n{meta_summary}"
        )

        # Call Venice AI for analysis --------------------------------------------
        raw_ai = venice_chat(TRACK_SYSTEM_PROMPT, user_prompt)
        try:
            ai_analysis = json.loads(raw_ai)
        except json.JSONDecodeError:
            log(f"  ⚠ Could not parse AI response as JSON, wrapping raw text.")
            ai_analysis = {"raw_response": raw_ai, "description": raw_ai[:300]}

        # Build embedding text ---------------------------------------------------
        embed_text = _build_embedding_text(meta, ai_analysis)
        log(f"  Generating embedding ({len(embed_text)} chars) …")
        embedding_vec = venice_embed(embed_text)
        embedding_blob = pack_embedding(embedding_vec) if embedding_vec else None

        # Compute duration_ms from yt-dlp's 'duration' (seconds) ----------------
        dur_sec = meta.get("duration") or 0
        duration_ms = int(dur_sec * 1000) if dur_sec else 0

        # Persist track ----------------------------------------------------------
        conn.execute(
            "INSERT INTO tracks "
            "(playlist_id, title, artist, url, genre, duration_ms, artwork_url, "
            " raw_metadata_json, ai_analysis_json, embedding_blob, analyzed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                playlist_id,
                track_title,
                artist,
                track_url,
                meta.get("genre", ""),
                duration_ms,
                meta.get("thumbnail", ""),
                json.dumps(_safe_meta(meta), ensure_ascii=False),
                json.dumps(ai_analysis, ensure_ascii=False),
                embedding_blob,
                now_iso,
            ),
        )
        conn.commit()

        track_analyses.append({
            "title": track_title,
            "artist": artist,
            "analysis": ai_analysis,
        })

        log(f"  ✓ Done ({idx}/{total})")

    # 3. Playlist-level analysis -------------------------------------------------
    log("Generating playlist-level analysis …")
    send_telegram(
        telegram_chat or "",
        f"🧠 Generating playlist-level analysis for *{playlist_title}* …",
    )

    analyses_summary = json.dumps(track_analyses, indent=1, ensure_ascii=False)
    playlist_user_prompt = (
        f"Here are the individual track analyses for the playlist "
        f'"{playlist_title}":\n\n{analyses_summary}'
    )
    raw_commonalities = venice_chat(PLAYLIST_SYSTEM_PROMPT, playlist_user_prompt)

    try:
        commonalities = json.loads(raw_commonalities)
    except json.JSONDecodeError:
        commonalities = {"raw_response": raw_commonalities}

    conn.execute(
        "UPDATE playlists SET commonalities_json = ?, description = ? WHERE id = ?",
        (
            json.dumps(commonalities, ensure_ascii=False),
            commonalities.get("description", playlist_data.get("description", "")),
            playlist_id,
        ),
    )
    conn.commit()
    conn.close()

    # 4. Final output ------------------------------------------------------------
    log("✅ Analysis complete!")
    send_telegram(
        telegram_chat or "",
        f"✅ *Analysis complete* for *{playlist_title}*\n"
        f"Tracks analyzed: {total}",
    )

    result = {
        "success": True,
        "playlist_id": playlist_id,
        "playlist_title": playlist_title,
        "track_count": total,
        "commonalities": commonalities,
        "tracks": [
            {
                "title": t["title"],
                "artist": t["artist"],
                "genre": t["analysis"].get("genre"),
                "mood_tags": t["analysis"].get("mood_tags"),
                "energy_level": t["analysis"].get("energy_level"),
                "danceability": t["analysis"].get("danceability"),
                "description": t["analysis"].get("description"),
            }
            for t in track_analyses
        ],
    }
    emit_json(result)


def _build_track_summary(meta: dict) -> str:
    """Build a human-readable summary of a track's metadata for the AI prompt."""
    parts = []
    for key in (
        "title", "uploader", "genre", "description", "tags", "duration",
        "view_count", "like_count", "repost_count", "comment_count",
        "upload_date", "release_year",
    ):
        val = meta.get(key)
        if val:
            if key == "tags" and isinstance(val, list):
                val = ", ".join(str(t) for t in val)
            if key == "duration":
                minutes = int(val) // 60
                seconds = int(val) % 60
                val = f"{minutes}m {seconds}s"
            parts.append(f"- {key}: {val}")

    return "\n".join(parts) if parts else "- (minimal metadata available)"


def _build_embedding_text(meta: dict, analysis: dict) -> str:
    """Concatenate all meaningful textual info for embedding."""
    chunks = []

    # Metadata fields
    for key in ("title", "uploader", "genre", "description", "tags"):
        val = meta.get(key)
        if val:
            if isinstance(val, list):
                val = ", ".join(str(t) for t in val)
            chunks.append(str(val))

    # AI analysis fields
    for key in (
        "description", "mood_tags", "instrumentation", "production_style",
        "similar_artists", "lyrical_themes", "sonic_palette", "emotional_arc",
    ):
        val = analysis.get(key)
        if val:
            if isinstance(val, list):
                val = ", ".join(str(t) for t in val)
            chunks.append(str(val))

    genre_info = analysis.get("genre")
    if isinstance(genre_info, dict):
        primary = genre_info.get("primary", "")
        subs = genre_info.get("subgenres", [])
        if primary:
            chunks.append(primary)
        if subs:
            chunks.append(", ".join(subs))

    return " | ".join(chunks)


def _safe_meta(meta: dict) -> dict:
    """Return a JSON-serialisable subset of yt-dlp metadata (strip large blobs)."""
    skip_keys = {
        "formats", "thumbnails", "subtitles", "automatic_captions",
        "requested_formats", "requested_subtitles", "http_headers",
    }
    return {k: v for k, v in meta.items() if k not in skip_keys}

# ---------------------------------------------------------------------------
# Core: search command
# ---------------------------------------------------------------------------

def cmd_search(args) -> None:
    """Semantic search across all analyzed tracks."""
    query = args.query
    top_k = getattr(args, "top_k", 10) or 10

    log(f"Embedding search query: {query!r}")
    query_vec = venice_embed(query)
    if not query_vec:
        emit_error("Failed to generate embedding for the query.")

    conn = init_db()
    rows = conn.execute(
        "SELECT t.id, t.title, t.artist, t.url, t.genre, t.duration_ms, "
        "       t.artwork_url, t.ai_analysis_json, t.embedding_blob, "
        "       p.title AS playlist_title, p.id AS playlist_id "
        "FROM tracks t "
        "JOIN playlists p ON t.playlist_id = p.id "
        "WHERE t.embedding_blob IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        emit_json({"success": True, "results": [], "message": "No tracks in database."})
        return

    scored = []
    for row in rows:
        track_vec = unpack_embedding(row["embedding_blob"])
        sim = cosine_similarity(query_vec, track_vec)

        ai_analysis = {}
        if row["ai_analysis_json"]:
            try:
                ai_analysis = json.loads(row["ai_analysis_json"])
            except json.JSONDecodeError:
                pass

        scored.append({
            "track_id": row["id"],
            "title": row["title"],
            "artist": row["artist"],
            "url": row["url"],
            "genre": row["genre"],
            "duration_ms": row["duration_ms"],
            "artwork_url": row["artwork_url"],
            "playlist_title": row["playlist_title"],
            "playlist_id": row["playlist_id"],
            "similarity": round(sim, 6),
            "description": ai_analysis.get("description", ""),
            "mood_tags": ai_analysis.get("mood_tags", []),
            "energy_level": ai_analysis.get("energy_level"),
        })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    results = scored[:top_k]

    emit_json({"success": True, "query": query, "top_k": top_k, "results": results})

# ---------------------------------------------------------------------------
# Core: describe command
# ---------------------------------------------------------------------------

def cmd_describe(args) -> None:
    """Show a detailed report for a playlist."""
    playlist_id = getattr(args, "playlist_id", None)

    conn = init_db()

    if playlist_id:
        playlist_row = conn.execute(
            "SELECT * FROM playlists WHERE id = ?", (playlist_id,)
        ).fetchone()
    else:
        playlist_row = conn.execute(
            "SELECT * FROM playlists ORDER BY analyzed_at DESC LIMIT 1"
        ).fetchone()

    if not playlist_row:
        conn.close()
        emit_error("No playlist found.")

    playlist_id = playlist_row["id"]
    track_rows = conn.execute(
        "SELECT * FROM tracks WHERE playlist_id = ? ORDER BY id", (playlist_id,)
    ).fetchall()
    conn.close()

    commonalities = {}
    if playlist_row["commonalities_json"]:
        try:
            commonalities = json.loads(playlist_row["commonalities_json"])
        except json.JSONDecodeError:
            pass

    tracks = []
    for tr in track_rows:
        ai = {}
        if tr["ai_analysis_json"]:
            try:
                ai = json.loads(tr["ai_analysis_json"])
            except json.JSONDecodeError:
                pass
        tracks.append({
            "id": tr["id"],
            "title": tr["title"],
            "artist": tr["artist"],
            "url": tr["url"],
            "genre": tr["genre"],
            "duration_ms": tr["duration_ms"],
            "artwork_url": tr["artwork_url"],
            "analysis": ai,
        })

    result = {
        "success": True,
        "playlist": {
            "id": playlist_row["id"],
            "url": playlist_row["url"],
            "title": playlist_row["title"],
            "description": playlist_row["description"],
            "analyzed_at": playlist_row["analyzed_at"],
            "track_count": playlist_row["track_count"],
            "commonalities": commonalities,
        },
        "tracks": tracks,
    }
    emit_json(result)

# ---------------------------------------------------------------------------
# Core: list command
# ---------------------------------------------------------------------------

def cmd_list(_args) -> None:
    """List all analyzed playlists."""
    conn = init_db()
    rows = conn.execute(
        "SELECT id, url, title, analyzed_at, track_count FROM playlists "
        "ORDER BY analyzed_at DESC"
    ).fetchall()
    conn.close()

    playlists = [
        {
            "id": r["id"],
            "url": r["url"],
            "title": r["title"],
            "analyzed_at": r["analyzed_at"],
            "track_count": r["track_count"],
        }
        for r in rows
    ]
    emit_json({"success": True, "playlists": playlists})

# ---------------------------------------------------------------------------
# CLI definition
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="soundcloud-analyzer",
        description="AI-powered SoundCloud playlist analyzer with vector search.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # analyze -------------------------------------------------------------------
    p_analyze = sub.add_parser("analyze", help="Analyze a SoundCloud playlist URL")
    p_analyze.add_argument("--url", required=True, help="SoundCloud playlist URL")
    p_analyze.add_argument("--telegram-chat", default=None,
                           help="Telegram chat ID for progress notifications")
    p_analyze.set_defaults(func=cmd_analyze)

    # search --------------------------------------------------------------------
    p_search = sub.add_parser("search", help="Semantic search across analyzed tracks")
    p_search.add_argument("--query", required=True, help="Natural-language search query")
    p_search.add_argument("--top-k", type=int, default=10,
                          help="Number of results to return (default: 10)")
    p_search.set_defaults(func=cmd_search)

    # describe ------------------------------------------------------------------
    p_describe = sub.add_parser("describe", help="Show detailed playlist report")
    p_describe.add_argument("--playlist-id", type=int, default=None,
                            help="Playlist ID (default: most recent)")
    p_describe.set_defaults(func=cmd_describe)

    # list ----------------------------------------------------------------------
    p_list = sub.add_parser("list", help="List all analyzed playlists")
    p_list.set_defaults(func=cmd_list)

    return parser

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        log("Interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        emit_error(f"Unexpected error: {exc}")


if __name__ == "__main__":
    main()
