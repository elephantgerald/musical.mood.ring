#!/usr/bin/env python3
"""
distill.py

Reads all training tracks from data/musical-gestalt/, maps each to a
(valence, energy) pair, and writes a compact sorted binary lookup file
to data/musical-affective-memory/affective_memory.mmar.

Mapping priority per track:
  1. AcousticBrainz mood features  → weighted formula from mapping.toml
  2. Zone label                    → anchor (V, E) from mapping.toml
  3. No usable data                → excluded from output

The binary format is designed for binary search on the ESP32 with minimal
RAM usage (seeks into the file, never loads it fully).

Binary format — affective_memory.mmar:
  HEADER  (16 bytes):
    [4]  magic    b"MMAR"
    [1]  version  0x01
    [3]  reserved 0x000000
    [4]  count    uint32 little-endian  (number of records)
    [4]  reserved 0x00000000

  RECORDS (10 bytes each, sorted ascending by hash):
    [8]  hash     uint64 LE  FNV-1a 64-bit of Spotify track ID (ASCII)
    [1]  valence  uint8      0 → 0.0, 255 → 1.0
    [1]  energy   uint8      0 → 0.0, 255 → 1.0

Usage:
    python distill.py [--mapping PATH] [--out PATH] [--split training|test|all]
"""

import argparse
import json
import struct
import tomllib
from pathlib import Path


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


HEADER_SIZE  = 16
RECORD_SIZE  = 10
MAGIC        = b"MMAR"
VERSION      = 0x01


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
# (valence, energy) derivation
# ---------------------------------------------------------------------------

def from_acousticbrainz(ab: dict, cfg: dict) -> tuple[float, float]:
    """Derive (valence, energy) from raw AcousticBrainz features using mapping.toml weights."""
    vc = cfg["valence"]
    ec = cfg["energy"]

    def weighted(weights: dict, features: dict) -> float:
        total = weights.get("bias", 0.0)
        for key, w in weights.items():
            if key in ("bias", "bpm_scale"):
                continue
            total += w * (features.get(key) or 0.0)
        if "bpm_scale" in weights:
            total += weights["bpm_scale"] * (features.get("bpm") or 0.0)
        return max(0.0, min(1.0, total))

    return weighted(vc, ab), weighted(ec, ab)


def from_zone(zone: str, anchors: dict) -> tuple[float, float] | None:
    """Look up zone anchor (valence, energy). Returns None if zone unknown."""
    pair = anchors.get(zone)
    if pair is None:
        return None
    return float(pair[0]), float(pair[1])


# ---------------------------------------------------------------------------
# Gestalt loader
# ---------------------------------------------------------------------------

def load_tracks(gestalt_dir: Path, split_filter: str, anchors: dict, cfg: dict) -> list[tuple[int, int, int]]:
    """
    Load all eligible tracks from gestalt JSON files.
    Returns list of (hash, valence_u8, energy_u8) tuples.
    """
    records: list[tuple[int, int, int]] = []
    stats = {"ab": 0, "zone": 0, "skipped": 0}

    for path in sorted(gestalt_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        zone  = data.get("zone")
        split = data.get("split", "training")

        if split_filter != "all" and split != split_filter:
            continue
        if split == "skip":
            continue

        for tid in data.get("track_ids", []):
            entry = data.get("metadata", {}).get(tid, {})
            if entry.get("error"):
                stats["skipped"] += 1
                continue

            ab = entry.get("acousticbrainz")
            if ab:
                v, e = from_acousticbrainz(ab, cfg)
                stats["ab"] += 1
            elif zone:
                result = from_zone(zone, anchors)
                if result is None:
                    stats["skipped"] += 1
                    continue
                v, e = result
                stats["zone"] += 1
            else:
                stats["skipped"] += 1
                continue

            h = fnv1a_64(tid)
            records.append((h, round(v * 255), round(e * 255)))

    return records, stats


# ---------------------------------------------------------------------------
# Binary writer
# ---------------------------------------------------------------------------

def write_mmar(path: Path, records: list[tuple[int, int, int]]) -> None:
    """Write sorted binary MMAR file."""
    records.sort(key=lambda r: r[0])

    with open(path, "wb") as f:
        # Header
        f.write(MAGIC)
        f.write(struct.pack("<B", VERSION))
        f.write(b"\x00\x00\x00")                   # reserved
        f.write(struct.pack("<I", len(records)))    # count
        f.write(b"\x00\x00\x00\x00")               # reserved

        # Records
        for h, v, e in records:
            f.write(struct.pack("<Q", h))
            f.write(struct.pack("<BB", v, e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Distill gestalt features into a binary ESP32 lookup file."
    )
    parser.add_argument(
        "--mapping", metavar="PATH",
        default=str(Path(__file__).parent / "mapping.toml"),
        help="Path to mapping.toml (default: mapping.toml alongside this script)"
    )
    parser.add_argument(
        "--out", metavar="PATH",
        default=None,
        help="Output path (default: data/musical-affective-memory/affective_memory.mmar)"
    )
    parser.add_argument(
        "--split", choices=["training", "test", "all"], default="training",
        help="Which gestalt split to include (default: training)"
    )
    args = parser.parse_args()

    root = project_root()
    gestalt_dir = root / "data" / "musical-gestalt"
    out_path = Path(args.out) if args.out else root / "data" / "musical-affective-memory" / "affective_memory.mmar"

    if not gestalt_dir.exists():
        print("No data/musical-gestalt/ directory found.")
        return

    with open(args.mapping, "rb") as f:
        cfg = tomllib.load(f)

    anchors = cfg.get("zone_anchors", {})

    print("musical-distillery — Distill")
    print("─" * 40)
    print(f"  gestalt : {gestalt_dir}")
    print(f"  output  : {out_path}")
    print(f"  split   : {args.split}")
    print()

    records, stats = load_tracks(gestalt_dir, args.split, anchors, cfg)

    print(f"  {stats['ab']:>4} tracks from AcousticBrainz features")
    print(f"  {stats['zone']:>4} tracks from zone anchor fallback")
    print(f"  {stats['skipped']:>4} tracks skipped (no usable data)")
    print(f"  {len(records):>4} total records")
    print()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_mmar(out_path, records)

    size_kb = out_path.stat().st_size / 1024
    print(f"  ✓ Written to {out_path}")
    print(f"    {len(records)} records × {RECORD_SIZE} bytes = {size_kb:.1f} KB")
    print()


if __name__ == "__main__":
    main()
