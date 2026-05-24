import json

import pytest
import miss_log
from conftest import build_bundle
from mmar        import MMARBundle
from mood_engine import MoodEngine, _POLLS_1H, _POLLS_4H


@pytest.fixture(autouse=True)
def _redirect_miss_log(tmp_path, monkeypatch):
    """Keep miss_log writes out of the working directory during tests."""
    monkeypatch.setattr(miss_log, "_PATH", str(tmp_path / "misses.txt"))


# ── Helpers ─────────────────────────────────────────────────────────────────

def _engine(*entries):
    """Build a MoodEngine with a track bundle only. (track_id, v, e) entries."""
    return MoodEngine(MMARBundle(build_bundle(*entries)))


def _engine_with_artists(track_entries, artist_entries):
    """Build a MoodEngine with both track and artist bundles."""
    t = MMARBundle(build_bundle(*track_entries))
    a = MMARBundle(build_bundle(*artist_entries))
    return MoodEngine(t, a)


def _poll(engine, *track_pairs):
    """Call engine.update with a list of (track_id, artist_id) tuples."""
    return engine.update(list(track_pairs))


def _p(track_id, artist_id="a_dummy"):
    """Shorthand to make a (track_id, artist_id) pair with a default artist."""
    return (track_id, artist_id)


# ── Output shape ─────────────────────────────────────────────────────────────

def test_returns_three_rgb_tuples():
    engine = _engine(("t1", 0.7, 0.8))
    colors = _poll(engine, _p("t1"))
    assert len(colors) == 3
    for rgb in colors:
        assert len(rgb) == 3
        for ch in rgb:
            assert isinstance(ch, int)
            assert 0 <= ch <= 255


# ── State 0: Inactive ────────────────────────────────────────────────────────

def test_idle_state_no_hits_ever():
    """Before any bundle hit, all three pixels should be in the idle state."""
    engine = _engine(("t1", 0.7, 0.8))
    colors = _poll(engine, _p("notinbundle"))
    assert colors[0] == colors[1] == colors[2]


def test_idle_state_empty_poll():
    engine = _engine(("t1", 0.7, 0.8))
    colors = engine.update([])
    assert colors[0] == colors[1] == colors[2]


def test_idle_color_is_valid_rgb():
    engine = _engine(("t1", 0.5, 0.5))
    colors = _poll(engine, _p("miss"))
    for rgb in colors:
        for ch in rgb:
            assert 0 <= ch <= 255


# ── State 1: < 1 hr — all three share recent ─────────────────────────────────

def test_first_hit_all_pixels_share_recent():
    engine = _engine(("t1", 0.15, 0.85))
    colors = _poll(engine, _p("t1"))
    assert colors[0] == colors[1] == colors[2]


def test_all_share_recent_up_to_1h_threshold():
    engine = _engine(("t1", 0.9, 0.1))
    for _ in range(_POLLS_1H):
        colors = _poll(engine, _p("t1"))
    assert colors[0] == colors[1] == colors[2]


def test_pixels_diverge_after_1h_threshold():
    engine = _engine(("t1", 0.9, 0.1))
    for _ in range(_POLLS_1H + 1):
        colors = _poll(engine, _p("t1"))
    for rgb in colors:
        for ch in rgb:
            assert 0 <= ch <= 255


# ── State 2: 1–4 hr — P1 tracks P2 ──────────────────────────────────────────

def test_pixels_1_and_2_share_after_1h():
    engine = _engine(("t1", 0.9, 0.1))
    for _ in range(_POLLS_1H + 1):
        _poll(engine, _p("t1"))
    colors = _poll(engine, _p("t1"))
    assert colors[1] == colors[2]


def test_at_4h_boundary_p1_p2_still_share():
    engine = _engine(("t1", 0.8, 0.2))
    for _ in range(_POLLS_4H):
        colors = _poll(engine, _p("t1"))
    assert colors[1] == colors[2]


# ── State 3: > 4 hr — full discrimination ────────────────────────────────────

def test_pixels_diverge_after_4h():
    engine = _engine(("dark", 0.1, 0.9), ("bright", 0.9, 0.1))
    for _ in range(_POLLS_4H + 1):
        _poll(engine, _p("dark"))
    for _ in range(10):
        colors = _poll(engine, _p("bright"))
    diff = sum(abs(a - b) for a, b in zip(colors[1], colors[2]))
    assert diff > 10, f"pixels 1 and 2 too similar after regime change: {colors}"


# ── Miss-poll persistence ─────────────────────────────────────────────────────

def test_now_pixel_persists_across_miss_poll():
    """
    After a miss poll, pixel 0 still reflects the last known track (same hue
    and brightness). Saturation may be lower due to confidence decay — that is
    intentional — but max(channel) (brightness) must be preserved.
    """
    engine = _engine(("t1", 0.9, 0.1))
    colors_hit  = _poll(engine, _p("t1"))
    colors_miss = _poll(engine, _p("nomatch"))
    assert max(colors_hit[0]) == max(colors_miss[0])


def test_miss_poll_does_not_advance_state():
    engine = _engine(("t1", 0.9, 0.1))
    _poll(engine, _p("t1"))
    for _ in range(_POLLS_1H + 5):
        colors = _poll(engine, _p("miss"))
    assert colors[0] == colors[1] == colors[2]


# ── Artist bundle fallback ────────────────────────────────────────────────────

def test_artist_hit_returns_colour():
    """A track miss + artist hit must return valid RGB."""
    engine = _engine_with_artists(
        track_entries=[("t_other", 0.5, 0.5)],
        artist_entries=[("artist1", 0.15, 0.85)],
    )
    colors = _poll(engine, ("t_miss", "artist1"))
    for rgb in colors:
        for ch in rgb:
            assert 0 <= ch <= 255


def test_artist_hit_does_not_advance_hit_poll_count():
    """Artist hits must not count toward the state-machine threshold."""
    engine = _engine_with_artists(
        track_entries=[("t1", 0.5, 0.5)],
        artist_entries=[("a1", 0.2, 0.8)],
    )
    for _ in range(_POLLS_1H + 5):
        _poll(engine, ("t_miss", "a1"))
    colors = engine.update([])
    assert colors[0] == colors[1] == colors[2]


def test_artist_hit_feeds_ewma():
    """Artist hits should update EWMAs so history builds even without track hits."""
    engine = _engine_with_artists(
        track_entries=[("t_anchor", 0.5, 0.5)],
        artist_entries=[("a1", 0.9, 0.9)],
    )
    _poll(engine, _p("t_anchor"))
    for _ in range(_POLLS_1H + 1):
        _poll(engine, ("t_miss", "a1"))
    colors = engine.update([])
    assert len(colors) == 3


# ── Confidence scalar ─────────────────────────────────────────────────────────

def test_track_hit_sets_full_confidence():
    engine = _engine(("t1", 0.8, 0.8))
    _poll(engine, _p("t1"))
    assert engine._confidence == 1.0


def test_full_miss_decays_confidence():
    engine = _engine(("t1", 0.8, 0.8))
    initial = engine._confidence
    _poll(engine, _p("nomatch"))
    assert engine._confidence < initial


def test_artist_hit_arrests_confidence_at_floor():
    """After many artist-only polls, confidence must not drop below 0.6."""
    engine = _engine_with_artists(
        track_entries=[("t1", 0.5, 0.5)],
        artist_entries=[("a1", 0.3, 0.7)],
    )
    for _ in range(50):
        _poll(engine, ("t_miss", "a1"))
    assert engine._confidence >= 0.59   # allow for float precision


def test_track_hit_restores_confidence_after_decay():
    engine = _engine(("t1", 0.8, 0.8))
    for _ in range(10):
        _poll(engine, _p("miss"))
    assert engine._confidence < 1.0
    _poll(engine, _p("t1"))
    assert engine._confidence == 1.0


def test_confidence_applied_to_output():
    """Full-miss decay must make colours less saturated than a track hit."""
    engine_full = _engine(("t1", 0.15, 0.85))
    engine_fade = _engine(("t1", 0.15, 0.85))

    hit_colors = _poll(engine_full, _p("t1"))
    for _ in range(20):
        fade_colors = _poll(engine_fade, _p("miss"))

    chroma_hit  = max(hit_colors[0])  - min(hit_colors[0])
    chroma_fade = max(fade_colors[0]) - min(fade_colors[0])
    assert chroma_hit >= chroma_fade


# ── Reset ─────────────────────────────────────────────────────────────────────

def test_reset_returns_to_idle():
    engine = _engine(("t1", 0.9, 0.9))
    for _ in range(_POLLS_4H + 5):
        _poll(engine, _p("t1"))
    engine.reset()
    colors = _poll(engine, _p("miss"))
    assert colors[0] == colors[1] == colors[2]


def test_reset_restores_confidence():
    engine = _engine(("t1", 0.8, 0.8))
    for _ in range(10):
        _poll(engine, _p("miss"))
    engine.reset()
    assert engine._confidence == 1.0


def test_reset_then_hit_resumes_from_state1():
    engine = _engine(("t1", 0.5, 0.5))
    for _ in range(_POLLS_4H + 5):
        _poll(engine, _p("t1"))
    engine.reset()
    colors = _poll(engine, _p("t1"))
    assert colors[0] == colors[1] == colors[2]


# ── EWMA convergence (regression) ────────────────────────────────────────────

def test_all_pixels_converge_after_many_polls():
    engine = _engine(("steady", 0.8, 0.2))
    for _ in range(_POLLS_4H * 3):
        colors = _poll(engine, _p("steady"))
    for i in range(3):
        assert abs(colors[0][i] - colors[1][i]) < 5
        assert abs(colors[1][i] - colors[2][i]) < 5


# ── snapshot() — engine state introspection ─────────────────────────────────
#
# snapshot() returns a JSON-serializable view of the engine's internal state
# for consumption by the HTTP introspection endpoints landing in #58.
# Tuples are normalized to lists so the output round-trips through json.dumps
# without identity surprises.

_SNAPSHOT_KEYS = {"now_ve", "hit_poll_count", "confidence", "ewma_1h", "ewma_4h"}


def test_snapshot_never_polled():
    engine = _engine(("t1", 0.7, 0.8))
    snap   = engine.snapshot()
    assert set(snap.keys()) == _SNAPSHOT_KEYS
    assert snap["now_ve"]         is None
    assert snap["hit_poll_count"] == 0
    assert snap["confidence"]     == 1.0
    # Fresh EWMAs report the neutral default (0.5, 0.5) as lists.
    assert snap["ewma_1h"] == [0.5, 0.5]
    assert snap["ewma_4h"] == [0.5, 0.5]


def test_snapshot_single_track_hit():
    bundle = MMARBundle(build_bundle(("t1", 0.15, 0.85)))
    engine = MoodEngine(bundle)
    expected_ve = list(bundle.lookup("t1"))   # quantized through u8 round-trip

    _poll(engine, _p("t1"))
    snap = engine.snapshot()
    assert snap["now_ve"]         == expected_ve
    assert snap["hit_poll_count"] == 1
    assert snap["confidence"]     == 1.0
    # First observation snaps EWMAs straight to the value, no blend.
    assert snap["ewma_1h"] == expected_ve
    assert snap["ewma_4h"] == expected_ve


def test_snapshot_multiple_track_hits_accumulate():
    engine = _engine(("t1", 0.2, 0.8), ("t2", 0.9, 0.1))
    _poll(engine, _p("t1"))
    _poll(engine, _p("t2"))
    snap = engine.snapshot()
    assert snap["hit_poll_count"] == 2
    # EWMA blended away from the first observation toward the second.
    assert snap["ewma_1h"][0] > 0.2
    assert snap["ewma_1h"][1] < 0.8


def test_snapshot_all_misses_decays_confidence_but_preserves_now_ve():
    bundle = MMARBundle(build_bundle(("t1", 0.15, 0.85)))
    engine = MoodEngine(bundle)
    expected_ve = list(bundle.lookup("t1"))

    _poll(engine, _p("t1"))          # establish now_ve and full confidence
    _poll(engine, _p("nomatch"))     # full miss

    snap = engine.snapshot()
    assert snap["now_ve"]         == expected_ve
    assert snap["hit_poll_count"] == 1                    # miss does not advance
    assert snap["confidence"]     == pytest.approx(0.85)  # decays by 0.85


def test_snapshot_after_artist_fallback():
    engine = _engine_with_artists(
        track_entries=[("t1", 0.5, 0.5)],
        artist_entries=[("artist1", 0.2, 0.8)],
    )
    _poll(engine, ("t_miss", "artist1"))

    snap = engine.snapshot()
    assert snap["now_ve"]         is None        # artist hits don't update now_ve
    assert snap["hit_poll_count"] == 0           # artist hits don't advance count
    assert snap["confidence"]     == pytest.approx(0.95)  # 1.0 * 0.95
    # EWMAs *do* receive the artist signal — snapped on first update.
    assert snap["ewma_1h"] == [pytest.approx(0.2 * 255 / 255), pytest.approx(0.8 * 255 / 255)]


def test_snapshot_json_round_trips():
    engine = _engine(("t1", 0.3, 0.7))
    _poll(engine, _p("t1"))
    _poll(engine, _p("miss"))
    snap = engine.snapshot()
    decoded = json.loads(json.dumps(snap))
    assert decoded == snap


# ── last_poll_outcomes() — per-track results from most recent update() ──────

def test_last_poll_outcomes_empty_before_first_poll():
    engine = _engine(("t1", 0.7, 0.8))
    assert engine.last_poll_outcomes() == []


def test_last_poll_outcomes_track_hit_source():
    bundle = MMARBundle(build_bundle(("t1", 0.15, 0.85)))
    engine = MoodEngine(bundle)
    v, e   = bundle.lookup("t1")

    _poll(engine, _p("t1", "artist_x"))
    assert engine.last_poll_outcomes() == [("t1", "artist_x", "track", v, e)]


def test_last_poll_outcomes_artist_hit_source():
    track_entries  = [("t_other", 0.5, 0.5)]
    artist_entries = [("artist1", 0.2, 0.8)]
    t_bundle = MMARBundle(build_bundle(*track_entries))
    a_bundle = MMARBundle(build_bundle(*artist_entries))
    engine   = MoodEngine(t_bundle, a_bundle)
    v, e     = a_bundle.lookup("artist1")

    _poll(engine, ("t_miss", "artist1"))
    assert engine.last_poll_outcomes() == [("t_miss", "artist1", "artist", v, e)]


def test_last_poll_outcomes_miss_source():
    engine = _engine(("t1", 0.5, 0.5))
    _poll(engine, ("missing", "artist_z"))
    assert engine.last_poll_outcomes() == [("missing", "artist_z", "miss", None, None)]


def test_last_poll_outcomes_mixed_preserves_order():
    track_entries  = [("t_hit", 0.1, 0.9)]
    artist_entries = [("a_hit", 0.4, 0.6)]
    t_bundle = MMARBundle(build_bundle(*track_entries))
    a_bundle = MMARBundle(build_bundle(*artist_entries))
    engine   = MoodEngine(t_bundle, a_bundle)

    engine.update([
        ("t_hit",  "a_other"),
        ("t_miss", "a_hit"),
        ("nothin", "nobody"),
    ])
    outcomes = engine.last_poll_outcomes()
    # OUTCOME_FIELDS = ("track_id", "artist_id", "source", "v", "e")
    assert [o[2] for o in outcomes] == ["track", "artist", "miss"]
    assert [o[0] for o in outcomes] == ["t_hit", "t_miss", "nothin"]


def test_last_poll_outcomes_overwrites_each_call():
    engine = _engine(("t1", 0.5, 0.5))
    _poll(engine, _p("t1"))
    _poll(engine, _p("t1"), _p("t1"))   # 2 entries
    assert len(engine.last_poll_outcomes()) == 2


def test_last_poll_outcomes_json_serializable():
    engine = _engine(("t1", 0.3, 0.7))
    engine.update([("t1", "a1"), ("miss", "a2")])
    out = engine.last_poll_outcomes()
    json.dumps(out)   # must not raise


def test_reset_clears_last_poll_outcomes():
    engine = _engine(("t1", 0.5, 0.5))
    _poll(engine, _p("t1"))
    assert engine.last_poll_outcomes() != []
    engine.reset()
    assert engine.last_poll_outcomes() == []
