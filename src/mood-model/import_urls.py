#!/usr/bin/env python3
"""
import_urls.py

Parse Spotify track URLs copied from the desktop app, extract track IDs,
and save them as a pending batch for later audio-feature enrichment.

Usage:
    python import_urls.py --playlist "grumpy people are grumpy" --zone industrial < urls.txt
    cat urls.txt | python import_urls.py --playlist "name" --zone zone-out
"""

import argparse
import json
import sys
from pathlib import Path


def project_root() -> Path:
    """Walk up from this file's location until we find the .git directory."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent  # fallback

ZONE_OPTIONS = [
    "ambient",
    "zone-out",
    "industrial",
    "fun/dance",
    "indie-melancholy",
    "americana",
    "darkwave",
    "shoegaze",
]


def extract_track_id(line: str) -> str | None:
    line = line.strip()
    if not line:
        return None
    if "open.spotify.com/track/" in line:
        return line.split("/track/")[-1].split("?")[0].strip()
    if line.startswith("spotify:track:"):
        return line.split(":")[-1].strip()
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Import Spotify track URLs into a pending enrichment batch."
    )
    parser.add_argument("--playlist", required=True, help="Playlist name")
    parser.add_argument(
        "--zone", required=True, choices=ZONE_OPTIONS,
        help=f"Mood zone: {', '.join(ZONE_OPTIONS)}"
    )
    parser.add_argument(
        "--split", default="training", choices=["training", "test", "skip"],
        help="Dataset split (default: training)"
    )
    args = parser.parse_args()

    lines = sys.stdin.read().splitlines()
    seen: set[str] = set()
    track_ids: list[str] = []
    for line in lines:
        tid = extract_track_id(line)
        if tid and tid not in seen:
            seen.add(tid)
            track_ids.append(tid)

    if not track_ids:
        print("No track IDs found in input.", file=sys.stderr)
        sys.exit(1)

    out_dir = project_root() / "data" / "pending"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = (
        args.playlist.lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("'", "")
    )
    out_path = out_dir / f"{safe_name}.json"

    record = {
        "playlist": args.playlist,
        "zone": args.zone,
        "split": args.split,
        "track_count": len(track_ids),
        "track_ids": track_ids,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    print(f"  ✓ {len(track_ids)} unique tracks saved")
    print(f"    playlist : {args.playlist!r}")
    print(f"    zone     : {args.zone}")
    print(f"    split    : {args.split}")
    print(f"    → {out_path}")
    print()
    print("  Run enrich.py (TODO) when quota resets to fetch audio features.")


if __name__ == "__main__":
    main()
