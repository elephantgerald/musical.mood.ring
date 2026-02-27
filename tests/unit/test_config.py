import json
import pytest
import config


# ── save() ─────────────────────────────────────────────────────────────────

def test_save_writes_valid_json(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(config, "_PATH", str(cfg_file))
    config.save({"wifi_ssid": "MyNet", "wifi_password": "s3cret"})
    data = json.loads(cfg_file.read_text())
    assert data["wifi_ssid"] == "MyNet"
    assert data["wifi_password"] == "s3cret"


def test_save_full_replacement(tmp_path, monkeypatch):
    """save() overwrites the entire file; old keys are gone."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(config, "_PATH", str(cfg_file))
    config.save({"wifi_ssid": "A", "wifi_password": "pw"})
    config.save({"wifi_ssid": "B", "wifi_password": "pw2"})
    data = json.loads(cfg_file.read_text())
    assert data["wifi_ssid"] == "B"


# ── reload() ───────────────────────────────────────────────────────────────

def test_reload_picks_up_new_ssid(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(config, "_PATH", str(cfg_file))
    config.save({"wifi_ssid": "NewNet", "wifi_password": "pw"})
    config.reload()
    assert config.WIFI_SSID == "NewNet"


def test_reload_missing_file_clears_constants(tmp_path, monkeypatch):
    """reload() with no config.json resets constants to defaults (empty strings)."""
    cfg_file = tmp_path / "nonexistent.json"
    monkeypatch.setattr(config, "_PATH", str(cfg_file))
    config.reload()
    assert config.WIFI_SSID == ""
    assert config.WIFI_PASSWORD == ""


# ── round-trip ──────────────────────────────────────────────────────────────

def test_roundtrip_all_fields(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(config, "_PATH", str(cfg_file))
    data = {
        "wifi_ssid":              "mynet",
        "wifi_password":          "mypass",
        "spotify_client_id":      "cid",
        "spotify_client_secret":  "csec",
        "spotify_refresh_token":  "rtoken",
    }
    config.save(data)
    config.reload()
    assert config.WIFI_SSID             == "mynet"
    assert config.WIFI_PASSWORD         == "mypass"
    assert config.SPOTIFY_CLIENT_ID     == "cid"
    assert config.SPOTIFY_CLIENT_SECRET == "csec"
    assert config.SPOTIFY_REFRESH_TOKEN == "rtoken"


def test_save_reload_unicode(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(config, "_PATH", str(cfg_file))
    config.save({"wifi_ssid": "Café_WiFi", "wifi_password": "p@$$"})
    config.reload()
    assert config.WIFI_SSID == "Café_WiFi"
