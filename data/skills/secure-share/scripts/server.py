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
DIRECTORY = Path(r"C:\Users\maxin\.gemini\antigravity\shared_files")
DIRECTORY.mkdir(parents=True, exist_ok=True)
PUBLIC_URL_FILE = DIRECTORY / ".public_url"

# Clear old URL
if PUBLIC_URL_FILE.exists():
    PUBLIC_URL_FILE.unlink()

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

def start_server():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Secure File Service running at http://localhost:{PORT}")
        httpd.serve_forever()

def start_tunnel():
    exe_path = Path(__file__).parent / "cloudflared.exe"
    if not exe_path.exists():
        print("Downloading cloudflared...")
        urllib.request.urlretrieve("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe", str(exe_path))
    
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
        # print(f"[Tunnel] {line.strip()}")
        match = url_pattern.search(line)
        if match:
            public_url = match.group(0)
            print(f"\n[PUBLIC URL] Internet URL established: {public_url}\n")
            PUBLIC_URL_FILE.write_text(public_url, encoding="utf-8")
            break

    # Keep reading so process doesn't block
    for line in process.stdout:
        pass

if __name__ == "__main__":
    t_server = threading.Thread(target=start_server, daemon=True)
    t_server.start()
    
    start_tunnel()
