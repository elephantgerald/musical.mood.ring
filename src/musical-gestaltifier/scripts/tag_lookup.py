#!/usr/bin/env python3
"""
tag_lookup.py

Queries Last.fm for genre tags on every artist in a pending playlist file,
then aggregates the results to reveal the playlist's dominant genre character.
Useful for identifying the zone of a playlist you're not sure about.

Requires LASTFM_API_KEY in .env (free key at https://www.last.fm/api/account/create).

Usage:
    python tag_lookup.py --file low_key_and_painless.json [--top 20]
"""

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

LASTFM_API = "http://ws.audioscrobbler.com/2.0/"


def project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent


def get_artist_tags(artist: str, api_key: str) -> list[str]:
    """Return top genre tags for an artist from Last.fm."""
    resp = requests.get(LASTFM_API, params={
        "method": "artist.getTopTags",
        "artist": artist,
        "api_key": api_key,
        "format": "json",
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        return []
    tags = data.get("toptags", {}).get("tag", [])
    # Only return tags with meaningful popularity (count > 5)
    return [t["name"].lower() for t in tags if int(t.get("count", 0)) > 5]


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate Last.fm genre tags for a pending playlist."
    )
    parser.add_argument("--file", required=True, metavar="NAME",
                        help="Pending JSON file name (e.g. low_key_and_painless.json)")
    parser.add_argument("--top", type=int, default=25,
                        help="Number of top tags to display (default: 25)")
    parser.add_argument("--delay", type=float, default=0.25,
                        help="Seconds between Last.fm requests (default: 0.25)")
    args = parser.parse_args()

    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        print("Missing LASTFM_API_KEY — add it to .env")
        print("Get a free key at: https://www.last.fm/api/account/create")
        return

    path = project_root() / "data" / "musical-gestalt" / args.file
    if not path.exists():
        print(f"File not found: {path}")
        return

    data = json.loads(path.read_text())
    metadata: dict = data.get("metadata", {})
    if not metadata:
        print("No metadata found — run fetch_metadata.py first")
        return

    artists = sorted({v["artist"] for v in metadata.values()
                      if v.get("artist") and not v.get("error")})

    print(f"musical.mood.ring — Tag Lookup: {data.get('playlist', args.file)}")
    print(f"─" * 40)
    print(f"  {len(artists)} unique artists to query\n")

    tag_counts: Counter = Counter()
    for i, artist in enumerate(artists, 1):
        try:
            tags = get_artist_tags(artist, api_key)
            tag_counts.update(tags)
            if i % 10 == 0 or i == len(artists):
                print(f"  {i}/{len(artists)}  {artist}: {', '.join(tags[:5]) or '(no tags)'}")
        except Exception as e:
            print(f"  ✗ {artist}: {e}")
        if i < len(artists):
            time.sleep(args.delay)

    print(f"\n  Top {args.top} tags across all artists:")
    print(f"  {'TAG':<30} COUNT")
    print(f"  {'─' * 38}")
    for tag, count in tag_counts.most_common(args.top):
        bar = "█" * min(count, 40)
        print(f"  {tag:<30} {count:>3}  {bar}")

    print(f"\n  Playlist: {data.get('playlist')}  |  Current zone: {data.get('zone')}  |  Split: {data.get('split')}")
    print(f"  To reassign: edit the 'zone' and 'split' fields in {args.file}")


if __name__ == "__main__":
    main()
