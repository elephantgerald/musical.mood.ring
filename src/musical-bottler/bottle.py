#!/usr/bin/env python3
"""
bottle.py

Reads the derived (valence, energy) JSON store from data/musical-affective-memory/
and compiles it into a versioned, sorted binary bundle at:

    data/musical-memory-bundle/memory-bundle-v{BUNDLE_VER}-{YYYYMMDD_HHMMSS}.bin

Binary format — MMAR (Musical Mood Affective Record):
  HEADER (16 bytes):
    [4]  magic    b"MMAR"
    [1]  version  0x01
    [3]  reserved 0x000000
    [4]  count    uint32 little-endian
    [4]  reserved 0x00000000

  RECORDS (10 bytes each, sorted ascending by hash):
    [8]  hash     uint64 LE  FNV-1a 64-bit of Spotify track ID (ASCII)
    [1]  valence  uint8      0 → 0.0, 255 → 1.0
    [1]  energy   uint8      0 → 0.0, 255 → 1.0

Usage:
    python bottle.py [--in DIR] [--out DIR]
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
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Bottle affective-memory JSONs into a versioned MMAR binary bundle."
    )
    parser.add_argument(
        "--in", metavar="DIR", dest="in_dir", default=None,
        help="Input directory (default: data/musical-affective-memory/)"
    )
    parser.add_argument(
        "--out", metavar="DIR", default=None,
        help="Output directory (default: data/musical-memory-bundle/)"
    )
    args = parser.parse_args()

    root    = project_root()
    in_dir  = Path(args.in_dir) if args.in_dir else root / "data" / "musical-affective-memory"
    out_dir = Path(args.out)    if args.out    else root / "data" / "musical-memory-bundle"

    if not in_dir.exists():
        print(f"No affective-memory directory found at {in_dir}")
        return

    timestamp   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle_name = f"memory-bundle-v{BUNDLE_VER}-{timestamp}.bin"
    out_path    = out_dir / bundle_name

    print("musical-bottler — Bottle")
    print("─" * 40)
    print(f"  input   : {in_dir}")
    print(f"  output  : {out_path}")
    print()

    records = load_records(in_dir)

    if not records:
        print("  No records found — run musical-distiller first.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    write_mmar(out_path, records)

    size_kb = out_path.stat().st_size / 1024
    print(f"  {len(records)} records × {RECORD_SIZE} B + {HEADER_SIZE} B header = {size_kb:.1f} KB")
    print(f"  ✓ {bundle_name}")
    print()


if __name__ == "__main__":
    main()
