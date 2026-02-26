# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

musical.mood.ring is a self-contained ESP32 ambient light system. Three NeoPixels in a keyboard shell glow with colors derived from the user's Spotify listening history. Colors are computed from a polar (valence, energy) mood model. Because Spotify's `/v1/audio-features` API is permanently blocked for apps registered after November 2024, (valence, energy) values are pre-computed offline via a four-stage data pipeline and compiled into a binary lookup bundle that lives on the ESP32's flash.

## Repository Structure

```
src/musical-cultivator/   # Stage 1: mine/import track IDs into data/musical-gestalt/
src/musical-mash-bill/    # Stage 2: enrich gestalt JSONs with MB + AB + Last.fm features
src/musical-distiller/    # Stage 3: derive (V,E) per track → data/musical-affective-memory/
src/musical-bottler/      # Stage 4: compile affective-memory into MMAR binary bundle
src/musical-mood-ring/    # MicroPython ESP32 firmware (not yet written)
data/musical-gestalt/     # Track metadata + enrichment (JSON per playlist, in-place enriched)
data/musical-affective-memory/  # (valence, energy) per track ID (JSON per playlist)
data/musical-memory-bundle/     # Versioned MMAR binaries for flashing to ESP32
tests/unit/               # pytest, hardware-mocked
tests/integration/        # Mock Spotify API server
tests/end-to-end/         # Hardware-in-loop
build/                    # Flash/deploy scripts
```

The venv currently lives at `src/musical-gestaltifier/.venv` (legacy location, not yet migrated to per-subproject venvs).

## Environment Setup

Each sub-project has its own `requirements.txt`. The shared venv at `src/musical-gestaltifier/.venv` covers all pipeline stages for now:

```bash
source src/musical-gestaltifier/.venv/bin/activate
```

**Credentials** — copy `.env.example` to `.env` in each sub-project that needs it:
- `src/musical-cultivator/.env` — `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`
- `src/musical-mash-bill/.env` — `LASTFM_API_KEY`

## M0 Pipeline Commands

All scripts are run from the repo root with the venv active. Each script walks up to the `.git` root to resolve `data/` paths automatically.

**Stage 1 — Cultivate** (populate `data/musical-gestalt/`):
```bash
# Mine Spotify library to find candidate albums
python src/musical-cultivator/scripts/mine_playlists.py [--min-tracks N]
# Annotate data/playlist_candidates.json (set zone + split), then:

# Import track URLs from stdin (copy Spotify URLs from the desktop app)
cat urls.txt | python src/musical-cultivator/scripts/import_urls.py \
    --playlist "playlist name" --zone industrial [--split training|test]

# Fetch human-readable metadata (artist/title/album) from Spotify web player
python src/musical-cultivator/scripts/fetch_metadata.py [--file name.json]
```

**Stage 2 — Enrich** (adds MB/AB/Last.fm data in-place to `data/musical-gestalt/`):
```bash
python src/musical-mash-bill/scripts/enrich_features.py \
    [--file name.json] [--phase 1|2|3|both|all] [--min-score 85]
# Phase 1 = MusicBrainz, 2 = AcousticBrainz, 3 = Last.fm, both = 1+2, all = 1+2+3
# All phases are idempotent — already-enriched tracks are skipped
```

**Stage 3 — Distill** (`data/musical-affective-memory/`):
```bash
python src/musical-distiller/distill.py [--split training|test|all]
```

**Stage 4 — Bottle** (`data/musical-memory-bundle/`):
```bash
python src/musical-bottler/bottle.py
```

## Key Architecture Decisions

**Mood model**: `(valence, energy)` → polar `(r, θ)` → `H(θ)` (hue), `S = r*k` (saturation), `V = floor + range*energy` (brightness). Averaging is done in (V, E) space; colors are never averaged directly.

**MMAR binary format**: 16-byte header (`MMAR` magic, version, record count) + 10-byte records sorted by FNV-1a 64-bit hash of Spotify track ID. The ESP32 does binary search at runtime — no external lookup service.

**distill.py priority order**: AcousticBrainz features (weighted formula) → Last.fm tag-zone vote → explicit zone anchor → skip. Weights and zone anchors live in `src/musical-distiller/mapping.toml`.

**Spotify `/v1/audio-features` is permanently 403** for this app. Do not attempt to use it. All (V, E) derivation goes through MusicBrainz → AcousticBrainz → Last.fm → zone anchor fallback chain.

**Three time horizons** on the ESP32: Pixel 1 = most recent poll, Pixel 2 = 1h EWMA, Pixel 3 = 4h EWMA. Stored as running averages only — no history log needed.

**Eight mood zones**: industrial, darkwave, shoegaze, zone-out, indie-melancholy, ambient, americana, fun/dance. Each has a `(valence, energy)` anchor in `mapping.toml` used as a fallback when feature data is absent.

**mDNS**: Device advertises as `musical-mood-ring.local`, providing a stable Spotify OAuth redirect URI (`http://musical-mood-ring.local/callback`) regardless of DHCP-assigned IP.

**Deployment**: `mpremote` (not ampy) for flashing MicroPython firmware to the ESP32.

## Data File Format

`data/musical-gestalt/*.json` — one file per playlist/batch:
```json
{
  "playlist": "name", "zone": "industrial", "split": "training",
  "track_ids": ["<spotify_id>", ...],
  "metadata": {
    "<spotify_id>": {
      "track": "title", "artist": "name", "album": "album", "year": "2001",
      "mbid": "...", "mbid_score": 95,
      "acousticbrainz": { "mood_happy": 0.12, "mood_aggressive": 0.87, "bpm": 142.0, ... },
      "lastfm_tags": { "industrial": 100, "ebm": 65 }
    }
  }
}
```

`data/musical-affective-memory/*.json`:
```json
{ "<spotify_id>": { "valence": 0.15, "energy": 0.85, "source": "ab|lastfm|zone" } }
```
