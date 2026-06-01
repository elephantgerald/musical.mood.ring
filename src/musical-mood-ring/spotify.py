# spotify.py
#
# Spotify recently-played API client for musical-mood-ring.
#
# Fetches recently-played tracks and manages OAuth token refresh.
# On MicroPython: uses urequests (bundled) and ubinascii (for base64).
# On CPython (tests/PC): uses standard requests and base64.
#
# Fully implemented: auth_url / exchange_code (M3), recently_played /
# refresh_token (M4).

try:
    import urequests as requests
except ImportError:
    import requests  # type: ignore[no-redef]

try:
    import ubinascii as _b64lib
    def _b64encode(s):
        return _b64lib.b2a_base64(s.encode()).decode().strip()
except ImportError:
    import base64 as _b64lib
    def _b64encode(s):
        return _b64lib.b64encode(s.encode()).decode()

import config as _config

# Set a 6 s socket timeout so hung connections fail before the 8 s WDT fires.
try:
    import usocket as _usocket
    _usocket.setdefaulttimeout(6)
except (ImportError, AttributeError):
    pass

_AUTH_URL         = "https://accounts.spotify.com/authorize"
_REDIRECT_URI     = "http://musical-mood-ring.local/callback"
_REDIRECT_URI_ENC = "http%3A%2F%2Fmusical-mood-ring.local%2Fcallback"
_SCOPE            = "user-read-recently-played"


def _mock_host_ok(host):
    """True only for loopback / RFC1918 mock targets.

    SPOTIFY_MOCK_HOST swaps Spotify's HTTPS endpoints for a plain-HTTP mock,
    so OAuth tokens travel in cleartext. That is acceptable for a local test
    rig but catastrophic if pointed at a public host — a misconfigured (or
    maliciously planted) value would exfiltrate the refresh token. We honour
    the override only when it names a private/loopback address, and otherwise
    fall back to real HTTPS Spotify. The host comes solely from flashed
    config.json (no HTTP write path), so this is defence in depth.
    """
    if not host:
        return False
    h = host.split(":")[0].split("/")[0]   # strip port and any path
    if h == "localhost" or h.startswith("127."):
        return True
    if h.startswith("10.") or h.startswith("192.168."):
        return True
    if h.startswith("172."):                # 172.16.0.0 – 172.31.255.255
        parts = h.split(".")
        if len(parts) >= 2 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
            return True
    return False


def _api_base():
    mock = _config.SPOTIFY_MOCK_HOST
    return ("http://" + mock) if _mock_host_ok(mock) else "https://api.spotify.com"


def _token_base():
    mock = _config.SPOTIFY_MOCK_HOST
    return ("http://" + mock) if _mock_host_ok(mock) else "https://accounts.spotify.com"


def auth_url(client_id):
    """
    Build the Spotify Authorization Code Flow URL.
    Redirect the user's browser here to grant permission.
    """
    return (
        _AUTH_URL
        + "?client_id="      + client_id
        + "&response_type=code"
        + "&redirect_uri="   + _REDIRECT_URI_ENC
        + "&scope="          + _SCOPE
    )


def exchange_code(client_id, client_secret, code):
    """
    Exchange an authorization code for tokens (Authorization Code Flow).
    Returns (access_token, refresh_token, expires_in) or (None, None, 0) on failure.
    """
    resp = None
    try:
        credentials = _b64encode(client_id + ":" + client_secret)
        resp = requests.post(
            _token_base() + "/api/token",
            headers={
                "Authorization": "Basic " + credentials,
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data=(
                "grant_type=authorization_code"
                "&code=" + code
                + "&redirect_uri=" + _REDIRECT_URI_ENC
            ),
        )
        if resp.status_code != 200:
            return None, None, 0
        body = resp.json()
        return body.get("access_token"), body.get("refresh_token"), body.get("expires_in", 3600)
    except Exception:
        return None, None, 0
    finally:
        if resp is not None:
            try: resp.close()
            except Exception: pass


def recently_played(access_token, limit=10):
    """
    Fetch recently-played tracks.
    Returns a list of (track_id, artist_id) tuples, most recent first.
    artist_id is the primary (first-listed) artist on the track.
    Returns [] when the user has no recent plays (successful empty response).
    Returns None on any network or API error — caller should call poller.on_error().
    """
    resp = None
    try:
        resp = requests.get(
            _api_base() + "/v1/me/player/recently-played?limit=" + str(limit),
            headers={"Authorization": "Bearer " + access_token},
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        return [
            (item["track"]["id"], item["track"]["artists"][0]["id"])
            for item in body.get("items", [])
        ]
    except Exception:
        return None
    finally:
        if resp is not None:
            try: resp.close()
            except Exception: pass


def refresh_token(client_id, client_secret, refresh_tok):
    """
    Exchange a refresh token for a new access token.
    Returns (access_token, expires_in_seconds) or (None, 0) on failure.
    """
    resp = None
    try:
        credentials = _b64encode(client_id + ":" + client_secret)
        resp = requests.post(
            _token_base() + "/api/token",
            headers={
                "Authorization":  "Basic " + credentials,
                "Content-Type":   "application/x-www-form-urlencoded",
            },
            data="grant_type=refresh_token&refresh_token=" + refresh_tok,
        )
        if resp.status_code != 200:
            return None, 0
        body = resp.json()
        return body.get("access_token"), body.get("expires_in", 3600)
    except Exception:
        return None, 0
    finally:
        if resp is not None:
            try: resp.close()
            except Exception: pass
