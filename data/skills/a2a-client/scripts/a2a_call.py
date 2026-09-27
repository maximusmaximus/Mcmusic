#!/usr/bin/env python3
"""
A2A Client Utility for PlanetaryExplorer
Sends messages and JSON-RPC calls over Tailscale to the A2A server.
"""

import argparse
import json
import sys
import urllib.request
import urllib.error

import os

DEFAULT_HOST = os.environ.get("A2A_HOST", "http://100.125.60.37:8080")
DEFAULT_TOKEN = os.environ.get("A2A_AUTH_TOKEN", "")
if not DEFAULT_TOKEN and os.path.exists("/opt/data/config.yaml"):
    try:
        import yaml
        with open("/opt/data/config.yaml") as f:
            cfg = yaml.safe_load(f) or {}
            DEFAULT_TOKEN = cfg.get("A2A_AUTH_TOKEN", cfg.get("a2a_auth_token", ""))
    except Exception:
        pass


class A2AClient:
    def __init__(self, base_url: str = DEFAULT_HOST, token: str = DEFAULT_TOKEN):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _request(self, endpoint: str, data: dict = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Antigravity-A2A-Client/1.0"
        }

        req_data = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=req_data, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            try:
                err_json = json.loads(err_body)
                return {"error": f"HTTP {e.code}", "details": err_json}
            except Exception:
                return {"error": f"HTTP {e.code}", "details": err_body}
        except Exception as e:
            return {"error": "ConnectionError", "details": str(e)}

    def get_status(self) -> dict:
        return self._request("/health")

    def get_agent_card(self) -> dict:
        return self._request("/.well-known/agent-card.json")

    def send_message(self, message: str, sender: str = "remote-node") -> dict:
        payload = {
            "message": message,
            "sender": sender
        }
        return self._request("/a2a/v1/message", payload)

    def send_rpc(self, method: str, params: dict = None) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {}
        }
        return self._request("/a2a/v1/rpc", payload)


def main():
    parser = argparse.ArgumentParser(description="Call PlanetaryExplorer A2A Server over Tailscale")
    parser.add_argument("--message", "-m", help="Message or task prompt to send")
    parser.add_argument("--sender", "-s", default="cli-agent", help="Sender identifier")
    parser.add_argument("--status", action="store_true", help="Check server health status")
    parser.add_argument("--agent-card", action="store_true", help="Fetch remote Agent Card")
    parser.add_argument("--host", default=DEFAULT_HOST, help="A2A server base URL")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="Bearer auth token")

    args = parser.parse_args()
    client = A2AClient(base_url=args.host, token=args.token)

    if args.status:
        res = client.get_status()
        print(json.dumps(res, indent=2))
    elif args.agent_card:
        res = client.get_agent_card()
        print(json.dumps(res, indent=2))
    elif args.message:
        res = client.send_message(args.message, sender=args.sender)
        print(json.dumps(res, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
