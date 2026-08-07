#!/usr/bin/env python3
"""
SoundCloud OAuth — paste the callback URL and exchange immediately.
Usage: python3 sc_exchange.py 'http://127.0.0.1:8080/callback?code=...'
"""
import base64, json, os, sys, time
from urllib.parse import urlparse, parse_qs, urlencode
import urllib.request, urllib.error

CLIENT_ID = "qDGpT3dys933ppKMK4ZYbLLFltFwmtNe"
CLIENT_SECRET = "aQc0cStdahtmyOOnSLNhlEdkyjEzrZsv"

if len(sys.argv) < 3:
    print("Usage: python3 sc_exchange.py <code_verifier> <callback_url_or_code>")
    sys.exit(1)

verifier = sys.argv[1]
raw = sys.argv[2]

# Extract code from URL or use directly
if raw.startswith("http"):
    params = parse_qs(urlparse(raw).query)
    code = params["code"][0]
else:
    code = raw

print(f"Code length: {len(code)}")
print(f"Verifier length: {len(verifier)}")

basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

body = urlencode({
    "grant_type": "authorization_code",
    "code": code,
    "redirect_uri": "http://127.0.0.1:8080/callback",
    "code_verifier": verifier,
}).encode()

req = urllib.request.Request(
    "https://api.soundcloud.com/oauth2/token",
    data=body,
    headers={
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read().decode())

    tokens = {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token", ""),
        "expires_at": int(time.time()) + result.get("expires_in", 3600),
        "scope": result.get("scope", ""),
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    for path in [
        "/mnt/d/hermes-music/data/home/.hermes/credentials/soundcloud_tokens.json",
        "/mnt/d/hermes-music/data/.soundcloud_auth/soundcloud_tokens.json",
    ]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(tokens, f, indent=2)
        print(f"Saved: {path}")

    # Verify
    me_req = urllib.request.Request(
        "https://api.soundcloud.com/me",
        headers={"Authorization": f"OAuth {tokens['access_token']}"},
    )
    with urllib.request.urlopen(me_req, timeout=15) as r:
        me = json.loads(r.read().decode())
        print(f"Username: {me.get('username')}")
        print(f"User ID: {me.get('id')}")
        print(f"Tracks: {me.get('track_count', 0)}")

    print("SUCCESS")

except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()[:500]}")
except Exception as e:
    print(f"Error: {e}")
