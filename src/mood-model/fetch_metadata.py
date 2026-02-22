#!/usr/bin/env python3
"""
fetch_metadata.py

Resolves Spotify track IDs to human-readable metadata (track name, artist,
album, year) by scraping Open Graph tags from Spotify's public web player.
No API key required. Reads all JSON files in data/pending/, enriches them
with metadata, and writes the result back in-place.

Usage:
    python fetch_metadata.py [--delay 0.5]
"""

import argparse
import json
import re
import time
from pathlib import Path

import requests

SPOTIFY_TRACK_URL = "https://open.spotify.com/track/{}"
HEADERS = {
    # Googlebot UA triggers Spotify's SSR path which serves og:meta tags.
    # Regular browser UAs get the React SPA shell with no useful metadata.
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
}

OG_CONTENT_RE = re.compile(r'property="og:([^"]+)"\s+content="([^"]*)"')


def project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent


def fetch_og_tags(track_id: str) -> dict:
    """Return a dict of og:* tag values for the given track ID."""
    url = SPOTIFY_TRACK_URL.format(track_id)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return dict(OG_CONTENT_RE.findall(resp.text))


def parse_description(description: str) -> tuple[str, str, str | None]:
    """
    Parse 'Artist · Album · Song · Year' or similar og:description variants.
    Returns (artist, album, year).
    """
    parts = [p.strip() for p in description.split("·")]
    # Format observed: "Artist · Album · Song · Year"
    artist = parts[0] if len(parts) > 0 else ""
    album  = parts[1] if len(parts) > 1 else ""
    year   = next((p for p in parts if re.fullmatch(r"\d{4}", p)), None)
    return artist, album, year


def enrich_pending_file(path: Path, delay: float) -> int:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    track_ids: list[str] = data.get("track_ids", [])
    existing: dict = data.get("metadata", {})

    needed = [tid for tid in track_ids if tid not in existing]
    if not needed:
        print(f"  ✓ {path.name} — already complete ({len(track_ids)} tracks)")
        return 0

    print(f"  {path.name} — fetching {len(needed)} of {len(track_ids)} tracks")
    fetched = 0
    errors = 0

    for i, tid in enumerate(needed, 1):
        try:
            tags = fetch_og_tags(tid)
            title = tags.get("title", "")
            desc  = tags.get("description", "")
            artist, album, year = parse_description(desc)
            existing[tid] = {
                "track": title,
                "artist": artist,
                "album": album,
                "year": year,
            }
            fetched += 1
            if i % 10 == 0 or i == len(needed):
                print(f"    {i}/{len(needed)}  {artist} — {title}")
        except Exception as e:
            existing[tid] = {"error": str(e)}
            errors += 1
            print(f"    ✗ {tid}: {e}")

        if i < len(needed):
            time.sleep(delay)

    data["metadata"] = existing
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"    → {fetched} fetched, {errors} errors — saved to {path.name}")
    return fetched


def main():
    parser = argparse.ArgumentParser(
        description="Enrich pending track batches with metadata from Spotify web player."
    )
    parser.add_argument(
        "--delay", type=float, default=0.5, metavar="SECONDS",
        help="Seconds between requests (default: 0.5)"
    )
    parser.add_argument(
        "--file", type=str, default=None, metavar="NAME",
        help="Process only this file (e.g. gazey_gaze.json); default: all"
    )
    args = parser.parse_args()

    pending_dir = project_root() / "data" / "pending"
    if not pending_dir.exists():
        print("No data/pending/ directory found.")
        return

    if args.file:
        files = [pending_dir / args.file]
    else:
        files = sorted(pending_dir.glob("*.json"))

    if not files:
        print("No .json files found in data/pending/.")
        return

    print(f"musical.mood.ring — Metadata Fetcher")
    print(f"─" * 40)
    total = 0
    for path in files:
        if not path.exists():
            print(f"  ✗ Not found: {path.name}")
            continue
        total += enrich_pending_file(path, args.delay)

    print(f"\n  Done. {total} tracks newly enriched.")


if __name__ == "__main__":
    main()
