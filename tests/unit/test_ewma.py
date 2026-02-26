import pytest
from ewma import EWMA


def test_neutral_before_first_update():
    ewma = EWMA(alpha=0.1)
    v, e = ewma.value
    assert v == pytest.approx(0.5)
    assert e == pytest.approx(0.5)


def test_first_update_snaps_not_blends():
    """First update should snap directly to the observed value, not blend from neutral."""
    ewma = EWMA(alpha=0.1)
    ewma.update(0.8, 0.2)
    v, e = ewma.value
    assert v == pytest.approx(0.8)
    assert e == pytest.approx(0.2)


def test_second_update_blends():
    ewma = EWMA(alpha=0.5)
    ewma.update(1.0, 0.0)   # snap
    ewma.update(0.0, 1.0)   # blend: 0.5*0 + 0.5*1 = 0.5
    v, e = ewma.value
    assert v == pytest.approx(0.5)
    assert e == pytest.approx(0.5)


def test_convergence():
    """Many updates of the same value should converge to that value."""
    ewma = EWMA(alpha=0.3)
    for _ in range(200):
        ewma.update(0.9, 0.1)
    v, e = ewma.value
    assert v == pytest.approx(0.9, abs=1e-3)
    assert e == pytest.approx(0.1, abs=1e-3)


def test_alpha_1_always_snaps():
    """alpha=1.0 means EWMA always equals the most recent observation."""
    ewma = EWMA(alpha=1.0)
    ewma.update(0.3, 0.7)
    ewma.update(0.9, 0.1)
    v, e = ewma.value
    assert v == pytest.approx(0.9)
    assert e == pytest.approx(0.1)


def test_slow_alpha_retains_history():
    """Very low alpha: one new observation barely moves the estimate."""
    ewma = EWMA(alpha=0.01)
    ewma.update(0.5, 0.5)   # seed
    ewma.update(1.0, 1.0)   # one update — should barely move
    v, e = ewma.value
    assert v == pytest.approx(0.5, abs=0.02)
    assert e == pytest.approx(0.5, abs=0.02)


def test_reset_returns_to_neutral():
    ewma = EWMA(alpha=0.5)
    ewma.update(1.0, 1.0)
    ewma.reset()
    v, e = ewma.value
    assert v == pytest.approx(0.5)
    assert e == pytest.approx(0.5)


def test_reset_then_snap():
    """After reset the next update should snap again, not blend from neutral."""
    ewma = EWMA(alpha=0.1)
    ewma.update(0.9, 0.9)
    ewma.reset()
    ewma.update(0.2, 0.3)
    v, e = ewma.value
    assert v == pytest.approx(0.2)
    assert e == pytest.approx(0.3)


def test_1h_decays_faster_than_4h():
    """The 1h alpha from the synaesthesia profile should be larger than the 4h alpha."""
    import synaesthesia
    a1 = synaesthesia.ewma_alpha("1h")
    a4 = synaesthesia.ewma_alpha("4h")
    assert a1 > a4
