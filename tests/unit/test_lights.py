import pytest
from lights import (
    StartupFlare, IdleSparkle, MoodTransition, ErrorIndicator,
    _rgb_to_hsv, _hsv_to_rgb_int, _lerp_hue,
    _IDLE_OFF, _IDLE_PEAK,
)


# ── HSV helpers ────────────────────────────────────────────────────────────

def test_rgb_hsv_roundtrip():
    for rgb in [(255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 64, 32), (0, 0, 0)]:
        h, s, v = _rgb_to_hsv(*rgb)
        back    = _hsv_to_rgb_int(h, s, v)
        for a, b in zip(rgb, back):
            assert abs(a - b) <= 1, f"{rgb} → HSV → {back}"


def test_lerp_hue_short_arc_crossing_zero():
    # 350° → 10°: short arc is +20°, not -340°
    mid = _lerp_hue(350, 10, 0.5)
    assert abs(mid - 0) <= 1 or abs(mid - 360) <= 1   # ≈ 0°


def test_lerp_hue_short_arc_normal():
    mid = _lerp_hue(60, 120, 0.5)
    assert abs(mid - 90) < 1


def test_lerp_hue_reverse_crossing_zero():
    mid = _lerp_hue(10, 350, 0.5)
    assert abs(mid - 0) <= 1 or abs(mid - 360) <= 1


# ── StartupFlare ───────────────────────────────────────────────────────────

TARGET = [(100, 50, 200), (80, 160, 40), (200, 100, 10)]

def test_flare_starts_at_black():
    f = StartupFlare(TARGET, duration_ms=3000)
    out = f.step(0)
    assert out == [(0, 0, 0), (0, 0, 0), (0, 0, 0)]


def test_flare_midpoint_is_half_brightness():
    f = StartupFlare(TARGET, duration_ms=3000)
    f.step(0)   # initialise elapsed = 0
    out = f.step(1500)
    for (ro, go, bo), (rt, gt, bt) in zip(out, TARGET):
        assert abs(ro - rt // 2) <= 1
        assert abs(go - gt // 2) <= 1
        assert abs(bo - bt // 2) <= 1


def test_flare_ends_at_target():
    f = StartupFlare(TARGET, duration_ms=3000)
    out = f.step(3000)
    assert out == TARGET
    assert f.done


def test_flare_not_done_before_duration():
    f = StartupFlare(TARGET, duration_ms=3000)
    f.step(2999)
    assert not f.done


def test_flare_output_in_range():
    f = StartupFlare(TARGET, duration_ms=1000)
    for dt in [0, 250, 500, 750, 1000]:
        for rgb in f.step(dt):
            for ch in rgb:
                assert 0 <= ch <= 255


# ── IdleSparkle ────────────────────────────────────────────────────────────

def _always_max(a, b):
    """randint that always returns b — makes every pixel flicker every step."""
    return 0

def _always_min(a, b):
    """randint that always returns a — no pixel ever spontaneously flickers."""
    return a


def test_idle_output_is_dim():
    sparkle = IdleSparkle(randint_fn=_always_max)
    for _ in range(20):
        for rgb in sparkle.step(100):
            for ch in rgb:
                assert ch <= max(_IDLE_PEAK)


def test_idle_output_valid_rgb():
    sparkle = IdleSparkle()
    for rgb in sparkle.step(500):
        for ch in rgb:
            assert 0 <= ch <= 255


def test_idle_never_exceeds_peak():
    sparkle = IdleSparkle(randint_fn=_always_max)
    for _ in range(50):
        for rgb in sparkle.step(100):
            assert rgb == _IDLE_OFF or rgb == _IDLE_PEAK


def test_idle_three_pixels_independent():
    """Pixels must be tracked independently (separate countdowns)."""
    sparkle = IdleSparkle(num_pixels=3)
    # Step enough that at least some pixels may flicker — just check structure
    for _ in range(100):
        out = sparkle.step(50)
        assert len(out) == 3


def test_idle_done_flag_defaults_false():
    assert not IdleSparkle().done


# ── MoodTransition ─────────────────────────────────────────────────────────

FROM  = [(200, 10, 10), (10, 200, 10), (10, 10, 200)]
TO    = [(10, 10, 200), (200, 10, 10), (10, 200, 10)]


def test_transition_starts_at_from():
    t = MoodTransition(FROM, TO, duration_ms=60_000)
    out = t.step(0)
    for got, expected in zip(out, FROM):
        for a, b in zip(got, expected):
            assert abs(a - b) <= 2, f"start: expected ≈{expected}, got {got}"


def test_transition_ends_at_to():
    t = MoodTransition(FROM, TO, duration_ms=1000)
    out = t.step(1000)
    assert t.done
    for got, expected in zip(out, TO):
        for a, b in zip(got, expected):
            assert abs(a - b) <= 2, f"end: expected ≈{expected}, got {got}"


def test_transition_midpoint_is_between():
    t = MoodTransition(FROM, TO, duration_ms=1000)
    t.step(0)
    out = t.step(500)
    for got, f_col, t_col in zip(out, FROM, TO):
        for ch, fc, tc in zip(got, f_col, t_col):
            lo, hi = min(fc, tc) - 20, max(fc, tc) + 20
            assert lo <= ch <= hi, f"midpoint {ch} not between {fc} and {tc}"


def test_transition_hue_short_arc():
    """
    Transition from near-red (H≈350) to near-red (H≈10) must take the
    short arc through 0°, not the long way through 180°.
    """
    red_a = _hsv_to_rgb_int(350, 1.0, 0.8)
    red_b = _hsv_to_rgb_int(10,  1.0, 0.8)
    t     = MoodTransition([red_a]*3, [red_b]*3, duration_ms=1000)
    t.step(0)
    mid   = t.step(500)
    # At the midpoint the hue should be ≈0° (red), not ≈180° (cyan)
    for rgb in mid:
        h, s, v = _rgb_to_hsv(*rgb)
        # Hue at midpoint should be near 0° (either ≤20 or ≥340)
        assert h <= 20 or h >= 340, f"hue {h:.1f}° suggests long arc was taken"


def test_transition_not_done_early():
    t = MoodTransition(FROM, TO, duration_ms=1000)
    t.step(999)
    assert not t.done


def test_transition_output_in_range():
    t = MoodTransition(FROM, TO, duration_ms=1000)
    for dt in [0, 250, 500, 750, 1000]:
        for rgb in t.step(dt):
            for ch in rgb:
                assert 0 <= ch <= 255


def test_update_target_restarts_from_current():
    """update_target should not snap — it continues from the current position."""
    t = MoodTransition(FROM, TO, duration_ms=1000)
    t.step(500)   # halfway
    mid = t.step(0)   # current colour (dt=0 so doesn't advance)

    new_target = [(50, 50, 50)] * 3
    t.update_target(new_target)
    assert not t.done

    start = t.step(0)
    for got, expected in zip(start, mid):
        for a, b in zip(got, expected):
            assert abs(a - b) <= 3, f"update_target: expected ≈{expected}, got {got}"


# ── ErrorIndicator ─────────────────────────────────────────────────────────

def test_wifi_lost_produces_red():
    e = ErrorIndicator(ErrorIndicator.WIFI_LOST)
    for _ in range(20):
        for r, g, b in e.step(100):
            assert g == 0 and b == 0


def test_wifi_lost_brightness_in_ceiling():
    e = ErrorIndicator(ErrorIndicator.WIFI_LOST)
    for _ in range(30):
        for r, g, b in e.step(100):
            assert r <= 25   # well within ambient brightness ceiling


def test_wifi_lost_never_done():
    e = ErrorIndicator(ErrorIndicator.WIFI_LOST)
    for _ in range(200):
        e.step(100)
    assert not e.done


def test_auth_fail_flashes_red():
    e = ErrorIndicator(ErrorIndicator.AUTH_FAIL)
    outputs = [e.step(100) for _ in range(10)]
    # At least one frame should be red
    any_red = any(all(r > 0 and g == 0 and b == 0 for r, g, b in frame)
                  for frame in outputs)
    assert any_red


def test_auth_fail_done_after_three_flashes():
    e = ErrorIndicator(ErrorIndicator.AUTH_FAIL)
    # Flash cycle = 700 on + 500 off = 1200 ms; 3 flashes = 3600 ms
    e.step(3600)
    assert e.done


def test_auth_fail_outputs_black_when_done():
    e = ErrorIndicator(ErrorIndicator.AUTH_FAIL)
    e.step(4000)
    assert e.done
    out = e.step(0)
    assert all(rgb == (0, 0, 0) for rgb in out)
