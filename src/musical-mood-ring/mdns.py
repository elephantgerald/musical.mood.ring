# mdns.py
#
# mDNS advertisement for musical-mood-ring.
#
# Advertises the device as <hostname>.local on the local network, giving a
# stable Spotify OAuth redirect URI (http://musical-mood-ring.local/callback)
# regardless of DHCP-assigned IP.
#
# On CPython (tests) the network.mDNS binding is absent; functions no-op.

try:
    import network as _network
    _HW = True
except ImportError:
    _network = None
    _HW = False


def start(hostname="musical-mood-ring"):
    """Advertise <hostname>.local via mDNS."""
    if not _HW:
        return
    try:
        mdns = _network.mDNS()
        mdns.start(hostname, "musical-mood-ring")
    except Exception:
        pass  # mDNS may not be available on all firmware builds


def stop():
    """Stop mDNS advertisement."""
    if not _HW:
        return
    try:
        mdns = _network.mDNS()
        mdns.stop()
    except Exception:
        pass
