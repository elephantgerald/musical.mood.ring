# wifi.py
#
# WiFi management for musical-mood-ring.
#
# Handles initial connection and reconnection on the ESP32.
# On CPython (tests/PC) the network module is absent; functions return safe
# defaults so callers need no special-casing.

try:
    import network as _network
    import utime   as _utime
    _HW = True
except ImportError:
    _network = None
    _utime   = None
    _HW      = False


def connect(ssid, password, timeout_ms=15000):
    """
    Connect to a WPA2 WiFi network. Blocks until connected or timeout.
    Returns True on success, False on timeout.
    """
    if not _HW:
        return True   # assume connected in non-hardware environments

    sta = _network.WLAN(_network.STA_IF)
    sta.active(True)
    if sta.isconnected():
        return True

    sta.connect(ssid, password)
    deadline = _utime.ticks_ms() + timeout_ms
    while not sta.isconnected():
        if _utime.ticks_diff(deadline, _utime.ticks_ms()) <= 0:
            return False
        _utime.sleep_ms(100)
    return True


def is_connected():
    """Return True if the station interface is currently connected."""
    if not _HW:
        return True
    sta = _network.WLAN(_network.STA_IF)
    return sta.active() and sta.isconnected()
