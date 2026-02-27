import pytest
from unittest.mock import MagicMock, patch

import config_server
import miss_log
from config_server import ConfigServer, _parse_form, _urldecode, _extract_body


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
    assert "/spotify/auth" in body


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

def test_callback_success_saves_token_and_sets_done(monkeypatch):
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
    assert server.done


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
