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
#                                   or PC-script instructions (if creds saved)
#     POST /spotify/credentials   → save client_id + secret, reload, redirect to /
#     GET  /spotify/auth          → 302 redirect to Spotify authorization URL
#     GET  /callback              → exchange code, save refresh token, done
#     POST /spotify/token         → accept pre-obtained refresh token from PC-side
#                                   OAuth helper (build/spotify_auth.py); saves and
#                                   signals done. Used because Spotify blocks non-HTTPS
#                                   redirect URIs for non-localhost hosts.
#
#   Read-only endpoints (also served in runtime mode from main.py's loop):
#     GET  /misses                → plain-text list of unrecognised track IDs
#                                   (one per line; pipe into cultivator pipeline)
#
# Lifecycle / security:
#   The server runs in one of two modes (see __init__):
#     mode="setup"   — boot.py, time-bounded by setup completion. ALL endpoints
#                      above are routed, including the config-mutating POSTs.
#     mode="runtime" — main.py, always-on for the device's full uptime. Only the
#                      read-only allowlist (_RUNTIME_ENDPOINTS) is routed; every
#                      mutating/setup endpoint returns 403. This is the security
#                      boundary that keeps the always-on server from exposing
#                      /wifi, /spotify/* writes to any LAN host indefinitely.
#
# The server sets done=True when setup is complete or the 5-min timer fires.
# Caller drives the loop: while not server.done: server.step(); animate; sleep

import socket

try:
    import ujson as json
except ImportError:
    import json

try:
    import machine as _machine
    _HW = True
except ImportError:
    _machine = None
    _HW = False

# uptime_ms for /state — ticks_ms is ms-since-boot on MicroPython; the CPython
# fallback is wall-clock and only used in tests (where the value is unused).
try:
    import utime
    def _now_ms(): return utime.ticks_ms()
except ImportError:
    import time
    def _now_ms(): return int(time.time() * 1000)

# free_mem for /state — gc.mem_free() exists only on MicroPython. CPython has gc
# but no mem_free, so report None there.
try:
    import gc as _gc
except ImportError:
    _gc = None

def _free_mem():
    fn = getattr(_gc, "mem_free", None) if _gc is not None else None
    return fn() if fn is not None else None

import config
import miss_log
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
    " and add <code>http://127.0.0.1:8888/callback</code> as a redirect URI.</p>"
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
    "<p>Credentials saved. On your PC, run:</p>"
    "<pre style='background:#f4f4f4;padding:.8em;overflow-x:auto'>"
    "python build/spotify_auth.py</pre>"
    "<p>If <code>musical-mood-ring.local</code> does not resolve, pass your device IP:</p>"
    "<pre style='background:#f4f4f4;padding:.8em;overflow-x:auto'>"
    "python build/spotify_auth.py 10.0.0.xx</pre>"
    "<p>The device will start automatically once authorized.</p>"
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
_HTML_403 = "HTTP/1.0 403 Forbidden\r\n\r\nConfiguration endpoints are disabled at runtime."

# (method, path) tuples reachable while the device runs normally (mode="runtime").
# Read-only only — anything that mutates config must be a setup-mode action so an
# always-on LAN server can't be used to rewrite credentials or redirect traffic.
# #58's introspection endpoints join this set — all read-only JSON GETs.
_RUNTIME_ENDPOINTS = {
    ("GET", "/misses"),
    ("GET", "/state"),
    ("GET", "/pixels"),
    ("GET", "/poll-log"),
    ("GET", "/config"),
}


# ── ConfigServer ─────────────────────────────────────────────────────────────

class ConfigServer:
    """
    Non-blocking HTTP config server.

    mode:  "setup"   — boot.py: all endpoints routed (time-bounded by setup).
           "runtime" — main.py: only _RUNTIME_ENDPOINTS routed; mutating
                       endpoints return 403. See module docstring.

    Pass _sock for testing (dependency injection); omit to use a real socket.
    """

    def __init__(self, host="0.0.0.0", port=80, mode="setup", state=None, _sock=None):
        self.done   = False
        self._mode  = mode
        self._state = state   # RuntimeState ref for introspection endpoints (#58)
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
            conn.settimeout(2.0)   # don't block WDT on slow or probe connections
            raw = conn.recv(1024).decode("utf-8", "ignore")
            self._dispatch(conn, raw)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def lock_runtime(self):
        """Permanently drop to runtime mode — one-way, read-only thereafter.

        main.py calls this once its boot setup window expires. After this,
        only _RUNTIME_ENDPOINTS are routed; every mutating endpoint 403s.
        Idempotent: safe to call every loop iteration.
        """
        self._mode = "runtime"

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

        # Security boundary: in runtime mode, only read-only endpoints are reachable.
        if self._mode == "runtime" and (method, path) not in _RUNTIME_ENDPOINTS:
            conn.send(_HTML_403.encode())
            return

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
        elif method == "POST" and path == "/spotify/token":
            self._handle_spotify_token(conn, _extract_body(raw))
        elif method == "GET" and path == "/misses":
            self._handle_misses(conn)
        elif method == "GET" and path == "/state":
            self._handle_state(conn)
        elif method == "GET" and path == "/pixels":
            self._handle_pixels(conn)
        elif method == "GET" and path == "/poll-log":
            self._handle_poll_log(conn, query)
        elif method == "GET" and path == "/config":
            self._handle_config(conn)
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
        # No done=True: same rationale as _handle_spotify_token. (In practice
        # this device-side callback is vestigial — Spotify blocks the device's
        # redirect URI, so tokens arrive via the PC helper's /spotify/token.)

    def _handle_spotify_token(self, conn, body):
        """Accept a pre-obtained refresh token from the PC-side OAuth helper."""
        token = _parse_form(body).get("refresh_token", "").strip()
        if not token:
            conn.send(b"HTTP/1.0 400 Bad Request\r\n\r\nMissing refresh_token")
            return
        conn.send(b"HTTP/1.0 200 OK\r\n\r\nOK")
        config.save({"spotify_refresh_token": token})
        config.reload()
        # No done=True: this runs inside main.py's live loop during the boot
        # setup window. main.py picks up the token on its next poll and keeps
        # serving read-only introspection. The grace timer governs the
        # setup→runtime transition, not this handler.

    def _handle_misses(self, conn):
        """Return the miss log as plain text (one track ID per line)."""
        body = "\n".join(miss_log.all())
        conn.send(
            ("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n" + body).encode()
        )

    # ── #58 introspection endpoints (read-only JSON) ──────────────────────────

    def _handle_state(self, conn):
        """Full runtime snapshot plus request-time ambient fields.

        Superset of RuntimeState.snapshot() (engine, last_* views, animator,
        error_mode) with wifi_connected / uptime_ms / free_mem resolved here —
        those are hardware-ambient, so they live at the HTTP boundary, not in
        the pure RuntimeState. Tolerates state=None (AP mode, boot.py).
        """
        data = self._state.snapshot() if self._state is not None else {"engine": None}
        data["wifi_connected"] = wifi.is_connected()
        data["uptime_ms"]      = _now_ms()
        data["free_mem"]       = _free_mem()
        _json_response(conn, data)

    def _handle_pixels(self, conn):
        """The colours on the LEDs plus the (v, e) source feeding each pixel.

        `pixels` is the animator's actual output (state.last_colors) — which may
        be an overlay (idle sparkle / error indicator), not the engine's mood
        colours. `source_ve` comes from the engine's tiered per-pixel sources.
        """
        if self._state is not None:
            pixels = [list(c) for c in self._state.last_colors]
            source_ve = (self._state.engine.pixel_sources()
                         if self._state.engine is not None else [None, None, None])
        else:
            pixels    = None
            source_ve = [None, None, None]
        _json_response(conn, {"pixels": pixels, "source_ve": source_ve})

    def _handle_poll_log(self, conn, query):
        """The poll ring buffer (#57), newest first, with an optional ?n= cap.

        The full buffer serializes to ~12 KB worst case (M10 learning); ?n= lets
        a probe pull just the newest few records.
        """
        log = self._state.poll_log_snapshot() if self._state is not None else []
        log.reverse()   # poll_log_snapshot() is oldest-first; serve newest-first
        n = _parse_form(query).get("n")
        if n is not None:
            try:
                limit = max(0, min(int(n), len(log)))
                log   = log[:limit]
            except ValueError:
                pass   # non-numeric ?n= → ignore, return the full log
        _json_response(conn, log)

    def _handle_config(self, conn):
        """Current effective config with secrets redacted.

        Non-secrets (ssid, client_id, mock_host) are shown plain. Secrets are
        masked to "***" when set, "" when unset — so a reader learns *whether* a
        credential exists without ever seeing its value. This masking IS the
        access control that lets /config sit on the read-only runtime allowlist.
        """
        _json_response(conn, {
            "wifi_ssid":             config.WIFI_SSID,
            "wifi_password":         _mask(config.WIFI_PASSWORD),
            "spotify_client_id":     config.SPOTIFY_CLIENT_ID,
            "spotify_client_secret": _mask(config.SPOTIFY_CLIENT_SECRET),
            "spotify_refresh_token": _mask(config.SPOTIFY_REFRESH_TOKEN),
            "spotify_mock_host":     config.SPOTIFY_MOCK_HOST,
        })


# ── Helpers ──────────────────────────────────────────────────────────────────

def _json_response(conn, obj):
    """Send obj as a 200 application/json response."""
    conn.send(
        ("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n"
         + json.dumps(obj)).encode()
    )


def _mask(value):
    """Redact a secret: '***' if present, '' if unset — never the value."""
    return "***" if value else ""


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
