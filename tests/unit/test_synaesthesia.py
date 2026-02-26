import pytest
import synaesthesia


def test_hue_at_each_knot():
    """hue() must return exactly the defined H at every anchor θ."""
    for theta, expected_h in synaesthesia._p["hue_map"]:
        got  = synaesthesia.hue(theta)
        diff = abs((got - expected_h + 180) % 360 - 180)
        assert diff < 0.5, f"theta={theta}: expected H={expected_h:.1f}, got H={got:.1f}"


def test_hue_in_range():
    """hue() output must be in [0, 360) for any theta."""
    for deg in range(0, 360, 3):
        h = synaesthesia.hue(deg)
        assert 0.0 <= h < 360.0, f"hue({deg}) = {h} out of range"


def test_hue_wraparound():
    """hue(0) and hue(360) must be identical."""
    assert synaesthesia.hue(0.0) == pytest.approx(synaesthesia.hue(360.0), abs=0.01)


def test_saturation_k_positive():
    assert synaesthesia.saturation_k() > 0


def test_brightness_ceiling():
    """floor + range must not exceed 50% (NeoPixel brightness budget)."""
    ceiling = synaesthesia.brightness_floor() + synaesthesia.brightness_range()
    assert ceiling <= 0.51   # small float slack


def test_brightness_floor_nonnegative():
    assert synaesthesia.brightness_floor() >= 0.0


def test_ewma_alphas_ordered():
    """4h alpha must be smaller than 1h alpha (slower decay = smaller alpha)."""
    a1 = synaesthesia.ewma_alpha("1h")
    a4 = synaesthesia.ewma_alpha("4h")
    assert 0 < a4 < a1 < 1


def test_zone_anchors_in_range():
    for zone, (v, e) in synaesthesia.zone_anchors().items():
        assert 0.0 <= v <= 1.0, f"{zone}: valence {v} out of range"
        assert 0.0 <= e <= 1.0, f"{zone}: energy {e} out of range"


def test_profile_name_is_string():
    assert isinstance(synaesthesia.profile_name(), str)
