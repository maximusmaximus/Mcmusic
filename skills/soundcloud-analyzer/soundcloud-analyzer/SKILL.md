---
name: soundcloud-analyzer
description: Analyze public SoundCloud playlists with AI-powered track descriptions, mood/genre/instrumentation tagging, commonality detection, and semantic vector search across all stored tracks.
tags: [soundcloud, analysis, tagging, vector-search, ai, music, playlist, metadata]
---

# SoundCloud Playlist Analyzer

Analyze public SoundCloud playlists: fetch track metadata, generate AI-powered descriptions and tags, identify playlist commonalities, and store everything in a vector database for semantic search.

## ⚠️ CRITICAL: How To Use This Skill

**YOU MUST use the `terminal` tool** to run the script. Do NOT use `process` — it cannot handle long-running commands.

```bash
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  COMMAND [OPTIONS]
```

Where COMMAND is one of: `analyze`, `search`, `describe`, `list`.

**You MUST always pass `--telegram-chat`** with the user's Telegram chat ID for the `analyze` command so they receive live progress updates.

**IMPORTANT RULES:**
1. Use `terminal` tool, NOT `process` — analysis of large playlists can take several minutes
2. Do NOT try to scrape SoundCloud directly — the script handles everything via yt-dlp
3. The script outputs JSON to stdout — parse it yourself to extract results
4. Tell the user you're starting the analysis BEFORE running the command
5. Warn that large playlists (50+ tracks) may take several minutes to process

**OUTPUT DELIVERY RULES:**
1. **Do NOT paste the JSON output** in the chat — parse it and respond naturally
2. **Do NOT show the terminal command, script logs, or code** to the user
3. After the script finishes, extract the relevant data from the JSON and write a brief, conversational summary
4. For `analyze`: Summarize the playlist — total tracks, top genres/moods, key commonalities
5. For `search`: Present matching tracks naturally — "I found these tracks matching your query..."
6. For `describe`: Present the playlist description and commonalities as a readable summary
7. For `list`: Present the stored playlists as a clean list with names and track counts
8. That's it — no code blocks, no file paths, no technical output

## Commands

### 1. `analyze` — Analyze a SoundCloud Playlist
**User says:** "analyze this playlist", "what's in this SoundCloud playlist", provides a SoundCloud URL
- **Required:** `--url` with a public SoundCloud playlist URL
- Fetches all tracks via yt-dlp
- Extracts metadata: title, artist, genre, tags, duration, description, artwork URL
- Sends each track's metadata to Venice AI (GLM 5.2) for deep analysis
- Generates per-track: mood, energy level, instrumentation, production style, similar artists, subgenre classification, BPM estimate, key signature estimate, lyrical themes
- Identifies commonalities across the entire playlist
- Embeds all descriptions + tags into the vector database

### 2. `search` — Semantic Search Across Stored Tracks
**User says:** "find tracks with dark ambient vibes", "search for upbeat electronic"
- **Required:** `--query` with natural language search text
- Searches across ALL previously analyzed playlists
- Returns the most semantically similar tracks
- Use `--top-k` to control number of results (default: 10)

### 3. `describe` — Get Playlist Description & Commonalities
**User says:** "describe that playlist", "what were the commonalities"
- **Optional:** `--playlist-id` to specify which playlist (defaults to most recent)
- Returns the full AI-generated playlist description
- Includes commonalities report: shared genres, moods, production styles, thematic threads

### 4. `list` — List All Analyzed Playlists
**User says:** "what playlists have I analyzed", "show stored playlists"
- No additional arguments required
- Returns all previously analyzed playlists with names, URLs, track counts, and analysis dates

## Model Selection Guide

### AI Analysis Model
- **`zai-org-glm-5-2`** — Primary analysis model
  - 1M token context window — handles large playlists with full metadata in a single pass
  - Best-in-class for detailed music analysis, genre classification, and mood tagging
  - Generates structured per-track analysis: mood, energy, instrumentation, production style, similar artists, subgenre, BPM estimate, key signature, lyrical themes
  - Also generates the cross-playlist commonalities report

### Embedding Model
- **`text-embedding-bge-m3`** — Vector embedding model
  - Used to embed track descriptions + tags for semantic search
  - High-quality multilingual embeddings
  - Stored in local SQLite-backed vector database at `/opt/data/soundcloud-analyzer/vectors.db`

## What It Does (Pipeline)

1. **Fetch** — Uses yt-dlp to extract all track metadata from the public SoundCloud playlist URL
2. **Extract** — For each track: title, artist, genre, user-applied tags, duration, description, artwork URL
3. **Analyze** — Sends track metadata to Venice AI (`zai-org-glm-5-2`) for deep analysis:
   - Mood & energy level
   - Instrumentation & production style
   - Similar artists & subgenre classification
   - BPM estimate & key signature estimate
   - Lyrical themes (if applicable)
4. **Commonalities** — Generates a cross-playlist report identifying shared genres, moods, production techniques, and thematic threads
5. **Embed** — Encodes all track descriptions + tags using `text-embedding-bge-m3`
6. **Store** — Persists embeddings + metadata in SQLite vector database at `/opt/data/soundcloud-analyzer/vectors.db`
7. **Search** — Supports semantic natural language queries across all stored tracks

## Script Output (JSON on stdout)

Analyze success:
```json
{"success": true, "command": "analyze", "playlist_id": "abc123", "playlist_title": "My Playlist", "track_count": 25, "tracks": [...], "commonalities": {...}, "analysis_time_seconds": 142.5}
```

Search success:
```json
{"success": true, "command": "search", "query": "dark ambient", "results": [{"track_title": "...", "artist": "...", "score": 0.92, "tags": [...], "description": "..."}], "total_results": 5}
```

Describe success:
```json
{"success": true, "command": "describe", "playlist_id": "abc123", "playlist_title": "My Playlist", "description": "...", "commonalities": {...}}
```

List success:
```json
{"success": true, "command": "list", "playlists": [{"playlist_id": "abc123", "title": "My Playlist", "url": "...", "track_count": 25, "analyzed_at": "2026-07-06T14:30:00Z"}]}
```

Error:
```json
{"success": false, "error": "Detailed error message"}
```

## ⛔ Known Pitfalls

| Constraint | Details |
|-----------|---------|
| Private playlists | **Not supported.** yt-dlp can only access public SoundCloud playlists |
| Large playlists (100+ tracks) | **Slow.** Each track requires an AI API call — expect 5-10+ minutes |
| Rate limiting | Venice API may rate-limit on very large playlists — the script handles retries automatically |
| SoundCloud URL format | **Must be a playlist URL** (e.g., `https://soundcloud.com/user/sets/playlist-name`), not a single track |
| Missing metadata | Some tracks have minimal SoundCloud metadata — AI analysis still works but may be less detailed |
| Vector DB location | Stored at `/opt/data/soundcloud-analyzer/vectors.db` — do not move or delete while analysis is running |
| Re-analyzing a playlist | Safe to re-run — existing entries are updated, not duplicated |

## Examples

```bash
# Analyze a SoundCloud playlist
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  analyze \
  --url "https://soundcloud.com/user/sets/my-playlist" \
  --telegram-chat 123456789

# Semantic search across all stored tracks
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  search \
  --query "melancholic lo-fi with vinyl crackle" \
  --top-k 5

# Get description and commonalities for a specific playlist
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  describe \
  --playlist-id 1

# List all analyzed playlists
python3 /opt/data/skills/soundcloud-analyzer/soundcloud-analyzer/scripts/soundcloud-analyzer.py \
  list
```
