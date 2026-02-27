#!/usr/bin/env python3
"""
bottle.py

Compiles two versioned MMAR binary bundles from pipeline data:

  memory-bundle-v{N}-{TS}.bin  — track-level lookup (precise)
    Input:  data/musical-affective-memory/*.json
    Key:    FNV-1a 64-bit hash of Spotify track ID

  artist-bundle-v{N}-{TS}.bin  — artist-level lookup (approximate)
    Input:  data/musical-affective-memory/ + data/musical-gestalt/ (for artist_id)
    Key:    FNV-1a 64-bit hash of Spotify artist ID
    Value:  mean (valence, energy) across all tracks by that artist in the
            affective memory. Requires fetch_artist_ids.py to have been run.

Both are written to data/musical-memory-bundle/.

Binary format — MMAR (Musical Mood Affective Record):
  HEADER (16 bytes):
    [4]  magic    b"MMAR"
    [1]  version  0x01
    [3]  reserved 0x000000
    [4]  count    uint32 little-endian
    [4]  reserved 0x00000000

  RECORDS (10 bytes each, sorted ascending by hash):
    [8]  hash     uint64 LE
    [1]  valence  uint8      0 → 0.0, 255 → 1.0
    [1]  energy   uint8      0 → 0.0, 255 → 1.0

Usage:
    python bottle.py [--in DIR] [--gestalt DIR] [--out DIR]
"""

import argparse
import json
import struct
from datetime import datetime, timezone
from pathlib import Path


HEADER_SIZE = 16
RECORD_SIZE = 10
MAGIC       = b"MMAR"
VERSION     = 0x01
BUNDLE_VER  = 1  # increment when the MMAR format changes


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Hash
# ---------------------------------------------------------------------------

def fnv1a_64(s: str) -> int:
    """
    FNV-1a 64-bit hash of an ASCII string.
    Identical implementation works in both CPython and MicroPython —
    no external dependencies, deterministic across platforms.
    """
    h = 14695981039346656037  # FNV offset basis
    for b in s.encode("ascii"):
        h ^= b
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF  # FNV prime, masked to 64 bits
    return h


# ---------------------------------------------------------------------------
# Load + write
# ---------------------------------------------------------------------------

def load_records(in_dir: Path) -> list[tuple[int, int, int]]:
    """
    Read all affective-memory JSONs and return (hash, valence_u8, energy_u8) tuples.
    Deduplicates by hash (first occurrence wins).
    """
    seen: set[int] = set()
    records: list[tuple[int, int, int]] = []

    for path in sorted(in_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for tid, entry in data.items():
            h = fnv1a_64(tid)
            if h in seen:
                continue
            seen.add(h)
            v_u8 = round(entry["valence"] * 255)
            e_u8 = round(entry["energy"]  * 255)
            records.append((h, v_u8, e_u8))

    return records


def write_mmar(path: Path, records: list[tuple[int, int, int]]) -> None:
    """Write sorted MMAR binary bundle."""
    records.sort(key=lambda r: r[0])

    with open(path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<B", VERSION))
        f.write(b"\x00\x00\x00")                 # reserved
        f.write(struct.pack("<I", len(records)))  # count
        f.write(b"\x00\x00\x00\x00")             # reserved

        for h, v, e in records:
            f.write(struct.pack("<Q", h))
            f.write(struct.pack("<BB", v, e))


# ---------------------------------------------------------------------------
# Artist bundle
# ---------------------------------------------------------------------------

def load_artist_records(
    gestalt_dir: Path,
    affective_dir: Path,
) -> list[tuple[int, int, int]]:
    """
    Build artist-level MMAR records by averaging (valence, energy) across all
    tracks in the affective memory that belong to each artist.

    Requires gestalt JSONs to have been enriched with `artist_id` fields
    (run src/musical-cultivator/scripts/fetch_artist_ids.py first).

    Returns (hash, valence_u8, energy_u8) tuples, one per unique artist_id.
    Artists with no tracks in the affective memory are skipped.
    """
    # Build track_id → artist_id map from gestalt JSONs
    track_to_artist: dict[str, str] = {}
    for path in sorted(gestalt_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for tid, meta in data.get("metadata", {}).items():
            aid = meta.get("artist_id")
            if aid:
                track_to_artist[tid] = aid

    if not track_to_artist:
        return []

    # Accumulate (valence, energy) sums per artist from affective memory
    artist_sums: dict[str, list] = {}   # artist_id → [v_sum, e_sum, count]
    for path in sorted(affective_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for tid, entry in data.items():
            aid = track_to_artist.get(tid)
            if not aid:
                continue
            if aid not in artist_sums:
                artist_sums[aid] = [0.0, 0.0, 0]
            artist_sums[aid][0] += entry["valence"]
            artist_sums[aid][1] += entry["energy"]
            artist_sums[aid][2] += 1

    seen: set[int] = set()
    records: list[tuple[int, int, int]] = []
    for aid, (v_sum, e_sum, count) in artist_sums.items():
        h = fnv1a_64(aid)
        if h in seen:
            continue
        seen.add(h)
        v_u8 = round((v_sum / count) * 255)
        e_u8 = round((e_sum / count) * 255)
        records.append((h, v_u8, e_u8))

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compile track and artist MMAR bundles from affective-memory data."
    )
    parser.add_argument(
        "--in", metavar="DIR", dest="in_dir", default=None,
        help="Affective-memory directory (default: data/musical-affective-memory/)"
    )
    parser.add_argument(
        "--gestalt", metavar="DIR", default=None,
        help="Gestalt directory for artist_id lookup (default: data/musical-gestalt/)"
    )
    parser.add_argument(
        "--out", metavar="DIR", default=None,
        help="Output directory (default: data/musical-memory-bundle/)"
    )
    args = parser.parse_args()

    root         = project_root()
    in_dir       = Path(args.in_dir)   if args.in_dir   else root / "data" / "musical-affective-memory"
    gestalt_dir  = Path(args.gestalt)  if args.gestalt  else root / "data" / "musical-gestalt"
    out_dir      = Path(args.out)      if args.out      else root / "data" / "musical-memory-bundle"

    if not in_dir.exists():
        print(f"No affective-memory directory found at {in_dir}")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("musical-bottler — Bottle")
    print("─" * 40)

    # ── Track bundle ──────────────────────────────────────────────────────────
    track_name = f"memory-bundle-v{BUNDLE_VER}-{timestamp}.bin"
    track_path = out_dir / track_name
    print(f"  track input  : {in_dir}")
    print(f"  track output : {track_path}")

    track_records = load_records(in_dir)
    if not track_records:
        print("  No track records found — run musical-distiller first.")
        return

    write_mmar(track_path, track_records)
    size_kb = track_path.stat().st_size / 1024
    print(f"  {len(track_records)} records × {RECORD_SIZE} B + {HEADER_SIZE} B header = {size_kb:.1f} KB")
    print(f"  ✓ {track_name}")
    print()

    # ── Artist bundle ─────────────────────────────────────────────────────────
    artist_name = f"artist-bundle-v{BUNDLE_VER}-{timestamp}.bin"
    artist_path = out_dir / artist_name
    print(f"  artist input : {gestalt_dir}")
    print(f"  artist output: {artist_path}")

    if not gestalt_dir.exists():
        print("  Gestalt directory not found — skipping artist bundle.")
        print("  Run fetch_artist_ids.py first to backfill artist_id fields.")
        return

    artist_records = load_artist_records(gestalt_dir, in_dir)
    if not artist_records:
        print("  No artist records found — run fetch_artist_ids.py to add artist_id fields.")
        return

    write_mmar(artist_path, artist_records)
    size_kb = artist_path.stat().st_size / 1024
    print(f"  {len(artist_records)} records × {RECORD_SIZE} B + {HEADER_SIZE} B header = {size_kb:.1f} KB")
    print(f"  ✓ {artist_name}")
    print()


if __name__ == "__main__":
    main()
