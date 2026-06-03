"""
Unit tests for main.run_poll_cycle — the poll-and-record wiring extracted from
main()'s loop so it can be tested without launching the infinite animation loop.

These lock down the glue the runtime_state tests can't reach: which error string
each outcome path emits, the once-per-poll record guarantee, the field sourcing
(track_ids / (v,e) outcomes / last_mood_colors), and the I1 None-colors fix.
"""
import json

import pytest

import miss_log
import spotify
import main
from conftest import build_bundle
from mmar          import MMARBundle
from mood_engine   import MoodEngine
from poller        import Poller
from runtime_state import RuntimeState


@pytest.fixture(autouse=True)
def _redirect_miss_log(tmp_path, monkeypatch):
    """Keep miss_log writes out of the working directory during tests."""
    monkeypatch.setattr(miss_log, "_PATH", str(tmp_path / "misses.txt"))


def _state():
    """RuntimeState with an engine that knows track 't1' and nothing else."""
    s = RuntimeState()
    s.engine = MoodEngine(MMARBundle(build_bundle(("t1", 0.3, 0.7))))
    return s


_VALID_TOKEN = ("tok", 3600)   # (access_token, expires_in)
_FAR_FUTURE  = 10 ** 12        # expires_at well beyond now_ms → no refresh


# ── Importability (the whole reason for the __main__ guard) ─────────────────

def test_importing_main_does_not_run_the_loop():
    """`import main` must not launch main(); both entry points are exposed."""
    assert hasattr(main, "run_poll_cycle")
    assert callable(main.run_poll_cycle)
    assert callable(main.main)


# ── One record per call, on every outcome path ──────────────────────────────

def test_auth_fail_records_one_auth_fail_record(monkeypatch):
    monkeypatch.setattr(spotify, "refresh_token", lambda *a: (None, 0))
    state, poller = _state(), Poller()

    res = main.run_poll_cycle(state, poller, access_token=None, expires_at=0, now_ms=1000)

    assert res["poll_error"] == "auth_fail"
    assert len(state.poll_log) == 1
    rec = state.poll_log[-1]
    assert rec["error"]         == "auth_fail"
    assert rec["track_ids"]     == []
    assert rec["track_results"] == []


def test_network_error_records_one_network_record(monkeypatch):
    monkeypatch.setattr(spotify, "refresh_token", lambda *a: _VALID_TOKEN)
    monkeypatch.setattr(spotify, "recently_played", lambda _t: None)
    state, poller = _state(), Poller()

    res = main.run_poll_cycle(state, poller, access_token=None, expires_at=0, now_ms=1000)

    assert res["poll_error"] == "network"
    assert len(state.poll_log) == 1
    rec = state.poll_log[-1]
    assert rec["error"]     == "network"
    assert rec["track_ids"] == []


def test_success_records_tracks_and_results(monkeypatch):
    # Token still valid → no refresh; t1 is a hit, "miss" is not in the bundle.
    monkeypatch.setattr(spotify, "recently_played",
                        lambda _t: [("t1", "a1"), ("miss", "a2")])
    state, poller = _state(), Poller()

    res = main.run_poll_cycle(state, poller, access_token="tok",
                              expires_at=_FAR_FUTURE, now_ms=1000)

    assert res["poll_error"] is None
    assert res["new_colors"] is not None
    assert len(state.poll_log) == 1
    rec = state.poll_log[-1]
    assert rec["error"]     is None
    assert rec["track_ids"] == ["t1", "miss"]
    # Order-aligned to track_ids: t1 → (v, e) pair, miss → null.
    assert rec["track_results"][0] is not None and len(rec["track_results"][0]) == 2
    assert rec["track_results"][1] is None
    # last_mood_colors was set, so colors_after is a real 3-pixel list.
    assert rec["colors_after"] is not None and len(rec["colors_after"]) == 3


def test_each_call_appends_exactly_one_record(monkeypatch):
    monkeypatch.setattr(spotify, "recently_played", lambda _t: [("t1", "a1")])
    state, poller = _state(), Poller()
    for i in range(3):
        main.run_poll_cycle(state, poller, "tok", _FAR_FUTURE, now_ms=1000 + i)
    assert len(state.poll_log) == 3


# ── I1: colors_after is None before the first successful poll, not black ─────

def test_auth_fail_before_any_success_records_none_colors(monkeypatch):
    monkeypatch.setattr(spotify, "refresh_token", lambda *a: (None, 0))
    state, poller = _state(), Poller()

    main.run_poll_cycle(state, poller, access_token=None, expires_at=0, now_ms=1000)

    rec = state.poll_log[-1]
    assert rec["colors_after"] is None            # NOT [[0,0,0],[0,0,0],[0,0,0]]
    assert json.loads(json.dumps(rec)) == rec     # still json-serializable


# ── Token state threads back out ────────────────────────────────────────────

def test_refresh_updates_token_and_expiry(monkeypatch):
    monkeypatch.setattr(spotify, "refresh_token", lambda *a: ("fresh", 3600))
    monkeypatch.setattr(spotify, "recently_played", lambda _t: [("t1", "a1")])
    state, poller = _state(), Poller()

    res = main.run_poll_cycle(state, poller, access_token=None, expires_at=0, now_ms=1000)

    assert res["access_token"] == "fresh"
    assert res["expires_at"]   == 1000 + (3600 - 60) * 1000
