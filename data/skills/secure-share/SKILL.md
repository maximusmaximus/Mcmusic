---
name: secure-share
description: A file service infrastructure for agents to securely package and share files via local and external shareable links.
---

# Secure Share

This skill allows agents to package files or directories into a ZIP archive and expose them via a secure shareable link.

## Usage

Agents can call the share.py script provided in the scripts directory.

### Command Line
`powershell
python path\to\scripts\share.py --path "C:\path\to\your\folder_or_file" [--external]
`

### Options
- --path: The absolute path to the file or directory you want to share. If a directory is provided, it will be automatically zipped.
- --external: Optional. If provided, the packaged file will also be uploaded to 	ransfer.sh to generate a public, ephemeral download link (valid for 14 days).

### Local Server
The sharing infrastructure relies on a local background file server serving C:\Users\maxin\.gemini\antigravity\shared_files on port 8123.
To start the server (if not already running), an agent can execute:
`powershell
python path\to\scripts\server.py
`
"@

 = @"
import http.server
import socketserver
import os
from pathlib import Path

PORT = 8123
DIRECTORY = Path(r"C:\Users\maxin\.gemini\antigravity\shared_files")
DIRECTORY.mkdir(parents=True, exist_ok=True)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Secure File Service running at http://localhost:{PORT}")
        print(f"Serving directory: {DIRECTORY}")
        httpd.serve_forever()
