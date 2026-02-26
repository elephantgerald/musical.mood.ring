"""
Unit test configuration for musical-mood-ring.

Adds src/musical-mood-ring to sys.path so all firmware modules import
cleanly in CPython without any install step.
"""
import struct
import sys
from pathlib import Path

import pytest

# Make firmware modules importable from CPython
_FIRMWARE = Path(__file__).parent.parent.parent / "src" / "musical-mood-ring"
if str(_FIRMWARE) not in sys.path:
    sys.path.insert(0, str(_FIRMWARE))

# ── Shared helpers ─────────────────────────────────────────────────────────

from mmar import fnv1a_64, MAGIC, HEADER_SIZE, RECORD_SIZE


def build_bundle(*entries):
    """
    Build an in-memory MMAR bundle from (track_id, valence, energy) tuples.
    Returns a bytes object suitable for passing to MMARBundle().
    """
    records = []
    for tid, v, e in entries:
        h    = fnv1a_64(tid)
        v_u8 = round(v * 255)
        e_u8 = round(e * 255)
        records.append((h, v_u8, e_u8))
    records.sort(key=lambda r: r[0])

    buf = bytearray()
    buf += MAGIC
    buf += struct.pack("<B", 0x01)           # version
    buf += b"\x00\x00\x00"                   # reserved
    buf += struct.pack("<I", len(records))   # count
    buf += b"\x00\x00\x00\x00"              # reserved
    for h, v_u8, e_u8 in records:
        buf += struct.pack("<Q", h)
        buf += struct.pack("<BB", v_u8, e_u8)
    return bytes(buf)


@pytest.fixture
def make_bundle():
    """Pytest fixture returning the build_bundle helper."""
    return build_bundle
