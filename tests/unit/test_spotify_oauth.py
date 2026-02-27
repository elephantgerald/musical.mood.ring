import pytest
from unittest.mock import MagicMock

import spotify
from spotify import auth_url, exchange_code, _REDIRECT_URI_ENC, _SCOPE, _AUTH_URL


# ── auth_url() ───────────────────────────────────────────────────────────────

def test_auth_url_starts_with_spotify_authorize():
    url = auth_url("my_client_id")
    assert url.startswith(_AUTH_URL)


def test_auth_url_contains_client_id():
    url = auth_url("abc123")
    assert "client_id=abc123" in url


def test_auth_url_response_type_code():
    url = auth_url("cid")
    assert "response_type=code" in url


def test_auth_url_contains_encoded_redirect_uri():
    url = auth_url("cid")
    assert _REDIRECT_URI_ENC in url


def test_auth_url_contains_scope():
    url = auth_url("cid")
    assert _SCOPE in url


def test_auth_url_is_string():
    assert isinstance(auth_url("cid"), str)


# ── exchange_code() — success ─────────────────────────────────────────────────

def _mock_token_response(access="acc", refresh="ref", expires=3600):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "access_token":  access,
        "refresh_token": refresh,
        "expires_in":    expires,
    }
    return resp


def test_exchange_code_returns_tokens(monkeypatch):
    monkeypatch.setattr(spotify.requests, "post", lambda *a, **kw: _mock_token_response())
    access, refresh, expires = exchange_code("cid", "csec", "authcode")
    assert access  == "acc"
    assert refresh == "ref"
    assert expires == 3600


def test_exchange_code_sends_grant_type(monkeypatch):
    calls = {}
    def fake_post(url, headers, data):
        calls["data"] = data
        return _mock_token_response()
    monkeypatch.setattr(spotify.requests, "post", fake_post)
    exchange_code("cid", "csec", "mycode")
    assert "grant_type=authorization_code" in calls["data"]


def test_exchange_code_sends_code(monkeypatch):
    calls = {}
    def fake_post(url, headers, data):
        calls["data"] = data
        return _mock_token_response()
    monkeypatch.setattr(spotify.requests, "post", fake_post)
    exchange_code("cid", "csec", "mycode123")
    assert "code=mycode123" in calls["data"]


def test_exchange_code_sends_redirect_uri(monkeypatch):
    calls = {}
    def fake_post(url, headers, data):
        calls["data"] = data
        return _mock_token_response()
    monkeypatch.setattr(spotify.requests, "post", fake_post)
    exchange_code("cid", "csec", "code")
    assert _REDIRECT_URI_ENC in calls["data"]


def test_exchange_code_sends_basic_auth(monkeypatch):
    calls = {}
    def fake_post(url, headers, data):
        calls["headers"] = headers
        return _mock_token_response()
    monkeypatch.setattr(spotify.requests, "post", fake_post)
    exchange_code("cid", "csec", "code")
    assert calls["headers"]["Authorization"].startswith("Basic ")


def test_exchange_code_default_expires_in(monkeypatch):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"access_token": "a", "refresh_token": "r"}
    monkeypatch.setattr(spotify.requests, "post", lambda *a, **kw: resp)
    _, _, expires = exchange_code("cid", "csec", "code")
    assert expires == 3600


# ── exchange_code() — failure ─────────────────────────────────────────────────

def test_exchange_code_non_200_returns_nones(monkeypatch):
    resp = MagicMock()
    resp.status_code = 400
    monkeypatch.setattr(spotify.requests, "post", lambda *a, **kw: resp)
    access, refresh, expires = exchange_code("cid", "csec", "badcode")
    assert access   is None
    assert refresh  is None
    assert expires  == 0


def test_exchange_code_exception_returns_nones(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("network error")
    monkeypatch.setattr(spotify.requests, "post", _raise)
    access, refresh, expires = exchange_code("cid", "csec", "code")
    assert access  is None
    assert refresh is None
    assert expires == 0
