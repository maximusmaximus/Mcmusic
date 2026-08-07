# Hermes Music 🎵

AI Music Producer powered by [Venice AI](https://venice.ai) and [Hermes Agent](https://hermes-agent.nousresearch.com).

Generate music, songs, sound effects, and audio on demand via **Telegram**.
Analyze SoundCloud playlists with AI-powered tagging and semantic search.

## Quick Start

```bash
cd hermes-music
podman-compose up -d --build
```

## Skills

### 🎶 Music Generation
| Model | Best For | Vocals |
|-------|----------|--------|
| `elevenlabs-music` | Songs with vocals, instrumentals | ✅ + `force_instrumental` |
| `minimax-music-v2` | Full songs, genre control | ✅ |
| `ace-step-15` | Complex song structure | ✅ |
| `stable-audio-25` | Ambient, loops, soundscapes | ❌ |
| `elevenlabs-sound-effects-v2` | Realistic foley, SFX | ❌ |
| `mmaudio-v2-text-to-audio` | Cinematic cues, SFX | ❌ |

### 🔍 SoundCloud Analyzer
Analyzes public SoundCloud playlists with AI-powered deep tagging and stores tracks in a vector database for semantic search.

| Model | Purpose |
|-------|---------|
| `zai-org-glm-5-2` | Deep music analysis, tagging, descriptions (1M context) |
| `text-embedding-bge-m3` | Vector embeddings for semantic search |

**Commands:**
- `analyze` — Process a SoundCloud playlist URL → AI tags + descriptions + commonalities
- `search` — Semantic search across all stored tracks ("find me chill lo-fi beats")
- `describe` — View the full analysis report for a playlist
- `list` — List all analyzed playlists

## Architecture

```
User (Telegram) → Hermes Agent (Venice LLM)
    ├── venice-music skill       → Venice Audio API → Audio file → Telegram
    ├── master-producer skill    → Multi-stem mix/master → Audio file → Telegram
    ├── producer-profiles skill  → Saved presets
    └── soundcloud-analyzer skill
            ├── yt-dlp → SoundCloud metadata
            ├── Venice GLM 5.2 → AI analysis + tagging
            ├── Venice BGE-M3 → Embeddings
            └── SQLite vector DB → Semantic search
```

## Ports

| Port | Service |
|------|---------|
| `18802` | Hermes Gateway (HTTP) |
| `18803` | Hermes Gateway (WebSocket) |

## Environment

| Variable | Purpose |
|----------|---------|
| `VENICE_API_KEY` | Venice AI API key (inference + audio + embeddings) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |

## Data

- Generated music: `./data/music/` (also at `/mnt/d/music`)
- SoundCloud analysis DB: `./data/soundcloud-analyzer/vectors.db`

