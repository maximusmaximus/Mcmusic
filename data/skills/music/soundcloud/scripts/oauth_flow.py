#!/usr/bin/env python3
"""
SoundCloud OAuth 2.1 Authorization Code Flow.

One-time authentication that:
1. Generates PKCE code_verifier + code_challenge (S256)
2. Builds the authorization URL
3. Starts a temporary HTTP server on 127.0.0.1:8080 to catch the callback
4. Exchanges the authorization code for access_token + refresh_token
5. Stores tokens securely in ~/.hermes/credentials/soundcloud_tokens.json

Usage:
    python3 oauth_flow.py --auth       # Run the full OAuth flow (local server)
    python3 oauth_flow.py --status     # Check current token status
    python3 oauth_flow.py --refresh    # Force a token refresh

IMPORTANT: SoundCloud no longer allows scope=non-expiring (returns 403).
           Use empty scope — tokens expire and must be refreshed.
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

# Configuration — correct endpoints per SoundCloud OpenAPI spec
SOUNDCLOUD_AUTH_URL = "https://api.soundcloud.com/connect"
SOUNDCLOUD_TOKEN_URL = "https://api.soundcloud.com/oauth2/token"
REDIRECT_URI = "http://127.0.0.1:8080/callback"
REDIRECT_PORT = 8080
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".hermes", "credentials", "soundcloud_tokens.json")


def get_credentials():
    """Get client_id and client_secret from environment variables."""
    client_id = os.environ.get("SOUNDCLOUD_CLIENT_ID", "")
    client_secret = os.environ.get("SOUNDCLOUD_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print(json.dumps({
            "success": False,
            "error": "SOUNDCLOUD_CLIENT_ID and SOUNDCLOUD_CLIENT_SECRET must be set as environment variables. "
                     "Get them from https://soundcloud.com/you/apps"
        }))
        sys.exit(1)
    return client_id, client_secret


def generate_pkce():
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def load_tokens():
    """Load tokens from disk. Returns dict or None."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_tokens(tokens):
    """Save tokens to disk with restricted permissions."""
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return tokens


def is_token_expired(tokens):
    """Check if the access token is expired (with 60s buffer)."""
    if not tokens or "expires_at" not in tokens:
        return True
    return time.time() > (tokens["expires_at"] - 60)


def refresh_access_token(tokens):
    """Refresh the access token using the refresh token. Returns new tokens dict."""
    client_id = tokens.get("client_id") or os.environ.get("SOUNDCLOUD_CLIENT_ID", "")
    client_secret = tokens.get("client_secret") or os.environ.get("SOUNDCLOUD_CLIENT_SECRET", "")

    if not tokens.get("refresh_token"):
        return None

    # SoundCloud requires client credentials in POST body (NOT Basic auth header)
    resp = requests.post(SOUNDCLOUD_TOKEN_URL, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=30)

    if resp.status_code != 200:
        return None

    new_tokens = resp.json()
    result = {
        "access_token": new_tokens["access_token"],
        "refresh_token": new_tokens.get("refresh_token", tokens.get("refresh_token")),
        "expires_at": int(time.time()) + new_tokens.get("expires_in", 3600),
        "scope": new_tokens.get("scope", tokens.get("scope", "")),
        "client_id": client_id,
        "client_secret": client_secret,
    }
    return save_tokens(result)


def get_valid_token():
    """
    Get a valid access token, refreshing if necessary.
    Returns (access_token, tokens_dict) or (None, None) if auth is needed.
    """
    tokens = load_tokens()
    if not tokens:
        return None, None

    if not is_token_expired(tokens):
        return tokens["access_token"], tokens

    new_tokens = refresh_access_token(tokens)
    if new_tokens:
        return new_tokens["access_token"], new_tokens

    return None, None


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that catches the OAuth callback."""

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
                <h1>&#x2713; Authenticated!</h1>
                <p>You can close this tab now.</p>
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
                <h1>&#x2717; Authentication Failed</h1>
                <p>{CallbackHandler.error}</p>
                </div></body></html>
            """.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default HTTP logging."""
        pass


def run_auth_flow():
    """Execute the full OAuth 2.1 PKCE authorization flow."""
    client_id, client_secret = get_credentials()
    code_verifier, _code_challenge = generate_pkce()

    # Build authorization URL — NO scope param (non-expiring is forbidden)
    # NOTE: PKCE code_challenge is NOT sent — SoundCloud returns invalid_request
    # on token exchange when PKCE is used, even with correct code_verifier.
    auth_params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
    }
    auth_url = SOUNDCLOUD_AUTH_URL + "?" + "&".join(
        f"{k}={v}" for k, v in auth_params.items()
    )

    print(f"[soundcloud] Authorization URL:\n{auth_url}\n", file=sys.stderr)

    # Try to open browser (won't work on WSL — user must copy URL manually)
    opened = webbrowser.open(auth_url)
    if opened:
        print("[soundcloud] Browser opened. Authorize the app and you'll be redirected.", file=sys.stderr)
    else:
        print("[soundcloud] Could not open browser automatically (common on WSL).", file=sys.stderr)
        print("[soundcloud] Copy the URL above into your browser manually.", file=sys.stderr)

    # Start local HTTP server to catch callback
    print(f"[soundcloud] Waiting for callback on http://127.0.0.1:{REDIRECT_PORT}...", file=sys.stderr)
    CallbackHandler.auth_code = None
    CallbackHandler.error = None

    server = HTTPServer(("127.0.0.1", REDIRECT_PORT), CallbackHandler)
    server.handle_request()  # Handle ONE request then stop

    if CallbackHandler.error:
        result = {"success": False, "error": f"OAuth error: {CallbackHandler.error}"}
        print(json.dumps(result))
        sys.exit(1)

    if not CallbackHandler.auth_code:
        result = {"success": False, "error": "No authorization code received"}
        print(json.dumps(result))
        sys.exit(1)

    print("[soundcloud] Authorization code received, exchanging for tokens...", file=sys.stderr)

    # Exchange code for tokens — SoundCloud requires body auth (NOT Basic auth header)
    resp = requests.post(SOUNDCLOUD_TOKEN_URL, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "grant_type": "authorization_code",
        "code": CallbackHandler.auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=30)

    if resp.status_code != 200:
        try:
            err = resp.json()
            error_msg = err.get("error_description", err.get("error", resp.text))
        except Exception:
            error_msg = resp.text
        result = {"success": False, "error": f"Token exchange failed ({resp.status_code}): {error_msg}"}
        print(json.dumps(result))
        sys.exit(1)

    token_data = resp.json()
    tokens = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_at": int(time.time()) + token_data.get("expires_in", 3600),
        "scope": token_data.get("scope", ""),
        "client_id": client_id,
        "client_secret": client_secret,
    }
    save_tokens(tokens)

    print("[soundcloud] ✅ Authentication successful! Tokens saved.", file=sys.stderr)
    print(json.dumps({
        "success": True,
        "message": "Authentication complete. Tokens saved to ~/.hermes/credentials/soundcloud_tokens.json",
        "expires_at": tokens["expires_at"],
        "scope": tokens["scope"],
    }))


def show_status():
    """Show current token status."""
    tokens = load_tokens()
    if not tokens:
        print(json.dumps({"success": False, "error": "No tokens found. Run with --auth to authenticate."}))
        sys.exit(1)

    expired = is_token_expired(tokens)
    if expired:
        new_tokens = refresh_access_token(tokens)
        if new_tokens:
            tokens = new_tokens
            expired = False
            status = "refreshed"
        else:
            status = "expired (re-auth needed)"
    else:
        remaining = tokens["expires_at"] - int(time.time())
        status = f"valid ({remaining // 60}m remaining)"

    print(json.dumps({
        "success": True,
        "status": status,
        "expired": expired,
        "has_refresh_token": bool(tokens.get("refresh_token")),
        "scope": tokens.get("scope", ""),
        "expires_at": tokens.get("expires_at"),
    }, indent=2))


def force_refresh():
    """Force a token refresh."""
    tokens = load_tokens()
    if not tokens:
        print(json.dumps({"success": False, "error": "No tokens found. Run with --auth first."}))
        sys.exit(1)

    new_tokens = refresh_access_token(tokens)
    if new_tokens:
        print(json.dumps({"success": True, "message": "Token refreshed", "expires_at": new_tokens["expires_at"]}))
    else:
        print(json.dumps({"success": False, "error": "Refresh failed. Run with --auth to re-authenticate."}))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="SoundCloud OAuth 2.1 PKCE Authentication")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--auth", action="store_true", help="Run the OAuth authorization flow")
    group.add_argument("--status", action="store_true", help="Check current token status")
    group.add_argument("--refresh", action="store_true", help="Force token refresh")

    args = parser.parse_args()

    if args.auth:
        run_auth_flow()
    elif args.status:
        show_status()
    elif args.refresh:
        force_refresh()


if __name__ == "__main__":
    main()
