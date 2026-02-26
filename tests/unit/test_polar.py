import math
import pytest
from polar import to_polar


def test_neutral_centre():
    r, _ = to_polar(0.5, 0.5)
    assert r == pytest.approx(0.0, abs=1e-9)


def test_due_east():
    # valence=1.0, energy=0.5 → θ=0°, r=0.5
    r, theta = to_polar(1.0, 0.5)
    assert r     == pytest.approx(0.5,  abs=1e-9)
    assert theta == pytest.approx(0.0,  abs=1e-9)


def test_due_north():
    # valence=0.5, energy=1.0 → θ=90°, r=0.5
    r, theta = to_polar(0.5, 1.0)
    assert r     == pytest.approx(0.5,  abs=1e-9)
    assert theta == pytest.approx(90.0, abs=1e-9)


def test_due_west():
    # valence=0.0, energy=0.5 → θ=180°, r=0.5
    r, theta = to_polar(0.0, 0.5)
    assert r     == pytest.approx(0.5,   abs=1e-9)
    assert theta == pytest.approx(180.0, abs=1e-9)


def test_due_south():
    # valence=0.5, energy=0.0 → θ=270°, r=0.5
    r, theta = to_polar(0.5, 0.0)
    assert r     == pytest.approx(0.5,   abs=1e-9)
    assert theta == pytest.approx(270.0, abs=1e-9)


def test_northeast_corner():
    r, theta = to_polar(1.0, 1.0)
    assert r     == pytest.approx(math.sqrt(0.5), abs=1e-9)
    assert theta == pytest.approx(45.0,            abs=1e-9)


def test_southwest_corner():
    r, theta = to_polar(0.0, 0.0)
    assert r     == pytest.approx(math.sqrt(0.5), abs=1e-9)
    assert theta == pytest.approx(225.0,           abs=1e-9)


def test_theta_always_in_range():
    """θ must be in [0, 360) for every grid point."""
    for vi in range(5):
        for ei in range(5):
            _, theta = to_polar(vi / 4, ei / 4)
            assert 0.0 <= theta < 360.0


def test_r_nonnegative():
    for vi in range(5):
        for ei in range(5):
            r, _ = to_polar(vi / 4, ei / 4)
            assert r >= 0.0
