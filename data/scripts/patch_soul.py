#!/usr/bin/env python3
"""Patch SOUL.md to add NEVER rules 7-11 and file delivery instructions if missing."""

import os

SOUL_PATH = "/opt/data/SOUL.md"

EXTRA_RULES = """7. **NEVER rename file extensions for Telegram** (.m3u8, .flac, etc). NEVER create .bin copies. NEVER `cp file.m3u8 file.bin`. NEVER tell the user to rename anything. Telegram sendDocument and MEDIA: both work with ANY extension. Send files with their ORIGINAL extension ALWAYS.
8. **NEVER pass --two-stems=no to demucs** — that is an invalid flag. 4-stem separation is the default. Only use --two-stems when you specifically want 2-stem mode (e.g. --two-stems vocals).
9. **NEVER pass "n": 1 or sizes > 1024x1024 to Venice image API** — both cause 400 errors. Venice generates 1 image by default. Generate at 1024x1024, then upscale via Venice /api/v1/image/upscale (scale=4, creativity=0.01, response=raw PNG). NEVER upscale locally with ffmpeg/PIL.
10. **NEVER write ad-hoc scripts to /tmp** and debug them in chat. Use existing pipeline scripts (gen_artwork.py, publish_release.py, tag_metadata.py). If a script fails, read the error and fix it.
11. **NEVER send FLAC files without also sending the .m3u8 VLC playlist**. Always create and send the playlist alongside the FLAC files. The playlist uses Windows paths (D:\\music\\exports\\).
12. **Track titles on SoundCloud MUST be ALL CAPS** (e.g. "GHOST MOTHERBOARD" not "Ghost Motherboard").
13. **NEVER make up album concepts ad-hoc**. When the user asks for album proposals, ALWAYS run: `python3 /opt/data/scripts/propose_albums.py --force` (or with `--seed-themes "theme here"` if the user specified a theme, or `--refine "direction"` to iterate). When a proposal is selected, `album_pipeline.py` handles production automatically — do NOT run produce-album.py or master-producer.py yourself.
14. **ALWAYS generate waveform artwork after creating album covers**. Use the waveform-artwork skill: `/opt/hermes/.venv/bin/python3 /opt/data/skills/waveform-artwork/waveform-artwork/scripts/gen_waveform_art.py --playlist-id <ID> --output-dir /opt/data/music/artwork/waveforms`. NEVER use system `python3` — only the venv Python has Pillow. Save all waveforms to `/opt/data/music/artwork/waveforms/`.
15. **ALWAYS use the "grok-imagine-image-quality" model** when generating image covers on Venice.
16. **NEVER interfere with the album pipeline**. When `[pipeline]` messages arrive, the script-driven album_pipeline.py is running. You may answer user questions about production status, but NEVER run `produce-album.py` or `master-producer.py` yourself when the pipeline is active. The pipeline handles production, review gates, artwork, and publishing autonomously.
17. **NEVER generate artwork before the user has approved the songs**. Artwork generation is Phase 3 of the pipeline — only after the user explicitly approves the produced tracks in Phase 2. Artwork for songs the user hasn't heard yet is wasted work.
"""

FILE_DELIVERY_BLOCK = """
## 📁 FILE DELIVERY RULES
- To send a file: output `MEDIA:/path/to/file.ext` — the gateway sends it as-is
- The file extension in the MEDIA: path IS the extension the user receives
- .m3u8 playlists: `MEDIA:/opt/data/music/exports/session_playlist.m3u8` — NEVER .bin
- .flac files: `MEDIA:/opt/data/music/exports/session/track_MASTER.flac`
- ALWAYS send the .m3u8 playlist after sending FLACs
- NEVER copy/rename files to .bin — there is NO reason to do this
"""

ANCHOR = "6. **NEVER leave the user hanging**"

# Wait for gateway to finish writing SOUL.md (it regenerates on every boot)
import time
for attempt in range(30):  # up to 30s
    if os.path.exists(SOUL_PATH):
        with open(SOUL_PATH, "r") as f:
            content = f.read()
        if ANCHOR in content:
            break
    time.sleep(1)
else:
    print("[patch_soul] Timed out waiting for gateway to write SOUL.md")
    content = ""

if not content:
    try:
        with open(SOUL_PATH, "r") as f:
            content = f.read()
    except FileNotFoundError:
        print("[patch_soul] SOUL.md not found, exiting")
        import sys
        sys.exit(1)

changed = False

if "NEVER rename file extensions" not in content:
    idx = content.find(ANCHOR)
    if idx == -1:
        print("[patch_soul] Anchor not found, skipping rules")
    else:
        eol = content.find("\n", idx)
        if eol == -1:
            eol = len(content)
        content = content[:eol+1] + EXTRA_RULES + content[eol+1:]
        changed = True
        print("[patch_soul] Added NEVER rules 7-12")
else:
    print("[patch_soul] NEVER rules already present")

if "FILE DELIVERY RULES" not in content:
    # Insert before "## 🎵 HOW TO MAKE MUSIC"
    music_idx = content.find("## 🎵 HOW TO MAKE MUSIC")
    if music_idx == -1:
        music_idx = content.find("HOW TO MAKE MUSIC")
    if music_idx != -1:
        content = content[:music_idx] + FILE_DELIVERY_BLOCK + "\n" + content[music_idx:]
        changed = True
        print("[patch_soul] Added FILE DELIVERY RULES section")
    else:
        # Append at end
        content += FILE_DELIVERY_BLOCK
        changed = True
        print("[patch_soul] Appended FILE DELIVERY RULES at end")
else:
    print("[patch_soul] FILE DELIVERY RULES already present")

if changed:
    # Also remove any lingering .bin instructions from conversation memory
    content = content.replace("rename .bin", "DO NOT rename files")
    content = content.replace(".m3u8.bin", ".m3u8")
    with open(SOUL_PATH, "w") as f:
        f.write(content)
    print("[patch_soul] SOUL.md updated successfully")

# ── Patch config.yaml model ──
CONFIG_PATH = "/opt/data/config.yaml"
TARGET_MODEL = "deepseek-v4-flash"
try:
    with open(CONFIG_PATH, "r") as f:
        cfg = f.read()
    if f"default: {TARGET_MODEL}" not in cfg:
        import re
        cfg = re.sub(r"default:\s+\S+", f"default: {TARGET_MODEL}", cfg, count=1)
        with open(CONFIG_PATH, "w") as f:
            f.write(cfg)
        print(f"[patch_soul] Model switched to {TARGET_MODEL}")
    else:
        print(f"[patch_soul] Model already {TARGET_MODEL}")
except Exception as e:
    print(f"[patch_soul] Config patch error: {e}")
