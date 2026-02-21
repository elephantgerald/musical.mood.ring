# musical.mood.ring

A self-contained ESP32 mood ring that surfaces emotional sentiment from your Spotify listening history as ambient light on your keyboard.

Three NeoPixels, mounted inside a WASD CODE 2.0 keyboard shell, glow with colors derived from the audio characteristics of your recent listening — the last track, the last hour, the last four hours. When Spotify is quiet, the lights softly sparkle. When music starts, they wake up together and gradually differentiate as listening history accumulates.

No companion app. No cloud intermediary. The ESP32 handles everything.

---

## Hardware

- **Microcontroller**: ESP32 (MicroPython)
- **LEDs**: 3× WS2812B NeoPixels, epoxy-mounted in drilled keyboard shell
- **Power**: 5V stolen from keyboard USB rail
- **Reflash port**: ESP32 USB-C routed to an externally accessible port on the keyboard

## Concept

Spotify exposes audio features for every track — notably `valence` (musical positivity) and `energy` (intensity). These two values place a track in a 2D mood space. The mood space is mapped to a continuous color field using a polar coordinate model: direction from neutral determines hue, distance from neutral determines saturation, and energy drives brightness.

The three pixels represent:
- **Pixel 1** — the most recent 3-minute poll
- **Pixel 2** — an exponentially weighted average over the last hour
- **Pixel 3** — an exponentially weighted average over the last four hours

See [`DESIGN.md`](DESIGN.md) for a full account of the architecture, color model, WiFi configuration pattern, and milestone plan.

---

## Project Structure

```
musical.mood.ring/
├── src/
│   ├── esp32/          # MicroPython firmware
│   └── mood-model/     # PC-side model calibration (Jupyter, Python)
├── tests/
│   ├── unit/           # Hardware-mocked unit tests (pytest)
│   ├── integration/    # Tests against mock Spotify API
│   └── end-to-end/     # Hardware-in-loop
├── build/              # Flash and deploy scripts
├── docs/               # Supplementary documentation
├── DESIGN.md           # Architecture and design decisions
├── ETHOS.md            # Project philosophy and structure rules
└── README.md           # This file
```

## License

Apache 2.0 — see [`LICENSE.md`](LICENSE.md).
