---
name: secure-share
description: File service infrastructure to securely package music releases, FLACs, and Windows playlists into ZIP archives and generate live local and Cloudflare external download links for review.
---

# Secure Share Skill

This skill packages music production files, FLAC masters, artwork, and Windows `.m3u8` playlists into ZIP archives and exposes them via live local and Cloudflare shareable links.

## Usage

### 1. Deliver Release / Package for Review (Primary)
Packages a release directory, generates a live Cloudflare download link, and sends a notification to Telegram:
```bash
python3 /opt/data/skills/secure-share/scripts/deliver_release.py --path "/opt/data/music/exports/<session>" --title "<ALBUM TITLE>"
```

### 2. Package Folder / File (CLI)
Packages any directory or file into `shared_files` and outputs local and external Cloudflare links:
```bash
python3 /opt/data/skills/secure-share/scripts/share.py --path "/opt/data/music/exports/<session>"
```

### 3. Server & Tunnel Service
Runs the local file server on port 8124 and maintains the Cloudflare tunnel (`*.trycloudflare.com`):
```bash
python3 /opt/data/skills/secure-share/scripts/server.py
```
*(Automatically launched in the background by `share.py` and `deliver_release.py` if not running).*
