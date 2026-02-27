import pytest
from unittest.mock import MagicMock

import spotify
from spotify import recently_played, refresh_token


# ── Helpers ──────────────────────────────────────────────────────────────────

def _item(track_id, artist_id="artist_default"):
    return {"track": {"id": track_id, "artists": [{"id": artist_id}]}}


def _get_resp(status, items=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"items": items or []}
    return resp


def _post_resp(status, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body or {}
    return resp


# ── recently_played() ────────────────────────────────────────────────────────

def test_recently_played_returns_track_artist_pairs(monkeypatch):
    items = [_item("abc123", "artist1"), _item("def456", "artist2")]
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: _get_resp(200, items))
    result = recently_played("token")
    assert result == [("abc123", "artist1"), ("def456", "artist2")]


def test_recently_played_empty_items_returns_empty_list(monkeypatch):
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: _get_resp(200, []))
    result = recently_played("token")
    assert result == []


def test_recently_played_non_200_returns_none(monkeypatch):
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: _get_resp(401))
    assert recently_played("token") is None


def test_recently_played_403_returns_none(monkeypatch):
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: _get_resp(403))
    assert recently_played("token") is None


def test_recently_played_429_returns_none(monkeypatch):
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: _get_resp(429))
    assert recently_played("token") is None


def test_recently_played_500_returns_none(monkeypatch):
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: _get_resp(500))
    assert recently_played("token") is None


def test_recently_played_exception_returns_none(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("network error")
    monkeypatch.setattr(spotify.requests, "get", _raise)
    assert recently_played("token") is None


def test_recently_played_sends_bearer_token(monkeypatch):
    calls = {}
    def fake_get(url, headers):
        calls["headers"] = headers
        return _get_resp(200)
    monkeypatch.setattr(spotify.requests, "get", fake_get)
    recently_played("mytoken")
    assert calls["headers"]["Authorization"] == "Bearer mytoken"


def test_recently_played_limit_in_url(monkeypatch):
    calls = {}
    def fake_get(url, headers):
        calls["url"] = url
        return _get_resp(200)
    monkeypatch.setattr(spotify.requests, "get", fake_get)
    recently_played("tok", limit=5)
    assert "limit=5" in calls["url"]


def test_recently_played_ids_are_strings(monkeypatch):
    items = [_item("id1", "a1"), _item("id2", "a2")]
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: _get_resp(200, items))
    result = recently_played("tok")
    assert all(isinstance(tid, str) and isinstance(aid, str) for tid, aid in result)


def test_recently_played_uses_primary_artist(monkeypatch):
    """Only artists[0].id must be returned regardless of how many artists are listed."""
    items = [{"track": {"id": "t1", "artists": [{"id": "primary"}, {"id": "featured"}]}}]
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: _get_resp(200, items))
    result = recently_played("tok")
    assert result == [("t1", "primary")]


# ── refresh_token() ───────────────────────────────────────────────────────────

def test_refresh_token_returns_access_and_expiry(monkeypatch):
    body = {"access_token": "new_acc", "expires_in": 3600}
    monkeypatch.setattr(spotify.requests, "post", lambda *a, **kw: _post_resp(200, body))
    token, expires = refresh_token("cid", "csec", "rtoken")
    assert token   == "new_acc"
    assert expires == 3600


def test_refresh_token_non_200_returns_none_zero(monkeypatch):
    monkeypatch.setattr(spotify.requests, "post", lambda *a, **kw: _post_resp(401))
    token, expires = refresh_token("cid", "csec", "rtoken")
    assert token   is None
    assert expires == 0


def test_refresh_token_exception_returns_none_zero(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("network error")
    monkeypatch.setattr(spotify.requests, "post", _raise)
    token, expires = refresh_token("cid", "csec", "rtoken")
    assert token   is None
    assert expires == 0


def test_refresh_token_default_expires_in(monkeypatch):
    body = {"access_token": "acc"}  # no expires_in field
    monkeypatch.setattr(spotify.requests, "post", lambda *a, **kw: _post_resp(200, body))
    _, expires = refresh_token("cid", "csec", "rtoken")
    assert expires == 3600


def test_refresh_token_sends_basic_auth(monkeypatch):
    calls = {}
    def fake_post(url, headers, data):
        calls["headers"] = headers
        return _post_resp(200, {"access_token": "a", "expires_in": 3600})
    monkeypatch.setattr(spotify.requests, "post", fake_post)
    refresh_token("cid", "csec", "rtoken")
    assert calls["headers"]["Authorization"].startswith("Basic ")


def test_refresh_token_sends_grant_type(monkeypatch):
    calls = {}
    def fake_post(url, headers, data):
        calls["data"] = data
        return _post_resp(200, {"access_token": "a", "expires_in": 3600})
    monkeypatch.setattr(spotify.requests, "post", fake_post)
    refresh_token("cid", "csec", "myrefresh")
    assert "grant_type=refresh_token" in calls["data"]
    assert "myrefresh" in calls["data"]
