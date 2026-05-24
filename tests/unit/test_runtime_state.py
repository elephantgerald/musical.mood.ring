"""
Unit tests for RuntimeState — the shared mutable state object passed by
reference from main.py (writer) to config_server.py (reader).
"""
import importlib
import json
import sys

import pytest
import miss_log
from conftest import build_bundle
from mmar          import MMARBundle
from mood_engine   import MoodEngine
from runtime_state import RuntimeState


@pytest.fixture(autouse=True)
def _redirect_miss_log(tmp_path, monkeypatch):
    """Keep miss_log writes out of the working directory during tests."""
    monkeypatch.setattr(miss_log, "_PATH", str(tmp_path / "misses.txt"))


def _engine_with_t1():
    return MoodEngine(MMARBundle(build_bundle(("t1", 0.3, 0.7))))


# ── Construction ────────────────────────────────────────────────────────────

def test_initial_state_is_idle():
    state = RuntimeState()
    assert state.engine          is None
    assert state.last_track_ids  == []
    assert state.last_poll_ms    == 0
    assert state.last_colors     == [(0, 0, 0), (0, 0, 0), (0, 0, 0)]


# ── snapshot() ──────────────────────────────────────────────────────────────

def test_snapshot_without_engine():
    state = RuntimeState()
    snap  = state.snapshot()
    assert snap["engine"]             is None
    assert snap["last_track_ids"]     == []
    assert snap["last_track_results"] == []
    assert snap["last_poll_ms"]       == 0
    assert snap["last_colors"]        == [[0, 0, 0], [0, 0, 0], [0, 0, 0]]


def test_snapshot_with_engine_reflects_engine_snapshot():
    state        = RuntimeState()
    state.engine = _engine_with_t1()
    state.engine.update([("t1", "artist1")])

    state.last_track_ids = ["t1"]
    state.last_poll_ms   = 12345
    state.last_colors    = [(10, 20, 30), (40, 50, 60), (70, 80, 90)]

    # Engine stores outcomes as tuples; snapshot rehydrates to dicts at the
    # HTTP boundary so curl users get self-describing JSON.
    raw_outcomes      = state.engine.last_poll_outcomes()
    expected_outcomes = [dict(zip(("track_id", "artist_id", "source", "v", "e"), o))
                         for o in raw_outcomes]

    snap = state.snapshot()
    assert snap["engine"]             == state.engine.snapshot()
    assert snap["last_track_ids"]     == ["t1"]
    assert snap["last_track_results"] == expected_outcomes
    assert snap["last_poll_ms"]       == 12345
    assert snap["last_colors"]        == [[10, 20, 30], [40, 50, 60], [70, 80, 90]]


def test_snapshot_round_trips_through_json():
    state        = RuntimeState()
    state.engine = _engine_with_t1()
    state.engine.update([("t1", "a1"), ("miss", "a2")])
    state.last_track_ids = ["t1", "miss"]
    state.last_poll_ms   = 999
    state.last_colors    = [(1, 2, 3), (4, 5, 6), (7, 8, 9)]

    snap    = state.snapshot()
    decoded = json.loads(json.dumps(snap))
    assert decoded == snap


def test_snapshot_copies_track_ids_not_aliases():
    """snapshot() must not hand out the live list — mutating the snapshot
    must not mutate state."""
    state = RuntimeState()
    state.last_track_ids = ["a", "b"]
    snap  = state.snapshot()
    snap["last_track_ids"].append("c")
    assert state.last_track_ids == ["a", "b"]


# ── No circular imports between runtime_state, mood_engine, config_server ───
#
# The whole point of RuntimeState is that ConfigServer can read engine state
# without ConfigServer and MoodEngine importing each other. Verify both
# import orders work.

def _reimport(*names):
    for n in names:
        sys.modules.pop(n, None)
    return [importlib.import_module(n) for n in names]


def test_no_circular_import_runtime_first():
    _reimport("runtime_state", "mood_engine", "config_server")


def test_no_circular_import_config_server_first():
    _reimport("config_server", "mood_engine", "runtime_state")
