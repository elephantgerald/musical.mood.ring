# spotify.py
#
# Spotify recently-played API client for musical-mood-ring.
#
# Fetches recently-played tracks and manages OAuth token refresh.
# On MicroPython: uses urequests (bundled) and ubinascii (for base64).
# On CPython (tests/PC): uses standard requests and base64.
#
# Implementation stubs — full implementation in M3 (OAuth) and M4 (polling).

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

_RECENTLY_PLAYED_URL = "https://api.spotify.com/v1/me/player/recently-played"
_TOKEN_URL           = "https://accounts.spotify.com/api/token"
_AUTH_URL            = "https://accounts.spotify.com/authorize"
_REDIRECT_URI        = "http://musical-mood-ring.local/callback"
_REDIRECT_URI_ENC    = "http%3A%2F%2Fmusical-mood-ring.local%2Fcallback"
_SCOPE               = "user-read-recently-played"


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
    try:
        credentials = _b64encode(client_id + ":" + client_secret)
        resp = requests.post(
            _TOKEN_URL,
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


def recently_played(access_token, limit=10):
    """
    Fetch recently-played tracks.
    Returns a list of Spotify track IDs (strings), most recent first.
    Returns [] on any error.
    """
    try:
        resp = requests.get(
            _RECENTLY_PLAYED_URL + "?limit=" + str(limit),
            headers={"Authorization": "Bearer " + access_token},
        )
        if resp.status_code != 200:
            return []
        body = resp.json()
        return [item["track"]["id"] for item in body.get("items", [])]
    except Exception:
        return []


def refresh_token(client_id, client_secret, refresh_tok):
    """
    Exchange a refresh token for a new access token.
    Returns (access_token, expires_in_seconds) or (None, 0) on failure.

    TODO (M3): implement and test against real Spotify token endpoint.
    """
    try:
        credentials = _b64encode(client_id + ":" + client_secret)
        resp = requests.post(
            _TOKEN_URL,
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
