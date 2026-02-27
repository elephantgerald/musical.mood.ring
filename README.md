# musical.mood.ring

Three tiny lights, mounted inside a mechanical keyboard, that glow with the emotional color of whatever you've been listening to on Spotify.

The leftmost light reflects the most recent track. The middle light is a slow average of the last hour. The right light holds the last four hours. When you've been working through dark electronic music all afternoon, the lights know. When you switched to something bright and dancey, you'll watch them drift.

No companion app. No PC script that has to be running. The ESP32 inside the keyboard handles everything — WiFi, Spotify auth, polling, math, LEDs.

---

## How It Works

Every track can be described by two numbers: **valence** (how positive or dark the music feels) and **energy** (how intense or calm it is). These two values place a track in a 2D mood space. The mood space is mapped to color using a polar coordinate model — the direction from neutral determines the hue, the distance from neutral determines how saturated the color is, and energy determines brightness.

The result is a continuous color field with no hard edges between moods. Dark, grinding industrial metal sits at blood crimson. Slow ambient drifts toward evening teal. Bright, danceable pop lands at electric green. The transitions between them are smooth and musical.

The three pixels show three different time slices of that mood space:

| Pixel | Time window |
|---|---|
| 1 — leftmost | Most recent 3-minute poll |
| 2 — middle | Exponentially weighted average over the last hour |
| 3 — rightmost | Exponentially weighted average over the last four hours |

When Spotify has been quiet, all three sparkle softly. When music starts, they flare to life together and slowly differentiate as history builds up.

### Personalised color mapping

The angle-to-hue mapping (`H(θ)`) is personal. Everyone's color intuition is slightly different — the hue that reads as "brooding" to one person may read as "serene" to another. The project stores this as a small JSON **synaesthesia profile** that gets flashed to the device alongside the mood bundle. A calibration notebook lets each person tune (or accept) the default mapping and export their own profile. The device works out of the box with the built-in defaults; the profile is an optional personalisation layer.

### A note on Spotify's API

Spotify's audio features endpoint (`/v1/audio-features`) has been blocked for new developer apps since late 2024. This project works around it: valence and energy values are pre-computed offline from a combination of MusicBrainz, AcousticBrainz, and Last.fm data, then compiled into a compact binary lookup file that lives on the ESP32's flash. At runtime, the device does a binary search in that file for each recently-played track ID — no audio analysis happens on-device, and no blocked API is called.

---

## Hardware

The final build lives inside a **WASD CODE 2.0** keyboard shell:

- **Microcontroller**: ESP32 running MicroPython
- **LEDs**: 3× WS2812B NeoPixels, epoxy-mounted in three drilled holes in the keyboard's top shell
- **Power**: 5V tapped from the keyboard's internal USB rail
- **Reflash access**: The ESP32's USB-C port is routed to an externally accessible connector on the keyboard, so firmware can be updated without disassembly

The LEDs also serve as a status display — slow white for WiFi connecting, blue pulse while waiting for setup, steady green breathing while healthy, red flash on error.

---

## Setup

On first boot, the ESP32 brings up a temporary WiFi access point. Connect to it,
open a browser, and a configuration page collects WiFi credentials. After
reconnecting, a second page handles Spotify OAuth. One reboot, done. The device
then advertises itself on the home network as `musical-mood-ring.local`.

To update the mood lookup bundle after adding music to your library, run the
offline pipeline on a PC and flash the new binary to the device.

Developer setup (virtualenv, API keys, ESP32 flashing):
→ [`docs/SETUP.md`](docs/SETUP.md)

Spotify app registration (redirect URI, user allowlist, API limitations):
→ [`docs/SPOTIFY-APP-REGISTRATION.md`](docs/SPOTIFY-APP-REGISTRATION.md)

---

## Status

Software is complete through M7. Waiting on hardware (NeoPixel chain) for M8.

**Milestones:**

| # | Name | Status |
|---|---|---|
| M0 | Mood model calibration (offline pipeline) | Complete |
| M1 | Firmware scaffold + unit test harness | Complete |
| M2 | WiFi + configuration server | Complete |
| M3 | Spotify OAuth | Complete |
| M4 | Spotify polling | Complete |
| M5 | Mood engine | Complete |
| M6 | Animations | Complete |
| M7 | Hardening | Complete |
| M8 | Physical test unit (breadboard) | In progress |
| M9 | Physical forever unit (keyboard installation) | Not started |

---

## Project Structure

```
src/
├── mood-model/           # M0 calibration notebook (Jupyter)
├── musical-cultivator/   # Stage 1 — collect track IDs into data/musical-gestalt/
├── musical-mash-bill/    # Stage 2 — enrich with MusicBrainz, AcousticBrainz, Last.fm
├── musical-distiller/    # Stage 3 — derive (valence, energy) per track
├── musical-bottler/      # Stage 4 — compile binary MMAR bundle for ESP32
└── musical-mood-ring/    # MicroPython ESP32 firmware
data/
├── musical-gestalt/           # Raw track batches + enrichment data
├── musical-affective-memory/  # Derived (valence, energy) per track
├── musical-memory-bundle/     # Compiled MMAR binaries ready to flash
└── synaesthesia/              # Generated colour profiles (gitignored; flash to device)
build/
├── reset.sh              # Erase and reflash the ESP32 with the latest MicroPython
└── firmware/             # Downloaded MicroPython binaries (gitignored)
```

See [`DESIGN.md`](DESIGN.md) for the full architecture, color model math, WiFi configuration pattern, and milestone detail.

---

## License

Apache 2.0 — see [`LICENSE.md`](LICENSE.md).
