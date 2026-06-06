import json

import pytest
from unittest.mock import MagicMock, patch

import config_server
import miss_log
from config_server import ConfigServer, _parse_form, _urldecode, _extract_body
from conftest import build_bundle
from mmar          import MMARBundle
from mood_engine   import MoodEngine
from runtime_state import RuntimeState


# ── Helpers ─────────────────────────────────────────────────────────────────

def _mock_sock():
    """A mock socket that raises OSError on accept() (no waiting connection)."""
    sock = MagicMock()
    sock.accept.side_effect = OSError("no connection")
    return sock


def _make_server():
    return ConfigServer(_sock=_mock_sock())


# ── Instantiation ───────────────────────────────────────────────────────────

def test_instantiates_without_hardware():
    server = _make_server()
    assert not server.done


def test_hw_flag_false_in_cpython():
    assert config_server._HW is False


def test_state_defaults_to_none():
    server = _make_server()
    assert server._state is None


def test_state_kwarg_is_stored():
    sentinel = object()
    server   = ConfigServer(state=sentinel, _sock=_mock_sock())
    assert server._state is sentinel


# ── stop() ──────────────────────────────────────────────────────────────────

def test_stop_sets_done():
    server = _make_server()
    server.stop()
    assert server.done


def test_stop_idempotent():
    server = _make_server()
    server.stop()
    server.stop()  # should not raise
    assert server.done


# ── step() ──────────────────────────────────────────────────────────────────

def test_step_no_connection_returns_immediately():
    server = _make_server()
    server.step()  # must not raise
    assert not server.done


def test_step_is_noop_when_done():
    sock = _mock_sock()
    server = ConfigServer(_sock=sock)
    server.stop()
    server.step()
    sock.accept.assert_not_called()


# ── GET / — HTML form ────────────────────────────────────────────────────────

def test_get_root_serves_form(monkeypatch):
    monkeypatch.setattr(config_server.config, "WIFI_SSID", "")
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET / HTTP/1.1\r\nHost: 192.168.4.1\r\n\r\n")
    conn.send.assert_called_once()
    body = conn.send.call_args[0][0].decode()
    assert "<form" in body
    assert 'action=/wifi' in body


def test_get_root_contains_ssid_input(monkeypatch):
    monkeypatch.setattr(config_server.config, "WIFI_SSID", "")
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET / HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert 'name=ssid' in body


# ── GET / — context-aware home page ─────────────────────────────────────────

def test_get_root_no_wifi_ssid_shows_wifi_form(monkeypatch):
    monkeypatch.setattr(config_server.config, "WIFI_SSID", "")
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET / HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "action=/wifi" in body


def test_get_root_wifi_set_no_spotify_shows_creds_form(monkeypatch):
    monkeypatch.setattr(config_server.config, "WIFI_SSID", "MyNet")
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_ID", "")
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET / HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "/spotify/credentials" in body


def test_get_root_spotify_creds_set_shows_authorize(monkeypatch):
    monkeypatch.setattr(config_server.config, "WIFI_SSID", "MyNet")
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_ID", "cid123")
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET / HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "spotify_auth.py" in body


# ── POST /spotify/credentials ────────────────────────────────────────────────

def test_post_spotify_credentials_saves_and_redirects(monkeypatch):
    saved = {}
    monkeypatch.setattr(config_server.config, "save",   lambda d: saved.update(d))
    monkeypatch.setattr(config_server.config, "reload", lambda: None)
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /spotify/credentials HTTP/1.1\r\n\r\nclient_id=cid&client_secret=csec")
    assert saved.get("spotify_client_id")     == "cid"
    assert saved.get("spotify_client_secret") == "csec"
    response = conn.send.call_args[0][0].decode()
    assert "302" in response
    assert "Location: /" in response


def test_post_spotify_credentials_missing_fields_reshows_form(monkeypatch):
    monkeypatch.setattr(config_server.config, "save",   lambda d: None)
    monkeypatch.setattr(config_server.config, "reload", lambda: None)
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /spotify/credentials HTTP/1.1\r\n\r\nclient_id=&client_secret=")
    body = conn.send.call_args[0][0].decode()
    assert "/spotify/credentials" in body


# ── GET /spotify/auth ─────────────────────────────────────────────────────────

def test_get_spotify_auth_redirects_to_spotify(monkeypatch):
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_ID", "my_client")
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /spotify/auth HTTP/1.1\r\n\r\n")
    response = conn.send.call_args[0][0].decode()
    assert "302" in response
    assert "accounts.spotify.com/authorize" in response
    assert "my_client" in response


def test_get_spotify_auth_no_client_id_shows_creds_form(monkeypatch):
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_ID", "")
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /spotify/auth HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "/spotify/credentials" in body


# ── GET /callback ─────────────────────────────────────────────────────────────

def test_callback_success_saves_token_without_stopping_server(monkeypatch):
    saved = {}
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_ID",     "cid")
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_SECRET", "csec")
    monkeypatch.setattr(config_server.config, "save",   lambda d: saved.update(d))
    monkeypatch.setattr(config_server.config, "reload", lambda: None)
    monkeypatch.setattr(config_server.spotify, "exchange_code",
                        lambda cid, csec, code: ("acc", "ref_tok", 3600))
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /callback?code=AUTHCODE HTTP/1.1\r\n\r\n")
    assert saved.get("spotify_refresh_token") == "ref_tok"
    # Must NOT stop the server: it runs inside main.py's live loop during the
    # boot setup window. The grace timer governs setup→runtime, not this handler.
    assert not server.done


def test_callback_error_param_shows_error_page(monkeypatch):
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /callback?error=access_denied HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "fail" in body.lower() or "denied" in body.lower() or "error" in body.lower()
    assert not server.done


def test_callback_no_code_shows_error_page(monkeypatch):
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /callback HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "fail" in body.lower() or "error" in body.lower()
    assert not server.done


def test_callback_exchange_fails_shows_error_page(monkeypatch):
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_ID",     "cid")
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_SECRET", "csec")
    monkeypatch.setattr(config_server.spotify, "exchange_code",
                        lambda cid, csec, code: (None, None, 0))
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /callback?code=BADCODE HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "fail" in body.lower() or "error" in body.lower()
    assert not server.done


# ── POST /spotify/token ───────────────────────────────────────────────────────

def test_post_spotify_token_saves_and_returns_200(monkeypatch):
    saved = {}
    monkeypatch.setattr(config_server.config, "save",   lambda d: saved.update(d))
    monkeypatch.setattr(config_server.config, "reload", lambda: None)
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /spotify/token HTTP/1.1\r\n\r\nrefresh_token=tok123")
    assert saved.get("spotify_refresh_token") == "tok123"
    # Must NOT stop the server: it keeps serving read-only introspection after
    # the token lands. The boot setup-window timer governs setup→runtime.
    assert not server.done
    assert "200" in conn.send.call_args[0][0].decode()


def test_post_spotify_token_missing_token_returns_400(monkeypatch):
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /spotify/token HTTP/1.1\r\n\r\nrefresh_token=")
    assert "400" in conn.send.call_args[0][0].decode()
    assert not server.done


# ── POST /config removed — no arbitrary-key write endpoint exists (C1) ───────

def test_post_config_route_is_404():
    """The arbitrary-key /config endpoint was removed. Setup mode must not route it."""
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /config HTTP/1.1\r\n\r\nspotify_mock_host=evil%3A80")
    assert "404" in conn.send.call_args[0][0].decode()


# ── Runtime-mode security gate (C1 / I1) ─────────────────────────────────────

def _runtime_server():
    return ConfigServer(mode="runtime", _sock=_mock_sock())


def test_runtime_mode_blocks_post_wifi(monkeypatch):
    saved = {}
    monkeypatch.setattr(config_server.config, "save", lambda d: saved.update(d))
    server = _runtime_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /wifi HTTP/1.1\r\n\r\nssid=Net&password=pw")
    assert "403" in conn.send.call_args[0][0].decode()
    assert saved == {}            # nothing written
    assert not server.done


def test_runtime_mode_blocks_spotify_token(monkeypatch):
    saved = {}
    monkeypatch.setattr(config_server.config, "save", lambda d: saved.update(d))
    monkeypatch.setattr(config_server.config, "reload", lambda: None)
    server = _runtime_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /spotify/token HTTP/1.1\r\n\r\nrefresh_token=attacker")
    assert "403" in conn.send.call_args[0][0].decode()
    assert saved == {}            # token not written
    assert not server.done


def test_runtime_mode_blocks_spotify_credentials(monkeypatch):
    saved = {}
    monkeypatch.setattr(config_server.config, "save", lambda d: saved.update(d))
    server = _runtime_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /spotify/credentials HTTP/1.1\r\n\r\nclient_id=x&client_secret=y")
    assert "403" in conn.send.call_args[0][0].decode()
    assert saved == {}


def test_runtime_mode_blocks_root_page():
    """The setup home page leaks config state — not served at runtime."""
    server = _runtime_server()
    conn = MagicMock()
    server._dispatch(conn, "GET / HTTP/1.1\r\n\r\n")
    assert "403" in conn.send.call_args[0][0].decode()


def test_runtime_mode_allows_misses(monkeypatch):
    """Read-only introspection stays available at runtime."""
    monkeypatch.setattr(config_server.miss_log, "all", lambda: ["abc", "def"])
    server = _runtime_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /misses HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "abc" in body and "def" in body


def test_setup_mode_allows_post_wifi(monkeypatch):
    """Setup mode (default) still routes mutating endpoints — gate is runtime-only."""
    monkeypatch.setattr(config_server.wifi, "try_connect", lambda s, p: None)
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /wifi HTTP/1.1\r\n\r\nssid=BadNet&password=wrong")
    # Reaches the handler (shows form error), not the 403 gate.
    assert "403" not in conn.send.call_args[0][0].decode()


# ── lock_runtime() — one-way setup→runtime flip (boot setup window) ──────────

def test_lock_runtime_closes_the_setup_window(monkeypatch):
    """After lock_runtime(), a previously-allowed mutating endpoint 403s."""
    monkeypatch.setattr(config_server.config, "save", lambda d: None)
    monkeypatch.setattr(config_server.config, "reload", lambda: None)
    server = _make_server()   # default setup mode

    # Before lock: /spotify/token reaches the handler (200).
    conn = MagicMock()
    server._dispatch(conn, "POST /spotify/token HTTP/1.1\r\n\r\nrefresh_token=tok")
    assert "200" in conn.send.call_args[0][0].decode()

    server.lock_runtime()

    # After lock: same request is rejected.
    conn = MagicMock()
    server._dispatch(conn, "POST /spotify/token HTTP/1.1\r\n\r\nrefresh_token=tok")
    assert "403" in conn.send.call_args[0][0].decode()


def test_lock_runtime_is_idempotent(monkeypatch):
    monkeypatch.setattr(config_server.miss_log, "all", lambda: [])
    server = ConfigServer(mode="runtime", _sock=_mock_sock())
    server.lock_runtime()
    server.lock_runtime()   # must not raise
    conn = MagicMock()
    server._dispatch(conn, "GET /misses HTTP/1.1\r\n\r\n")  # read-only still works
    assert "403" not in conn.send.call_args[0][0].decode()


# ── /spotify/callback route removed — now 404 ────────────────────────────────

def test_old_spotify_callback_route_is_404():
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /spotify/callback HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "404" in body


# ── Unknown route ────────────────────────────────────────────────────────────

def test_unknown_route_returns_404():
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /unknown HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "404" in body


# ── POST /wifi — bad credentials ─────────────────────────────────────────────

def test_post_wifi_bad_credentials_shows_error(monkeypatch):
    monkeypatch.setattr(config_server.wifi, "try_connect", lambda s, p: None)
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /wifi HTTP/1.1\r\n\r\nssid=BadNet&password=wrong")
    body = conn.send.call_args[0][0].decode()
    assert "fail" in body.lower() or "error" in body.lower() or "not" in body.lower()
    assert not server.done


def test_post_wifi_empty_ssid_shows_error(monkeypatch):
    monkeypatch.setattr(config_server.wifi, "try_connect", lambda s, p: None)
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /wifi HTTP/1.1\r\n\r\nssid=&password=pw")
    body = conn.send.call_args[0][0].decode()
    assert "fail" in body.lower() or "error" in body.lower() or "not" in body.lower()


# ── POST /wifi — good credentials ────────────────────────────────────────────

def test_post_wifi_good_credentials_saves_config(monkeypatch):
    saved = {}
    monkeypatch.setattr(config_server.wifi, "try_connect", lambda s, p: "10.0.0.1")
    monkeypatch.setattr(config_server.config, "save", lambda d: saved.update(d))
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /wifi HTTP/1.1\r\n\r\nssid=GoodNet&password=pass123")
    assert saved.get("wifi_ssid") == "GoodNet"
    assert saved.get("wifi_password") == "pass123"


def test_post_wifi_good_credentials_sets_done_in_cpython(monkeypatch):
    monkeypatch.setattr(config_server.wifi, "try_connect", lambda s, p: "10.0.0.1")
    monkeypatch.setattr(config_server.config, "save", lambda d: None)
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /wifi HTTP/1.1\r\n\r\nssid=GoodNet&password=pw")
    assert server.done  # _HW=False so done is set instead of machine.reset()


def test_post_wifi_good_credentials_shows_ok_page(monkeypatch):
    monkeypatch.setattr(config_server.wifi, "try_connect", lambda s, p: "10.0.0.1")
    monkeypatch.setattr(config_server.config, "save", lambda d: None)
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /wifi HTTP/1.1\r\n\r\nssid=GoodNet&password=pw")
    body = conn.send.call_args[0][0].decode()
    assert "200" in body
    assert "connect" in body.lower()


def test_post_wifi_url_decoded_ssid(monkeypatch):
    received = {}
    monkeypatch.setattr(config_server.wifi, "try_connect",
                        lambda s, p: received.update({"s": s, "p": p}) or "10.0.0.1")
    monkeypatch.setattr(config_server.config, "save", lambda d: None)
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "POST /wifi HTTP/1.1\r\n\r\nssid=My+Network&password=p%40ss")
    assert received.get("s") == "My Network"
    assert received.get("p") == "p@ss"


# ── _parse_form ──────────────────────────────────────────────────────────────

def test_parse_form_basic():
    result = _parse_form("ssid=MyNet&password=pass123")
    assert result["ssid"] == "MyNet"
    assert result["password"] == "pass123"


def test_parse_form_single_field():
    result = _parse_form("ssid=OnlySSID")
    assert result["ssid"] == "OnlySSID"
    assert "password" not in result


def test_parse_form_empty_value():
    result = _parse_form("ssid=&password=pw")
    assert result["ssid"] == ""


# ── _urldecode ───────────────────────────────────────────────────────────────

def test_urldecode_plus_to_space():
    assert _urldecode("hello+world") == "hello world"


def test_urldecode_percent_encoding():
    assert _urldecode("hello%20world") == "hello world"


def test_urldecode_at_sign():
    assert _urldecode("My%40Net") == "My@Net"


def test_urldecode_mixed():
    assert _urldecode("p%40%24%24") == "p@$$"


def test_urldecode_passthrough():
    assert _urldecode("normalstring") == "normalstring"


# ── _extract_body ─────────────────────────────────────────────────────────────

def test_extract_body_crlf():
    raw = "POST /wifi HTTP/1.1\r\nContent-Length: 10\r\n\r\nssid=hello"
    assert _extract_body(raw) == "ssid=hello"


def test_extract_body_lf_only():
    raw = "POST /wifi HTTP/1.1\nContent-Length: 10\n\nssid=hello"
    assert _extract_body(raw) == "ssid=hello"


def test_extract_body_no_separator():
    raw = "no headers here"
    assert _extract_body(raw) == ""


# ── GET /misses ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _tmp_miss_log(tmp_path, monkeypatch):
    monkeypatch.setattr(miss_log, "_PATH", str(tmp_path / "misses.txt"))


def test_get_misses_returns_200():
    server = _make_server()
    conn   = MagicMock()
    server._dispatch(conn, "GET /misses HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "200" in body


def test_get_misses_returns_track_ids():
    miss_log.append("id_abc")
    miss_log.append("id_def")
    server = _make_server()
    conn   = MagicMock()
    server._dispatch(conn, "GET /misses HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert "id_abc" in body
    assert "id_def" in body


def test_get_misses_empty_log_returns_empty_body():
    server = _make_server()
    conn   = MagicMock()
    server._dispatch(conn, "GET /misses HTTP/1.1\r\n\r\n")
    # Split on header/body separator
    raw  = conn.send.call_args[0][0].decode()
    body = raw.split("\r\n\r\n", 1)[-1]
    assert body == ""


# ── #58 introspection endpoints: /state, /pixels, /poll-log, /config ─────────
#
# Read-only JSON views of runtime state, served in BOTH setup and runtime modes
# (they're on the _RUNTIME_ENDPOINTS allowlist). Each guards state=None so AP
# mode (boot.py creates ConfigServer with no state) returns valid JSON, no crash.

def _state_with_engine():
    """A populated RuntimeState: one track hit polled through the engine."""
    state        = RuntimeState()
    state.engine = MoodEngine(MMARBundle(build_bundle(("t1", 0.3, 0.7))))
    state.engine.update([("t1", "artist1")])
    state.last_track_ids   = ["t1"]
    state.last_poll_ms     = 12345
    state.last_colors      = [(10, 20, 30), (40, 50, 60), (70, 80, 90)]
    state.last_mood_colors = [(11, 22, 33), (44, 55, 66), (77, 88, 99)]
    return state


def _server(state=None, mode="setup"):
    return ConfigServer(mode=mode, state=state, _sock=_mock_sock())


def _dispatch_get(server, path):
    """Dispatch a GET and return (header_text, parsed_json_body)."""
    conn = MagicMock()
    server._dispatch(conn, "GET %s HTTP/1.1\r\n\r\n" % path)
    raw          = conn.send.call_args[0][0].decode()
    header, body = raw.split("\r\n\r\n", 1)
    return header, body


def _get_json(server, path):
    header, body = _dispatch_get(server, path)
    assert "200" in header
    assert "application/json" in header
    return json.loads(body)


# ── GET /state ───────────────────────────────────────────────────────────────

def test_get_state_returns_json_200(monkeypatch):
    monkeypatch.setattr(config_server.wifi, "is_connected", lambda: True)
    data = _get_json(_server(_state_with_engine()), "/state")
    # Superset: full RuntimeState.snapshot() plus ambient hardware fields.
    for key in ("engine", "last_track_ids", "last_track_results", "last_poll_ms",
                "last_colors", "last_mood_colors", "animator", "error_mode",
                "wifi_connected", "uptime_ms", "free_mem"):
        assert key in data


def test_get_state_reports_wifi_and_engine(monkeypatch):
    monkeypatch.setattr(config_server.wifi, "is_connected", lambda: True)
    state = _state_with_engine()
    data  = _get_json(_server(state), "/state")
    assert data["wifi_connected"] is True
    assert data["engine"] == state.engine.snapshot()
    assert data["last_track_ids"] == ["t1"]
    assert isinstance(data["uptime_ms"], int)


def test_get_state_wifi_disconnected(monkeypatch):
    monkeypatch.setattr(config_server.wifi, "is_connected", lambda: False)
    data = _get_json(_server(_state_with_engine()), "/state")
    assert data["wifi_connected"] is False


def test_get_state_ap_mode_state_none(monkeypatch):
    """boot.py serves /state with no state — must not crash; engine is null."""
    monkeypatch.setattr(config_server.wifi, "is_connected", lambda: False)
    data = _get_json(_server(state=None), "/state")
    assert data["engine"] is None
    assert "wifi_connected" in data and "uptime_ms" in data and "free_mem" in data


def test_get_state_allowed_in_runtime_mode(monkeypatch):
    monkeypatch.setattr(config_server.wifi, "is_connected", lambda: True)
    header, _ = _dispatch_get(_server(_state_with_engine(), mode="runtime"), "/state")
    assert "403" not in header


# ── GET /pixels ──────────────────────────────────────────────────────────────

def test_get_pixels_echoes_last_colors():
    state = _state_with_engine()
    data  = _get_json(_server(state), "/pixels")
    assert data["pixels"] == [[10, 20, 30], [40, 50, 60], [70, 80, 90]]
    assert len(data["source_ve"]) == 3


def test_get_pixels_source_ve_reflects_engine():
    state = _state_with_engine()
    data  = _get_json(_server(state), "/pixels")
    # One track hit, under the 1h threshold → all three pixels share now_ve.
    expected = state.engine.pixel_sources()
    assert data["source_ve"] == expected


def test_get_pixels_ap_mode_state_none():
    data = _get_json(_server(state=None), "/pixels")
    assert data["source_ve"] == [None, None, None]


def test_get_pixels_allowed_in_runtime_mode():
    header, _ = _dispatch_get(_server(_state_with_engine(), mode="runtime"), "/pixels")
    assert "403" not in header


# ── GET /poll-log ────────────────────────────────────────────────────────────

def _record(state, n):
    state.record_poll(time_ms=n * 1000, track_ids=["t%d" % n],
                      track_results=[(0.3, 0.7)],
                      colors_after=[(1, 2, 3)] * 3, confidence_after=1.0, error=None)


def test_get_poll_log_newest_first():
    state = _state_with_engine()
    for n in range(3):
        _record(state, n)
    data = _get_json(_server(state), "/poll-log")
    assert [r["time_ms"] for r in data] == [2000, 1000, 0]   # newest first


def test_get_poll_log_n_caps_to_newest():
    state = _state_with_engine()
    for n in range(5):
        _record(state, n)
    data = _get_json(_server(state), "/poll-log?n=2")
    assert [r["time_ms"] for r in data] == [4000, 3000]


def test_get_poll_log_n_over_length_returns_all():
    state = _state_with_engine()
    for n in range(3):
        _record(state, n)
    data = _get_json(_server(state), "/poll-log?n=999")
    assert len(data) == 3


def test_get_poll_log_ap_mode_state_none():
    assert _get_json(_server(state=None), "/poll-log") == []


def test_get_poll_log_allowed_in_runtime_mode():
    header, _ = _dispatch_get(_server(_state_with_engine(), mode="runtime"), "/poll-log")
    assert "403" not in header


# ── GET /config — redacted ───────────────────────────────────────────────────

_SECRETS = {
    "wifi_password":         "hunter2_supersecret",
    "spotify_client_secret": "csecret_abc123",
    "spotify_refresh_token": "reftok_xyz789",
}


def _set_config(monkeypatch):
    monkeypatch.setattr(config_server.config, "WIFI_SSID", "HomeNet")
    monkeypatch.setattr(config_server.config, "WIFI_PASSWORD", _SECRETS["wifi_password"])
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_ID", "client_id_visible")
    monkeypatch.setattr(config_server.config, "SPOTIFY_CLIENT_SECRET", _SECRETS["spotify_client_secret"])
    monkeypatch.setattr(config_server.config, "SPOTIFY_REFRESH_TOKEN", _SECRETS["spotify_refresh_token"])
    monkeypatch.setattr(config_server.config, "SPOTIFY_MOCK_HOST", "10.0.0.21:5000")


def test_get_config_shows_nonsecrets_plain(monkeypatch):
    _set_config(monkeypatch)
    data = _get_json(_server(_state_with_engine()), "/config")
    assert data["wifi_ssid"]         == "HomeNet"
    assert data["spotify_client_id"] == "client_id_visible"
    assert data["spotify_mock_host"] == "10.0.0.21:5000"


def test_get_config_masks_secrets(monkeypatch):
    _set_config(monkeypatch)
    data = _get_json(_server(_state_with_engine()), "/config")
    assert data["wifi_password"]         == "***"
    assert data["spotify_client_secret"] == "***"
    assert data["spotify_refresh_token"] == "***"


def test_get_config_no_secret_values_in_response(monkeypatch):
    """Acceptance criterion: scan the raw body for known secret values."""
    _set_config(monkeypatch)
    _, body = _dispatch_get(_server(_state_with_engine()), "/config")
    for secret in _SECRETS.values():
        assert secret not in body


def test_get_config_unset_secret_is_empty(monkeypatch):
    monkeypatch.setattr(config_server.config, "WIFI_PASSWORD", "")
    monkeypatch.setattr(config_server.config, "SPOTIFY_REFRESH_TOKEN", "")
    data = _get_json(_server(_state_with_engine()), "/config")
    # Empty (not "***") so a reader can tell "no token" from "token present".
    assert data["wifi_password"]         == ""
    assert data["spotify_refresh_token"] == ""


def test_get_config_allowed_in_runtime_mode(monkeypatch):
    _set_config(monkeypatch)
    header, _ = _dispatch_get(_server(_state_with_engine(), mode="runtime"), "/config")
    assert "403" not in header
