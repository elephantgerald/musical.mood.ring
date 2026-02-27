#!/usr/bin/env python3
"""
fetch_artist_ids.py

Backfills `artist_id` into gestalt JSON metadata using Spotify's
/v1/tracks?ids= endpoint (Client Credentials flow, no user auth needed).

For each track in data/musical-gestalt/ that is missing an `artist_id`,
this script fetches the track object from the Spotify API and stores
the primary (first-listed) artist's ID back into the gestalt metadata.

Idempotent — already-enriched tracks are skipped.
Batches up to 50 track IDs per API call. Respects a 1 req/s rate limit.

Usage:
    python fetch_artist_ids.py [--delay 1.0] [--file NAME.json]

Prerequisites:
    src/musical-cultivator/.env must contain:
        SPOTIFY_CLIENT_ID=...
        SPOTIFY_CLIENT_SECRET=...
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
import os


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


_SCRIPT_DIR = Path(__file__).resolve().parent
_ENV_FILE   = _SCRIPT_DIR.parent / ".env"

load_dotenv(_ENV_FILE)

_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID", "")
_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
_TOKEN_URL     = "https://accounts.spotify.com/api/token"
_TRACKS_URL    = "https://api.spotify.com/v1/tracks"
_BATCH_SIZE    = 50   # Spotify API maximum


# ---------------------------------------------------------------------------
# Spotify Client Credentials
# ---------------------------------------------------------------------------

def get_client_token(client_id: str, client_secret: str) -> str | None:
    """Obtain a Bearer token via Client Credentials flow."""
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        _TOKEN_URL,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data="grant_type=client_credentials",
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")


def fetch_primary_artist_ids(
    track_ids: list[str],
    token: str,
) -> dict[str, str]:
    """
    Fetch track objects for up to _BATCH_SIZE track IDs.
    Returns {track_id: primary_artist_id} for all tracks found.
    """
    resp = requests.get(
        _TRACKS_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"ids": ",".join(track_ids)},
    )
    if resp.status_code != 200:
        return {}
    result = {}
    for track in resp.json().get("tracks", []):
        if track and track.get("artists"):
            result[track["id"]] = track["artists"][0]["id"]
    return result


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def enrich_file(path: Path, token: str, delay: float) -> tuple[int, int]:
    """
    Add artist_id to all tracks in a gestalt JSON file that are missing it.
    Returns (enriched_count, skipped_count).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    metadata = data.get("metadata", {})

    pending = [
        tid for tid in metadata
        if not metadata[tid].get("artist_id")
    ]

    if not pending:
        return 0, len(metadata)

    enriched = 0
    for i in range(0, len(pending), _BATCH_SIZE):
        batch = pending[i : i + _BATCH_SIZE]
        artist_map = fetch_primary_artist_ids(batch, token)
        for tid, aid in artist_map.items():
            if tid in metadata:
                metadata[tid]["artist_id"] = aid
                enriched += 1
        if i + _BATCH_SIZE < len(pending):
            time.sleep(delay)

    if enriched:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return enriched, len(pending) - enriched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Backfill artist_id into gestalt JSONs via Spotify API."
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Seconds between API batches (default: 1.0)"
    )
    parser.add_argument(
        "--file", metavar="NAME",
        help="Process a single gestalt file by name (default: all files)"
    )
    args = parser.parse_args()

    if not _CLIENT_ID or not _CLIENT_SECRET:
        print("Error: SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in")
        print(f"  {_ENV_FILE}")
        sys.exit(1)

    root        = project_root()
    gestalt_dir = root / "data" / "musical-gestalt"

    if not gestalt_dir.exists():
        print(f"Gestalt directory not found: {gestalt_dir}")
        sys.exit(1)

    print("Getting Spotify client token…")
    token = get_client_token(_CLIENT_ID, _CLIENT_SECRET)
    if not token:
        print("Failed to obtain Spotify token. Check credentials.")
        sys.exit(1)
    print("Token obtained.")
    print()

    if args.file:
        paths = [gestalt_dir / args.file]
    else:
        paths = sorted(gestalt_dir.glob("*.json"))

    total_enriched = 0
    total_skipped  = 0

    for path in paths:
        if not path.exists():
            print(f"  {path.name}: not found")
            continue
        enriched, skipped = enrich_file(path, token, args.delay)
        total_enriched += enriched
        total_skipped  += skipped
        if enriched:
            print(f"  {path.name}: +{enriched} artist IDs ({skipped} already done)")
        else:
            print(f"  {path.name}: all {skipped} tracks already have artist_id")

    print()
    print(f"Done. {total_enriched} artist IDs added, {total_skipped} already present.")


if __name__ == "__main__":
    main()
