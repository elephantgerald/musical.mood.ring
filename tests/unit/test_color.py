import pytest
from color import mood_to_rgb, apply_confidence

_RED = (200, 30, 30)   # a clearly saturated colour for confidence tests


def test_returns_three_ints():
    r, g, b = mood_to_rgb(0.5, 0.5)
    for ch in (r, g, b):
        assert isinstance(ch, int)
        assert 0 <= ch <= 255


def test_all_grid_points_in_range():
    """Every point on a coarse grid must produce valid RGB."""
    for vi in range(5):
        for ei in range(5):
            rgb = mood_to_rgb(vi / 4, ei / 4)
            assert len(rgb) == 3
            for ch in rgb:
                assert 0 <= ch <= 255


def test_neutral_is_greyscale():
    """Centre of mood space: r=0 → S=0 → all channels equal (greyscale)."""
    r, g, b = mood_to_rgb(0.5, 0.5)
    assert r == g == b


def test_brightness_tracks_energy():
    """Higher energy at the same valence → higher max channel value."""
    low_e  = mood_to_rgb(0.5, 0.1)
    high_e = mood_to_rgb(0.5, 0.9)
    assert max(high_e) > max(low_e)


def test_opposing_corners_differ():
    """Two diagonally opposite extremes should produce clearly different colours."""
    c1 = mood_to_rgb(0.15, 0.85)   # industrial region
    c2 = mood_to_rgb(0.75, 0.15)   # americana/ambient region
    diff = sum(abs(a - b) for a, b in zip(c1, c2))
    assert diff > 80, f"corners too similar: {c1} vs {c2}"


def test_saturation_increases_with_r():
    """Tracks further from centre should be more saturated (higher chroma)."""
    near   = mood_to_rgb(0.55, 0.55)   # r ≈ 0.07
    far    = mood_to_rgb(0.9,  0.9)    # r ≈ 0.57
    chroma_near = max(near) - min(near)
    chroma_far  = max(far)  - min(far)
    assert chroma_far > chroma_near


# ── apply_confidence ────────────────────────────────────────────────────────

def test_apply_confidence_identity():
    """confidence=1.0 must return the original colour unchanged."""
    assert apply_confidence(_RED, 1.0) == _RED


def test_apply_confidence_zero_gives_greyscale():
    """confidence=0.0 must desaturate fully: r == g == b."""
    r, g, b = apply_confidence(_RED, 0.0)
    assert r == g == b


def test_apply_confidence_half_reduces_chroma():
    """confidence=0.5 must reduce chroma relative to 1.0."""
    full = apply_confidence(_RED, 1.0)
    half = apply_confidence(_RED, 0.5)
    chroma_full = max(full) - min(full)
    chroma_half = max(half) - min(half)
    assert chroma_half < chroma_full


def test_apply_confidence_preserves_brightness():
    """Max channel (brightness proxy) should be unchanged by confidence scaling."""
    assert max(apply_confidence(_RED, 1.0)) == max(apply_confidence(_RED, 0.0))


def test_apply_confidence_black_stays_black():
    assert apply_confidence((0, 0, 0), 0.5) == (0, 0, 0)


def test_apply_confidence_output_in_range():
    for conf in [0.0, 0.3, 0.6, 1.0]:
        r, g, b = apply_confidence(_RED, conf)
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255


def test_apply_confidence_returns_tuple_of_three_ints():
    result = apply_confidence(_RED, 0.7)
    assert len(result) == 3
    for ch in result:
        assert isinstance(ch, int)
