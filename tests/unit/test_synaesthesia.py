import pytest
import synaesthesia


def test_color_map_sorted_ascending():
    """color.py's segment walk assumes the knots are in theta order."""
    thetas = [t for t, _ in synaesthesia.color_map()]
    assert thetas == sorted(thetas)
    assert len(thetas) == len(set(thetas)), "duplicate theta would give a zero-width segment"


def test_color_map_thetas_in_range():
    for theta, _ in synaesthesia.color_map():
        assert 0.0 <= theta < 360.0


def test_color_map_entries_are_hex():
    for theta, hexcode in synaesthesia.color_map():
        assert hexcode.startswith("#") and len(hexcode) == 7, \
            "theta={}: {!r} is not #RRGGBB".format(theta, hexcode)
        int(hexcode[1:], 16)


def test_color_map_covers_every_zone():
    """Every zone anchor's direction must have a knot within a degree of it.

    Knots may exist that are not zones (the steering knot at 95 degrees), but
    no zone may be left without its own colour.
    """
    import math
    thetas = [t for t, _ in synaesthesia.color_map()]
    for zone, (v, e) in synaesthesia.zone_anchors().items():
        theta = math.degrees(math.atan2(e - 0.5, v - 0.5)) % 360
        assert any(abs(theta - t) < 1.0 for t in thetas), \
            "{} at theta {:.1f} has no knot".format(zone, theta)


def test_energy_tilt_in_range():
    """A tilt above ~0.5 would let energy restate the colour rather than shade it."""
    assert 0.0 <= synaesthesia.energy_tilt() <= 0.5


def test_master_brightness_in_range():
    assert 0.0 < synaesthesia.master_brightness() <= 1.0


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


# ── Fallback behaviour ─────────────────────────────────────────────────────

def test_missing_field_falls_back_to_default():
    """A stale v1 profile on flash must degrade, not raise.

    v1 profiles carry hue_map/saturation_k and no color_map at all. The device
    should come up on the built-in palette rather than failing to boot.
    """
    saved = synaesthesia._p
    synaesthesia._p = {"version": 1, "name": "stale", "hue_map": [[0.0, 0.0]],
                       "saturation_k": 2.0}
    try:
        assert synaesthesia.color_map() == synaesthesia._DEFAULT["color_map"]
        assert synaesthesia.energy_tilt() == synaesthesia._DEFAULT["energy_tilt"]
        assert synaesthesia.master_brightness() == synaesthesia._DEFAULT["master_brightness"]
        assert synaesthesia.zone_anchors() == synaesthesia._DEFAULT["zone_anchors"]
        assert synaesthesia.profile_name() == "stale"
    finally:
        synaesthesia._p = saved


def test_partial_profile_keeps_its_own_fields():
    """Fallback is per key: a profile contributes whatever it does carry."""
    saved = synaesthesia._p
    synaesthesia._p = {"name": "partial", "master_brightness": 0.2}
    try:
        assert synaesthesia.master_brightness() == 0.2
        assert synaesthesia.color_map() == synaesthesia._DEFAULT["color_map"]
    finally:
        synaesthesia._p = saved


def test_default_profile_is_self_consistent():
    """The built-in default must satisfy every rule a loaded profile does."""
    d = synaesthesia._DEFAULT
    thetas = [t for t, _ in d["color_map"]]
    assert thetas == sorted(thetas)
    assert 0.0 <= d["energy_tilt"] <= 0.5
    assert 0.0 < d["master_brightness"] <= 1.0
    assert 0 < d["ewma_alpha_4h"] < d["ewma_alpha_1h"] < 1
