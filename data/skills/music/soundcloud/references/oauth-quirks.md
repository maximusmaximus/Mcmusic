# SoundCloud OAuth 2.1 — Integration Quirks

Discovered during live integration testing on 2026-07-14. These override
any older tutorials or docs that reference `secure.soundcloud.com` or `scope=non-expiring`.

## Endpoints

| Purpose | URL |
|---------|-----|
| Authorization | `GET https://api.soundcloud.com/connect` |
| Token exchange | `POST https://api.soundcloud.com/oauth2/token` |

**Wrong URLs that do NOT work:**
- `https://secure.soundcloud.com/authorize` — redirects to `api.soundcloud.com/connect` for the auth page, but the token endpoint on `secure.soundcloud.com` returns 404 ("Cannot POST /oauth2/token")
- `https://secure.soundcloud.com/oauth2/token` — 404

## Scope Restriction

SoundCloud **forbids** `scope=non-expiring`. Response:

```json
{"code": 403, "message": "Requesting non-expiring tokens is not allowed. Set scope=''."}
```

**Fix:** Omit the `scope` parameter entirely from the authorization URL.
Tokens expire after ~1 hour and must be refreshed via `grant_type=refresh_token`.

## Client Authentication — Body Params Required

The `/oauth2/token` endpoint requires client credentials as **POST body parameters** (`client_id` and `client_secret`), NOT as a Basic Authorization header.

**Working:**
```python
resp = requests.post(TOKEN_URL, headers={
    "Content-Type": "application/x-www-form-urlencoded",
}, data={
    "grant_type": "authorization_code",
    "code": auth_code,
    "redirect_uri": redirect_uri,
    "client_id": client_id,
    "client_secret": client_secret,
})
```

**NOT working** (returns `invalid_request`):
```python
import base64
basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
resp = requests.post(TOKEN_URL, headers={
    "Authorization": f"Basic {basic}",        # ← rejected
    "Content-Type": "application/x-www-form-urlencoded",
}, data={
    "grant_type": "authorization_code",
    "code": auth_code,
    "redirect_uri": redirect_uri,
})
```

This applies to both `authorization_code` and `refresh_token` grant types.

## PKCE — DO NOT USE

> **⚠️ Skip PKCE for now.** Auth requests WITHOUT `code_challenge` work fine.
> Auth requests WITH `code_challenge` (S256) succeed at the authorization step,
> but the subsequent token exchange returns `invalid_request` even when a correct
> `code_verifier` is provided. This may be a SoundCloud bug or undocumented restriction.

~~Standard PKCE works:~~
1. ~~`code_verifier` = `secrets.token_urlsafe(64)[:128]`~~
2. ~~`code_challenge` = `base64.urlsafe_b64encode(SHA256(code_verifier)).rstrip("=")`~~
3. ~~Send `code_challenge` + `code_challenge_method=S256` in auth URL~~
4. ~~Send `code_verifier` in token exchange request~~

**Do NOT send `code_challenge` or `code_challenge_method` in the authorization URL.**
**Do NOT send `code_verifier` in the token exchange request.**

Auth code format is JWE (starts with `eyJlbm...`), not a simple short string.

## Rate Limiting

The `/oauth2/token` endpoint has aggressive rate limiting:
- ~5 failed attempts trigger a 429
- 429 cooldown appears to be 30-60+ seconds
- No `Retry-After` header observed on the token endpoint
- Other endpoints (e.g. GET /tracks with client_id) may not be affected

**Recommendation:** Do not retry token exchange rapidly on failure.
Use exponential backoff (30s, 60s, 90s...).

## WSL-Specific Auth Flow

On WSL, the standard OAuth flow (`--auth` with local HTTP server) fails because:
1. `webbrowser.open()` cannot open the Windows browser from WSL
2. The browser redirect to `http://127.0.0.1:8080/callback` cannot reach the WSL HTTP server

**Workaround — manual 3-step flow:**
1. Run `oauth_flow.py --auth-url` → prints the authorization URL
2. User opens URL in Windows browser, signs in, authorizes
3. User copies the callback URL from the browser address bar (page shows error, but URL contains the code)
4. Run `oauth_flow.py --exchange-code CODE` or `--exchange-url 'http://127.0.0.1:8080/callback?code=...'`

## Token Lifecycle

- Access tokens expire ~1 hour after issuance
- Refresh tokens are single-use — each refresh returns a new refresh_token
- If refresh fails (token revoked, already used), user must re-authenticate
- Store `client_id` and `client_secret` alongside tokens for automatic refresh
