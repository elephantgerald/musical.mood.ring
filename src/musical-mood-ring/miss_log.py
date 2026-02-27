# miss_log.py
#
# Rolling log of Spotify track IDs that didn't get a precise track-bundle hit.
# Covers both artist-bundle hits (approximate answer) and full misses (no answer).
#
# The file acts as a feedback queue: pull it via GET /misses and feed the IDs
# back into the cultivator pipeline to build a richer track bundle over time.
#
# Format: one Spotify track ID per line (~23 KB at capacity).
# Pure Python — no hardware dependencies.

try:
    import ujson as _json   # noqa: F401 (unused — kept for symmetry with other modules)
except ImportError:
    pass

_PATH     = "misses.txt"
_CAPACITY = 1000


def append(track_id):
    """Add track_id to the log. Trims to the last _CAPACITY entries."""
    existing = _read()
    existing.append(track_id)
    if len(existing) > _CAPACITY:
        existing = existing[-_CAPACITY:]
    _write(existing)


def all():
    """Return all logged track IDs. Returns [] if the file is absent."""
    return _read()


def clear():
    """Wipe the log file."""
    _write([])


def _read():
    try:
        with open(_PATH) as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


def _write(ids):
    with open(_PATH, "w") as f:
        for tid in ids:
            f.write(tid + "\n")
