import math

import pytest

import color
import synaesthesia
from color import mood_to_rgb, apply_confidence
from polar import to_polar

_RED = (200, 30, 30)   # a clearly saturated colour for confidence tests


def _lab(rgb):
    return color._rgb_to_lab(rgb)


def _delta_e(c1, c2):
    return math.dist(_lab(c1), _lab(c2))


def _chroma(rgb):
    _, a, b = _lab(rgb)
    return math.hypot(a, b)


@pytest.fixture
def plain_profile():
    """The default palette with the tilt and the dim switched off.

    Isolates the colour table from the two modulations, so a test can assert
    what a knot is without arithmetic on top of it.
    """
    saved = synaesthesia._p
    synaesthesia._p = dict(saved, energy_tilt=0.0, master_brightness=1.0)
    yield synaesthesia._p
    synaesthesia._p = saved


def _on_ray(theta_deg, r):
    """The (v, e) at distance r along mood direction theta."""
    return (0.5 + r * math.cos(math.radians(theta_deg)),
            0.5 + r * math.sin(math.radians(theta_deg)))


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


def test_out_of_range_energy_is_clamped():
    """Energy outside [0, 1] must not drive the tilt past its stated range."""
    for e in (-1.0, 2.0):
        rgb = mood_to_rgb(0.5, e)
        for ch in rgb:
            assert 0 <= ch <= 255


# ── The colour table is emitted, not reinterpreted ──────────────────────────

def test_knots_emit_their_own_colour(plain_profile):
    """At a knot's theta, the ring emits that knot's hex.

    This is the whole point of the Lab model: the profile states the colour
    and nothing downstream re-derives it.
    """
    for theta, hexcode in plain_profile["color_map"]:
        rgb = mood_to_rgb(*_on_ray(theta, 0.35))
        want = color._hex_to_rgb(hexcode)
        assert _delta_e(rgb, want) < 1.0, \
            "theta={}: wanted {}, got {}".format(theta, hexcode, rgb)


def test_radius_does_not_change_colour(plain_profile):
    """Mood intensity r is not an input — only direction is."""
    for theta in (50.2, 95.0, 135.0, 206.6, 300.0):
        near = mood_to_rgb(*_on_ray(theta, 0.10))
        far  = mood_to_rgb(*_on_ray(theta, 0.50))
        assert near == far, "theta={} moved with r".format(theta)


def test_centre_is_not_grey(plain_profile):
    """The old model collapsed centrist moods to grey; this one must not."""
    rgb = mood_to_rgb(0.5, 0.5)
    assert _chroma(rgb) > 20.0


def test_midpoint_lies_between_its_two_knots(plain_profile):
    """Interpolation is linear in Lab between adjacent knots."""
    cm = plain_profile["color_map"]
    t0, hex0 = cm[0]
    t1, hex1 = cm[1]
    mid = mood_to_rgb(*_on_ray((t0 + t1) / 2, 0.35))
    lab0, lab1, labm = _lab(color._hex_to_rgb(hex0)), _lab(color._hex_to_rgb(hex1)), _lab(mid)
    for i in range(3):
        lo, hi = sorted((lab0[i], lab1[i]))
        assert lo - 1.0 <= labm[i] <= hi + 1.0


def test_wraparound_is_continuous(plain_profile):
    """The segment through 0/360 must not jump."""
    before = mood_to_rgb(*_on_ray(359.5, 0.35))
    after  = mood_to_rgb(*_on_ray(0.5, 0.35))
    assert _delta_e(before, after) < 4.0


# ── Separation guarantees ──────────────────────────────────────────────────

def test_knots_are_mutually_distinguishable(plain_profile):
    """No two knots may sit within the confusable range of each other."""
    cm = plain_profile["color_map"]
    worst = min(
        (_delta_e(color._hex_to_rgb(a[1]), color._hex_to_rgb(b[1])), a[0], b[0])
        for i, a in enumerate(cm) for b in cm[i + 1:]
    )
    assert worst[0] > 15.0, "knots {} and {} are only dE {:.1f} apart".format(
        worst[1], worst[2], worst[0])


def test_no_band_impersonates_a_distant_knot(plain_profile):
    """No interpolated colour may read as a knot it does not sit between.

    The failure this guards against is concrete: interpolating hue put
    fun/dance's violet between shoegaze and darkwave, and interpolating Lab
    across the unanchored 75-120 degree gap put shoegaze's magenta between
    fun/dance and industrial. Both were invisible until swept.
    """
    cm     = plain_profile["color_map"]
    thetas = [t for t, _ in cm]
    labs   = [(t, _lab(color._hex_to_rgb(h))) for t, h in cm]
    n      = len(cm)

    for i in range(360):
        t = i * 360.0 / 360
        rgb = mood_to_rgb(*_on_ray(t, 0.35))
        for j in range(n):
            t0 = thetas[j]
            t1 = thetas[(j + 1) % n] + (360 if j == n - 1 else 0)
            tt = t + 360 if (j == n - 1 and t < t0) else t
            if t0 <= tt < t1:
                lo, hi = thetas[j], thetas[(j + 1) % n]
                break
        d, who = min((math.dist(_lab(rgb), L), tk) for tk, L in labs
                     if tk not in (lo, hi))
        assert d > 15.0, \
            "theta={:.1f} (between {} and {}) reads as knot {} at dE {:.1f}".format(
                t, lo, hi, who, d)


# ── Energy tilt ────────────────────────────────────────────────────────────

def test_brightness_tracks_energy():
    """Higher energy at the same valence → a lighter colour."""
    low_e  = mood_to_rgb(0.5, 0.1)
    high_e = mood_to_rgb(0.5, 0.9)
    assert _lab(high_e)[0] > _lab(low_e)[0]


def test_energy_tilt_rises_along_a_ray():
    """Same direction, more energy → lighter.

    Energy is a coordinate of theta, so the only way to vary it while holding
    the knot colour fixed is to move along one ray: further out is both the
    same theta and higher energy.
    """
    near = mood_to_rgb(*_on_ray(95.0, 0.10))
    far  = mood_to_rgb(*_on_ray(95.0, 0.45))
    assert _lab(far)[0] > _lab(near)[0]


def test_energy_tilt_respects_its_stated_range():
    """Emitted lightness stays within +/- energy_tilt of the knot's own.

    Checked over the whole disk rather than at one point: the tilt is the only
    thing permitted to move L, so no (v, e) may land outside the band.
    """
    saved = synaesthesia._p
    synaesthesia._p = dict(saved, master_brightness=1.0)
    try:
        tilt = synaesthesia.energy_tilt()
        for vi in range(1, 10):
            for ei in range(1, 10):
                v, e = vi / 10.0, ei / 10.0
                _, theta = to_polar(v, e)
                base = color._lab_at(theta)[0]
                got  = _lab(mood_to_rgb(v, e))[0]
                assert base * (1 - tilt) - 2.0 <= got <= base * (1 + tilt) + 2.0, \
                    "({}, {}): knot L {:.1f}, emitted L {:.1f}".format(v, e, base, got)
    finally:
        synaesthesia._p = saved


def test_master_brightness_dims_without_shifting_hue():
    """Scaling all channels in linear light preserves chromaticity."""
    saved = synaesthesia._p
    try:
        synaesthesia._p = dict(saved, master_brightness=1.0)
        full = mood_to_rgb(0.5, 0.15)
        synaesthesia._p = dict(saved, master_brightness=0.5)
        dim = mood_to_rgb(0.5, 0.15)
    finally:
        synaesthesia._p = saved

    assert _lab(dim)[0] < _lab(full)[0]
    # Ratios between channels are what chromaticity is; compare in linear light.
    lf = [color._srgb_to_linear(c) for c in full]
    ld = [color._srgb_to_linear(c) for c in dim]
    scale = [d / f for d, f in zip(ld, lf)]
    assert max(scale) - min(scale) < 0.02
    assert abs(sum(scale) / 3 - 0.5) < 0.01


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
    assert _chroma(apply_confidence(_RED, 0.5)) < _chroma(apply_confidence(_RED, 1.0))


def test_apply_confidence_preserves_lightness():
    """Lab L is held constant; only chroma moves."""
    for conf in (0.0, 0.3, 0.6):
        assert abs(_lab(apply_confidence(_RED, conf))[0] - _lab(_RED)[0]) < 1.5


def test_apply_confidence_zero_is_not_near_white():
    """The HSV version washed a mid red out to (200,200,200); Lab must not."""
    grey = apply_confidence(_RED, 0.0)[0]
    assert 80 < grey < 160


def test_apply_confidence_black_stays_black():
    assert apply_confidence((0, 0, 0), 0.5) == (0, 0, 0)


def test_apply_confidence_clamps_out_of_range():
    assert apply_confidence(_RED, 5.0) == _RED
    r, g, b = apply_confidence(_RED, -1.0)
    assert r == g == b


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


# ── Lab round trip ─────────────────────────────────────────────────────────

def test_lab_round_trip():
    """_rgb_to_lab and _lab_to_rgb must be inverses within rounding."""
    for rgb in [(0, 0, 0), (255, 255, 255), (200, 30, 30), (18, 78, 173),
                (175, 242, 212), (63, 211, 74)]:
        back = color._lab_to_rgb(color._rgb_to_lab(rgb))
        for a, b in zip(rgb, back):
            assert abs(a - b) <= 1, "{} -> {}".format(rgb, back)
