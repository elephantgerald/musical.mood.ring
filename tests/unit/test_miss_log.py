import pytest
import miss_log


@pytest.fixture(autouse=True)
def _tmp_path(tmp_path, monkeypatch):
    monkeypatch.setattr(miss_log, "_PATH", str(tmp_path / "misses.txt"))


# ── Basic round-trip ────────────────────────────────────────────────────────

def test_append_and_all():
    miss_log.append("track001")
    miss_log.append("track002")
    assert miss_log.all() == ["track001", "track002"]


def test_all_on_missing_file_returns_empty():
    assert miss_log.all() == []


def test_clear_empties_log():
    miss_log.append("track001")
    miss_log.clear()
    assert miss_log.all() == []


def test_clear_on_missing_file_does_not_raise():
    miss_log.clear()   # no file yet — should not raise


# ── Capacity cap ────────────────────────────────────────────────────────────

def test_capacity_cap_keeps_last_n(monkeypatch):
    monkeypatch.setattr(miss_log, "_CAPACITY", 5)
    for i in range(8):
        miss_log.append(f"t{i}")
    result = miss_log.all()
    assert len(result) == 5
    assert result == [f"t{i}" for i in range(3, 8)]  # last 5


def test_capacity_not_exceeded_on_single_append(monkeypatch):
    monkeypatch.setattr(miss_log, "_CAPACITY", 3)
    for i in range(10):
        miss_log.append(f"id{i}")
    assert len(miss_log.all()) == 3


# ── Content integrity ────────────────────────────────────────────────────────

def test_spotify_ids_round_trip():
    """22-char Spotify-style IDs survive a write/read cycle."""
    ids = ["4iV5W9uYEdYUVa79Axb7Rh", "1301WleyT98MSxVHPZCA6M"]
    for tid in ids:
        miss_log.append(tid)
    assert miss_log.all() == ids


def test_blank_lines_not_included():
    """Blank lines in the file must not appear in all()."""
    miss_log.append("t1")
    miss_log.append("t2")
    result = miss_log.all()
    assert all(r.strip() == r and r for r in result)
