# config.py
#
# Configuration loader for musical-mood-ring.
# Reads config.json from the ESP32's flash filesystem.
# Written once by the config server during first-boot setup.
#
# try/except makes this importable in CPython (tests) where the file won't exist.

try:
    import ujson as json
except ImportError:
    import json

_PATH = "config.json"

_DEFAULTS = {
    "wifi_ssid":              "",
    "wifi_password":          "",
    "spotify_client_id":      "",
    "spotify_client_secret":  "",
    "spotify_refresh_token":  "",
}

try:
    with open(_PATH) as f:
        _cfg = json.load(f)
except OSError:
    _cfg = {}


def get(key, default=None):
    return _cfg.get(key, _DEFAULTS.get(key, default))


WIFI_SSID             = get("wifi_ssid")
WIFI_PASSWORD         = get("wifi_password")
SPOTIFY_CLIENT_ID     = get("spotify_client_id")
SPOTIFY_CLIENT_SECRET = get("spotify_client_secret")
SPOTIFY_REFRESH_TOKEN = get("spotify_refresh_token")
