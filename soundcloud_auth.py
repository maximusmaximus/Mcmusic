#!/usr/bin/env python3
"""
SoundCloud OAuth — Host-side auth flow.
Run this on the host machine (not in the container).
Opens browser → catches callback → saves tokens into the container volume.
"""
import base64
import hashlib
import json
import os
import secrets
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

try:
    import requests
except ImportError:
    # Fall back to urllib if requests isn't available
    import urllib.request
    import urllib.error

CLIENT_ID = "qDGpT3dys933ppKMK4ZYbLLFltFwmtNe"
CLIENT_SECRET = "aQc0cStdahtmyOOnSLNhlEdkyjEzrZsv"
REDIRECT_URI = "http://127.0.0.1:8080/callback"
TOKEN_FILE = "/mnt/d/hermes-music/data/home/.hermes/credentials/soundcloud_tokens.json"

# Also save to the container-mapped path
TOKEN_FILE_ALT = "/mnt/d/hermes-music/data/.soundcloud_auth/soundcloud_tokens.json"


def generate_pkce():
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


class CallbackHandler(BaseHTTPRequestHandler):
    auth_code = None
    error = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "code" in params:
            CallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="background:#111;color:#0f0;font-family:monospace;
                display:flex;align-items:center;justify-content:center;height:100vh">
                <div style="text-align:center">
                <h1>&#x2713; SoundCloud Authenticated!</h1>
                <p>You can close this tab. Tokens are being saved...</p>
                </div></body></html>
            """)
        elif "error" in params:
            CallbackHandler.error = params.get("error_description", [params["error"][0]])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"""
                <html><body style="background:#111;color:#f00;font-family:monospace;
                display:flex;align-items:center;justify-content:center;height:100vh">
                <div style="text-align:center">
                <h1>&#x2717; Auth Failed</h1>
                <p>{CallbackHandler.error}</p>
                </div></body></html>
            """.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    code_verifier, code_challenge = generate_pkce()

    auth_params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = "https://api.soundcloud.com/connect?" + urlencode(auth_params)

    print(f"\n🔗 Open this URL in your browser:\n")
    print(f"   {auth_url}\n")
    print(f"⏳ Waiting for callback on http://127.0.0.1:8080 ...\n")

    server = HTTPServer(("127.0.0.1", 8080), CallbackHandler)
    server.handle_request()

    if CallbackHandler.error:
        print(f"❌ OAuth error: {CallbackHandler.error}")
        sys.exit(1)

    if not CallbackHandler.auth_code:
        print("❌ No authorization code received")
        sys.exit(1)

    print("✅ Authorization code received, exchanging for tokens...")

    # Exchange code for tokens
    basic_auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

    for attempt in range(5):
        try:
            import requests as req
            resp = req.post("https://api.soundcloud.com/oauth2/token", headers={
                "Authorization": f"Basic {basic_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            }, data={
                "grant_type": "authorization_code",
                "code": CallbackHandler.auth_code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": code_verifier,
            }, timeout=30)
            status = resp.status_code
            body = resp.text
        except ImportError:
            data = urlencode({
                "grant_type": "authorization_code",
                "code": CallbackHandler.auth_code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": code_verifier,
            }).encode()
            req = urllib.request.Request(
                "https://api.soundcloud.com/oauth2/token",
                data=data,
                headers={
                    "Authorization": f"Basic {basic_auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    status = r.status
                    body = r.read().decode()
            except urllib.error.HTTPError as e:
                status = e.code
                body = e.read().decode()

        if status == 429:
            wait = 15 * (attempt + 1)
            print(f"   Rate limited, waiting {wait}s... (attempt {attempt+1}/5)")
            time.sleep(wait)
            continue
        break

    if status != 200:
        print(f"❌ Token exchange failed ({status}): {body[:300]}")
        sys.exit(1)

    token_data = json.loads(body)
    tokens = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_at": int(time.time()) + token_data.get("expires_in", 3600),
        "scope": token_data.get("scope", ""),
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    # Save to both locations
    for path in [TOKEN_FILE, TOKEN_FILE_ALT]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(tokens, f, indent=2)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        print(f"   💾 Saved: {path}")

    # Verify token works
    try:
        import requests as req
        me_resp = req.get("https://api.soundcloud.com/me",
                          headers={"Authorization": f"OAuth {tokens['access_token']}"},
                          timeout=15)
        if me_resp.status_code == 200:
            me = me_resp.json()
            print(f"\n🎉 Authenticated as: {me.get('username', 'unknown')}")
            print(f"   User ID: {me.get('id')}")
            print(f"   Tracks: {me.get('track_count', 0)}")
        else:
            print(f"\n⚠️ Token saved but /me check returned {me_resp.status_code}")
    except Exception as e:
        print(f"\n⚠️ Token saved but /me check failed: {e}")

    print(f"\n✅ SoundCloud OAuth complete! Token expires in {token_data.get('expires_in', 3600)}s")
    print("   The agent can now upload tracks to SoundCloud.")


if __name__ == "__main__":
    main()
