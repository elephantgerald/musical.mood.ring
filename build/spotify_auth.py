#!/usr/bin/env python3
"""
spotify_auth.py — PC-side Spotify OAuth helper for musical.mood.ring.

Spotify blocks non-HTTPS redirect URIs for non-localhost hosts, so the device
cannot serve the OAuth callback directly. This script runs the OAuth flow on
the PC (using http://127.0.0.1:8888/callback) and injects the refresh token
into the device via POST /spotify/token.

Usage:
    python build/spotify_auth.py [device-host]

    device-host  IP or hostname of the device (default: musical-mood-ring.local)

Prerequisites:
    - http://127.0.0.1:8888/callback registered in your Spotify app dashboard
    - Run this within the device's boot SETUP WINDOW — the first ~5 minutes
      after power-on, while WiFi + Spotify credentials are already saved
      (SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET). POST /spotify/token returns
      403 once that window closes and the device locks to read-only runtime,
      so re-auth means power-cycling the board and acting within the window.

Environment variables (optional — prompted if absent):
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event

_REDIRECT_URI = "http://127.0.0.1:8888/callback"
_SCOPE        = "user-read-recently-played"
_PORT         = 8888

_done      = Event()
_auth_code = None
_auth_error = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code, _auth_error
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            _auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Authorized. You can close this tab.</h2>")
        else:
            _auth_error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h2>Error: {_auth_error}</h2>".encode())
        _done.set()

    def log_message(self, *_):
        pass


def _prompt(env_key, label):
    val = os.environ.get(env_key, "").strip()
    return val if val else input(f"{label}: ").strip()


def main():
    device_host   = sys.argv[1] if len(sys.argv) > 1 else "musical-mood-ring.local"
    client_id     = _prompt("SPOTIFY_CLIENT_ID",     "Spotify Client ID    ")
    client_secret = _prompt("SPOTIFY_CLIENT_SECRET", "Spotify Client Secret")

    auth_url = (
        "https://accounts.spotify.com/authorize"
        "?client_id="      + urllib.parse.quote(client_id, safe="")
        + "&response_type=code"
        + "&redirect_uri=" + urllib.parse.quote(_REDIRECT_URI, safe="")
        + "&scope="        + urllib.parse.quote(_SCOPE, safe="")
    )

    print("\nOpening Spotify authorization in your browser...")
    webbrowser.open(auth_url)
    print(f"Waiting for callback on {_REDIRECT_URI} ...")

    server = HTTPServer(("127.0.0.1", _PORT), _CallbackHandler)
    server.timeout = 1.0
    while not _done.is_set():
        server.handle_request()
    server.server_close()

    if _auth_error or not _auth_code:
        print(f"\nERROR: Authorization failed — {_auth_error or 'no code received'}")
        sys.exit(1)

    print("Code received. Exchanging for refresh token...")

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    token_req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({
            "grant_type":   "authorization_code",
            "code":         _auth_code,
            "redirect_uri": _REDIRECT_URI,
        }).encode(),
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(token_req) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"\nERROR: Token exchange failed — {e.code} {e.read().decode()}")
        sys.exit(1)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print(f"\nERROR: No refresh token in response: {tokens}")
        sys.exit(1)

    print(f"Token obtained. Injecting into device at {device_host} ...")

    inject_req = urllib.request.Request(
        f"http://{device_host}/spotify/token",
        data=urllib.parse.urlencode({"refresh_token": refresh_token}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(inject_req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        print(f"\nERROR: Could not reach device at {device_host} — {e}")
        print(f"\nRefresh token (inject manually if needed):\n  {refresh_token}")
        sys.exit(1)

    print("\nDone. Device authorized and starting up.")


if __name__ == "__main__":
    main()
