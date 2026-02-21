#!/usr/bin/env python3
"""
collect.py

Reads annotated data/playlist_candidates.json and fetches Spotify audio
features for every track on each annotated album. Computes per-album
statistics and writes:

    data/training.json   — albums where split == "training"
    data/test.json       — albums where split == "test"

Uses Client Credentials flow — no user login required.

Usage:
    python collect.py

Prerequisites:
    - data/playlist_candidates.json with 'zone' and 'split' fields filled in
    - SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

load_dotenv()

FEATURES_OF_INTEREST = [
    "valence",
    "energy",
    "danceability",
    "acousticness",
    "instrumentalness",
    "speechiness",
    "tempo",
    "loudness",
]


# ---------------------------------------------------------------------------
# Spotify client
# ---------------------------------------------------------------------------

def get_client() -> spotipy.Spotify:
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
        if not os.environ.get(key):
            raise EnvironmentError(
                f"Missing {key}. Copy .env.example to .env and fill it in."
            )
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=os.environ["SPOTIFY_CLIENT_ID"],
            client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        )
    )


# ---------------------------------------------------------------------------
# Spotify helpers
# ---------------------------------------------------------------------------

def get_album_track_ids(sp: spotipy.Spotify, album_id: str) -> list:
    """Fetch all track IDs for an album (all pages)."""
    track_ids = []
    result = sp.album_tracks(album_id, limit=50)
    while result:
        for item in result.get("items") or []:
            if item and item.get("id"):
                track_ids.append(item["id"])
        result = sp.next(result) if result.get("next") else None
    return track_ids


def get_audio_features(sp: spotipy.Spotify, track_ids: list) -> list:
    """Batch-fetch audio features in chunks of 100. Drops null responses."""
    features = []
    for i in range(0, len(track_ids), 100):
        batch = track_ids[i : i + 100]
        result = sp.audio_features(batch)
        if result:
            features.extend(f for f in result if f is not None)
        if i + 100 < len(track_ids):
            time.sleep(0.1)
    return features


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_stats(features: list) -> Optional[dict]:
    """
    Compute mean and std dev for each audio feature across all tracks.
    Returns None if no features were provided.
    """
    if not features:
        return None

    stats: dict = {"track_count": len(features)}

    for key in FEATURES_OF_INTEREST:
        values = [f[key] for f in features if f.get(key) is not None]
        if not values:
            continue
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        stats[f"{key}_mean"] = round(mean, 4)
        stats[f"{key}_std"]  = round(variance ** 0.5, 4)

    return stats


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_split(sp: spotipy.Spotify, candidates: list, split: str) -> list:
    group = [c for c in candidates if c.get("split") == split]
    if not group:
        print(f"  No '{split}' albums found — skipping.")
        return []

    print(f"\n  [{split.upper()}] {len(group)} albums")
    results = []

    for c in group:
        album_id = c.get("album_id")
        artist   = c.get("artist", "Unknown")
        album    = c.get("album",  "Unknown")
        zone     = c.get("zone")

        if not album_id:
            print(f"  ⚠  No album_id for {artist} — {album}, skipping")
            continue

        print(f"  ▸  {artist} — {album}  [{zone or '?'}]")

        try:
            track_ids = get_album_track_ids(sp, album_id)
            if not track_ids:
                print("     ⚠  No tracks returned")
                continue

            features = get_audio_features(sp, track_ids)
            if not features:
                print("     ⚠  No audio features returned")
                continue

            stats = compute_stats(features)
            if not stats:
                continue

            v = stats.get("valence_mean", 0)
            e = stats.get("energy_mean",  0)
            print(
                f"     ✓  {stats['track_count']} tracks  |  "
                f"valence {v:.3f} ± {stats.get('valence_std', 0):.3f}  |  "
                f"energy {e:.3f} ± {stats.get('energy_std', 0):.3f}"
            )

            results.append({
                "artist":   artist,
                "album":    album,
                "album_id": album_id,
                "zone":     zone,
                **stats,
            })

        except Exception as exc:
            print(f"     ✗  {exc}")
            continue

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("musical.mood.ring — Audio Feature Collector")
    print("─" * 44)

    candidates_path = Path("data/playlist_candidates.json")
    if not candidates_path.exists():
        print(f"Error: {candidates_path} not found.")
        print("Run mine_playlists.py first, then annotate 'zone' and 'split'.")
        return

    with open(candidates_path, encoding="utf-8") as f:
        candidates = json.load(f)

    total      = len(candidates)
    annotated  = [c for c in candidates if c.get("split") in ("training", "test")]
    skipped    = [c for c in candidates if c.get("split") == "skip"]
    unannotated = [c for c in candidates if c.get("split") is None]

    print(f"  {total} candidates loaded")
    print(f"  {len(annotated)} to collect ({len([c for c in annotated if c['split']=='training'])} training, "
          f"{len([c for c in annotated if c['split']=='test'])} test)")
    if skipped:
        print(f"  {len(skipped)} skipped")
    if unannotated:
        print(f"  ⚠  {len(unannotated)} unannotated — will be ignored")

    if not annotated:
        print("\nNothing to collect. Annotate 'zone' and 'split' in the JSON first.")
        return

    print("\nConnecting to Spotify (Client Credentials)...")
    sp = get_client()
    print("  ✓ Connected\n")

    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)

    for split in ("training", "test"):
        results = process_split(sp, candidates, split)
        if results:
            out_path = out_dir / f"{split}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"\n  ✓ data/{split}.json written ({len(results)} albums)")

    print("\nDone. Open model.ipynb to begin analysis.\n")


if __name__ == "__main__":
    main()
