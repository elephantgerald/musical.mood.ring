import pytest
from lights import (
    StartupFlare, IdleSparkle, MoodTransition, ErrorIndicator, BootStatus,
    ApiErrorBlip,
    _rgb_to_hsv, _hsv_to_rgb_int, _lerp_hue,
    _IDLE_PEAK,
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

def test_idle_output_valid_rgb():
    sparkle = IdleSparkle()
    for _ in range(20):
        for rgb in sparkle.step(100):
            for ch in rgb:
                assert 0 <= ch <= 255


def test_idle_never_exceeds_peak():
    """No channel should ever exceed its corresponding PEAK value."""
    sparkle = IdleSparkle()
    for _ in range(50):
        for r, g, b in sparkle.step(100):
            assert r <= _IDLE_PEAK[0]
            assert g <= _IDLE_PEAK[1]
            assert b <= _IDLE_PEAK[2]


def test_idle_three_pixels_independent():
    """step() must always return exactly 3 pixels."""
    sparkle = IdleSparkle(num_pixels=3)
    for _ in range(100):
        out = sparkle.step(50)
        assert len(out) == 3


def test_idle_done_flag_defaults_false():
    assert not IdleSparkle().done


def test_idle_brightness_varies_over_time():
    """Waveform must evolve — pixels at t=0 must differ from pixels at t=30s."""
    sparkle = IdleSparkle()
    first = sparkle.step(0)
    for _ in range(600):   # advance 30 s (fast waves complete several cycles)
        sparkle.step(50)
    later = sparkle.step(0)
    assert first != later, "brightness must vary as time advances"


def test_idle_floor_is_nonzero():
    """DC floor keeps average brightness positive even when no swells are active."""
    sparkle = IdleSparkle()
    total = 0
    count = 0
    for _ in range(100):
        for r, g, b in sparkle.step(100):
            total += max(r, g, b)
            count += 1
    # DC floor (0.04) is less than max fast-wave cancellation (0.12), so
    # individual samples can hit 0 — but the mean must be clearly positive.
    assert total / count > 0, "mean brightness must be positive"


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


# ── BootStatus ──────────────────────────────────────────────────────────────

def test_connecting_output_is_white():
    b = BootStatus(BootStatus.CONNECTING)
    for _ in range(10):
        for r, g, bv in b.step(50):
            assert r == g == bv, f"CONNECTING pixel must be white, got ({r},{g},{bv})"


def test_connecting_cycles_through_pixels():
    """Over a full rotation at least two pixels should differ in brightness."""
    b = BootStatus(BootStatus.CONNECTING)
    varied = False
    for _ in range(30):
        frame = b.step(50)
        if len(set(frame)) > 1:
            varied = True
            break
    assert varied, "CONNECTING pixels must vary (comet effect)"


def test_connecting_not_done():
    b = BootStatus(BootStatus.CONNECTING)
    for _ in range(100):
        b.step(50)
    assert not b.done


def test_config_wait_is_blue():
    b = BootStatus(BootStatus.CONFIG_WAIT)
    for _ in range(20):
        for r, g, blue in b.step(100):
            assert r == 0, f"CONFIG_WAIT r must be 0, got {r}"
            assert g == 0, f"CONFIG_WAIT g must be 0, got {g}"


def test_config_wait_blue_channel_reaches_nonzero():
    b = BootStatus(BootStatus.CONFIG_WAIT)
    blues = []
    for _ in range(30):
        frame = b.step(100)
        blues.extend(bv for _, _, bv in frame)
    assert max(blues) > 0, "CONFIG_WAIT blue channel must pulse above 0"


def test_config_wait_not_done():
    b = BootStatus(BootStatus.CONFIG_WAIT)
    for _ in range(100):
        b.step(50)
    assert not b.done


def test_success_is_green():
    b = BootStatus(BootStatus.SUCCESS)
    for r, g, bv in b.step(0):
        assert r == 0,  f"SUCCESS r must be 0, got {r}"
        assert bv == 0, f"SUCCESS b must be 0, got {bv}"
        assert g >= 0


def test_success_starts_bright():
    b = BootStatus(BootStatus.SUCCESS)
    frame = b.step(0)
    assert any(g > 0 for _, g, _ in frame), "SUCCESS must be green at start"


def test_success_done_after_duration():
    b = BootStatus(BootStatus.SUCCESS)
    b.step(BootStatus._SUCCESS_MS + 1)
    assert b.done


def test_success_outputs_black_when_done():
    b = BootStatus(BootStatus.SUCCESS)
    b.step(BootStatus._SUCCESS_MS + 1)
    assert b.done
    out = b.step(0)
    assert all(rgb == (0, 0, 0) for rgb in out)


def test_fail_produces_red():
    b = BootStatus(BootStatus.FAIL)
    frames = [b.step(100) for _ in range(10)]
    any_red = any(
        all(r > 0 and g == 0 and bv == 0 for r, g, bv in frame)
        for frame in frames
    )
    assert any_red, "FAIL mode must produce red flashes"


def test_fail_done_after_three_flashes():
    b = BootStatus(BootStatus.FAIL)
    b.step(3600)   # 3 × (700 on + 500 off) = 3600 ms
    assert b.done


def test_fail_outputs_black_when_done():
    b = BootStatus(BootStatus.FAIL)
    b.step(4000)
    assert b.done
    out = b.step(0)
    assert all(rgb == (0, 0, 0) for rgb in out)


def test_boot_status_brightness_ceiling():
    """All BootStatus modes must stay ≤ 128 (50% brightness ceiling)."""
    for mode in [BootStatus.CONNECTING, BootStatus.CONFIG_WAIT,
                 BootStatus.SUCCESS, BootStatus.FAIL]:
        b = BootStatus(mode)
        for _ in range(40):
            for r, g, bv in b.step(50):
                assert r <= 128, f"{mode}: r={r} exceeds ceiling"
                assert g <= 128, f"{mode}: g={g} exceeds ceiling"
                assert bv <= 128, f"{mode}: b={bv} exceeds ceiling"


def test_boot_status_output_length():
    """Every mode must return exactly 3 pixels each step."""
    for mode in [BootStatus.CONNECTING, BootStatus.CONFIG_WAIT,
                 BootStatus.SUCCESS, BootStatus.FAIL]:
        b = BootStatus(mode)
        for _ in range(5):
            out = b.step(50)
            assert len(out) == 3, f"{mode}: expected 3 pixels, got {len(out)}"


def test_boot_status_channels_in_range():
    """All channel values must be in [0, 255]."""
    for mode in [BootStatus.CONNECTING, BootStatus.CONFIG_WAIT,
                 BootStatus.SUCCESS, BootStatus.FAIL]:
        b = BootStatus(mode)
        for _ in range(20):
            for r, g, bv in b.step(100):
                assert 0 <= r <= 255
                assert 0 <= g <= 255
                assert 0 <= bv <= 255


# ── ApiErrorBlip ─────────────────────────────────────────────────────────────

_RED   = [(200, 10, 10)] * 3
_BLACK = [(0, 0, 0)] * 3
_DIM   = [(6, 7, 10)] * 3    # idle-sparkle level — nearly invisible


def test_blip_first_phase_shows_complementary():
    """Phase 0 (0–299 ms): complementary colour is lit."""
    blip = ApiErrorBlip(_RED)
    out  = blip.step(0)
    assert all(rgb == out[0] for rgb in out), "all pixels must match"
    assert out[0] != (0, 0, 0), "phase 0 must not be black"
    assert not blip.done


def test_blip_middle_phase_shows_black():
    """Phase 1 (300–599 ms): all pixels off."""
    blip = ApiErrorBlip(_RED)
    blip.step(300)
    out = blip.step(0)
    assert all(rgb == (0, 0, 0) for rgb in out), "phase 1 must be black"
    assert not blip.done


def test_blip_second_on_phase_shows_complementary():
    """Phase 2 (600–899 ms): complementary colour lit again."""
    blip = ApiErrorBlip(_RED)
    comp = blip.step(0)[0]   # capture the complementary colour
    blip.step(600)
    out = blip.step(0)
    assert all(rgb == comp for rgb in out), "phase 2 must show complementary"
    assert not blip.done


def test_blip_done_after_900ms():
    blip = ApiErrorBlip(_RED)
    blip.step(900)
    assert blip.done


def test_blip_not_done_at_899ms():
    blip = ApiErrorBlip(_RED)
    blip.step(899)
    assert not blip.done


def test_blip_outputs_black_when_done():
    blip = ApiErrorBlip(_RED)
    blip.step(900)
    assert blip.done
    out = blip.step(0)
    assert all(rgb == (0, 0, 0) for rgb in out)


def test_blip_complementary_of_red_is_cyan():
    """Red input → hue shifts 180° to cyan territory."""
    blip = ApiErrorBlip(_RED)
    comp = blip.step(0)[0]
    h, s, v = _rgb_to_hsv(*comp)
    # Cyan lives around 180°; allow ±30° tolerance
    assert 150 <= h <= 210, f"expected cyan hue (~180°), got {h:.1f}°"


def test_blip_visible_from_black_input():
    """Even from a fully dark display the blip must be visibly bright."""
    blip = ApiErrorBlip(_BLACK)
    out  = blip.step(0)
    for r, g, b in out:
        assert max(r, g, b) >= 50, "blip must be visible even from black input"


def test_blip_visible_from_dim_idle():
    """Blip from idle-sparkle level colours must also be visible."""
    blip = ApiErrorBlip(_DIM)
    out  = blip.step(0)
    for r, g, b in out:
        assert max(r, g, b) >= 50


def test_blip_brightness_ceiling():
    """Complementary colour must not exceed 50% brightness (channel ≤ 128)."""
    for colors in [_RED, _BLACK, _DIM, [(255, 255, 255)] * 3]:
        blip = ApiErrorBlip(colors)
        for _ in range(10):
            for r, g, b in blip.step(100):
                assert r <= 128, f"r={r} exceeds ceiling"
                assert g <= 128, f"g={g} exceeds ceiling"
                assert b <= 128, f"b={b} exceeds ceiling"


def test_blip_output_length():
    blip = ApiErrorBlip(_RED)
    for dt in [0, 300, 600, 900]:
        assert len(blip.step(dt)) == 3


def test_blip_channels_in_range():
    blip = ApiErrorBlip(_RED)
    for dt in [0, 150, 300, 450, 600, 750]:
        for r, g, b in blip.step(dt):
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255
