#!/usr/bin/env python3
"""
probe_artist_sources.py — find out which Spotify endpoints still work, and how
many distinct artists each one yields.

Two questions in one pass:

  1. Which endpoints are actually reachable for this app? The known-403 list
     (audio-features, playlists/{id}/tracks) was recorded in Feb 2026 and may
     have shifted either way since. Every endpoint here is probed independently
     and a failure is reported, never fatal.

  2. How many artists can we harvest? The artist fallback tier needs artist IDs;
     the bundle currently holds 25 of a possible ~415 because artist_id was only
     ever backfilled into one gestalt file. Artists reachable directly from the
     API don't need that backfill at all.

Genres come from the same responses: /me/top/artists and /me/following return
FULL artist objects, which carry a `genres` array. /v1/artists (the obvious way
to backfill genres for everyone else) is 403 for this app, so the endpoints that
hand us full objects are the only genre source — capture it on the way past.
Artists discovered only via tracks (saved/recently-played) arrive as SIMPLIFIED
artist objects with no genres, and are recorded with an empty list.

Writes the union to data/artist_candidates.json for the next pipeline stage.

Usage:
    python src/musical-cultivator/scripts/probe_artist_sources.py

A browser window opens once for OAuth; the token is cached in
.spotipyoauthcache at the repo root. Scopes here are a superset of
mine_playlists.py's, so the first run re-prompts for consent.
"""

import json
import os
import sys
from pathlib import Path

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth


def project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("could not locate repo root (.git)")


ROOT = project_root()
load_dotenv(ROOT / "src" / "musical-cultivator" / ".env")

SCOPES = " ".join([
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "user-top-read",             # /me/top/artists
    "user-follow-read",          # /me/following
    "user-read-recently-played", # /me/player/recently-played
])


def client() -> spotipy.Spotify:
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
        if not os.environ.get(key):
            sys.exit(f"Missing {key} in src/musical-cultivator/.env")
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=os.environ["SPOTIFY_CLIENT_ID"],
        client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        redirect_uri="http://127.0.0.1:8888/callback",
        scope=SCOPES,
        cache_path=str(ROOT / ".spotipyoauthcache"),
        open_browser=True,
    ))


def probe(label, fn):
    """Run one source. Returns {artist_id: {name, genres}}; never raises."""
    try:
        found = fn()
        withg = sum(1 for v in found.values() if v.get("genres"))
        print(f"  OK    {label:<34} {len(found):>4} artists  ({withg} with genres)")
        return found
    except spotipy.SpotifyException as e:
        print(f"  FAIL  {label:<34} HTTP {e.http_status} — {e.msg.splitlines()[0][:60]}")
    except Exception as e:                      # noqa: BLE001 — diagnostic breadth is the point
        print(f"  FAIL  {label:<34} {type(e).__name__}: {str(e)[:60]}")
    return {}


def _pages(sp, result, per_item):
    """Walk a paged result, applying per_item to each item."""
    out = {}
    while result:
        for item in result.get("items", []):
            per_item(out, item)
        result = sp.next(result) if result.get("next") else None
    return out


def _full_artist(out, a):
    """A full artist object — name plus the genres array we actually came for."""
    out[a["id"]] = {"name": a.get("name", ""), "genres": a.get("genres", [])}


def _add_track_artists(out, item):
    """Artists named on a track. These are SIMPLIFIED objects: no genres field."""
    track = item.get("track") or item
    for a in (track or {}).get("artists", []):
        if a.get("id"):
            out.setdefault(a["id"], {"name": a.get("name", ""), "genres": []})


def main():
    sp = client()
    print("Probing Spotify artist sources…\n")
    sources = {}

    for term in ("short_term", "medium_term", "long_term"):
        sources[f"top_artists_{term}"] = probe(
            f"/me/top/artists ({term})",
            lambda t=term: _pages(sp, sp.current_user_top_artists(limit=50, time_range=t),
                                  _full_artist))

    sources["followed"] = probe(
        "/me/following (artists)",
        lambda: {a["id"]: {"name": a.get("name", ""), "genres": a.get("genres", [])}
                 for a in sp.current_user_followed_artists(limit=50)["artists"]["items"]})

    sources["saved_tracks"] = probe(
        "/me/tracks (saved)",
        lambda: _pages(sp, sp.current_user_saved_tracks(limit=50), _add_track_artists))

    sources["recently_played"] = probe(
        "/me/player/recently-played",
        lambda: _pages(sp, sp.current_user_recently_played(limit=50), _add_track_artists))

    sources["saved_albums"] = probe(
        "/me/albums (saved)",
        lambda: _pages(sp, sp.current_user_saved_albums(limit=50),
                       lambda o, i: [o.setdefault(a["id"], {"name": a.get("name", ""), "genres": []})
                                     for a in i["album"].get("artists", [])]))

    # Playlist tracks were 403 in Feb 2026 for reasons never established.
    # Probed per-playlist so one bad playlist doesn't mask the rest.
    def playlist_artists():
        out, pls, ok, bad = {}, sp.current_user_playlists(limit=50), 0, 0
        while pls:
            for pl in pls.get("items", []):
                if not pl:
                    continue
                try:
                    out.update(_pages(sp, sp.playlist_items(pl["id"], limit=100),
                                      _add_track_artists))
                    ok += 1
                except Exception:                # noqa: BLE001
                    bad += 1
            pls = sp.next(pls) if pls.get("next") else None
        print(f"        ({ok} playlists readable, {bad} refused)")
        return out
    sources["playlists"] = probe("/playlists/{id}/tracks", playlist_artists)

    union = {}
    for found in sources.values():
        for aid, rec in found.items():
            if rec.get("genres") or aid not in union:
                union[aid] = rec

    withg = sum(1 for v in union.values() if v.get("genres"))
    print(f"\n  UNION: {len(union)} distinct artists, {withg} with genres "
          f"({100 * withg // max(1, len(union))}%)\n")

    # How much of this is genuinely new to the pipeline?
    known = set()
    gestalt = ROOT / "data" / "musical-gestalt"
    for f in gestalt.glob("*.json"):
        for m in json.loads(f.read_text()).get("metadata", {}).values():
            if m.get("artist_id"):
                known.add(m["artist_id"])
    new = set(union) - known
    print(f"  already carrying artist_id in gestalt : {len(known)}")
    print(f"  NEW artists from the API              : {len(new)}")

    out_path = ROOT / "data" / "artist_candidates.json"
    out_path.write_text(json.dumps(
        {"artists": [{"artist_id": k, "name": v["name"], "genres": v["genres"]}
                     for k, v in sorted(union.items(), key=lambda x: x[1]["name"].lower())],
         "sources": {k: len(v) for k, v in sources.items()}},
        indent=2))

    from collections import Counter
    genres = Counter(g for v in union.values() for g in v.get("genres", []))
    print(f"  distinct genre strings: {len(genres)}")
    print("\n  top 25 genres in your listening:")
    for g, c in genres.most_common(25):
        print(f"    {c:>4}  {g}")
    print(f"\n  wrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
