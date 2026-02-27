# config_server.py
#
# Non-blocking HTTP config server for musical-mood-ring.
# Serves a WiFi credential form on first boot (AP mode).
#
# The caller drives the event loop by calling step() repeatedly:
#
#     server = ConfigServer()
#     while not server.done:
#         server.step()
#         pixel.write(animator.step(FRAME_MS))
#         sleep_ms(FRAME_MS)
#
# The server sets done=True when:
#   - WiFi credentials are validated and saved (device will reboot)
#   - The 5-minute config window expires (stop() is called by the timer)

import socket

try:
    import machine as _machine
    _HW = True
except ImportError:
    _machine = None
    _HW = False

import config
import wifi

# ── HTML responses ──────────────────────────────────────────────────────────

_HTML_FORM = (
    "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n"
    "<!DOCTYPE html><html>"
    "<head><meta charset=utf-8><title>musical.mood.ring</title>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<style>body{font-family:sans-serif;max-width:400px;margin:2em auto;padding:0 1em}"
    "input{width:100%;box-sizing:border-box;padding:.5em;margin:.3em 0 .8em}"
    "button{width:100%;padding:.7em;background:#2255aa;color:#fff;border:none;"
    "font-size:1em;cursor:pointer}</style></head>"
    "<body><h2>musical.mood.ring</h2>"
    "<p>Enter your WiFi credentials to connect.</p>"
    "<form method=post action=/wifi>"
    "<label>Network name (SSID)<br>"
    "<input name=ssid type=text autocomplete=off></label>"
    "<label>Password<br>"
    "<input name=password type=password autocomplete=off></label>"
    "<button type=submit>Connect</button>"
    "</form></body></html>"
)

_HTML_OK = (
    "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n"
    "<!DOCTYPE html><html><body>"
    "<h2>Connected!</h2>"
    "<p>Device is connecting to WiFi and will reboot.</p>"
    "</body></html>"
)

_HTML_ERROR = (
    "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n"
    "<!DOCTYPE html><html><body>"
    "<h2>Connection failed</h2>"
    "<p>Could not connect to that network. Check your credentials and try again.</p>"
    "<p><a href=/>Try again</a></p>"
    "</body></html>"
)

_HTML_STUB = (
    "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n"
    "<!DOCTYPE html><html><body>"
    "<p>Spotify setup not yet available (M3).</p>"
    "</body></html>"
)

_HTML_404 = "HTTP/1.0 404 Not Found\r\n\r\n"


# ── ConfigServer ────────────────────────────────────────────────────────────

class ConfigServer:
    """
    Non-blocking HTTP server that serves the WiFi config form.

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
        method = parts[0].upper()
        path   = parts[1]

        if method == "GET" and path == "/":
            conn.send(_HTML_FORM.encode())
        elif method == "POST" and path == "/wifi":
            body = _extract_body(raw)
            self._handle_wifi(conn, body)
        elif method == "GET" and path == "/spotify/auth":
            conn.send(_HTML_STUB.encode())
        elif method == "GET" and path == "/spotify/callback":
            conn.send(_HTML_STUB.encode())
        else:
            conn.send(_HTML_404.encode())

    def _handle_wifi(self, conn, body):
        """Validate WiFi credentials; save and reboot on success."""
        params   = _parse_form(body)
        ssid     = params.get("ssid", "").strip()
        password = params.get("password", "")
        if not ssid:
            conn.send(_HTML_ERROR.encode())
            return
        ok = wifi.try_connect(ssid, password)
        if not ok:
            conn.send(_HTML_ERROR.encode())
            return
        conn.send(_HTML_OK.encode())
        config.save({"wifi_ssid": ssid, "wifi_password": password})
        if _HW:
            _machine.reset()
        else:
            self.done = True  # signal done to the test loop


# ── Helpers ─────────────────────────────────────────────────────────────────

def _extract_body(raw):
    """Return everything after the blank header line."""
    if "\r\n\r\n" in raw:
        return raw.split("\r\n\r\n", 1)[1]
    if "\n\n" in raw:
        return raw.split("\n\n", 1)[1]
    return ""


def _parse_form(body):
    """Parse application/x-www-form-urlencoded body into a dict."""
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
