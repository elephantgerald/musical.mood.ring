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
    assert state.engine            is None
    assert state.last_track_ids    == []
    assert state.last_poll_ms      == 0
    assert state.last_colors       == [(0, 0, 0), (0, 0, 0), (0, 0, 0)]
    assert state.last_mood_colors  is None


# ── snapshot() ──────────────────────────────────────────────────────────────

def test_snapshot_without_engine():
    state = RuntimeState()
    snap  = state.snapshot()
    assert snap["engine"]             is None
    assert snap["last_track_ids"]     == []
    assert snap["last_track_results"] == []
    assert snap["last_poll_ms"]       == 0
    assert snap["last_colors"]        == [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    assert snap["last_mood_colors"]   is None


def test_snapshot_with_engine_reflects_engine_snapshot():
    state        = RuntimeState()
    state.engine = _engine_with_t1()
    state.engine.update([("t1", "artist1")])

    state.last_track_ids   = ["t1"]
    state.last_poll_ms     = 12345
    state.last_colors      = [(10, 20, 30), (40, 50, 60), (70, 80, 90)]
    state.last_mood_colors = [(11, 22, 33), (44, 55, 66), (77, 88, 99)]

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
    assert snap["last_mood_colors"]   == [[11, 22, 33], [44, 55, 66], [77, 88, 99]]


def test_snapshot_last_mood_colors_serialized_as_list_of_lists():
    """Tuples → lists at the HTTP boundary for clean json round-trip."""
    state = RuntimeState()
    state.last_mood_colors = [(1, 2, 3), (4, 5, 6), (7, 8, 9)]
    snap = state.snapshot()
    assert snap["last_mood_colors"] == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    # Must be lists, not tuples — json.dumps wouldn't care, but equality checks would.
    assert all(isinstance(c, list) for c in snap["last_mood_colors"])


def test_snapshot_last_mood_colors_distinguishes_from_last_colors():
    """The whole point of the separate field: animator output vs. engine output."""
    state = RuntimeState()
    state.last_colors      = [(255, 0, 0), (255, 0, 0), (255, 0, 0)]   # WIFI_LOST red
    state.last_mood_colors = [(40, 80, 120), (40, 80, 120), (40, 80, 120)]  # actual mood
    snap = state.snapshot()
    assert snap["last_colors"]      != snap["last_mood_colors"]
    assert snap["last_colors"]      == [[255, 0, 0], [255, 0, 0], [255, 0, 0]]
    assert snap["last_mood_colors"] == [[40, 80, 120], [40, 80, 120], [40, 80, 120]]


def test_snapshot_round_trips_through_json():
    state        = RuntimeState()
    state.engine = _engine_with_t1()
    state.engine.update([("t1", "a1"), ("miss", "a2")])
    state.last_track_ids   = ["t1", "miss"]
    state.last_poll_ms     = 999
    state.last_colors      = [(1, 2, 3), (4, 5, 6), (7, 8, 9)]
    state.last_mood_colors = [(10, 20, 30), (40, 50, 60), (70, 80, 90)]

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


# ── Poll ring buffer (#57) ──────────────────────────────────────────────────
#
# A rolling log of the last RuntimeState._POLL_LOG_SIZE poll outcomes, appended
# once per poll on every path (success, network error, auth-fail). Bounded
# memory; each record json.dumps()-able. Feeds #58's /poll-log endpoint.

from runtime_state import _POLL_LOG_SIZE


def _record(state, n, error=None):
    """Append one synthetic poll record numbered n."""
    state.record_poll(
        time_ms=n * 1000,
        track_ids=["t%d" % n],
        track_results=[(0.3, 0.7)],
        colors_after=[(10, 20, 30), (40, 50, 60), (70, 80, 90)],
        confidence_after=1.0,
        error=error,
    )


def test_poll_log_starts_empty():
    state = RuntimeState()
    assert state.poll_log == []
    assert state.poll_log_snapshot() == []


def test_poll_log_caps_at_size_after_30_polls():
    """Required by the issue: 30 polls, only the most recent 20 retained."""
    state = RuntimeState()
    for n in range(30):
        _record(state, n)
    log = state.poll_log_snapshot()
    assert len(log) == _POLL_LOG_SIZE == 20
    # Oldest-first; the first 10 (0–9) have been evicted, 10–29 remain.
    assert [r["time_ms"] for r in log] == [n * 1000 for n in range(10, 30)]


def test_poll_log_no_growth_over_100_plus_cycles():
    state = RuntimeState()
    for n in range(150):
        _record(state, n)
    assert len(state.poll_log) == _POLL_LOG_SIZE
    assert len(state.poll_log_snapshot()) == _POLL_LOG_SIZE


def test_poll_record_shape_and_fields():
    state = RuntimeState()
    state.record_poll(
        time_ms=12345,
        track_ids=["a", "b"],
        track_results=[(0.1, 0.2), None],
        colors_after=[(1, 2, 3), (4, 5, 6), (7, 8, 9)],
        confidence_after=0.6,
        error=None,
    )
    rec = state.poll_log_snapshot()[0]
    assert rec == {
        "time_ms":          12345,
        "track_ids":        ["a", "b"],
        "track_results":    [[0.1, 0.2], None],   # miss → null; tuples → lists
        "colors_after":     [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
        "confidence_after": 0.6,
        "error":            None,
    }


def test_poll_record_json_dumps_able():
    state = RuntimeState()
    _record(state, 0)
    _record(state, 1, error="auth_fail")
    snap = state.poll_log_snapshot()
    assert json.loads(json.dumps(snap)) == snap


@pytest.mark.parametrize("error", [None, "auth_fail", "network"])
def test_poll_log_records_every_outcome_path(error):
    """Append happens regardless of whether error_mode is None or set."""
    state = RuntimeState()
    state.record_poll(
        time_ms=1, track_ids=[], track_results=[],
        colors_after=[(0, 0, 0)] * 3, confidence_after=1.0, error=error,
    )
    assert state.poll_log_snapshot()[0]["error"] == error


def test_poll_log_snapshot_returns_copies():
    """Mutating the snapshot must not corrupt the live log."""
    state = RuntimeState()
    _record(state, 0)
    snap = state.poll_log_snapshot()
    snap[0]["error"] = "tampered"
    snap[0]["track_ids"].append("x")
    assert state.poll_log[0]["error"] is None
    assert state.poll_log[0]["track_ids"] == ["t0"]


def test_record_poll_copies_inputs_not_aliases():
    """A caller mutating the lists it passed in must not change a stored record."""
    state = RuntimeState()
    ids = ["t0"]
    results = [(0.3, 0.7)]
    colors = [(1, 2, 3), (4, 5, 6), (7, 8, 9)]
    state.record_poll(time_ms=0, track_ids=ids, track_results=results,
                      colors_after=colors, confidence_after=1.0, error=None)
    ids.append("mutated")
    results.append((9.9, 9.9))
    rec = state.poll_log[0]
    assert rec["track_ids"] == ["t0"]
    assert rec["track_results"] == [[0.3, 0.7]]
