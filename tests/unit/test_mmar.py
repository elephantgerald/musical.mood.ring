import pytest
from conftest import build_bundle
from mmar import MMARBundle, fnv1a_64


# ── fnv1a_64 ───────────────────────────────────────────────────────────────

def test_fnv1a_empty_string():
    # Empty string → FNV offset basis (no bytes processed)
    assert fnv1a_64("") == 14695981039346656037


def test_fnv1a_deterministic():
    tid = "4iV5W9qcyo6meDRnEzqTQ4"   # typical Spotify track ID format
    assert fnv1a_64(tid) == fnv1a_64(tid)


def test_fnv1a_distinct():
    assert fnv1a_64("a") != fnv1a_64("b")
    assert fnv1a_64("abc") != fnv1a_64("cba")


def test_fnv1a_well_known():
    # FNV-1a 64-bit for "foobar" — published test vector
    assert fnv1a_64("foobar") == 0x85944171f73967e8


# ── MMARBundle construction ────────────────────────────────────────────────

def test_bad_magic_raises():
    with pytest.raises(ValueError):
        MMARBundle(b"XXXX" + b"\x00" * 12)


def test_count_empty():
    data = build_bundle()
    assert MMARBundle(data).count == 0


def test_count_matches_entries():
    data = build_bundle(("a", 0.1, 0.9), ("b", 0.5, 0.5), ("c", 0.8, 0.2))
    assert MMARBundle(data).count == 3


# ── Lookup ─────────────────────────────────────────────────────────────────

def test_lookup_hit_single():
    data   = build_bundle(("abc123", 0.3, 0.7))
    bundle = MMARBundle(data)
    v, e   = bundle.lookup("abc123")
    assert abs(v - 0.3) < 0.005
    assert abs(e - 0.7) < 0.005


def test_lookup_miss():
    data = build_bundle(("abc123", 0.3, 0.7))
    assert MMARBundle(data).lookup("notinbundle") is None


def test_lookup_empty_bundle():
    data = build_bundle()
    assert MMARBundle(data).lookup("anything") is None


def test_lookup_all_entries():
    entries = [("x", 0.1, 0.9), ("y", 0.5, 0.5), ("z", 0.8, 0.2)]
    data    = build_bundle(*entries)
    bundle  = MMARBundle(data)
    for tid, v, e in entries:
        result = bundle.lookup(tid)
        assert result is not None, f"expected hit for {tid!r}"
        assert abs(result[0] - v) < 0.005
        assert abs(result[1] - e) < 0.005


def test_lookup_extremes():
    data   = build_bundle(("min", 0.0, 0.0), ("max", 1.0, 1.0))
    bundle = MMARBundle(data)
    v, e   = bundle.lookup("min")
    assert abs(v) < 0.005 and abs(e) < 0.005
    v, e = bundle.lookup("max")
    assert abs(v - 1.0) < 0.005 and abs(e - 1.0) < 0.005


def test_lookup_large_bundle():
    # Regression: binary search must work at scale
    entries = [(str(i), i / 999, 1 - i / 999) for i in range(1000)]
    data    = build_bundle(*entries)
    bundle  = MMARBundle(data)
    assert bundle.count == 1000
    assert bundle.lookup("0") is not None
    assert bundle.lookup("999") is not None
    assert bundle.lookup("500") is not None
    assert bundle.lookup("nothere") is None
