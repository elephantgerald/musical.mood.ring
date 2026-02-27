# ap.py
#
# WiFi Access Point management for musical-mood-ring.
#
# On first boot (no config.json), the ESP32 brings up a WiFi AP so the user
# can connect and configure credentials via the config web server.
#
# On CPython (tests) the network module is absent; both functions silently no-op.

try:
    import network as _network
    _HW = True
except ImportError:
    _network = None
    _HW = False


def allow_configure(ssid="musical.mood.ring", max_clients=3):
    """Bring up the WiFi access point so the config server is reachable."""
    if not _HW:
        return
    ap = _network.WLAN(_network.AP_IF)
    ap.config(essid=ssid, max_clients=max_clients)
    ap.active(True)


def disallow_configure():
    """Shut down the access point."""
    if not _HW:
        return
    ap = _network.WLAN(_network.AP_IF)
    ap.active(False)
