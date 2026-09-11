import argparse
import shutil
import uuid
import os
from pathlib import Path
import subprocess

SHARED_DIR = Path(r"C:\Users\maxin\.gemini\antigravity\shared_files")
BASE_URL = "http://localhost:8124"

def main():
    parser = argparse.ArgumentParser(description="Securely share a file or folder")
    parser.add_argument("--path", required=True, help="Path to file or folder")
    parser.add_argument("--external", action="store_true", help="Deprecated flag (now automatically provides external link if tunnel is running)")
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

    public_url_file = SHARED_DIR / ".public_url"
    if public_url_file.exists():
        external_base = public_url_file.read_text(encoding="utf-8").strip()
        external_url = f"{external_base}/{share_id}/{final_path.name}"
        print(f"[EXTERNAL LINK] {external_url}")
    else:
        print("[INFO] External tunnel is not running. Start server.py to expose it to the internet.")

if __name__ == "__main__":
    main()
