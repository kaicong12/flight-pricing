"""THROWAWAY SPIKE: sign in with the Google client already in .env, and print what comes back.

Verified live 2026-09-11. redirect_uri must be exactly http://localhost:3000 — the only one
registered, and the trailing-slash variant is a mismatch. The id_token carries sub, email,
email_verified, name, given_name, family_name and picture, which is everything userinfo returned,
so sign-in needs no userinfo call. The id_token signature is NOT verified here.
"""

import base64
import json
import os
import secrets
import urllib.parse
import urllib.request
import webbrowser

REDIRECT_URI = "http://localhost:3000"

dotenv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.env")
env = dict(line.strip().split("=", 1) for line in open(dotenv) if "=" in line)
client_id = env["GOOGLE_AUTH_CLIENT_ID"]
client_secret = env["GOOGLE_AUTH_CLIENT_SECRET"]
state, nonce = secrets.token_urlsafe(16), secrets.token_urlsafe(16)

# 1. Send the browser to Google.
url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
    "client_id": client_id,
    "redirect_uri": REDIRECT_URI,
    "response_type": "code",
    "scope": "openid email profile",
    "state": state,
    "nonce": nonce,
    "access_type": "offline",   # the only way to get a refresh_token
    "prompt": "consent",        # else a returning user yields no refresh_token
})
webbrowser.open(url)
print(url)
callback = input("\npaste the URL the browser landed on: ").strip()
q = urllib.parse.parse_qs(urllib.parse.urlparse(callback).query)
assert q["state"][0] == state, "state mismatch"

# 2. Exchange the code for tokens. redirect_uri must byte-match step 1.
body = urllib.parse.urlencode({
    "code": q["code"][0],
    "client_id": client_id,
    "client_secret": client_secret,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code",
}).encode()
req = urllib.request.Request(
    "https://oauth2.googleapis.com/token", data=body,
    headers={"Content-Type": "application/x-www-form-urlencoded"})
tokens = json.loads(urllib.request.urlopen(req).read())
print({k: f"{len(v)} chars" if k.endswith("token") else v for k, v in tokens.items()})

# 3. The user, out of the id_token.
payload = tokens["id_token"].split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
print(json.dumps(claims, indent=2, ensure_ascii=False, sort_keys=True))
assert claims["aud"] == client_id and claims["nonce"] == nonce
