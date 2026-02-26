# mmar.py
#
# MMAR binary bundle lookup for musical-mood-ring.
#
# Reads the MMAR bundle (written by musical-bottler) and provides a binary-search
# lookup: Spotify track ID → (valence, energy).
#
# Pure Python — no hardware dependencies. Works identically in CPython and
# MicroPython. The struct module is present in both environments.

import struct

HEADER_SIZE = 16
RECORD_SIZE = 10
MAGIC       = b"MMAR"


def fnv1a_64(s):
    """FNV-1a 64-bit hash of an ASCII string. Identical in CPython and MicroPython."""
    h = 14695981039346656037   # FNV offset basis
    for b in s.encode("ascii"):
        h ^= b
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF  # FNV prime, masked to 64 bits
    return h


class MMARBundle:
    """
    Wraps an MMAR bundle (bytes) and exposes a binary-search lookup.

    Construct from a bytes object — the caller is responsible for loading it
    from flash (on the ESP32) or from a file (in tests).
    """

    def __init__(self, data):
        if data[:4] != MAGIC:
            raise ValueError("not a valid MMAR bundle")
        self._version = data[4]
        self._count   = struct.unpack_from("<I", data, 8)[0]
        self._data    = data

    @property
    def count(self):
        return self._count

    def lookup(self, track_id):
        """
        Binary search for track_id.
        Returns (valence, energy) as floats in [0, 1], or None if not found.
        """
        target = fnv1a_64(track_id)
        lo, hi = 0, self._count - 1
        while lo <= hi:
            mid    = (lo + hi) >> 1
            offset = HEADER_SIZE + mid * RECORD_SIZE
            h      = struct.unpack_from("<Q", self._data, offset)[0]
            if h == target:
                v_u8, e_u8 = struct.unpack_from("<BB", self._data, offset + 8)
                return v_u8 / 255.0, e_u8 / 255.0
            elif h < target:
                lo = mid + 1
            else:
                hi = mid - 1
        return None


def load(path):
    """Load an MMAR bundle from a file path. Returns MMARBundle."""
    with open(path, "rb") as f:
        return MMARBundle(f.read())
