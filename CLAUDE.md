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
tests/hardware/           # Hardware-in-loop tests (run via mpremote on real ESP32)
build/                    # Flash/deploy scripts
build/firmware/           # Downloaded MicroPython binaries (gitignored)
```

## Environment Setup

See [`docs/SETUP.md`](docs/SETUP.md) for the full developer setup: venv, all
`.env` files, external service credentials (Spotify, Last.fm, MusicBrainz /
AcousticBrainz), and WSL2 flash prerequisites.

For Spotify app registration specifically (redirect URI, user allowlist, API
limitations), see [`docs/SPOTIFY-APP-REGISTRATION.md`](docs/SPOTIFY-APP-REGISTRATION.md).

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

# Backfill artist_id into gestalt JSONs (required before bottle.py for artist bundle)
python src/musical-cultivator/scripts/fetch_artist_ids.py [--file name.json]
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

**Library growth — import device miss log into the pipeline:**
```bash
# Pull novel track IDs from a running device and write a new gestalt batch:
python src/musical-cultivator/scripts/import_misses.py [--host musical-mood-ring.local] [--clear]
# Then continue with the normal pipeline from fetch_metadata.py through bottle.py.
# Also supports --file PATH and --stdin for offline miss logs; --dry-run to preview.
```

**Unit tests** (pure CPython, no board needed):
```bash
pytest tests/unit/
```

**Offline board harness** (run the real engine in CPython — no ESP32, no Spotify):

This is the primary way to watch the mood engine work. `dev/fake_board.py` drives
the actual `main.run_poll_cycle()` against the mock Spotify server with a
`FakeClock`, so simulated hours pass in seconds and the 1h/4h pixel tiers are
reachable in a handful of polls. Prefer this over flashing a board — a device
round-trip costs a `reset.sh` that wipes WiFi credentials.

```bash
dev/start.sh                       # start musical-radio-station (mock Spotify) on :5000
python dev/fake_board.py --visual --sim-interval 4000   # 3-bar NOW/1h/4h colour panel
python dev/fake_board.py                                # verbose per-poll log
dev/stop.sh                        # stop the mock
```
Useful flags: `--polls N` (stop after N), `--interval S` (wall-clock seconds
between polls), `--sim-interval S` (simulated seconds each poll advances),
`--advance` (step the mock's playback between polls), `--mock HOST:PORT`.

**Flash MicroPython to the ESP32** (WSL2):
```bash
./build/reset.sh --chip esp32c3   # Seeed XIAO ESP32-C3 (/dev/ttyACM0)
./build/reset.sh --chip esp32     # Adafruit HUZZAH32   (/dev/ttyUSB0)  [default]
./build/reset.sh --help           # full usage
```

One-time WSL2 prerequisites:
```bash
sudo apt install linux-tools-generic hwdata
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", GROUP="dialout"' \
    | sudo tee /etc/udev/rules.d/99-esp32.rules
sudo udevadm control --reload-rules
# Ensure /etc/wsl.conf has: [boot]\nsystemd=true
```

**M0 calibration notebook** (visualise mood space, sweep θ for colour collisions, export synaesthesia profile):
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
- `ewma.py` — time-weighted `EWMA(tau_ms)` accumulator; `update(v, e, dt_ms)` decays by `alpha = 1 - exp(-dt_ms/tau_ms)`, snap-on-first-update, `reset()`. `tau_from_alpha(alpha, ref_ms)` converts a profile alpha (calibrated for the nominal 3-min poll) to a time constant, so cadence irregularity (back-off, silence) no longer distorts the average
- `clock.py` — pluggable monotonic ms clock. `Clock` (production) folds raw `utime.ticks_ms` deltas through `ticks_diff` into a non-wrapping counter; `FakeClock(start_ms).advance(ms)/set(ms)` makes time deterministic in tests and `dev/fake_board.py`. The one place the firmware reads wall-clock time
- `color.py` — `mood_to_rgb(v, e)` → `(r, g, b)` **sRGB** via synaesthesia profile: θ picks a colour by interpolating the profile's `color_map` **in CIELAB**, energy tilts its Lab lightness ±`energy_tilt`, and `master_brightness` scales linear light last. Mood intensity `r` is deliberately unused. `apply_confidence(rgb, c)` scales Lab chroma, holding lightness, so a zero-confidence colour lands on a mid grey rather than near-white
- `mood_engine.py` — `MoodEngine(bundle, artist_bundle, clock).update(track_pairs, now_ms)` → 3 RGB tuples; two-tier lookup (track → artist fallback); confidence scalar applied to Lab chroma; now-pixel persistence across miss polls. **Pixel tiers gate on elapsed wall-clock since the first track hit (1h/4h), not poll count** — and the EWMA takes one time-weighted observation per poll (mean of that poll's hits). `snapshot()` / `last_poll_outcomes()` / `OUTCOME_FIELDS` / `pixel_sources()` (per-pixel `(v,e)`, from the shared tier ladder) expose internal state to `dev/fake_board.py`
- `runtime_state.py` — `RuntimeState` carries the last-poll view (colours, track IDs, per-track outcomes) plus the rolling 20-entry poll log (#57). `main.py` owns one; `dev/fake_board.py` builds one to drive the same `run_poll_cycle()` off-board. `snapshot()` returns a JSON-serializable view and `poll_log_snapshot()` a deep copy of the buffer. Imports `OUTCOME_FIELDS` from `mood_engine` one-way, so the engine's hot path stays free of any reporting concern
- `miss_log.py` — rolling 1000-entry miss log on flash (`misses.txt`); `append(track_id)`, `all()`, `clear()`
- `poller.py` — poll timing with exponential back-off; `should_poll()`, `on_success()`, `on_error()`
- `synaesthesia.py` — colour profile loader (see below)

**Hardware glue — thin try/except wrappers, no-op in CPython:**
- `pixel.py` — NeoPixel WS2812B driver (`write(colors)`, `off()`); clamps to [0, 255]. Owns the LED transfer function: `color.py` emits sRGB, but WS2812B duty is **linear in the byte**, so `to_duty()` converts via a 256-entry table built at import. Without it every mid-tone over-brightens and the palette washes pale. `_GAMMA_CORRECT = False` disables it for bench comparison
- `wifi.py` — `connect(ssid, password)`, `is_connected()`, `try_connect(ssid, password)`
- `ap.py` — `allow_configure()` / `disallow_configure()` (AP_IF wrapper)
- `mdns.py` — `start(hostname)` / `stop()` (mDNS advertisement)
- `spotify.py` — `auth_url()`, `exchange_code()`, `recently_played()` → `[(track_id, artist_id)]`, `refresh_token()`. `SPOTIFY_MOCK_HOST` swaps in a plain-HTTP mock but is honoured **only for loopback/RFC1918 targets** (`_mock_host_ok`) and only from flashed `config.json` — never settable over HTTP — so a public host can't downgrade OAuth traffic to cleartext
- `config.py` — reads/writes `config.json`; `save(data)` merges, `reload()` refreshes constants
- `config_server.py` — non-blocking HTTP server with a `mode` arg: `mode="setup"` routes all WiFi/Spotify config endpoints; `mode="runtime"` routes only the read-only allowlist (`_RUNTIME_ENDPOINTS` — `GET /misses` alone) and returns **403** for every mutating endpoint. `lock_runtime()` is the one-way setup→runtime flip. This is the security boundary that stops the always-on server exposing credential writes to any LAN host. **Engine introspection is deliberately not served here** — `dev/fake_board.py` runs the real poll loop in CPython, which is where mood-state debugging happens; `/misses` stays because the miss log exists only on device flash and mpremote cannot reach it once WiFi is up. A handler exception returns **500** rather than dropping the connection. Spotify handlers never set `done` — the boot setup window (below) governs the setup→runtime transition
- `boot.py` — first-boot AP setup (WiFi), then normal-boot WiFi connect + hand off to main.py
- `main.py` — 3-minute poll loop. Serves `ConfigServer` in `setup` mode for a bounded **setup window** (`_SETUP_GRACE_MS`, 5 min after power-on — the owner is physically present), then calls `lock_runtime()` so only `GET /misses` is served for the rest of uptime. Spotify OAuth (via the PC helper's `POST /spotify/token`) and mock-host changes happen during this window; re-config = power-cycle and act within it. Also: WDT, gc, active WiFi reconnect, panic guard

The try/except convention: each module that needs a MicroPython-specific import wraps it in `try: import ujson / except ImportError: import json` (or equivalent). Pure modules have no such imports and run identically on both platforms.

## Synaesthesia Profile

`src/musical-mood-ring/synaesthesia.py` loads `synaesthesia.json` from the ESP32's flash via `ujson`. If the file is absent the module falls back to a built-in `_DEFAULT` — the device works out of the box without a personalised profile.

The profile is generated by the calibration notebook export cell and flashed to the device alongside the MMAR bundle. Each person can have their own — the file is named `synaesthesia-{name}.json` and lives in `data/synaesthesia/` (gitignored). Profile fields:

```json
{
  "version": 2, "name": "colin",
  "zone_anchors": { "industrial": [0.15, 0.85], ... },
  "color_map": [[50.2, "#E67112"], [135.0, "#F00001"], [153.4, "#BA0EAD"], ...],
  "energy_tilt": 0.15, "master_brightness": 0.65,
  "ewma_alpha_1h": 0.0341, "ewma_alpha_4h": 0.0086
}
```

Public API: `color_map()`, `energy_tilt()`, `master_brightness()`, `ewma_alpha("1h"|"4h")`, `zone_anchors()`, `profile_name()`. The module is a pure accessor — the interpolation lives in `color.py`. Lookups fall back to `_DEFAULT` **key by key**, so a stale v1 profile (`hue_map`/`saturation_k`) left on flash degrades to the built-in palette instead of raising.

`color_map` is a knot table over θ — one knot per zone, each parked at that zone's own anchor direction, with **hue running monotonically around θ**. The monotonicity is load-bearing, not decorative: when colour order matches zone order, a band between two knots is between them in colour too, so it cannot impersonate a third. A non-monotonic table winds the hue circle several times per revolution, and every extra winding is a collision — one draft put 18% of the wheel within chromaticity 0.006 of a zone it was not. The cost is that zone↔colour pairings are set by geometry rather than by taste: fun/dance sits between americana and industrial in θ, so its colour must lie between theirs in hue, which is why it is pumpkin and not violet.

**Separation is measured as duty chromaticity, not Lab ΔE.** ΔE models a reflective patch under D65; a NeoPixel behind diffusion is emissive, and the eye adapts the absolute level away, so two knots differing mostly in lightness arrive as one colour. Bench-measured on the C3: a pair at chromaticity 0.064 read as one colour, a pair at 0.182 read as two — and ΔE ranked that pair the *closer* of the two (25.9 against 35.7). The shipped table's worst pair is 0.251. This is also why root beer cannot be in the palette: emitted, it is the fun/dance pumpkin at lower output, 0.097 away.

## Key Architecture Decisions

**Mood model**: `(valence, energy)` → polar `(r, θ)` → the colour at θ, interpolated **in CIELAB** across the `color_map` knot table (piecewise-linear, circular wraparound). Energy tilts Lab lightness by ±`energy_tilt`; `master_brightness` scales linear light last, which preserves chromaticity exactly. Averaging is done in (V, E) space; colors are never averaged directly.

Two things the model deliberately does **not** do, both learned the hard way (issue #9):

- **`r` does not modulate anything.** Letting mood intensity pull centrist zones toward neutral is how the previous model collapsed 8 zones into ~4 colours. Mud is a *brightness* problem, not a saturation one — root beer **is** ginger ale at V=0.47 — so every palette entry is pinned at V≥0.55 and S≥0.15, the latter to stay clear of the near-grey shown at zero confidence.
- **Interpolation never happens in hue space.** Hue interpolation pins saturation high across the whole sweep, so the bands *between* anchors reproduce other zones' colours outright. Lab passes near the neutral axis instead, so midpoints desaturate — that desaturation is the mechanism, not a defect. `tests/unit/test_color.py::test_no_band_impersonates_a_distant_knot` sweeps θ and fails if any interpolated colour comes within ΔE 15 of a knot it does not sit between.

**MMAR binary format**: 16-byte header (`MMAR` magic, version, record count) + 10-byte records sorted by FNV-1a 64-bit hash of Spotify track ID. The ESP32 does binary search at runtime — no external lookup service.

**distill.py priority order**: AcousticBrainz features (weighted formula) → Last.fm tag-zone vote → explicit zone anchor → skip. Weights and zone anchors live in `src/musical-distiller/mapping.toml`.

**Spotify `/v1/audio-features` is permanently 403** for this app. Do not attempt to use it. All (V, E) derivation goes through MusicBrainz → AcousticBrainz → Last.fm → zone anchor fallback chain.

**Three time horizons** on the ESP32: Pixel 1 = most recent poll, Pixel 2 = 1h EWMA, Pixel 3 = 4h EWMA. Stored as running averages only — no history log needed.

**Eight mood zones**: industrial, darkwave, shoegaze, zone-out, indie-melancholy, ambient, americana, fun/dance. Each has a `(valence, energy)` anchor in `mapping.toml` used as a fallback when feature data is absent.

**mDNS**: Device advertises as `musical-mood-ring.local`, providing a stable Spotify OAuth redirect URI (`http://musical-mood-ring.local/callback`) regardless of DHCP-assigned IP.

**Config-server security model**: The HTTP config server runs in two modes. Mutating endpoints (`/wifi`, `/spotify/*`) are reachable only in `setup` mode — during first-boot AP setup and during a bounded **setup window** (`_SETUP_GRACE_MS`, 5 min) at the start of every normal boot, after which `main.py` calls `lock_runtime()` and only `GET /misses` is served for the rest of uptime. Engine introspection is deliberately **not** an HTTP concern — see the offline harness above. **Accepted risk**: that 5-minute window is *unauthenticated* and runs on the home LAN, so for 5 min after every power-on any LAN host can write config (WiFi creds, Spotify token). This is a deliberate trade-off — the owner is physically present at power-on, exposure is bounded, and the device targets a trusted home network. If the threat model tightens, the hardening path is a flashed shared-secret header on the mutating endpoints (not yet implemented). `SPOTIFY_MOCK_HOST` is flash-only (no HTTP write path) and honoured only for loopback/RFC1918 targets, so it can't be used to downgrade OAuth traffic to cleartext.

**Deployment**: `mpremote` (not ampy) for flashing files to the ESP32. Use `build/reset.sh` to erase and reflash MicroPython itself. Use `build/deploy.sh` to copy firmware and bundles to an already-flashed board:

```bash
./build/deploy.sh --chip esp32c3                        # full mood ring firmware + bundles (C3)
./build/deploy.sh --chip esp32c3 --project twinkle      # hardware test: twinkle animation
./build/deploy.sh --chip esp32c3 --project whitenoise   # hardware test: white noise candle
./build/deploy.sh --chip esp32c3 --project flicker      # hardware test: candle + bell-strike peaks
./build/deploy.sh --chip esp32c3 --firmware-only        # mood.ring: .py files only, skip bundles
./build/deploy.sh --chip esp32c3 --bundles-only         # mood.ring: bundles only, skip .py files
./build/deploy.sh --chip esp32c3 --no-reset             # skip board reset after copy
# (omit --chip esp32c3 for HUZZAH32)
```

If the board is stuck running firmware (WiFi/AP stack active), `reset.sh` must be run first — the serial interrupt cannot break through the network stack.

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
