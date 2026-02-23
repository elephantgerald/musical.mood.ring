#!/usr/bin/env python3
"""
enrich_features.py

Three-phase feature enrichment for gestalt track batches:

Phase 1 — MusicBrainz: for each track with metadata (artist + title) but no
MBID, query the MusicBrainz recording search API. Tries the top N results
in score order until one has AcousticBrainz coverage.

Phase 2 — AcousticBrainz: for each track with an MBID, fetch high-level mood
and low-level BPM/key data. Stores raw values — valence/energy approximations
are derived downstream in musical-distiller.

Phase 3 — Last.fm: for each track that still lacks AcousticBrainz features,
fetch track.getTopTags and store the tag dict. musical-distiller uses these
as a zone classifier fallback when no AB features are available.

All phases are idempotent: already-enriched tracks are skipped. Tracks with
no MusicBrainz match are marked mbid_status="no_match" to avoid re-querying.

Usage:
    python enrich_features.py [--file NAME.json] [--phase 1|2|3|both|all] [--min-score N]

    both = phases 1 + 2 (MusicBrainz + AcousticBrainz)
    all  = phases 1 + 2 + 3 (adds Last.fm tag fallback)
"""

import argparse
import html
import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MB_SEARCH_URL = "https://musicbrainz.org/ws/2/recording/"
AB_HL_URL     = "https://acousticbrainz.org/api/v1/{mbid}/high-level"
AB_LL_URL     = "https://acousticbrainz.org/api/v1/{mbid}/low-level"
LASTFM_API    = "http://ws.audioscrobbler.com/2.0/"

MB_HEADERS = {
    # MusicBrainz requires a descriptive User-Agent or they rate-limit aggressively
    "User-Agent": "musical-mood-ring/0.1 (https://github.com/elephantgerald/musical.mood.ring)",
    "Accept": "application/json",
}
MB_DELAY  = 1.1   # MusicBrainz enforces 1 req/sec; stay just over
AB_DELAY  = 0.5
LFM_DELAY = 0.25  # Last.fm allows 5 req/sec


def project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent


def clean_title(title: str) -> str:
    """Unescape HTML entities and strip common remaster/live/version suffixes."""
    title = html.unescape(title)
    title = re.sub(
        r"\s*[-–]\s*(Remaster(ed)?(\s+\d{4})?|\d{4}\s+Remaster|Live\b.*|"
        r"Single Version.*|Radio Edit.*|Original Mix.*|\d{4}\s+Mix.*)",
        "", title, flags=re.IGNORECASE,
    )
    return title.strip()


def mb_search(artist: str, title: str, min_score: int, try_n: int = 5) -> list[tuple[str, int]]:
    """
    Query MusicBrainz recording search.
    Returns list of (mbid, score) tuples with score >= min_score, up to try_n results.
    """
    query = f'recording:"{clean_title(title)}" AND artist:"{html.unescape(artist)}"'
    r = requests.get(MB_SEARCH_URL, headers=MB_HEADERS, params={
        "query": query,
        "fmt": "json",
        "limit": try_n,
    }, timeout=15)
    r.raise_for_status()
    recordings = r.json().get("recordings", [])
    return [
        (rec["id"], int(rec.get("score", 0)))
        for rec in recordings
        if int(rec.get("score", 0)) >= min_score
    ]


def ab_fetch_hl(mbid: str) -> dict | None:
    """Fetch AcousticBrainz high-level features. Returns None on 404 or error."""
    r = requests.get(AB_HL_URL.format(mbid=mbid), timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    hl = r.json().get("highlevel", {})

    def prob(key: str) -> float | None:
        val = hl.get(key, {}).get("probability")
        return round(float(val), 4) if val is not None else None

    return {
        "mood_happy":      prob("mood_happy"),
        "mood_sad":        prob("mood_sad"),
        "mood_aggressive": prob("mood_aggressive"),
        "mood_relaxed":    prob("mood_relaxed"),
        "mood_acoustic":   prob("mood_acoustic"),
        "mood_party":      prob("mood_party"),
        "mood_electronic": prob("mood_electronic"),
        "danceability":    prob("danceability"),
    }


def ab_fetch_ll(mbid: str) -> dict:
    """Fetch AcousticBrainz low-level features (BPM, key, mode). Returns {} on failure."""
    r = requests.get(AB_LL_URL.format(mbid=mbid), timeout=15)
    if r.status_code != 200:
        return {}
    ll = r.json()
    bpm = ll.get("rhythm", {}).get("bpm")
    tonal = ll.get("tonal", {})
    return {
        "bpm":  round(float(bpm), 1) if bpm is not None else None,
        "key":  tonal.get("key_key"),
        "mode": tonal.get("key_scale"),
    }


def lastfm_fetch_tags(artist: str, title: str, api_key: str) -> dict[str, int]:
    """
    Fetch track.getTopTags from Last.fm.
    Returns {tag_name_lower: count} for all tags with count > 0.
    """
    r = requests.get(LASTFM_API, params={
        "method":  "track.getTopTags",
        "artist":  html.unescape(artist),
        "track":   html.unescape(clean_title(title)),
        "api_key": api_key,
        "format":  "json",
    }, timeout=10)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        return {}
    tags = data.get("toptags", {}).get("tag", [])
    return {
        t["name"].lower(): int(t.get("count", 0))
        for t in tags
        if int(t.get("count", 0)) > 0
    }


def phase1_mb(entry: dict, min_score: int) -> dict:
    """Enrich entry with MBID via MusicBrainz. Mutates and returns entry."""
    artist = html.unescape(entry.get("artist", ""))
    title  = entry.get("track", "")
    if not artist or not title:
        return entry

    try:
        candidates = mb_search(artist, title, min_score)
    except Exception as e:
        entry["mbid_status"] = f"error: {e}"
        return entry

    if not candidates:
        entry["mbid_status"] = "no_match"
        return entry

    # Try each candidate against AcousticBrainz — take the first with coverage
    for mbid, score in candidates:
        hl = ab_fetch_hl(mbid)
        time.sleep(AB_DELAY)
        if hl is not None:
            ll = ab_fetch_ll(mbid)
            time.sleep(AB_DELAY)
            entry["mbid"]       = mbid
            entry["mbid_score"] = score
            entry["acousticbrainz"] = {**hl, **ll}
            return entry

    # All candidates found in MB but none in AB — store top match anyway
    entry["mbid"]       = candidates[0][0]
    entry["mbid_score"] = candidates[0][1]
    entry["acousticbrainz_status"] = "not_in_archive"
    return entry


def phase2_ab(entry: dict) -> dict:
    """Enrich entry with AcousticBrainz features for an existing MBID. Mutates and returns entry."""
    mbid = entry.get("mbid")
    if not mbid:
        return entry
    hl = ab_fetch_hl(mbid)
    time.sleep(AB_DELAY)
    if hl is None:
        entry["acousticbrainz_status"] = "not_in_archive"
    else:
        ll = ab_fetch_ll(mbid)
        time.sleep(AB_DELAY)
        entry["acousticbrainz"] = {**hl, **ll}
    return entry


def phase3_lastfm(entry: dict, api_key: str) -> dict:
    """Fetch Last.fm top tags for a track missing AB features. Mutates and returns entry."""
    artist = entry.get("artist", "")
    title  = entry.get("track", "")
    if not artist or not title:
        return entry

    try:
        tags = lastfm_fetch_tags(artist, title, api_key)
    except Exception as e:
        entry["lastfm_status"] = f"error: {e}"
        return entry

    if tags:
        entry["lastfm_tags"] = tags
    else:
        entry["lastfm_status"] = "no_tags"
    return entry


def enrich_file(path: Path, phase: str, min_score: int, lfm_api_key: str | None) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    metadata: dict = data.get("metadata", {})
    track_ids = data.get("track_ids", [])

    mb_done = mb_needed = ab_done = ab_needed = lfm_done = lfm_needed = 0

    for tid in track_ids:
        entry = metadata.get(tid, {})
        if entry.get("error"):
            continue

        needs_mb = (
            phase in ("1", "both", "all")
            and "mbid" not in entry
            and entry.get("mbid_status") != "no_match"
            and not entry.get("mbid_status", "").startswith("error")
        )
        needs_ab = (
            phase in ("2", "both", "all")
            and entry.get("mbid")
            and "acousticbrainz" not in entry
            and entry.get("acousticbrainz_status") != "not_in_archive"
        )
        needs_lfm = (
            phase in ("3", "all")
            and entry.get("artist") and entry.get("track")
            and "acousticbrainz" not in entry
            and "lastfm_tags" not in entry
            and entry.get("lastfm_status") != "no_tags"
            and not entry.get("lastfm_status", "").startswith("error")
        )

        if needs_mb:
            mb_needed += 1
            entry = phase1_mb(entry, min_score)
            time.sleep(MB_DELAY)
            if entry.get("mbid"):
                mb_done += 1
            if entry.get("acousticbrainz"):
                ab_done += 1  # AB was fetched as part of MB phase

        elif needs_ab:
            ab_needed += 1
            entry = phase2_ab(entry)
            if entry.get("acousticbrainz"):
                ab_done += 1

        if needs_lfm and "acousticbrainz" not in entry:
            lfm_needed += 1
            entry = phase3_lastfm(entry, lfm_api_key)
            time.sleep(LFM_DELAY)
            if entry.get("lastfm_tags"):
                lfm_done += 1

        metadata[tid] = entry

    data["metadata"] = metadata
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return {
        "mb_done": mb_done, "mb_needed": mb_needed,
        "ab_done": ab_done, "ab_needed": ab_needed,
        "lfm_done": lfm_done, "lfm_needed": lfm_needed,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Enrich gestalt tracks with MusicBrainz, AcousticBrainz, and Last.fm features."
    )
    parser.add_argument("--file", metavar="NAME",
                        help="Process only this file (e.g. grumpy_people_are_grumpy.json)")
    parser.add_argument("--phase", choices=["1", "2", "3", "both", "all"], default="both",
                        help="1=MB, 2=AB, 3=Last.fm tags, both=1+2, all=1+2+3 (default: both)")
    parser.add_argument("--min-score", type=int, default=85, metavar="N",
                        help="Minimum MusicBrainz match confidence 0-100 (default: 85)")
    args = parser.parse_args()

    lfm_api_key = None
    if args.phase in ("3", "all"):
        lfm_api_key = os.environ.get("LASTFM_API_KEY")
        if not lfm_api_key:
            print("Phase 3 requires LASTFM_API_KEY — add it to src/musical-mash-bill/.env")
            print("Get a free key at: https://www.last.fm/api/account/create")
            return

    gestalt_dir = project_root() / "data" / "musical-gestalt"
    if not gestalt_dir.exists():
        print("No data/musical-gestalt/ directory found.")
        return

    if args.file:
        files = [gestalt_dir / args.file]
    else:
        files = sorted(gestalt_dir.glob("*.json"))

    files = [f for f in files if f.exists()]
    if not files:
        print("No files to process.")
        return

    phase_label = {
        "1":    "MusicBrainz lookup (with AB coverage check)",
        "2":    "AcousticBrainz only (existing MBIDs)",
        "3":    "Last.fm tags (AB-miss tracks only)",
        "both": "MusicBrainz + AcousticBrainz",
        "all":  "MusicBrainz + AcousticBrainz + Last.fm",
    }
    print("musical-mash-bill — Feature Enrichment")
    print("─" * 42)
    print(f"  phase     : {phase_label[args.phase]}")
    print(f"  min-score : {args.min_score}")
    print(f"  files     : {len(files)}")
    print()

    totals = {"mb_done": 0, "mb_needed": 0, "ab_done": 0, "ab_needed": 0,
              "lfm_done": 0, "lfm_needed": 0}
    for path in files:
        data = json.load(open(path))
        total_tracks = len(data.get("track_ids", []))
        print(f"  ▸  {path.name} ({total_tracks} tracks)")
        counts = enrich_file(path, args.phase, args.min_score, lfm_api_key)
        if args.phase in ("1", "both", "all"):
            print(f"     MB  : {counts['mb_done']}/{counts['mb_needed']} matched")
        if args.phase in ("1", "2", "both", "all"):
            print(f"     AB  : {counts['ab_done']} features fetched")
        if args.phase in ("3", "all"):
            print(f"     LFM : {counts['lfm_done']}/{counts['lfm_needed']} tags fetched")
        for k in totals:
            totals[k] += counts[k]

    print()
    print("  Totals:")
    if args.phase in ("1", "both", "all"):
        print(f"    MusicBrainz   : {totals['mb_done']}/{totals['mb_needed']} tracks matched")
    if args.phase in ("1", "2", "both", "all"):
        print(f"    AcousticBrainz: {totals['ab_done']} tracks with features")
    if args.phase in ("3", "all"):
        print(f"    Last.fm tags  : {totals['lfm_done']}/{totals['lfm_needed']} tracks tagged")
    print()


if __name__ == "__main__":
    main()
