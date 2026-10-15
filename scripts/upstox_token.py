"""Daily Upstox login helper: turns the one-time login `code` into an access token the bot reads.

    Step 1  python scripts/upstox_token.py            prints the login URL
    Step 2  open it, log in, copy the `code=` value from the redirect URL
    Step 3  python scripts/upstox_token.py --code XXXXXX   saves .state/upstox_token.txt

Needs UPSTOX_API_KEY, UPSTOX_API_SECRET and UPSTOX_REDIRECT_URI in .env (the same redirect URI as in your
Upstox developer app). The bot re-reads the token file on every cycle, so no restart is needed.
This follows Upstox's standard OAuth flow; confirm against their current docs if a step fails.
"""
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

p = argparse.ArgumentParser()
p.add_argument("--code", help="authorization code from the redirect URL")
p.add_argument("--out", default=os.getenv("UPSTOX_TOKEN_FILE", ".state/upstox_token.txt"))
a = p.parse_args()

key, secret, redirect = (os.getenv(k, "") for k in ("UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_REDIRECT_URI"))
if not (key and redirect):
    sys.exit("Set UPSTOX_API_KEY and UPSTOX_REDIRECT_URI (and UPSTOX_API_SECRET for step 3) in .env")

if not a.code:
    q = urlencode({"client_id": key, "redirect_uri": redirect, "response_type": "code"})
    print("Open this URL, log in, then copy the code= value from the page you land on:\n")
    print(f"https://api.upstox.com/v2/login/authorization/dialog?{q}")
    sys.exit(0)

if not secret:
    sys.exit("Set UPSTOX_API_SECRET in .env")
r = requests.post(
    "https://api.upstox.com/v2/login/authorization/token",
    headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    data={"code": a.code, "client_id": key, "client_secret": secret, "redirect_uri": redirect,
          "grant_type": "authorization_code"},
    timeout=20,
)
if not r.ok:
    sys.exit(f"Token request failed (HTTP {r.status_code}): {r.text[:300]}")
token = r.json().get("access_token")
if not token:
    sys.exit(f"No access_token in response: {r.text[:300]}")
out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(token)
try:
    out.chmod(0o600)
except OSError:
    pass
print(f"Saved token to {out}. The bot picks it up on its next cycle.")
