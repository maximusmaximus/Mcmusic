import argparse
import subprocess
import json
import urllib.request
import urllib.parse
from pathlib import Path
import os
import re

def get_bot_token():
    config_p = Path("D:/hermes-music/data/config.yaml")
    if not config_p.exists():
        return ""
    for line in config_p.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("bot_token:"):
            return line.split(":", 1)[1].strip().strip('\"').strip('\x27')
    return ""

def main():
    parser = argparse.ArgumentParser(description="Package release and send to Telegram")
    parser.add_argument("--path", required=True, help="Path to release folder")
    parser.add_argument("--chat_id", default="8293122782", help="Telegram chat ID")
    parser.add_argument("--title", default="VØIDRIDE Release", help="Title for the Telegram message")
    args = parser.parse_args()

    bot_token = get_bot_token()
    if not bot_token:
        print("Error: Could not find bot_token in config.yaml")
        return

    share_script = Path(__file__).parent / "share.py"
    print(f"Running secure-share on {args.path}...")
    
    process = subprocess.run(
        ["python", str(share_script), "--path", args.path],
        capture_output=True, text=True
    )
    
    print(process.stdout)
    if process.stderr:
        print("Error during share.py:", process.stderr)

    # Extract [EXTERNAL LINK]
    ext_link = None
    for line in process.stdout.splitlines():
        if "[EXTERNAL LINK]" in line or "[PUBLIC URL]" in line or "trycloudflare.com" in line:
            # find http...
            match = re.search(r'(https?://[^\s]+)', line)
            if match:
                ext_link = match.group(1)
                break

    if not ext_link:
        print("Warning: Could not extract external Cloudflare link. Is the tunnel running?")
        ext_link = "No external link generated (Tunnel offline?)"

    print(f"Extracted Link: {ext_link}")

    # Send to Telegram
    text = (
        f"🎵 *{args.title}*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *Package:* {Path(args.path).name}.zip\n\n"
        f"🔗 [Download Secure Package]({ext_link})\n\n"
        "_Ready for review._"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": args.chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true"
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req) as resp:
            print("Telegram notification sent successfully!")
    except Exception as e:
        print("Error sending Telegram message:", e)

if __name__ == "__main__":
    main()
