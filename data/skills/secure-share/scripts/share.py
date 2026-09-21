import argparse
import shutil
import uuid
import os
import sys
import time
import socket
from pathlib import Path
import subprocess

PORT = 8124
BASE_URL = f"http://localhost:{PORT}"

if sys.platform == "win32":
    SHARED_DIR = Path(os.environ.get("SHARED_DIR", r"D:\music\shared_files"))
    LEGACY_URL_FILE = Path(r"C:\Users\maxin\.gemini\antigravity\shared_files\.public_url")
else:
    SHARED_DIR = Path(os.environ.get("SHARED_DIR", "/opt/data/music/shared_files"))
    LEGACY_URL_FILE = None

def is_port_open(port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(('127.0.0.1', port)) == 0

def get_public_url():
    public_url_file = SHARED_DIR / ".public_url"
    if public_url_file.exists():
        url = public_url_file.read_text(encoding="utf-8").strip()
        if url.startswith("http"):
            return url
    if LEGACY_URL_FILE and LEGACY_URL_FILE.exists():
        url = LEGACY_URL_FILE.read_text(encoding="utf-8").strip()
        if url.startswith("http"):
            return url
    return None

def ensure_server_running():
    url = get_public_url()
    if sys.platform == "win32" and is_port_open(PORT) and url:
        return url
    if sys.platform != "win32" and url:
        return url

    server_script = Path(__file__).parent / "server.py"
    if server_script.exists():
        print("[INFO] Starting background secure-share server & Cloudflare tunnel...")
        public_url_file = SHARED_DIR / ".public_url"
        if public_url_file.exists():
            try:
                public_url_file.unlink()
            except Exception:
                pass
        flags = 0
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            [sys.executable, str(server_script)],
            creationflags=flags,
            close_fds=(sys.platform != "win32")
        )
        for _ in range(30):
            time.sleep(0.5)
            url = get_public_url()
            if url:
                return url
    return url

def main():
    parser = argparse.ArgumentParser(description="Securely share a file or folder")
    parser.add_argument("--path", required=True, help="Path to file or folder")
    parser.add_argument("--external", action="store_true", help="Deprecated flag (automatically provides external link if tunnel is running)")
    args = parser.parse_args()

    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    share_id = str(uuid.uuid4())
    target_dir = SHARED_DIR / share_id
    target_dir.mkdir(parents=True, exist_ok=True)

    source = Path(args.path)
    if not source.exists():
        print(f"Error: {source} does not exist.")
        return

    if source.is_dir():
        zip_name = f"{source.name}.zip"
        shutil.make_archive(str(target_dir / source.name), 'zip', source)
        final_path = target_dir / zip_name
    else:
        final_path = target_dir / source.name
        shutil.copy2(source, final_path)

    local_url = f"{BASE_URL}/{share_id}/{final_path.name}"
    print(f"[SUCCESS] Packaged successfully: {final_path}")
    print(f"[LOCAL LINK] {local_url}")

    external_base = ensure_server_running()
    if external_base:
        external_url = f"{external_base}/{share_id}/{final_path.name}"
        print(f"[EXTERNAL LINK] {external_url}")
    else:
        print("[INFO] External tunnel is not running. Start server.py to expose it to the internet.")

if __name__ == "__main__":
    main()
