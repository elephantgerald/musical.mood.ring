#!/usr/bin/env python3
"""
bottle.py

Reads the derived (valence, energy) JSON store from data/musical-affective-memory/
and compiles it into a versioned, sorted binary bundle at:

    data/musical-memory-bundle/memory-bundle-v{VERSION}-{YYYYMMDD_HHMMSS}.bin

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
    python bottle.py [--out DIR]

TODO: implement once musical-distiller outputs data/musical-affective-memory/*.json
"""

# Stub — to be implemented after musical-distiller outputs JSON affective memory.
print("musical-bottler: not yet implemented")
