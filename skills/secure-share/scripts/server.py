import http.server
import socketserver
import os
import sys
import threading
import subprocess
import urllib.request
import re
import time
from pathlib import Path

PORT = 8124

if sys.platform == "win32":
    DIRECTORY = Path(os.environ.get("SHARED_DIR", r"D:\music\shared_files"))
    BIN_NAME = "cloudflared.exe"
    DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
else:
    DIRECTORY = Path(os.environ.get("SHARED_DIR", "/opt/data/music/shared_files"))
    BIN_NAME = "cloudflared"
    DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"

DIRECTORY.mkdir(parents=True, exist_ok=True)
PUBLIC_URL_FILE = DIRECTORY / ".public_url"
LEGACY_URL_FILE = Path(r"C:\Users\maxin\.gemini\antigravity\shared_files\.public_url") if sys.platform == "win32" else None

# Clear old URL
if PUBLIC_URL_FILE.exists():
    try:
        PUBLIC_URL_FILE.unlink()
    except Exception:
        pass

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

def start_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Secure File Service running at http://localhost:{PORT}")
        print(f"Serving directory: {DIRECTORY}")
        httpd.serve_forever()

def start_tunnel():
    exe_path = Path(__file__).parent / BIN_NAME
    if not exe_path.exists():
        print(f"Downloading {BIN_NAME}...")
        urllib.request.urlretrieve(DOWNLOAD_URL, str(exe_path))
        if sys.platform != "win32":
            os.chmod(str(exe_path), 0o755)
    
    print("Starting Cloudflare tunnel...")
    process = subprocess.Popen(
        [str(exe_path), "tunnel", "--url", f"http://localhost:{PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    
    for line in process.stdout:
        match = url_pattern.search(line)
        if match:
            public_url = match.group(0)
            print(f"\n[PUBLIC URL] Internet URL established: {public_url}\n", flush=True)
            PUBLIC_URL_FILE.write_text(public_url, encoding="utf-8")
            if LEGACY_URL_FILE:
                try:
                    LEGACY_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
                    LEGACY_URL_FILE.write_text(public_url, encoding="utf-8")
                except Exception:
                    pass
            break

    for line in process.stdout:
        pass

if __name__ == "__main__":
    t_server = threading.Thread(target=start_server, daemon=True)
    t_server.start()
    start_tunnel()
