#!/usr/bin/env python3
"""
setup_gcal_auth.py

Run ONCE on the Pi to authorize Google Calendar access and save
a refresh token to .env. After that, fetch_data.py handles token
refresh automatically.

Usage:
  python setup_gcal_auth.py
"""

import http.server
import os
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
REDIRECT_URI = "http://localhost:3456/oauth2callback"
ENV_PATH = Path(__file__).parent / ".env"

_code_holder: dict[str, str] = {}


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _code_holder["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorized &#10003;</h1><p>You can close this tab.</p>")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # suppress access logs


def _wait_for_code(timeout: int = 300) -> str:
    server = http.server.HTTPServer(("localhost", 3456), _OAuthCallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    elapsed = 0
    while "code" not in _code_holder and elapsed < timeout:
        time.sleep(1)
        elapsed += 1

    server.shutdown()

    if "code" not in _code_holder:
        print("\nTimeout waiting for authorization.", file=sys.stderr)
        sys.exit(1)

    return _code_holder["code"]


def main() -> None:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first.", file=sys.stderr)
        sys.exit(1)

    flow = Flow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": [REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    print("\n─────────────────────────────────────────────────")
    print("1. Open this URL in your browser:\n")
    print(f"   {auth_url}")
    print("\n2. Authorize — the token will be saved automatically.")
    print("─────────────────────────────────────────────────\n")

    code = _wait_for_code()
    flow.fetch_token(code=code)
    creds = flow.credentials

    if not creds.refresh_token:
        print(
            "\nNo refresh token returned. This happens if you've already authorized this app.\n"
            "Go to https://myaccount.google.com/permissions, revoke access for this app, "
            "then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    content = ENV_PATH.read_text()
    if "GOOGLE_REFRESH_TOKEN=" in content:
        content = re.sub(
            r"GOOGLE_REFRESH_TOKEN=.*",
            f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}",
            content,
        )
    else:
        content += f"\nGOOGLE_REFRESH_TOKEN={creds.refresh_token}\n"
    ENV_PATH.write_text(content)

    print("\n✓ Refresh token saved to .env — you're all set.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Auth setup failed: {e}", file=sys.stderr)
        sys.exit(1)
