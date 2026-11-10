import argparse
import subprocess
import json
import urllib.request
import urllib.parse
from pathlib import Path
import os
import re

DEFAULT_SONGPROCESSOR_TOKEN = ""

def get_bot_tokens(requested_token=None):
    if requested_token:
        return [requested_token]

    tokens = []
    
    # Check environment variable
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if env_token and env_token not in tokens:
        tokens.append(env_token)

    # Check known config paths, prioritizing hermes-music (.env has songprocessor_bot)
    candidates = [
        Path("D:/hermes-music/.env"),
        Path("/opt/data/.env"),
        Path("D:/sp2/.env"),
        Path("D:/hermes-music/data/config.yaml"),
        Path("D:/sp2/data/config.yaml"),
        Path("/opt/data/config.yaml"),
    ]
    for c in candidates:
        if c.exists():
            try:
                for line in c.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if "bot_token:" in line:
                        tok = line.split(":", 1)[1].strip().strip('\"').strip('\'')
                        if tok and tok not in tokens:
                            tokens.append(tok)
                    elif "TELEGRAM_BOT_TOKEN=" in line:
                        tok = line.split("=", 1)[1].strip().strip('\"').strip('\'')
                        if tok and tok not in tokens:
                            tokens.append(tok)
            except Exception:
                pass

    if DEFAULT_SONGPROCESSOR_TOKEN and DEFAULT_SONGPROCESSOR_TOKEN not in tokens:
        tokens.insert(0, DEFAULT_SONGPROCESSOR_TOKEN)

    return tokens

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true"
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_json = json.loads(resp.read().decode())
            return res_json.get("ok", False)
    except Exception as e:
        print(f"Error sending Telegram message with token ...{token[-6:]}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Package release/song and send to Telegram")
    parser.add_argument("--path", required=True, help="Path to release folder or audio file")
    parser.add_argument("--chat_id", default="8293122782", help="Telegram chat ID")
    parser.add_argument("--title", default=None, help="Title for the Telegram message")
    parser.add_argument("--token", default=None, help="Specific bot token to use")
    parser.add_argument("--all-bots", action="store_true", help="Send notification to all discovered bots")
    args = parser.parse_args()

    source = Path(args.path)
    if not source.exists():
        print(f"Error: Path {source} does not exist.")
        return

    share_script = Path(__file__).parent / "share.py"
    print(f"Running secure-share on {args.path}...")
    
    process = subprocess.run(
        ["python", str(share_script), "--path", str(source)],
        capture_output=True, text=True
    )
    
    print(process.stdout)
    if process.stderr:
        print("share.py stderr:", process.stderr)

    # Extract [EXTERNAL LINK]
    ext_link = None
    for line in process.stdout.splitlines():
        if "[EXTERNAL LINK]" in line:
            ext_link = line.split("[EXTERNAL LINK]")[-1].strip()
            break
        elif "trycloudflare.com" in line:
            match = re.search(r'(https?://[^\s]+)', line)
            if match:
                ext_link = match.group(1)
                break

    if not ext_link:
        print("Warning: Could not extract external Cloudflare link.")
        ext_link = "No external link generated (Tunnel offline?)"

    print(f"Extracted External Link: {ext_link}")

    pkg_label = f"{source.name}.zip" if source.is_dir() else source.name
    title = args.title or (f"VØIDRIDE — {source.stem.replace('_', ' ').upper()}" if not source.is_dir() else f"VØIDRIDE Release — {source.name.replace('-', ' ').upper()}")

    # Format text for Telegram
    text = (
        f"🎵 *{title}*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *File:* `{pkg_label}`\n\n"
        f"🌐 *Cloudflare Mobile Link:*\n"
        f"🔗 [{pkg_label}]({ext_link})\n\n"
        "📱 _Direct download ready for mobile or off-network review._"
    )

    tokens = get_bot_tokens(args.token)
    if not tokens:
        print("Error: No bot tokens available.")
        return

    if not args.all_bots:
        # Default: send via @songprocessor_bot (or first found token)
        # Prioritize DEFAULT_SONGPROCESSOR_TOKEN if present
        primary = DEFAULT_SONGPROCESSOR_TOKEN if DEFAULT_SONGPROCESSOR_TOKEN in tokens else tokens[0]
        targets = [primary]
    else:
        targets = tokens

    for tok in targets:
        print(f"Sending notification via bot (...{tok[-6:]}) to chat {args.chat_id}...")
        ok = send_telegram(tok, args.chat_id, text)
        if ok:
            print(f"[SUCCESS] Telegram notification sent successfully via ...{tok[-6:]}!")
        else:
            print(f"[ERROR] Failed to send via ...{tok[-6:]}")

if __name__ == "__main__":
    main()
