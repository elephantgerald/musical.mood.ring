import math

import pytest
from ewma import EWMA, tau_from_alpha


def test_neutral_before_first_update():
    ewma = EWMA(tau_ms=1000)
    v, e = ewma.value
    assert v == pytest.approx(0.5)
    assert e == pytest.approx(0.5)


def test_first_update_snaps_not_blends():
    """First update snaps directly to the observed value, whatever the dt."""
    ewma = EWMA(tau_ms=1000)
    ewma.update(0.8, 0.2, dt_ms=1)
    v, e = ewma.value
    assert v == pytest.approx(0.8)
    assert e == pytest.approx(0.2)


def test_zero_dt_does_not_move_estimate():
    """No time elapsed → no decay; the estimate holds."""
    ewma = EWMA(tau_ms=1000)
    ewma.update(1.0, 0.0, dt_ms=1000)   # snap
    ewma.update(0.0, 1.0, dt_ms=0)      # no time passed
    v, e = ewma.value
    assert v == pytest.approx(1.0)
    assert e == pytest.approx(0.0)


def test_blend_at_one_time_constant():
    """dt == tau gives alpha = 1 - 1/e ≈ 0.632."""
    ewma = EWMA(tau_ms=1000)
    ewma.update(0.0, 0.0, dt_ms=1000)   # snap to 0
    ewma.update(1.0, 1.0, dt_ms=1000)   # dt == tau
    a = 1.0 - math.exp(-1)
    v, e = ewma.value
    assert v == pytest.approx(a)
    assert e == pytest.approx(a)


def test_large_dt_snaps_toward_new():
    """dt >> tau → alpha → 1 → estimate jumps to the new observation."""
    ewma = EWMA(tau_ms=1000)
    ewma.update(0.0, 0.0, dt_ms=1000)
    ewma.update(1.0, 1.0, dt_ms=100_000)   # 100 * tau
    v, e = ewma.value
    assert v == pytest.approx(1.0, abs=1e-3)
    assert e == pytest.approx(1.0, abs=1e-3)


def test_convergence():
    """Many updates of the same value converge to that value."""
    ewma = EWMA(tau_ms=1000)
    for _ in range(500):
        ewma.update(0.9, 0.1, dt_ms=500)
    v, e = ewma.value
    assert v == pytest.approx(0.9, abs=1e-3)
    assert e == pytest.approx(0.1, abs=1e-3)


def test_tau_zero_always_snaps():
    """tau_ms == 0 → alpha 1 → EWMA always equals the most recent observation."""
    ewma = EWMA(tau_ms=0)
    ewma.update(0.3, 0.7, dt_ms=10)
    ewma.update(0.9, 0.1, dt_ms=10)
    v, e = ewma.value
    assert v == pytest.approx(0.9)
    assert e == pytest.approx(0.1)


def test_infinite_tau_never_decays():
    """tau_ms == inf → alpha 0 → estimate holds after the first snap."""
    ewma = EWMA(tau_ms=float("inf"))
    ewma.update(0.3, 0.7, dt_ms=10)
    ewma.update(0.9, 0.1, dt_ms=10_000)
    v, e = ewma.value
    assert v == pytest.approx(0.3)
    assert e == pytest.approx(0.7)


def test_reset_returns_to_neutral():
    ewma = EWMA(tau_ms=1000)
    ewma.update(1.0, 1.0, dt_ms=1000)
    ewma.reset()
    v, e = ewma.value
    assert v == pytest.approx(0.5)
    assert e == pytest.approx(0.5)


def test_reset_then_snap():
    """After reset the next update snaps again, not blends from neutral."""
    ewma = EWMA(tau_ms=1000)
    ewma.update(0.9, 0.9, dt_ms=1000)
    ewma.reset()
    ewma.update(0.2, 0.3, dt_ms=1000)
    v, e = ewma.value
    assert v == pytest.approx(0.2)
    assert e == pytest.approx(0.3)


# ── tau_from_alpha: backward-compat with the fixed-alpha calibration ─────────

def test_tau_from_alpha_reproduces_alpha_at_reference_cadence():
    """An update with dt == ref_ms must blend by exactly the original alpha,
    so behaviour at the nominal poll cadence is unchanged by the rewrite."""
    ref, alpha = 180_000, 0.2
    ewma = EWMA(tau_ms=tau_from_alpha(alpha, ref))
    ewma.update(0.0, 0.0, dt_ms=ref)     # snap to 0
    ewma.update(1.0, 1.0, dt_ms=ref)     # one step at nominal cadence
    v, e = ewma.value
    assert v == pytest.approx(alpha)
    assert e == pytest.approx(alpha)


def test_tau_from_alpha_edge_values():
    assert tau_from_alpha(1.0, 1000) == 0.0            # always snap
    assert tau_from_alpha(0.0, 1000) == float("inf")   # never decays
    assert tau_from_alpha(0.5, 1000) > 0


def test_1h_decays_faster_than_4h():
    """1h alpha > 4h alpha ⇒ the 1h time constant is SHORTER than the 4h one."""
    import synaesthesia
    ref = 180_000
    tau1 = tau_from_alpha(synaesthesia.ewma_alpha("1h"), ref)
    tau4 = tau_from_alpha(synaesthesia.ewma_alpha("4h"), ref)
    assert tau1 < tau4
