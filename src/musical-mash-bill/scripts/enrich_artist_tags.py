#!/usr/bin/env python3
"""
enrich_artist_tags.py — derive (valence, energy) per ARTIST from Last.fm tags.

The artist fallback tier needs a (v, e) for every artist the device might see.
bottle.py can only average tracks we already distilled, which covers 25 artists.
probe_artist_sources.py harvests ~1144 artist IDs straight from the account, but
brings no mood data with them — Spotify strips `genres` from artist objects for
this app and /v1/artists is 403, so there is no genre signal on that side at all.

Last.fm indexes by artist NAME, which is exactly what we do have. artist.getTopTags
gives a weighted tag cloud per artist; the existing [lastfm_tag_zones] table in
mapping.toml votes those tags to one of the eight zones, and [zone_anchors] turns
the winning zone into a (v, e). Same classifier the track-level path already uses,
applied one level up.

RAW TAGS ARE CACHED. The tag→zone table will need tuning for an idiosyncratic
library, and refetching 1144 artists to try a new mapping would be absurd — so
tags are stored verbatim and the vote is recomputed offline on every run. Use
--revote to skip the network entirely and just re-derive from cache.

Reads   data/artist_candidates.json          (from probe_artist_sources.py)
Writes  data/artist_tags.json                (raw tag cloud per artist — cache)
        data/musical-affective-memory/artist_memory.json   ({artist_id: {v,e,source}})

Usage:
    python src/musical-mash-bill/scripts/enrich_artist_tags.py [--limit N] [--revote]
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("could not locate repo root (.git)")


ROOT = project_root()
load_dotenv(ROOT / "src" / "musical-mash-bill" / ".env")
load_dotenv(ROOT / "src" / "musical-cultivator" / ".env")

LASTFM_API   = "http://ws.audioscrobbler.com/2.0/"
CANDIDATES   = ROOT / "data" / "artist_candidates.json"
TAG_CACHE    = ROOT / "data" / "artist_tags.json"
OUT_PATH     = ROOT / "data" / "musical-affective-memory" / "artist_memory.json"
MAPPING      = ROOT / "src" / "musical-distiller" / "mapping.toml"


def fetch_artist_tags(name: str, api_key: str) -> dict:
    """artist.getTopTags → {tag_lower: count}. Empty dict on any miss or error."""
    r = requests.get(LASTFM_API, params={
        "method":  "artist.getTopTags",
        "artist":  name,
        "api_key": api_key,
        "format":  "json",
    }, timeout=10)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        return {}
    tags = data.get("toptags", {}).get("tag", [])
    return {t["name"].lower(): int(t.get("count", 0))
            for t in tags if int(t.get("count", 0)) > 0}


def vote_zone(tags: dict, tag_zones: dict) -> tuple:
    """Weighted vote from a tag cloud to one zone. Returns (zone, confidence).

    Confidence is the winning zone's share of all *recognised* tag weight — a
    cloud that maps cleanly to one zone scores near 1.0, a genuinely mixed
    artist scores low. It is reported so the caller can decide what to trust,
    not used to filter here.
    """
    scores = Counter()
    for tag, count in tags.items():
        zone = tag_zones.get(tag)
        if zone:
            scores[zone] += count
    if not scores:
        return None, 0.0
    zone, top = scores.most_common(1)[0]
    return zone, top / sum(scores.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="only process the first N artists")
    ap.add_argument("--revote", action="store_true",
                    help="recompute zones from the cached tags; make no network calls")
    ap.add_argument("--sleep", type=float, default=0.2,
                    help="seconds between Last.fm calls (default 0.2 = 5/sec)")
    args = ap.parse_args()

    if not CANDIDATES.exists():
        sys.exit("No data/artist_candidates.json — run probe_artist_sources.py first")

    mapping   = tomllib.loads(MAPPING.read_text())
    tag_zones = {k.lower(): v for k, v in mapping["lastfm_tag_zones"].items()}
    anchors   = mapping["zone_anchors"]

    artists = json.loads(CANDIDATES.read_text())["artists"]
    if args.limit:
        artists = artists[:args.limit]

    cache = json.loads(TAG_CACHE.read_text()) if TAG_CACHE.exists() else {}

    if not args.revote:
        api_key = os.environ.get("LASTFM_API_KEY")
        if not api_key:
            sys.exit("Missing LASTFM_API_KEY (src/musical-mash-bill/.env)")
        todo = [a for a in artists if a["artist_id"] not in cache]
        print(f"{len(artists)} artists, {len(cache)} already cached, {len(todo)} to fetch")
        for i, a in enumerate(todo, 1):
            try:
                cache[a["artist_id"]] = fetch_artist_tags(a["name"], api_key)
            except Exception as e:                # noqa: BLE001 — one artist must not end the run
                print(f"\n  {a['name']}: {type(e).__name__}: {str(e)[:50]}")
                cache[a["artist_id"]] = {}
            if i % 25 == 0 or i == len(todo):
                print(f"\r  {i}/{len(todo)}", end="", flush=True)
                TAG_CACHE.write_text(json.dumps(cache))   # checkpoint; the run is resumable
            time.sleep(args.sleep)
        print()
        TAG_CACHE.write_text(json.dumps(cache))

    # ── Vote every cached cloud to a zone ────────────────────────────────────
    memory, zones, unmapped = {}, Counter(), Counter()
    no_tags = weak = 0
    for a in artists:
        tags = cache.get(a["artist_id"], {})
        if not tags:
            no_tags += 1
            continue
        zone, conf = vote_zone(tags, tag_zones)
        if zone is None:
            weak += 1
            # Surface the top unmapped tags — this is the tuning signal for
            # [lastfm_tag_zones]; an idiosyncratic library will land here often.
            for t in list(tags)[:3]:
                unmapped[t] += 1
            continue
        v, e = anchors[zone]
        memory[a["artist_id"]] = {"valence": v, "energy": e,
                                  "source": "lastfm-artist", "zone": zone,
                                  "confidence": round(conf, 3)}
        zones[zone] += 1

    OUT_PATH.write_text(json.dumps(memory, indent=2))

    n = len(artists)
    print(f"\n  artists processed        : {n}")
    print(f"  no Last.fm tags at all   : {no_tags} ({100 * no_tags // max(1, n)}%)")
    print(f"  tags but no zone matched : {weak} ({100 * weak // max(1, n)}%)")
    print(f"  ZONED (usable (v,e))     : {len(memory)} ({100 * len(memory) // max(1, n)}%)")
    print("\n  zone distribution:")
    for z, c in zones.most_common():
        print(f"    {c:>5}  {z:<18} {anchors[z]}")
    if unmapped:
        print("\n  top unmapped tags — candidates for [lastfm_tag_zones]:")
        for t, c in unmapped.most_common(25):
            print(f"    {c:>4}  {t}")
    print(f"\n  wrote {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
