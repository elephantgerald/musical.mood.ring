#!/usr/bin/env python3
"""
mine_playlists.py

Mines the user's Spotify library — Liked Songs and all playlists — to surface
favorite albums ranked by how many unique tracks appear across the collection.

Outputs data/playlist_candidates.json, a ranked list of albums ready for
manual annotation. Open that file and set each album's 'zone' and 'split'
fields before running collect.py.

    zone  : one of "ambient", "zone-out", "industrial", "fun/dance",
                   "indie-melancholy", "singer-songwriter", "darkwave"
            (or null to skip)
    split : one of "training", "test", "skip"

Usage:
    python mine_playlists.py [--min-tracks N] [--include-singles]
"""

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path


def project_root() -> Path:
    """Walk up from this file's location until we find the .git directory."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent  # fallback

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

SCOPES = " ".join([
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
])

REDIRECT_URI = "http://127.0.0.1:8888/callback"

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
        auth_manager=SpotifyOAuth(
            client_id=os.environ["SPOTIFY_CLIENT_ID"],
            client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
            redirect_uri=REDIRECT_URI,
            scope=SCOPES,
            cache_path=".spotipyoauthcache",
            open_browser=True,
        )
    )


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def iter_pages(sp: spotipy.Spotify, initial_result: dict):
    """Yield every item from a paginated Spotify result set."""
    result = initial_result
    while result:
        yield from (result.get("items") or [])
        result = sp.next(result) if result.get("next") else None


# ---------------------------------------------------------------------------
# Track extraction
# ---------------------------------------------------------------------------

def extract_album_info(track_item: dict, include_singles: bool) -> dict | None:
    """
    Pull album metadata from a playlist or library track item.
    Returns None for local files, podcasts, null tracks, and (optionally) singles.
    """
    track = track_item.get("track")
    if not track or not track.get("id"):
        return None

    album = track.get("album")
    if not album or not album.get("id"):
        return None

    album_type = album.get("album_type", "")
    if not include_singles and album_type == "single":
        return None

    artists = track.get("artists") or []
    artist_name = artists[0]["name"] if artists else "Unknown"

    return {
        "album_id":   album["id"],
        "album_name": album["name"],
        "album_type": album_type,
        "artist_name": artist_name,
        "track_id":   track["id"],
    }


# ---------------------------------------------------------------------------
# Mining
# ---------------------------------------------------------------------------

def mine_liked_songs(sp: spotipy.Spotify, albums: dict, include_singles: bool):
    label = "♥ Liked Songs"
    print(f"  {label}")
    count = 0
    for item in iter_pages(sp, sp.current_user_saved_tracks(limit=50)):
        info = extract_album_info(item, include_singles)
        if not info:
            continue
        key = info["album_id"]
        albums[key]["album_id"]   = info["album_id"]
        albums[key]["album"]      = info["album_name"]
        albums[key]["album_type"] = info["album_type"]
        albums[key]["artist"]     = info["artist_name"]
        albums[key]["track_ids"].add(info["track_id"])
        albums[key]["playlist_names"].add(label)
        count += 1
    print(f"     → {count} tracks")


def mine_playlists(sp: spotipy.Spotify, albums: dict, include_singles: bool, playlist_filter: str | None = None):
    playlists = list(iter_pages(sp, sp.current_user_playlists(limit=50)))
    print(f"\n  {len(playlists)} playlists found")

    if playlist_filter:
        needle = playlist_filter.lower()
        playlists = [p for p in playlists if needle in (p.get("name") or "").lower()]
        print(f"  Filtered to {len(playlists)} matching {playlist_filter!r}")

    for pl in playlists:
        if not pl:
            continue
        name  = pl.get("name") or "Untitled"
        pl_id = pl["id"]

        try:
            first_page = sp.playlist_items(pl_id, limit=100, additional_types=("track",))
        except spotipy.SpotifyException as e:
            reason = e.reason.strip() if e.reason else ""
            print(f"  ✗  {name!r} (HTTP {e.http_status}{': ' + reason if reason else ''})")
            continue
        except Exception as e:
            print(f"  ✗  {name!r} (skipped: {e})")
            continue

        total = first_page.get("total", 0)
        if total == 0:
            continue

        print(f"  ▸  {name} ({total} tracks)")
        count = 0
        for item in iter_pages(sp, first_page):
            info = extract_album_info(item, include_singles)
            if not info:
                continue
            key = info["album_id"]
            albums[key]["album_id"]   = info["album_id"]
            albums[key]["album"]      = info["album_name"]
            albums[key]["album_type"] = info["album_type"]
            albums[key]["artist"]     = info["artist_name"]
            albums[key]["track_ids"].add(info["track_id"])
            albums[key]["playlist_names"].add(name)
            count += 1
        print(f"     → {count} valid tracks")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def build_candidates(albums: dict, min_tracks: int) -> list:
    candidates = []
    for data in albums.values():
        track_count = len(data["track_ids"])
        if track_count < min_tracks:
            continue
        candidates.append({
            "artist":       data["artist"],
            "album":        data["album"],
            "album_id":     data["album_id"],
            "album_type":   data["album_type"],
            "track_count":  track_count,
            "playlist_count": len(data["playlist_names"]),
            "playlists":    sorted(data["playlist_names"]),
            # --- annotation fields (fill these in before running collect.py) ---
            "zone":  None,   # ambient | zone-out | industrial | fun/dance |
                             # indie-melancholy | americana | darkwave | shoegaze
            "split": None,   # training | test | skip
        })
    candidates.sort(key=lambda x: (-x["track_count"], -x["playlist_count"], x["artist"].lower()))
    return candidates


def print_table(candidates: list, n: int = 60):
    divider = "─" * 74
    print(f"\n{divider}")
    print(f"  {'TRK':>4}  {'PLST':>4}  {'TYPE':<6}  ARTIST — ALBUM")
    print(divider)
    for c in candidates[:n]:
        label = f"{c['artist']} — {c['album']}"
        if len(label) > 54:
            label = label[:51] + "..."
        print(f"  {c['track_count']:>4}  {c['playlist_count']:>4}  {c['album_type']:<6}  {label}")
    if len(candidates) > n:
        print(f"  ... and {len(candidates) - n} more — see the JSON file")
    print(divider)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Mine Spotify playlists for favorite albums."
    )
    parser.add_argument(
        "--min-tracks", type=int, default=2,
        help="Minimum unique tracks from an album to include it (default: 2)"
    )
    parser.add_argument(
        "--include-singles", action="store_true",
        help="Include single-track releases (excluded by default)"
    )
    parser.add_argument(
        "--playlist", type=str, default=None, metavar="NAME",
        help="Only mine playlists whose name contains NAME (case-insensitive)"
    )
    parser.add_argument(
        "--skip-liked-songs", action="store_true",
        help="Skip mining Liked Songs (saves ~6 API calls when debugging playlists)"
    )
    args = parser.parse_args()

    print("musical.mood.ring — Playlist Miner")
    print("─" * 40)
    print("Authenticating with Spotify...")
    print("(A browser window will open — approve access, then return here)\n")

    sp = get_client()
    me = sp.me()
    print(f"  ✓ Logged in as: {me.get('display_name') or me['id']}")

    token = sp.auth_manager.get_cached_token()
    if token:
        print(f"  Token scopes: {token.get('scope', '(none)')}")
    print()

    albums: dict = defaultdict(lambda: {
        "album_id":     "",
        "album":        "",
        "album_type":   "",
        "artist":       "",
        "track_ids":    set(),
        "playlist_names": set(),
    })

    print("Mining your library...")
    if not args.skip_liked_songs:
        mine_liked_songs(sp, albums, args.include_singles)
    mine_playlists(sp, albums, args.include_singles, playlist_filter=args.playlist)

    print("\nBuilding candidate list...")
    candidates = build_candidates(albums, args.min_tracks)
    print(f"  {len(candidates)} albums with ≥{args.min_tracks} unique tracks")

    print_table(candidates)

    out_path = project_root() / "data" / "playlist_candidates.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)

    print(f"\n  ✓ Written to {out_path}")
    print()
    print("  Next steps:")
    print("  1. Open data/playlist_candidates.json")
    print("  2. For each album you recognize, set:")
    print(f"       \"zone\":  one of {ZONE_OPTIONS}")
    print(f"       \"split\": \"training\", \"test\", or \"skip\"")
    print("  3. Run: python collect.py")
    print()


if __name__ == "__main__":
    main()
