#!/usr/bin/env python3
"""
send_agent_notification.py — Sends structured status/progress notifications to Telegram.
Usage:
    python3 send_agent_notification.py "Your message here"
    python3 send_agent_notification.py --title "System Update" --body "Details..."
"""

import argparse
import json
import os
import sys
import urllib.request

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8293122782")


def send_notification(text, chat_id=None, parse_mode="HTML"):
    token = TELEGRAM_BOT_TOKEN
    cid = chat_id or CHAT_ID
    if not token or not cid:
        print("[notify] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID", file=sys.stderr)
        return False

    payload = {
        "chat_id": str(cid),
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode())
            ok = res.get("ok", False)
            if ok:
                print(f"[notify] Successfully sent message {res.get('result', {}).get('message_id')}")
            return ok
    except Exception as e:
        print(f"[notify] Send failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Send agent notification to Telegram")
    parser.add_argument("message", nargs="?", default="", help="Notification message text")
    parser.add_argument("--title", help="Bold title header")
    parser.add_argument("--body", help="Body text or bullet points")
    parser.add_argument("--chat-id", default=None, help="Telegram chat ID")
    parser.add_argument("--raw", action="store_true", help="Send raw text without formatting")
    args = parser.parse_args()

    if args.title and args.body:
        text = f"<b>{args.title}</b>\n\n{args.body}"
    elif args.title:
        text = f"<b>{args.title}</b>\n\n{args.message}"
    elif args.message:
        text = args.message
    else:
        parser.print_help()
        sys.exit(1)

    parse_mode = None if args.raw else "HTML"
    success = send_notification(text, chat_id=args.chat_id, parse_mode=parse_mode)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
