# config_server.py
#
# Non-blocking HTTP config server for musical-mood-ring.
#
# Handles two distinct setup phases driven by boot.py:
#
#   Phase 1 — WiFi setup (AP mode, first boot):
#     GET  /                      → WiFi SSID + password form
#     POST /wifi                  → validate, save, machine.reset()
#
#   Phase 2 — Spotify OAuth (STA mode, after WiFi is configured):
#     GET  /                      → Spotify credentials form (if not saved yet)
#                                   or "Authorize" button (if creds saved)
#     POST /spotify/credentials   → save client_id + secret, reload, redirect to /
#     GET  /spotify/auth          → 302 redirect to Spotify authorization URL
#     GET  /callback              → exchange code, save refresh token, done
#
# The server sets done=True when setup is complete or the 5-min timer fires.
# Caller drives the loop: while not server.done: server.step(); animate; sleep

import socket

try:
    import machine as _machine
    _HW = True
except ImportError:
    _machine = None
    _HW = False

import config
import wifi
import spotify

# ── HTML templates ───────────────────────────────────────────────────────────

_STYLE = (
    "<style>body{font-family:sans-serif;max-width:400px;margin:2em auto;padding:0 1em}"
    "input{width:100%;box-sizing:border-box;padding:.5em;margin:.3em 0 .8em}"
    ".btn{display:block;width:100%;padding:.7em;border:none;font-size:1em;"
    "cursor:pointer;text-align:center;text-decoration:none;box-sizing:border-box}"
    ".blue{background:#2255aa;color:#fff}.green{background:#1db954;color:#fff}</style>"
)

_HEAD = (
    "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n"
    "<!DOCTYPE html><html><head><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
)

_HTML_WIFI_FORM = (
    _HEAD + "<title>musical.mood.ring — WiFi</title>" + _STYLE + "</head>"
    "<body><h2>musical.mood.ring</h2>"
    "<p>Enter your WiFi credentials to connect.</p>"
    "<form method=post action=/wifi>"
    "<label>Network name (SSID)<br>"
    "<input name=ssid type=text autocomplete=off></label>"
    "<label>Password<br>"
    "<input name=password type=password autocomplete=off></label>"
    "<button type=submit class='btn blue'>Connect</button>"
    "</form></body></html>"
)

_HTML_WIFI_OK = (
    _HEAD + "<title>Connected</title></head>"
    "<body><h2>Connected!</h2>"
    "<p>Device is connecting to WiFi and will reboot.</p>"
    "</body></html>"
)

_HTML_WIFI_ERROR = (
    _HEAD + "<title>Error</title></head>"
    "<body><h2>Connection failed</h2>"
    "<p>Could not connect to that network. Check your credentials and try again.</p>"
    "<p><a href=/>Try again</a></p>"
    "</body></html>"
)

_HTML_SPOTIFY_CREDS_FORM = (
    _HEAD + "<title>musical.mood.ring — Spotify</title>" + _STYLE + "</head>"
    "<body><h2>Spotify Setup</h2>"
    "<p>Enter your Spotify app credentials. "
    "<a href=https://developer.spotify.com/dashboard target=_blank>Create an app</a>"
    " and set the redirect URI to "
    "<code>http://musical-mood-ring.local/callback</code>.</p>"
    "<form method=post action=/spotify/credentials>"
    "<label>Client ID<br>"
    "<input name=client_id type=text autocomplete=off></label>"
    "<label>Client Secret<br>"
    "<input name=client_secret type=password autocomplete=off></label>"
    "<button type=submit class='btn green'>Save &amp; Continue</button>"
    "</form></body></html>"
)

_HTML_SPOTIFY_AUTHORIZE = (
    _HEAD + "<title>musical.mood.ring — Authorize</title>" + _STYLE + "</head>"
    "<body><h2>Authorize Spotify</h2>"
    "<p>App credentials saved. Click below to grant this device access.</p>"
    "<a href=/spotify/auth class='btn green'>Authorize with Spotify</a>"
    "</body></html>"
)

_HTML_SPOTIFY_SUCCESS = (
    _HEAD + "<title>Done</title></head>"
    "<body><h2>Spotify Connected!</h2>"
    "<p>Authorization complete. Device is saving tokens and starting up.</p>"
    "</body></html>"
)

_HTML_SPOTIFY_ERROR = (
    _HEAD + "<title>Error</title></head>"
    "<body><h2>Authorization Failed</h2>"
    "<p>Spotify authorization was denied or an error occurred.</p>"
    "<p><a href=/>Try again</a></p>"
    "</body></html>"
)

_HTML_404 = "HTTP/1.0 404 Not Found\r\n\r\n"


# ── ConfigServer ─────────────────────────────────────────────────────────────

class ConfigServer:
    """
    Non-blocking HTTP config server.

    Pass _sock for testing (dependency injection); omit to use a real socket.
    """

    def __init__(self, host="0.0.0.0", port=80, _sock=None):
        self.done = False
        if _sock is not None:
            self._sock = _sock
        else:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((host, port))
            self._sock.listen(1)
            self._sock.setblocking(False)

    def step(self):
        """Accept and handle at most one HTTP request. Returns immediately."""
        if self.done:
            return
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return  # no connection waiting — normal in non-blocking mode
        try:
            raw = conn.recv(1024).decode("utf-8", "ignore")
            self._dispatch(conn, raw)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        """Close the server socket and signal done."""
        self.done = True
        try:
            self._sock.close()
        except Exception:
            pass

    def _dispatch(self, conn, raw):
        """Parse the request line, route to the right handler."""
        lines = raw.replace("\r\n", "\n").split("\n")
        if not lines:
            conn.send(_HTML_404.encode())
            return
        parts = lines[0].split()
        if len(parts) < 2:
            conn.send(_HTML_404.encode())
            return
        method  = parts[0].upper()
        path_qs = parts[1]
        path    = path_qs.split("?")[0]
        query   = path_qs.split("?")[1] if "?" in path_qs else ""

        if method == "GET" and path == "/":
            self._handle_root(conn)
        elif method == "POST" and path == "/wifi":
            self._handle_wifi(conn, _extract_body(raw))
        elif method == "POST" and path == "/spotify/credentials":
            self._handle_spotify_credentials(conn, _extract_body(raw))
        elif method == "GET" and path == "/spotify/auth":
            self._handle_spotify_auth(conn)
        elif method == "GET" and path == "/callback":
            self._handle_spotify_callback(conn, _parse_form(query))
        else:
            conn.send(_HTML_404.encode())

    # ── Route handlers ────────────────────────────────────────────────────────

    def _handle_root(self, conn):
        """Context-aware home page: WiFi form → Spotify creds form → Authorize."""
        if not config.WIFI_SSID:
            conn.send(_HTML_WIFI_FORM.encode())
        elif not config.SPOTIFY_CLIENT_ID:
            conn.send(_HTML_SPOTIFY_CREDS_FORM.encode())
        else:
            conn.send(_HTML_SPOTIFY_AUTHORIZE.encode())

    def _handle_wifi(self, conn, body):
        """Validate WiFi credentials; save and reboot on success."""
        params   = _parse_form(body)
        ssid     = params.get("ssid", "").strip()
        password = params.get("password", "")
        if not ssid:
            conn.send(_HTML_WIFI_ERROR.encode())
            return
        ok = wifi.try_connect(ssid, password)
        if not ok:
            conn.send(_HTML_WIFI_ERROR.encode())
            return
        conn.send(_HTML_WIFI_OK.encode())
        config.save({"wifi_ssid": ssid, "wifi_password": password})
        if _HW:
            _machine.reset()
        else:
            self.done = True  # CPython: signal done instead of rebooting

    def _handle_spotify_credentials(self, conn, body):
        """Save Spotify client_id + client_secret; redirect to / to show Authorize."""
        params        = _parse_form(body)
        client_id     = params.get("client_id", "").strip()
        client_secret = params.get("client_secret", "").strip()
        if not client_id or not client_secret:
            conn.send(_HTML_SPOTIFY_CREDS_FORM.encode())
            return
        config.save({"spotify_client_id": client_id, "spotify_client_secret": client_secret})
        config.reload()
        conn.send(b"HTTP/1.0 302 Found\r\nLocation: /\r\n\r\n")

    def _handle_spotify_auth(self, conn):
        """Redirect the browser to Spotify's authorization page."""
        client_id = config.SPOTIFY_CLIENT_ID
        if not client_id:
            conn.send(_HTML_SPOTIFY_CREDS_FORM.encode())
            return
        url = spotify.auth_url(client_id)
        conn.send(("HTTP/1.0 302 Found\r\nLocation: " + url + "\r\n\r\n").encode())

    def _handle_spotify_callback(self, conn, query_params):
        """Exchange the authorization code for tokens; save and signal done."""
        if query_params.get("error"):
            conn.send(_HTML_SPOTIFY_ERROR.encode())
            return
        code = query_params.get("code", "")
        if not code:
            conn.send(_HTML_SPOTIFY_ERROR.encode())
            return
        _, refresh_token, _ = spotify.exchange_code(
            config.SPOTIFY_CLIENT_ID,
            config.SPOTIFY_CLIENT_SECRET,
            code,
        )
        if not refresh_token:
            conn.send(_HTML_SPOTIFY_ERROR.encode())
            return
        conn.send(_HTML_SPOTIFY_SUCCESS.encode())
        config.save({"spotify_refresh_token": refresh_token})
        config.reload()
        self.done = True  # boot.py exits the loop and falls through to main.py


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_body(raw):
    """Return everything after the blank header line."""
    if "\r\n\r\n" in raw:
        return raw.split("\r\n\r\n", 1)[1]
    if "\n\n" in raw:
        return raw.split("\n\n", 1)[1]
    return ""


def _parse_form(body):
    """Parse application/x-www-form-urlencoded string into a dict."""
    params = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            params[_urldecode(k)] = _urldecode(v)
    return params


def _urldecode(s):
    """Minimal URL percent-decoding: + → space, %XX → char."""
    s = s.replace("+", " ")
    out = []
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                out.append(chr(int(s[i + 1:i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(s[i])
        i += 1
    return "".join(out)
