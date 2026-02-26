import pytest
from conftest import build_bundle
from mmar        import MMARBundle
from mood_engine import MoodEngine


def _engine(*entries):
    """Helper: build a MoodEngine from (track_id, valence, energy) entries."""
    return MoodEngine(MMARBundle(build_bundle(*entries)))


# ── Output shape ───────────────────────────────────────────────────────────

def test_returns_three_rgb_tuples():
    engine = _engine(("t1", 0.7, 0.8))
    colors = engine.update(["t1"])
    assert len(colors) == 3
    for rgb in colors:
        assert len(rgb) == 3
        for ch in rgb:
            assert isinstance(ch, int)
            assert 0 <= ch <= 255


# ── Miss behaviour ─────────────────────────────────────────────────────────

def test_all_misses_returns_valid_colors():
    engine = _engine(("t1", 0.7, 0.8))
    colors = engine.update(["notinbundle"])
    for rgb in colors:
        for ch in rgb:
            assert 0 <= ch <= 255


def test_empty_track_list():
    engine = _engine(("t1", 0.7, 0.8))
    colors = engine.update([])
    assert len(colors) == 3


# ── Hit behaviour ──────────────────────────────────────────────────────────

def test_mixed_hit_and_miss():
    engine = _engine(("known", 0.15, 0.85))
    colors = engine.update(["unknown", "known", "alsounknown"])
    for rgb in colors:
        for ch in rgb:
            assert 0 <= ch <= 255


def test_now_pixel_persists_across_miss_poll():
    """
    Pixel 0 should not reset to neutral when a poll returns no bundle hits.
    It should hold the last known mood until a new hit arrives.
    """
    engine = _engine(("t1", 0.9, 0.1))

    colors_hit  = engine.update(["t1"])
    colors_miss = engine.update(["nomatch"])

    # Pixel 0 should be the same after a miss poll
    assert colors_hit[0] == colors_miss[0]


# ── EWMA convergence ───────────────────────────────────────────────────────

def test_ewma_converges():
    """After many identical polls, all three pixels should land at the same colour."""
    engine = _engine(("steady", 0.8, 0.2))
    for _ in range(300):
        colors = engine.update(["steady"])
    pix0, pix1, pix2 = colors
    for i in range(3):
        assert abs(pix0[i] - pix1[i]) < 5, f"ch{i}: pix0={pix0[i]} pix1={pix1[i]}"
        assert abs(pix1[i] - pix2[i]) < 5, f"ch{i}: pix1={pix1[i]} pix2={pix2[i]}"


# ── Reset ──────────────────────────────────────────────────────────────────

def test_reset_clears_state():
    engine = _engine(("t1", 0.9, 0.9))
    for _ in range(50):
        engine.update(["t1"])
    engine.reset()

    # After reset, the engine should behave as if freshly constructed.
    # A single miss poll should give neutral-ish colours (near grey).
    colors = engine.update(["nomatch"])
    for rgb in colors:
        spread = max(rgb) - min(rgb)
        assert spread < 30, f"expected near-grey after reset+miss, got {rgb}"
