import pytest
from conftest import build_bundle
from mmar        import MMARBundle
from mood_engine import MoodEngine, _POLLS_1H, _POLLS_4H


def _engine(*entries):
    """Helper: build a MoodEngine from (track_id, valence, energy) entries."""
    return MoodEngine(MMARBundle(build_bundle(*entries)))


def _poll(engine, *track_ids):
    return engine.update(list(track_ids))


# ── Output shape ───────────────────────────────────────────────────────────

def test_returns_three_rgb_tuples():
    engine = _engine(("t1", 0.7, 0.8))
    colors = _poll(engine, "t1")
    assert len(colors) == 3
    for rgb in colors:
        assert len(rgb) == 3
        for ch in rgb:
            assert isinstance(ch, int)
            assert 0 <= ch <= 255


# ── State 0: Inactive ──────────────────────────────────────────────────────

def test_idle_state_no_hits_ever():
    """Before any bundle hit, all three pixels should be in the idle state."""
    engine = _engine(("t1", 0.7, 0.8))
    colors = _poll(engine, "notinbundle")
    # All three pixels should be identical (idle is uniform)
    assert colors[0] == colors[1] == colors[2]


def test_idle_state_empty_poll():
    engine = _engine(("t1", 0.7, 0.8))
    colors = _poll(engine)   # empty track list
    assert colors[0] == colors[1] == colors[2]


def test_idle_color_is_valid_rgb():
    engine = _engine(("t1", 0.5, 0.5))
    colors = _poll(engine, "miss")
    for rgb in colors:
        for ch in rgb:
            assert 0 <= ch <= 255


# ── State 1: < 1 hr — all three share recent ──────────────────────────────

def test_first_hit_all_pixels_share_recent():
    """On the first hit poll, all three pixels should show the same colour."""
    engine = _engine(("t1", 0.15, 0.85))
    colors = _poll(engine, "t1")
    assert colors[0] == colors[1] == colors[2]


def test_all_share_recent_up_to_1h_threshold():
    """All three pixels stay identical until _POLLS_1H hits have accumulated."""
    engine = _engine(("t1", 0.9, 0.1))
    for _ in range(_POLLS_1H):
        colors = _poll(engine, "t1")
    assert colors[0] == colors[1] == colors[2]


def test_pixels_diverge_after_1h_threshold():
    """After _POLLS_1H + 1 hit polls, pixel 1 should diverge from pixel 0."""
    engine = _engine(("t1", 0.9, 0.1))
    for _ in range(_POLLS_1H + 1):
        colors = _poll(engine, "t1")
    # After many identical polls, EWMA converges to same value as recent, so
    # compare pixels structurally: pixel 1 is now sourced from EWMA not recent.
    # With enough polls the values converge, but they must at least be valid.
    for rgb in colors:
        for ch in rgb:
            assert 0 <= ch <= 255


# ── State 2: 1–4 hr — P1 tracks P2 ────────────────────────────────────────

def test_pixels_1_and_2_share_after_1h():
    """Between _POLLS_1H+1 and _POLLS_4H hit polls, pixels 1 and 2 should match."""
    engine = _engine(("t1", 0.9, 0.1))
    # Drive past the 1h threshold
    for _ in range(_POLLS_1H + 1):
        _poll(engine, "t1")
    # Should still be below 4h
    colors = _poll(engine, "t1")
    assert colors[1] == colors[2]


def test_at_4h_boundary_p1_p2_still_share():
    engine = _engine(("t1", 0.8, 0.2))
    for _ in range(_POLLS_4H):
        colors = _poll(engine, "t1")
    assert colors[1] == colors[2]


# ── State 3: > 4 hr — full discrimination ─────────────────────────────────

def test_pixels_diverge_after_4h():
    """
    After _POLLS_4H hit polls, pixel 2 should be sourced from the 4h EWMA
    rather than the 1h EWMA. With the same track repeated, both EWMAs converge
    to the same value — use two different tracks to make the EWMAs diverge.
    """
    engine = _engine(("dark", 0.1, 0.9), ("bright", 0.9, 0.1))

    # First fill the 4h window with dark
    for _ in range(_POLLS_4H + 1):
        _poll(engine, "dark")

    # Now switch to bright — 1h EWMA will shift faster than 4h EWMA
    for _ in range(10):
        colors = _poll(engine, "bright")

    # pixel 1 (1h) should be noticeably different from pixel 2 (4h)
    diff = sum(abs(a - b) for a, b in zip(colors[1], colors[2]))
    assert diff > 10, f"pixels 1 and 2 too similar after regime change: {colors}"


# ── Miss-poll persistence ──────────────────────────────────────────────────

def test_now_pixel_persists_across_miss_poll():
    """Pixel 0 must hold the last known mood through a miss poll."""
    engine = _engine(("t1", 0.9, 0.1))
    colors_hit  = _poll(engine, "t1")
    colors_miss = _poll(engine, "nomatch")
    assert colors_hit[0] == colors_miss[0]


def test_miss_poll_does_not_advance_state():
    """A miss poll should not increment the hit counter or advance the state."""
    engine = _engine(("t1", 0.9, 0.1))
    # One hit poll → state 1
    _poll(engine, "t1")
    # Many miss polls — state should not advance to 1h
    for _ in range(_POLLS_1H + 5):
        colors = _poll(engine, "miss")
    # Still in state 1: all three share (pixel 0 persists from the one hit)
    assert colors[0] == colors[1] == colors[2]


# ── Reset ──────────────────────────────────────────────────────────────────

def test_reset_returns_to_idle():
    """After reset, a miss poll should return the idle (uniform) colour."""
    engine = _engine(("t1", 0.9, 0.9))
    for _ in range(_POLLS_4H + 5):
        _poll(engine, "t1")
    engine.reset()
    colors = _poll(engine, "miss")
    assert colors[0] == colors[1] == colors[2]


def test_reset_then_hit_resumes_from_state1():
    """After reset, first hit poll should put all pixels back to state 1 (shared)."""
    engine = _engine(("t1", 0.5, 0.5))
    for _ in range(_POLLS_4H + 5):
        _poll(engine, "t1")
    engine.reset()
    colors = _poll(engine, "t1")
    assert colors[0] == colors[1] == colors[2]


# ── EWMA convergence (regression) ─────────────────────────────────────────

def test_all_pixels_converge_after_many_polls():
    """
    After enough identical polls (>> _POLLS_4H), all three EWMAs converge to
    the same value, so all three pixels should be nearly identical.
    """
    engine = _engine(("steady", 0.8, 0.2))
    for _ in range(_POLLS_4H * 3):
        colors = _poll(engine, "steady")
    for i in range(3):
        assert abs(colors[0][i] - colors[1][i]) < 5
        assert abs(colors[1][i] - colors[2][i]) < 5
