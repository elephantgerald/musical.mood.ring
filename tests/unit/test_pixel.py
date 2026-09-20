import pixel


def test_to_duty_endpoints_are_fixed():
    """Black and full scale must survive the transfer function exactly."""
    assert pixel.to_duty((0, 0, 0)) == (0, 0, 0)
    assert pixel.to_duty((255, 255, 255)) == (255, 255, 255)


def test_to_duty_is_monotonic():
    prev = -1
    for c in range(256):
        duty = pixel.to_duty((c, 0, 0))[0]
        assert duty >= prev, "duty fell at input {}".format(c)
        prev = duty


def test_to_duty_darkens_midtones():
    """sRGB 50% grey is ~21% of full light, not 50%.

    This is the whole reason the table exists: handing the strip the sRGB byte
    directly over-brightens every mid-tone and washes the palette pale.
    """
    duty = pixel.to_duty((128, 128, 128))[0]
    assert 50 <= duty <= 60


def test_to_duty_clamps_out_of_range():
    assert pixel.to_duty((-10, 300, 128))[:2] == (0, 255)


def test_to_duty_returns_three_ints():
    duty = pixel.to_duty((10, 20, 30))
    assert len(duty) == 3
    for ch in duty:
        assert isinstance(ch, int)
        assert 0 <= ch <= 255


def test_to_duty_preserves_channel_order():
    """A colour must not come back with its channels transposed."""
    r, g, b = pixel.to_duty((255, 128, 0))
    assert r == 255
    assert 0 < g < 255
    assert b == 0


def test_gamma_table_is_full_width():
    assert len(pixel._GAMMA) == 256


def test_write_and_off_are_safe_without_hardware():
    """CPython has no neopixel module; both calls must no-op rather than raise."""
    assert pixel._HW is False
    pixel.write([(10, 20, 30)] * 3)
    pixel.off()
