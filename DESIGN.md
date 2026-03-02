# Design Document: musical.mood.ring

This document captures the architectural decisions, design rationale, and implementation plan for the musical.mood.ring project. It is the authoritative reference for why things are built the way they are.

---

## 1. Concept

musical.mood.ring is a self-contained ambient light system that reads the emotional character of a Spotify user's listening history and expresses it as color on three NeoPixel LEDs mounted inside a mechanical keyboard.

The emotional character is derived from two values per track — `valence` (musical positivity, 0–1) and `energy` (intensity, 0–1) — mapped through a continuous polar color model to an RGB output. The three pixels represent three time horizons: the most recent 3-minute poll, an hour-long exponentially weighted average, and a four-hour exponentially weighted average.

These values are pre-computed offline via the M0 pipeline and stored in a compact binary lookup file on the ESP32's flash. The ESP32 looks up each recently-played track ID at runtime; the Spotify audio features API is not used directly (it is permanently blocked for apps registered after November 2024).

The system is entirely self-contained on the ESP32. No companion app, no cloud intermediary, no dependency on a running PC.

---

## 2. Hardware

### Target Board
ESP32 development board with USB-C, sufficient GPIO, and a small physical footprint to fit inside the keyboard shell.

### LEDs
3× WS2812B NeoPixels (addressable RGB). Mounted by drilling three holes in the keyboard's plastic top shell and fixing the LEDs with epoxy. GPIO-driven from the ESP32.

### Power
5V stolen from the keyboard's internal USB power rail. The ESP32 and NeoPixels share this supply.

### Reflash Access
The ESP32's USB-C port is routed to an externally accessible USB-C connector added to the keyboard shell. This allows firmware updates without disassembling the keyboard.

### Physical Build Milestones
- **M8 — Test Unit**: Breadboard build. No drilling, no epoxy. NeoPixels on jumper wires, ESP32 on bench. Validates the full software stack before any permanent hardware modifications.
- **M9 — Forever Unit**: Final installation. Drill shell, epoxy LEDs, steal 5V rail, route USB-C. This is the unit that lives in the keyboard permanently.

M8 is a prerequisite for M9. Nothing gets drilled until the software is boring and reliable.

---

## 3. Firmware Architecture

### Platform
MicroPython on ESP32. Python is more accessible than Arduino C++ for this use case and adequate for the polling, math, and LED control involved.

### Self-Contained Design
The ESP32 handles all of the following autonomously:
- WiFi client connection to home network
- Spotify OAuth 2.0 (Authorization Code flow) via the onboard configuration server
- Polling the Spotify API every 3 minutes
- Computing the mood model
- Driving the NeoPixels

This is a deliberate constraint. A mood ring that only works when a companion script is running on a PC is not a mood ring.

### Boot Sequence
```
boot.py
  ├── First-boot (no wifi_ssid in config.json):
  │     Enable AP (192.168.4.1)
  │     Start ConfigServer → serve WiFi credentials form
  │     Start 5-min ONE_SHOT Timer(0) → auto-stop
  │     Animate BootStatus.CONFIG_WAIT on NeoPixels
  │     On POST /wifi: validate credentials, save config.json, machine.reset()
  │
  └── Normal-boot (wifi_ssid present):
        Connect to WiFi, animate BootStatus.CONNECTING
        On success:
          mdns.start() → musical-mood-ring.local
          Animate BootStatus.SUCCESS briefly
          If no spotify_refresh_token in config.json:
            Start ConfigServer → serve Spotify OAuth pages
            Start 5-min ONE_SHOT Timer(0) → auto-stop
            Animate BootStatus.CONFIG_WAIT
            On GET /callback: exchange code, save refresh_token, config.reload()
          Fall through → main.py
        On failure:
          Pulse ErrorIndicator.WIFI_LOST indefinitely
```

### Animation State Machine
```
main.py
  idle sparkle  ←  startup / no bundle hits / persistent API failure
      ↓  first track-bundle hit after idle
  startup flare  (3 s fade-in from black)
      ↓  flare complete
  mood transition  (60 s smooth HSV crossfade to current target)
      ↑  target updated each successful poll

Error overlays (exit to idle sparkle when condition clears):
  wifi_lost   — slow dim red pulse; active reconnect attempt every 60 s
  auth_fail   — 3 red flashes, then idle sparkle
  api_blip    — brief flash on transient network error; does not interrupt main animator
```

**IdleSparkle** is a three-layer animation:
- **Candle flicker baseline** — Gaussian white noise (Box-Muller, μ=0.08, σ=0.06) gives organic, never-repeating texture
- **Medium swell** — sin^6 half-rectified wave (~67 s period) lifts brightness to ~0.60, roughly once per minute per pixel
- **Bell-strike peak** — at each ~360 s swell zero-crossing, brightness spikes instantly to ~0.90 then decays exponentially (~1.5 s half-life), like a struck bell ringing out

Each pixel runs an independent noise stream with slightly detuned swell periods so they breathe and ring independently. EWMA output smoothing (α=0.15) keeps frame-to-frame transitions fluid.

### Source Structure
```
src/musical-mood-ring/
├── boot.py           # Two-branch boot: first-boot AP setup or WiFi + Spotify OAuth
├── main.py           # Main loop: 10 fps animation state machine + 3-min poll cycle
├── ap.py             # AP_IF wrapper: allow_configure / disallow_configure
├── mdns.py           # mDNS: start(hostname) / stop()
├── wifi.py           # WiFi client: connect / is_connected / try_connect
├── config.py         # config.json: get / save / reload
├── config_server.py  # Non-blocking HTTP: WiFi form, Spotify OAuth, GET /misses
├── spotify.py        # Spotify API: auth_url / exchange_code / recently_played / refresh_token
├── mmar.py           # MMAR bundle: fnv1a_64 hash + binary search lookup
├── mood_engine.py    # Two-tier lookup → confidence scalar → EWMA → 3×RGB
├── color.py          # mood_to_rgb(v, e) → (r, g, b); apply_confidence(rgb, c)
├── polar.py          # to_polar(v, e) → (r, theta_deg)
├── ewma.py           # EWMA accumulator; snap-on-first-update; reset()
├── synaesthesia.py   # Colour profile loader (synaesthesia.json or built-in defaults)
├── lights.py         # Animators: IdleSparkle, StartupFlare, MoodTransition,
│                     #            BootStatus, ErrorIndicator, ApiErrorBlip
├── pixel.py          # NeoPixel WS2812B driver; channel clamping to [0, 255]
├── poller.py         # Poll timing with exponential back-off
└── miss_log.py       # Rolling 1000-entry miss log on flash (misses.txt)
```

---

## 4. WiFi and Configuration

### Pattern
Inspired by a prior project (dancey.dancey). Boot branches on whether WiFi credentials are saved:

**First-boot**: No credentials in config.json. The device opens an AP (`192.168.4.1`) and serves a WiFi credentials form. A 5-minute `Timer.ONE_SHOT` shuts down the server automatically if the user takes too long. On successful credential submission, the device reboots into normal-boot.

**Normal-boot**: Credentials present. The device connects as a WiFi client, starts mDNS, and falls through to the main loop. If no Spotify refresh token is saved yet, a second config server window opens (still in STA mode, reachable at `musical-mood-ring.local`) to complete the Spotify OAuth flow before main.py starts. The AP is **not** re-opened on normal boots.

### Improvements Over dancey.dancey

**Combined setup flow.** The config page handles both WiFi credentials and Spotify OAuth in a single experience. One setup session, one reboot.

**mDNS hostname.** The device advertises itself as `musical-mood-ring.local` once on the home network. This provides a stable, human-readable address regardless of DHCP-assigned IP changes. It also gives us a stable Spotify OAuth redirect URI: `http://musical-mood-ring.local/callback`.

**NeoPixels as status indicators.** The LEDs communicate system state without requiring a serial console:
- Slow spinning white — connecting to WiFi
- Slow blue pulse — AP config mode, waiting for setup
- Steady breathing green — healthy, polling Spotify
- Red flash — error condition

**Credential validation before reboot.** WiFi credentials are tested before saving and rebooting, so a typo in the password surfaces immediately rather than after a full reboot cycle.

### Credential Storage
Stored in a single `config.json` file on ESP32 flash. `config.py` exposes module-level constants (`WIFI_SSID`, `WIFI_PASSWORD`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN`) and a `save()` function that merges updates into the existing file — so WiFi credentials survive a Spotify token write. `reload()` refreshes all constants in place without a reboot.

---

## 5. Spotify Integration

### Why No Stream Disruption
Stream disruption (the "my daughter's phone stole my stream" problem) occurs when a device registers as a **Spotify Connect device** — competing for active playback control. This project does not do that.

We exclusively use `GET /v1/me/player/recently-played`, a read-only history endpoint. It returns listening history with timestamps. It is invisible to the Spotify playback layer. No active player is affected.

The only behavioral note: Spotify only logs tracks played for a meaningful duration (~30 seconds). Short skips do not appear. This is desirable — we only want tracks the user actually listened to.

### OAuth Flow
The Spotify Authorization Code flow is handled during the initial configuration window:

1. User connects to the AP and opens the config page.
2. User clicks "Connect Spotify." The config page constructs a Spotify auth URL and opens it.
3. User logs in and approves. Spotify redirects to `http://musical-mood-ring.local/callback` (registered in the Spotify developer app).
4. The ESP32 receives the auth code, exchanges it for an access token and refresh token over HTTPS, and stores the refresh token on flash.
5. On subsequent boots, the ESP32 uses the stored refresh token to obtain fresh access tokens (Spotify access tokens expire after 1 hour).

### Polling
Every 3 minutes, the ESP32:
1. Refreshes the access token if expired or absent.
2. Calls `GET /v1/me/player/recently-played?limit=10`.
3. For each returned `(track_id, artist_id)` pair, performs a two-tier MMAR lookup:
   - **Track bundle** (primary): precise (v, e) from the AcousticBrainz/Last.fm pipeline.
   - **Artist bundle** (fallback, if present on flash): average (v, e) for the primary artist.
4. Unrecognised track IDs are appended to `misses.txt` (retrievable at `GET /misses`) for pipeline feedback.
5. Passes results to the mood engine, which updates the EWMA accumulators and returns 3 RGB tuples.

The bundles are compiled offline via the M0 pipeline and re-flashed as needed.

**Note**: `GET /v1/audio-features` is permanently blocked for apps registered after November 2024. Runtime audio feature lookups are not possible; the pre-computed bundle is the only viable path.

---

## 6. The Mood Model

### Philosophy
The color output is a **continuous mathematical function** of the (valence, energy) mood space, not a decision tree or zone lookup table. This means:
- There are no hard boundaries between moods.
- Interpolation between states is smooth and musically meaningful.
- Averaging is done in (valence, energy) space, then the color function is applied once. Colors are never averaged directly.

### Polar Coordinate Transform
The (valence, energy) unit square is re-centered and converted to polar:

```
v' = valence - 0.5
e' = energy  - 0.5

r = sqrt(v'² + e'²)   # mood intensity (0 = neutral, ~0.71 = extreme)
θ = atan2(e', v')      # mood direction
```

- **r** — how strongly you're feeling anything. Small r = mild, ambiguous. Large r = committed emotional state.
- **θ** — what you're feeling. This determines the hue.

### Confidence Scalar
A per-session scalar multiplied against saturation communicates lookup certainty:

| Lookup result | Confidence update |
|---|---|
| Track hit | `= 1.0` — vivid; device is certain |
| Artist hit | `= max(0.6, × 0.95)` — washes toward 0.6 over ~10 polls, then arrests |
| Full miss | `×= 0.85` — decays from wherever toward 0.0 (near-white) |

`confidence = 1.0` is the identity; `confidence = 0.0` gives greyscale. Applied via `apply_confidence(rgb, c)` in `color.py`.

### Color Function
Three independent mappings:

```
H = H(θ)                          # hue — a fitted function of mood direction
S = min(1.0, r * k)               # saturation — grows with mood intensity
V = V_floor + V_range * energy    # brightness — tracks energy, never reaches zero
```

`H(θ)` is a smooth periodic function fitted to eight anchor points derived from real Spotify audio feature data. See §7 for the anchors and §9 (Milestone 0) for how they are calibrated.

### Temporal Averaging
Each pixel represents a different time horizon over the (valence, energy) space:

- **Pixel 1** — most recent track's (valence, energy) → mapped directly.
- **Pixel 2** — exponentially weighted moving average (EWMA) over ~1 hour.
- **Pixel 3** — EWMA over ~4 hours.

EWMA update rule (applied to both valence and energy independently):

```
v̄ₙ = α * vₙ + (1 - α) * v̄ₙ₋₁
ēₙ = α * eₙ + (1 - α) * ēₙ₋₁
```

α is chosen so that the half-life of each pixel's memory matches its target horizon. No historical data needs to be stored — only the running average.

### Pixel State Machine
The system handles sparse early data gracefully. Transitions are gated on **track-bundle hit polls** only (artist-only and miss polls do not advance the counter):

| Track-hit poll count | Pixel 0 | Pixel 1 | Pixel 2 |
|---|---|---|---|
| 0 (inactive) | candle flicker | candle flicker | candle flicker |
| 1 – 20 (< ~1 hr) | recent | recent | recent |
| 21 – 80 (1 – 4 hr) | recent | 1h EWMA | 1h EWMA |
| > 80 (> ~4 hr) | recent | 1h EWMA | 4h EWMA |

On first Spotify activity after idle, all three pixels flare to life together via `StartupFlare`, then transition to `MoodTransition` once the flare completes.

---

## 7. Color Palette

### Design Principles
- **Ambient, not attention-seeking.** These lights live at the edge of peripheral vision on a working keyboard. They must never demand attention.
- **Transitions are slow** — 45–90 seconds to fully cross between states. Changes should be noticed only in retrospect.
- **No strobing, no beat-sync, no pulsing.** The only motion is a glacial brightness breathing. The only exception is the idle sparkle, which is near-invisible.
- **Maximum brightness is modest** — approximately 40–50% of NeoPixel ceiling. These are mood indicators, not accent lights.

### Anchor Colors
These are the eight reference points that constrain the H(θ) function. Positions in (valence, energy) space are estimates, to be refined by Milestone 0 data collection.

| Zone | Representative Artists | Est. (V, E) | Color | Hex |
|---|---|---|---|---|
| Industrial | Front Line Assembly, Ministry | (0.15, 0.85) | Blood crimson | `#6b0000` |
| Darkwave | TR/ST, Depeche Mode | (0.25, 0.55) | Ice blue | `#0a1a70` |
| Shoegaze | My Bloody Valentine, Slowdive | (0.30, 0.60) | Blue jeans | TBD |
| Zone-out / groovy | Orb, DJ Shadow, Amon Tobin, BOC | (0.40, 0.45) | Phosphor amber | `#6a3800` |
| Indie melancholy | Yo La Tengo, Cocteau Twins, NewDad | (0.35, 0.50) | Deep violet | `#2d0a50` |
| Ambient / relaxing | Robert Fripp, Ulrich Schnauss | (0.50, 0.15) | Evening teal | `#003d3d` |
| Americana / folksy | Fleet Foxes, Josh Ritter, Tom Petty | (0.70, 0.35) | Root beer | `#3d1000` |
| Fun / dance | LCD Soundsystem, Talking Heads | (0.75, 0.80) | Electric green | `#1a5a10` |

The shoegaze (V, E) estimate and hex are placeholders — to be anchored by M0 data from `gazey_gaze` playlist. The color should read as a warm, faded denim blue: somewhere between ice blue and deep violet, with more warmth than either.

The phosphor amber zone-out color intentionally sits near the center of the polar space (low r), so it presents as a warm, desaturated glow — appropriate for the mild, focused listening state it represents.

The color wheel distribution is intentionally spread: red, blue, mid-blue, amber, violet, teal, root beer, green — no two adjacent anchors compete visually.

---

## 8. Testing Strategy

### Unit Tests (`tests/unit/`)
Run on the development PC using pytest. Hardware modules (`machine`, `neopixel`, `network`) are replaced with thin stubs in `tests/unit/mocks/`. All mood math, color mapping, and EWMA averaging logic is tested here with no hardware required.

### Integration Tests (`tests/integration/`)
A mock Spotify API server (FastAPI, containerized with Docker) returns canned responses. Tests validate the full pipeline: Spotify poll → audio feature parsing → mood computation → color output. Tests against a live Spotify sandbox can also be run here with appropriate credentials.

### End-to-End Tests (`tests/end-to-end/`)
Hardware-in-loop. Flash the device, verify behavior over serial assertions and visual inspection. This tier is intentionally thin — it exists to catch things that only manifest on real hardware (memory pressure, timing, hardware-specific behavior).

### Mood Model Validation (M0 pipeline)
Four PC-side sub-projects (see §9, Milestone 0). Validates the color function against real audio feature data before any firmware is written.

---

## 9. Milestones

### Milestone 0 — Mood Model Calibration
**Goal**: Validate the polar color model against real audio feature data before writing firmware.

Four-stage whisky pipeline. Workflow:
1. `src/musical-cultivator/` — curates labeled track batches by zone (mine playlists, import URLs, scrape metadata). Output to `data/musical-gestalt/`.
2. `src/musical-mash-bill/` — three-phase enrichment: Phase 1 MusicBrainz (artist+title fuzzy match → MBID), Phase 2 AcousticBrainz (MBID → mood/BPM features), Phase 3 Last.fm (track.getTopTags for tracks with no AB coverage). Output written back to `data/musical-gestalt/` in-place.
3. `src/musical-distiller/` — derives (valence, energy) from enriched features via `mapping.toml` using priority order: AB features → Last.fm tag-zone vote → explicit zone anchor. Output to `data/musical-affective-memory/` (one JSON per source playlist).
4. `src/musical-bottler/` — compiles affective-memory JSONs into a versioned binary bundle (`data/musical-memory-bundle/memory-bundle-v{N}-{YYYYMMDD_HHMMSS}.bin`) in MMAR format for ESP32 binary search.
5. Notebook analysis — plot training tracks in (valence, energy) space, verify anchor positions, fit H(θ) to the anchor color set.
6. Notebook validation — apply the fitted function to a held-out test set. Verify colors feel musically correct.

Training set: ~680 labeled tracks across 8 zones. Test set: `something_new` (~313 tracks, multi-zone, no zone label — used for step 6 validation only).

**Spotify audio features**: `/v1/audio-features` is permanently blocked for apps registered after Nov 27, 2024. Audio features are sourced via AcousticBrainz archive (artist+title → MusicBrainz MBID, then MBID → AB features). Last.fm tags serve as a tertiary fallback for tracks absent from both archives. Essentia local audio analysis is a planned Phase 4 for tracks the user has on disk.

### Milestone 1 — Repo Scaffolding
Directory structure, `.gitignore`, `.gitattributes`, `CLAUDE.md`, hardware mock stubs, pytest configuration, Docker compose for mock Spotify server.

### Milestone 2 — WiFi and Configuration Server
AP-mode config server, WiFi credential capture and validation, mDNS, `Timer.ONE_SHOT` shutdown, NeoPixel status indicators during boot.

### Milestone 3 — Spotify OAuth
OAuth flow via config server, auth code exchange, refresh token storage, access token refresh logic.

### Milestone 4 — Spotify Polling
Recently-played fetch, 3-minute poll loop, MMAR bundle lookup for each track ID, error handling and backoff.

### Milestone 5 — Mood Engine
Polar transform, H(θ) implementation (using fitted function from M0), saturation and brightness mappings, EWMA accumulators for 1h and 4h windows, pixel state machine. (valence, energy) values sourced from on-flash MMAR bundle, not from Spotify API.

### Milestone 6 — Animations
Startup flare, idle sparkle, slow mood transitions, NeoPixel status indicators for error states.

### Milestone 7 — Hardening
Memory pressure testing, watchdog timer, error recovery, graceful handling of Spotify API downtime, graceful handling of WiFi disconnection.

### Milestone 8 — Physical Test Unit
Breadboard assembly. Validate full firmware stack on real hardware before permanent installation.

### Milestone 9 — Physical Forever Unit
Final keyboard installation. Drill shell, epoxy LEDs, steal 5V rail, route USB-C reflash port.
