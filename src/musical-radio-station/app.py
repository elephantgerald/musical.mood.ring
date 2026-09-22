#!/usr/bin/env python3
"""
app.py — musical-radio-station mock Spotify server.

Emulates the Spotify endpoints the mood ring firmware uses, plus a
control API for test scenario management.

Spotify endpoints:
  POST /api/token                     → fake access token
  GET  /v1/me/player/recently-played  → tracks from active playlist (sliding window)

Control endpoints:
  PUT  /control/playlist     → load playlist by name (?name=X or JSON body)
  POST /control/fast-forward → advance window position (body: {"count": N}, default 5)
  POST /control/pause        → inject response delay (body: {"ms": N}, 0 to clear)
  POST /control/error        → inject HTTP errors (body: {"count": N, "status": S})
  GET  /control/log          → request log (last 200 entries)
  GET  /control/status       → current server state
  GET  /control/playlists    → list available playlist names
"""

import glob
import json
import os
import time

from flask import Flask, jsonify, request

app = Flask(__name__)

_PLAYLISTS_DIR = os.path.join(os.path.dirname(__file__), "playlists")

# ── Server state ──────────────────────────────────────────────────────────────

_state = {
    "playlist_name": None,
    "tracks":        [],    # [{"track_id": ..., "artist_id": ...}, ...]
    "position":      0,     # index of the most recently played track
    "pause_ms":      0,     # extra latency injected on Spotify endpoints
    "error_count":   0,     # remaining error injections
    "error_status":  500,   # HTTP status used for injected errors
    "log":           [],    # [{"time": ..., "method": ..., "path": ..., "status": ...}]
}

_LOG_MAX = 200


# ── Helpers ───────────────────────────────────────────────────────────────────

def _record(method, path, status):
    _state["log"].append({
        "time":   time.strftime("%H:%M:%S"),
        "method": method,
        "path":   path,
        "status": status,
    })
    if len(_state["log"]) > _LOG_MAX:
        _state["log"].pop(0)


def _check_error():
    """Consume one injected error. Returns (response, code) or None."""
    if _state["error_count"] > 0:
        _state["error_count"] -= 1
        code = _state["error_status"]
        _record(request.method, request.path, code)
        return jsonify({"error": "injected"}), code
    return None


def _apply_pause():
    if _state["pause_ms"] > 0:
        time.sleep(_state["pause_ms"] / 1000.0)


def _load_playlist_file(name):
    """Read a playlist JSON and return its track list, or None if not found."""
    path = os.path.join(_PLAYLISTS_DIR, name + ".json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    return data.get("tracks", [])


def _window(limit):
    """Return the `limit` most recent tracks, ending at current position (wrapping)."""
    tracks = _state["tracks"]
    if not tracks:
        return []
    pos = _state["position"] % len(tracks)
    return [tracks[(pos - i) % len(tracks)] for i in range(limit)]


# ── Spotify API ───────────────────────────────────────────────────────────────

@app.route("/api/token", methods=["POST"])
def token():
    _record("POST", "/api/token", 200)
    return jsonify({
        "access_token": "mock_access_token",
        "token_type":   "Bearer",
        "expires_in":   3600,
    })


@app.route("/v1/me/player/recently-played")
def recently_played():
    err = _check_error()
    if err:
        return err
    _apply_pause()

    limit = int(request.args.get("limit", 10))
    items = [
        {
            "track": {
                "id":      t["track_id"],
                "artists": [{"id": t.get("artist_id") or ""}],
            }
        }
        for t in _window(limit)
    ]
    _record("GET", request.full_path, 200)
    return jsonify({"items": items})


# ── Control API ───────────────────────────────────────────────────────────────

@app.route("/control/playlist", methods=["PUT"])
def set_playlist():
    name = request.args.get("name") or (request.get_json(silent=True) or {}).get("name")
    if not name:
        return jsonify({"error": "name required"}), 400
    tracks = _load_playlist_file(name)
    if tracks is None:
        return jsonify({"error": f"playlist '{name}' not found"}), 404
    _state["playlist_name"] = name
    _state["tracks"]        = tracks
    _state["position"]      = len(tracks) - 1
    _record("PUT", "/control/playlist", 200)
    return jsonify({"playlist": name, "track_count": len(tracks)})


@app.route("/control/fast-forward", methods=["POST"])
def fast_forward():
    body  = request.get_json(silent=True) or {}
    count = int(body.get("count", 5))
    n     = max(len(_state["tracks"]), 1)
    _state["position"] = (_state["position"] + count) % n
    _record("POST", "/control/fast-forward", 200)
    return jsonify({"position": _state["position"], "advanced": count})


@app.route("/control/pause", methods=["POST"])
def set_pause():
    body = request.get_json(silent=True) or {}
    ms   = int(body.get("ms", 0))
    _state["pause_ms"] = ms
    _record("POST", "/control/pause", 200)
    return jsonify({"pause_ms": ms})


@app.route("/control/error", methods=["POST"])
def inject_error():
    body = request.get_json(silent=True) or {}
    _state["error_count"]  = int(body.get("count", 1))
    _state["error_status"] = int(body.get("status", 500))
    _record("POST", "/control/error", 200)
    return jsonify({"error_count": _state["error_count"], "error_status": _state["error_status"]})


@app.route("/control/log")
def get_log():
    return jsonify(_state["log"])


@app.route("/control/status")
def status():
    tracks = _state["tracks"]
    pos    = _state["position"] % len(tracks) if tracks else 0
    return jsonify({
        "playlist":      _state["playlist_name"],
        "track_count":   len(tracks),
        "position":      pos,
        "current_track": tracks[pos] if tracks else None,
        "pause_ms":      _state["pause_ms"],
        "error_count":   _state["error_count"],
        "error_status":  _state["error_status"],
    })


@app.route("/control/playlists")
def list_playlists():
    names = sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(_PLAYLISTS_DIR, "*.json"))
    )
    return jsonify(names)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
