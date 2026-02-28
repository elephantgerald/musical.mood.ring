"""
twinkle_test.py — Tune the IdleSparkle twinkle brightness

Runs the IdleSparkle pattern at PEAK. Adjust PEAK below and re-run until
the twinkle looks right, then copy the value to _IDLE_PEAK in lights.py.

Run intensity_test.py first to find the minimum visible threshold.

Run:
    mpremote connect /dev/ttyUSB0 run tests/hardware/twinkle_test.py

Ctrl-C to stop (pixels go dark).
"""

import machine
import neopixel
import time
import urandom

_PIN  = 4   # GPIO 4 = A5 on HUZZAH32
_NUM  = 3

np = neopixel.NeoPixel(machine.Pin(_PIN), _NUM)

# ── Tune this, then copy to _IDLE_PEAK in lights.py ──────────────────────────
PEAK = (28, 30, 45)

MIN_MS     = 2000   # min pause between twinkles per pixel
MAX_MS     = 8000   # max pause between twinkles per pixel
FLICKER_MS = 250    # how long each twinkle lasts
FRAME_MS   = 50


def _show(colors):
    for i, c in enumerate(colors):
        np[i] = c
    np.write()


def _off():
    _show([(0, 0, 0)] * _NUM)


px = [
    {"countdown": urandom.randint(0, MAX_MS), "flickering": False, "flicker_left": 0}
    for _ in range(_NUM)
]

print(f"Twinkle at PEAK={PEAK}  (Ctrl-C to stop)")

try:
    while True:
        colors = []
        for p in px:
            if p["flickering"]:
                p["flicker_left"] -= FRAME_MS
                if p["flicker_left"] <= 0:
                    p["flickering"] = False
                    p["countdown"]  = urandom.randint(MIN_MS, MAX_MS)
                colors.append(PEAK)
            else:
                p["countdown"] -= FRAME_MS
                if p["countdown"] <= 0:
                    p["flickering"]   = True
                    p["flicker_left"] = FLICKER_MS
                    colors.append(PEAK)
                else:
                    colors.append((0, 0, 0))
        _show(colors)
        time.sleep_ms(FRAME_MS)

except KeyboardInterrupt:
    _off()
