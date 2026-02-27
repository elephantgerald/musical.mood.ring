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
