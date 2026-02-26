import pytest
from color import mood_to_rgb


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
