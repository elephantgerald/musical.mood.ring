# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

musical.mood.ring is a self-contained ESP32 ambient light system. Three NeoPixels in a keyboard shell glow with colors derived from the user's Spotify listening history. Colors are computed from a polar (valence, energy) mood model. Because Spotify's `/v1/audio-features` API is permanently blocked for apps registered after November 2024, (valence, energy) values are pre-computed offline via a four-stage data pipeline and compiled into a binary lookup bundle that lives on the ESP32's flash.

## Repository Structure

```
src/mood-model/           # M0 calibration notebook (m0_calibration.ipynb)
src/musical-cultivator/   # Stage 1: mine/import track IDs into data/musical-gestalt/
src/musical-mash-bill/    # Stage 2: enrich gestalt JSONs with MB + AB + Last.fm features
src/musical-distiller/    # Stage 3: derive (V,E) per track → data/musical-affective-memory/
src/musical-bottler/      # Stage 4: compile affective-memory into MMAR binary bundle
src/musical-mood-ring/    # MicroPython ESP32 firmware
data/musical-gestalt/     # Track metadata + enrichment (JSON per playlist, in-place enriched)
data/musical-affective-memory/  # (valence, energy) per track ID (JSON per playlist)
data/musical-memory-bundle/     # Versioned MMAR binaries for flashing to ESP32
data/synaesthesia/        # Generated colour profiles, one per person (gitignored)
tests/unit/               # pytest, hardware-mocked
tests/integration/        # Mock Spotify API server
tests/end-to-end/         # Hardware-in-loop
build/                    # Flash/deploy scripts
build/firmware/           # Downloaded MicroPython binaries (gitignored)
```

## Environment Setup

One venv covers everything — pipeline, notebook, and tests:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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

**Unit tests** (pure CPython, no board needed):
```bash
pytest tests/unit/
```

**Flash MicroPython to the ESP32** (WSL2 + HUZZAH32):
```bash
./build/reset.sh          # auto-activates .venv; prompts for usbipd if board not found
./build/reset.sh --help   # full usage
```

One-time WSL2 prerequisites:
```bash
sudo apt install linux-tools-generic hwdata
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", GROUP="dialout"' \
    | sudo tee /etc/udev/rules.d/99-esp32.rules
sudo udevadm control --reload-rules
# Ensure /etc/wsl.conf has: [boot]\nsystemd=true
```

**M0 calibration notebook** (visualise mood space, fit H(θ), export synaesthesia profile):
```bash
source .venv/bin/activate
jupyter notebook src/mood-model/m0_calibration.ipynb
# Run all cells → review plots → edit Final Parameters cell → run Export cell
# Output: data/synaesthesia/synaesthesia-{name}.json
```

## Firmware Modules (`src/musical-mood-ring/`)

**Pure logic — CPython-compatible, fully unit-tested:**
- `mmar.py` — MMAR binary search; `fnv1a_64` hash; `MMARBundle.lookup(track_id)`
- `polar.py` — `to_polar(v, e)` → `(r, theta_deg)`
- `ewma.py` — `EWMA(alpha)` accumulator with snap-on-first-update and `reset()`
- `color.py` — `mood_to_rgb(v, e)` → `(r, g, b)` via synaesthesia profile; inline HSV→RGB
- `mood_engine.py` — `MoodEngine(bundle).update(track_ids)` → 3 RGB tuples; now-pixel persistence across miss polls
- `synaesthesia.py` — colour profile loader (see below)

**Hardware glue — thin try/except wrappers, no-op in CPython:**
- `pixel.py` — NeoPixel WS2812B driver (`write(colors)`, `off()`)
- `wifi.py` — `connect(ssid, password)`, `is_connected()`
- `spotify.py` — `recently_played(token)`, `refresh_token(id, secret, refresh)`
- `config.py` — reads `config.json` from flash; exposes `WIFI_SSID`, `SPOTIFY_*` etc.
- `boot.py` — WiFi boot sequence with dim-white status and red error blink
- `main.py` — 3-minute poll loop skeleton (M4 implementation pending)

The try/except convention: each module that needs a MicroPython-specific import wraps it in `try: import ujson / except ImportError: import json` (or equivalent). Pure modules have no such imports and run identically on both platforms.

## Synaesthesia Profile

`src/musical-mood-ring/synaesthesia.py` loads `synaesthesia.json` from the ESP32's flash via `ujson`. If the file is absent the module falls back to a built-in `_DEFAULT` — the device works out of the box without a personalised profile.

The profile is generated by the calibration notebook export cell and flashed to the device alongside the MMAR bundle. Each person can have their own — the file is named `synaesthesia-{name}.json` and lives in `data/synaesthesia/` (gitignored). Profile fields:

```json
{
  "version": 1, "name": "colin",
  "zone_anchors": { "industrial": [0.15, 0.85], ... },
  "hue_map": [[50.2, 111.9], [135.0, 0.0], ...],
  "saturation_k": 2.0,
  "brightness_floor": 0.15, "brightness_range": 0.35,
  "ewma_alpha_1h": 0.0341, "ewma_alpha_4h": 0.0086
}
```

Public API: `hue(theta_deg)`, `saturation_k()`, `brightness_floor()`, `brightness_range()`, `ewma_alpha("1h"|"4h")`, `zone_anchors()`, `profile_name()`.

## Key Architecture Decisions

**Mood model**: `(valence, energy)` → polar `(r, θ)` → `H(θ)` (hue), `S = min(1, r*k)` (saturation), `V = floor + range*energy` (brightness). Averaging is done in (V, E) space; colors are never averaged directly. `H(θ)` uses piecewise-linear interpolation with circular wraparound and shortest-angular-path hue blending — the knot table is the `hue_map` in the synaesthesia profile.

**MMAR binary format**: 16-byte header (`MMAR` magic, version, record count) + 10-byte records sorted by FNV-1a 64-bit hash of Spotify track ID. The ESP32 does binary search at runtime — no external lookup service.

**distill.py priority order**: AcousticBrainz features (weighted formula) → Last.fm tag-zone vote → explicit zone anchor → skip. Weights and zone anchors live in `src/musical-distiller/mapping.toml`.

**Spotify `/v1/audio-features` is permanently 403** for this app. Do not attempt to use it. All (V, E) derivation goes through MusicBrainz → AcousticBrainz → Last.fm → zone anchor fallback chain.

**Three time horizons** on the ESP32: Pixel 1 = most recent poll, Pixel 2 = 1h EWMA, Pixel 3 = 4h EWMA. Stored as running averages only — no history log needed.

**Eight mood zones**: industrial, darkwave, shoegaze, zone-out, indie-melancholy, ambient, americana, fun/dance. Each has a `(valence, energy)` anchor in `mapping.toml` used as a fallback when feature data is absent.

**mDNS**: Device advertises as `musical-mood-ring.local`, providing a stable Spotify OAuth redirect URI (`http://musical-mood-ring.local/callback`) regardless of DHCP-assigned IP.

**Deployment**: `mpremote` (not ampy) for flashing files to the ESP32. Use `build/reset.sh` to erase and reflash MicroPython itself.

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
