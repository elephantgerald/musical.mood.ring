"""
whitenoise_test.py — Filtered white noise LED animation

Each pixel gets an independent stream of uniform random noise, EWMA-smoothed
to control how fast brightness transitions.  Tweak _ALPHA, _FLOOR, _CEIL to
taste — then optionally steal the approach back into lights.py.

Parameters:
  _ALPHA      — smoothing factor (lower = slower/dreamier, higher = snappier)
  _FLOOR/CEIL — per-pixel amplitude range; slightly detuned for independence

Run:
    mpremote connect /dev/ttyUSB0 run tests/hardware/whitenoise_test.py

Ctrl-C to stop (pixels go dark).
"""

import machine
import math
import neopixel
import random
import time

_PIN      = 4    # GPIO 4 = A5 on HUZZAH32
_NUM      = 3
_FRAME_MS = 100   # 20 fps

_PEAK  = (28, 30, 45)   # cool white at brightness 1.0

# ── Tune these ────────────────────────────────────────────────────────────────

_ALPHA = 0.20   # EWMA alpha — 0.05 = very slow drift, 0.5 = snappy flicker

_FLOOR = 0.02   # hard clamp — minimum brightness
_CEIL  = 0.40   # hard clamp — maximum brightness
_MU    = 0.18   # bell-curve centre
_SIGMA = 0.20   # std dev — 68% of raw samples land in [0.02, 0.38]

# ─────────────────────────────────────────────────────────────────────────────

def _gauss():
    """Box-Muller normal sample — MicroPython has no random.gauss()."""
    u1 = random.random() or 1e-9   # guard against exact 0 in log
    u2 = random.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


np = neopixel.NeoPixel(machine.Pin(_PIN), _NUM)

_br = [_MU] * _NUM   # start at the mean


def _show():
    for i in range(_NUM):
        target  = min(_CEIL, max(_FLOOR, _MU + _SIGMA * _gauss()))
        _br[i]  = _ALPHA * target + (1.0 - _ALPHA) * _br[i]
        v = _br[i]
        np[i] = (int(_PEAK[0] * v), int(_PEAK[1] * v), int(_PEAK[2] * v))
    np.write()


tick = 0
print("White noise twinkle  (Ctrl-C to stop)")
print(f"  alpha={_ALPHA}  mu={_MU}  sigma={_SIGMA}  floor={_FLOOR}  ceil={_CEIL}")
print()

try:
    while True:
        _show()
        if tick % 20 == 0:   # print readout every ~1 s
            print(f"  px0={_br[0]:.2f}  px1={_br[1]:.2f}  px2={_br[2]:.2f}")
        tick += 1
        time.sleep_ms(_FRAME_MS)

except KeyboardInterrupt:
    for i in range(_NUM):
        np[i] = (0, 0, 0)
    np.write()
