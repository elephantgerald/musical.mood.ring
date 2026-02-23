#!/usr/bin/env python3
"""
distill.py

Reads all training tracks from data/musical-gestalt/, derives (valence, energy)
for each track, and writes one JSON file per gestalt source to
data/musical-affective-memory/.

Output format — one file per gestalt JSON, same base name:
  {
    "<spotify_track_id>": {
      "valence": <float 0.0–1.0>,
      "energy":  <float 0.0–1.0>,
      "source":  "ab" | "zone"
    },
    ...
  }

Mapping priority per track:
  1. AcousticBrainz mood features  → weighted formula from mapping.toml
  2. Zone label                    → anchor (V, E) from mapping.toml
  3. No usable data                → excluded from output

Usage:
    python distill.py [--mapping PATH] [--out DIR] [--split training|test|all]
"""

import argparse
import json
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
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Distill gestalt features into per-track (valence, energy) JSON."
    )
    parser.add_argument(
        "--mapping", metavar="PATH",
        default=str(Path(__file__).parent / "mapping.toml"),
        help="Path to mapping.toml (default: alongside this script)"
    )
    parser.add_argument(
        "--out", metavar="DIR",
        default=None,
        help="Output directory (default: data/musical-affective-memory/)"
    )
    parser.add_argument(
        "--split", choices=["training", "test", "all"], default="training",
        help="Which gestalt split to include (default: training)"
    )
    args = parser.parse_args()

    root = project_root()
    gestalt_dir = root / "data" / "musical-gestalt"
    out_dir = Path(args.out) if args.out else root / "data" / "musical-affective-memory"

    if not gestalt_dir.exists():
        print("No data/musical-gestalt/ directory found.")
        return

    with open(args.mapping, "rb") as f:
        cfg = tomllib.load(f)

    anchors = cfg.get("zone_anchors", {})
    out_dir.mkdir(parents=True, exist_ok=True)

    print("musical-distiller — Distill")
    print("─" * 40)
    print(f"  gestalt : {gestalt_dir}")
    print(f"  output  : {out_dir}")
    print(f"  split   : {args.split}")
    print()

    total_ab = total_zone = total_skipped = total_written = 0

    for path in sorted(gestalt_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        zone  = data.get("zone")
        split = data.get("split", "training")

        if args.split != "all" and split != args.split:
            continue
        if split == "skip":
            continue

        out: dict[str, dict] = {}

        for tid in data.get("track_ids", []):
            entry = data.get("metadata", {}).get(tid, {})
            if entry.get("error"):
                total_skipped += 1
                continue

            ab = entry.get("acousticbrainz")
            if ab:
                v, e = from_acousticbrainz(ab, cfg)
                source = "ab"
                total_ab += 1
            elif zone:
                result = from_zone(zone, anchors)
                if result is None:
                    total_skipped += 1
                    continue
                v, e = result
                source = "zone"
                total_zone += 1
            else:
                total_skipped += 1
                continue

            out[tid] = {"valence": round(v, 6), "energy": round(e, 6), "source": source}

        if out:
            out_path = out_dir / path.name
            out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
            total_written += len(out)
            print(f"  {path.stem}: {len(out)} tracks")

    print()
    print(f"  {total_ab:>4} tracks from AcousticBrainz features")
    print(f"  {total_zone:>4} tracks from zone anchor fallback")
    print(f"  {total_skipped:>4} tracks skipped")
    print(f"  {total_written:>4} total records written to {out_dir}")
    print()


if __name__ == "__main__":
    main()
