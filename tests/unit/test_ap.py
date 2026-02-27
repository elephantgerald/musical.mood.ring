import ap


def test_allow_configure_no_error():
    """CPython no-op path — must not raise."""
    ap.allow_configure()


def test_allow_configure_custom_ssid_no_error():
    ap.allow_configure(ssid="test-ap", max_clients=1)


def test_disallow_configure_no_error():
    """CPython no-op path — must not raise."""
    ap.disallow_configure()


def test_hw_flag_false_in_cpython():
    assert ap._HW is False
