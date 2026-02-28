"""
rgb_color_test.py — NeoPixel hardware sanity check

Two-phase test:
  1. Color cycle — one pass through all 3 rotations to confirm every pixel
     can produce red, green, and blue:
       [R, G, B] → [B, R, G] → [G, B, R]

  2. Breathe white — all pixels ramp black → white → black once.

Wiring (HUZZAH32):
  Data → A5  (GPIO 4)
  GND  → GND
  5 V  → USB

Run directly from the repo (does not need to be copied to flash):
    mpremote connect /dev/ttyUSB0 run tests/hardware/rgb_color_test.py

Ctrl-C to stop (pixels go dark).
"""

import machine
import neopixel
import time

_PIN      = 4      # GPIO 4 = A5 on HUZZAH32
_NUM      = 3
_STEP_MS  = 8      # ms per brightness step during breathing


np = neopixel.NeoPixel(machine.Pin(_PIN), _NUM)


def _show(colors):
    for i, c in enumerate(colors):
        np[i] = c
    np.write()


def _off():
    _show([(0, 0, 0)] * _NUM)


try:
    # ── Phase 1: color cycle ──────────────────────────────────────────────────
    base = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    for r in range(_NUM):
        rotated = [base[(i - r) % _NUM] for i in range(_NUM)]
        _show(rotated)
        time.sleep_ms(800)

    _off()
    time.sleep_ms(500)

    # ── Phase 2: breathe white black → white → black ──────────────────────────
    for v in list(range(0, 256, 2)) + list(range(255, -1, -2)):
        _show([(v, v, v)] * _NUM)
        time.sleep_ms(_STEP_MS)

    _off()

except KeyboardInterrupt:
    _off()
