import pytest
from unittest.mock import MagicMock, patch

import config_server
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

def test_get_root_serves_form():
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET / HTTP/1.1\r\nHost: 192.168.4.1\r\n\r\n")
    conn.send.assert_called_once()
    body = conn.send.call_args[0][0].decode()
    assert "<form" in body
    assert 'action=/wifi' in body


def test_get_root_contains_ssid_input():
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET / HTTP/1.1\r\n\r\n")
    body = conn.send.call_args[0][0].decode()
    assert 'name=ssid' in body


# ── GET /spotify/auth and /spotify/callback — stubs ─────────────────────────

def test_get_spotify_auth_returns_stub():
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /spotify/auth HTTP/1.1\r\n\r\n")
    conn.send.assert_called_once()
    body = conn.send.call_args[0][0].decode()
    assert "200" in body


def test_get_spotify_callback_returns_stub():
    server = _make_server()
    conn = MagicMock()
    server._dispatch(conn, "GET /spotify/callback HTTP/1.1\r\n\r\n")
    conn.send.assert_called_once()
    body = conn.send.call_args[0][0].decode()
    assert "200" in body


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
