"""
twinkle_test.py — Tune the IdleSparkle additive-synthesis animation

Five sine waves per pixel summed together — like analog oscillators:
  3 fast, small waves (periods ~5, 8, 12 s) → chaotic texture, floor ≤ 0.20
  1 medium half-rectified wave (~67 s)       → ~0.60 peak roughly once/min
  1 slow  half-rectified wave  (~330 s)      → ~0.90 peak roughly once/5 min

Each pixel runs on slightly detuned periods so they move independently.

To tune:
  - Adjust _AMED to change the height of medium peaks (~0.60 target)
  - Adjust _ASLO to change the height of rare peaks   (~0.90 target)
  - Adjust T values in _PIXELS to change peak frequency
  After tuning, copy final values into lights.py (_IDLE_* constants).

Run:
    mpremote connect /dev/ttyUSB0 run tests/hardware/twinkle_test.py

Ctrl-C to stop (pixels go dark).
"""

import machine
import math
import neopixel
import time

_PIN      = 4    # GPIO 4 = A5 on HUZZAH32
_NUM      = 3
_FRAME_MS = 50
_TAU      = 2.0 * math.pi

np = neopixel.NeoPixel(machine.Pin(_PIN), _NUM)

# ── Tune these, then copy to lights.py ───────────────────────────────────────

_PEAK = (28, 30, 45)   # cool white at full brightness (1.0)

_DC   = 0.04   # DC floor  — always-on dim glow
_A1   = 0.05   # fast wave 1  ─┐
_A2   = 0.04   # fast wave 2   ├ together ±0.12: chaotic texture, floor ≤ 0.20
_A3   = 0.03   # fast wave 3  ─┘
_AMED = 0.44   # medium swell amplitude → ~0.60 peak per ~67 s  (~1 / min)
_ASLO = 0.74   # slow swell amplitude   → ~0.90 peak per ~330 s (~1 / 5 min)

# Per-pixel: (phase_offset, T_fast1, T_fast2, T_fast3, T_medium, T_slow)
_PIXELS = (
    (0.0,  5.1,  7.7, 11.9,  67.0, 331.0),   # pixel 0
    (2.1,  5.3,  8.1, 12.7,  71.0, 349.0),   # pixel 1
    (4.2,  4.9,  7.3, 11.3,  61.0, 313.0),   # pixel 2
)

# ─────────────────────────────────────────────────────────────────────────────

def _brightness(t, phi, T1, T2, T3, Tm, Ts):
    b  = _DC
    b += _A1   * math.sin(_TAU * t / T1 + phi)
    b += _A2   * math.sin(_TAU * t / T2 + phi * 1.3)
    b += _A3   * math.sin(_TAU * t / T3 + phi * 0.7)
    b += _AMED * max(0.0, math.sin(_TAU * t / Tm + phi * 0.5))
    b += _ASLO * max(0.0, math.sin(_TAU * t / Ts + phi * 0.3))
    return max(0.0, min(1.0, b))


def _show(t):
    for i, params in enumerate(_PIXELS):
        br = _brightness(t, *params)
        np[i] = (int(_PEAK[0] * br), int(_PEAK[1] * br), int(_PEAK[2] * br))
    np.write()


t    = 0.0
dt   = _FRAME_MS / 1000.0
tick = 0

print("Additive-synthesis twinkle  (Ctrl-C to stop)")
print("  floor ≤ 0.20 | medium ~0.60 / min | rare ~0.90 / 5 min")
print()

try:
    while True:
        _show(t)
        if tick % 20 == 0:   # print brightness every ~1 s
            b = [_brightness(t, *p) for p in _PIXELS]
            print(f"  t={t:7.1f}s   px0={b[0]:.2f}  px1={b[1]:.2f}  px2={b[2]:.2f}")
        t    += dt
        tick += 1
        time.sleep_ms(_FRAME_MS)

except KeyboardInterrupt:
    for i in range(_NUM):
        np[i] = (0, 0, 0)
    np.write()
