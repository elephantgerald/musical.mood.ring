"""
flicker_test.py — Hybrid candle-flicker + deterministic swell animation

Gaussian white noise drives the baseline flicker (organic, never repeating).
Swells layer on top for occasional bright peaks:

  baseline  Gaussian noise (μ, σ) → candle texture, stays in [FLOOR, NOISE_CEIL]
  medium    sin^6 swell (~67 s)   → peak near 0.60 roughly once/min
  slow      bell-strike envelope  → strikes to _ASLO then decays exponentially,
                                    roughly once every 6 min per pixel

The slow peak mimics striking a bell: instantaneous attack at the zero-crossing
of the slow swell period, followed by exponential amplitude decay (_RING_DECAY
per frame).  Medium swell keeps sin^6 — only the rare high peaks get the bell.

Each pixel uses slightly detuned swell periods so they breathe independently.
EWMA smooths the combined signal frame-to-frame.

Run:
    mpremote connect /dev/ttyUSB0 run tests/hardware/flicker_test.py

Ctrl-C to stop (pixels go dark).
"""

import machine
import math
import neopixel
import random
import time

_PIN      = 4    # GPIO 4 = A5 on HUZZAH32
_NUM      = 3
_FRAME_MS = 50   # 20 fps

_TAU  = 2.0 * math.pi
_PEAK = (28, 30, 45)   # cool white at brightness 1.0

# ── Tune these ────────────────────────────────────────────────────────────────

_ALPHA      = 0.15   # EWMA smoothing — lower = dreamier, higher = snappier

# Noise baseline (candle flicker texture)
_MU         = 0.08   # noise centre — keeps baseline dim, leaves headroom for swells
_SIGMA      = 0.06   # std dev — 68% of noise in [0.02, 0.14]
_FLOOR      = 0.01   # hard floor
_NOISE_CEIL = 0.20   # noise hard cap — swells push above this

# Medium swell (sin^6)
_AMED = 0.52   # amplitude → ~0.60 total peak
_POW  = 6      # sin^6 — collapses duty cycle to ~15%

# Slow swell — bell-strike envelope
_ASLO       = 0.82   # strike amplitude → ~0.90 total peak
_RING_DECAY = 0.977  # per-frame multiplier — ring halves in ~1.5 s at 20 fps

# Per-pixel swell parameters: (phi, T_med, t_off_med, T_slow, t_off_slow)
# Slightly detuned so pixels breathe independently.
# Slow periods ~360 s → bell strikes roughly once per 6 min per pixel.
_PIXELS = (
    (0.0,  67.0,  40.2,  360.0, 216.0),   # pixel 0
    (2.1,  71.0,  49.7,  379.0, 265.3),   # pixel 1
    (4.2,  61.0,  48.8,  341.0, 272.8),   # pixel 2
)

# ─────────────────────────────────────────────────────────────────────────────

def _gauss():
    """Box-Muller normal sample — MicroPython has no random.gauss()."""
    u1 = random.random() or 1e-9
    u2 = random.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


np = neopixel.NeoPixel(machine.Pin(_PIN), _NUM)

_br         = [_MU]   * _NUM   # smoothed output brightness
_ring_amp   = [0.0]   * _NUM   # current bell-ring amplitude (decays toward 0)
_was_silent = [True]  * _NUM   # was slow swell at zero last frame?


def _show(t):
    for i, (phi, Tm, t_off_m, Ts, t_off_s) in enumerate(_PIXELS):
        # ── Noise baseline ────────────────────────────────────────────────
        noise = min(_NOISE_CEIL, max(_FLOOR, _MU + _SIGMA * _gauss()))

        # ── Medium swell (sin^6) ──────────────────────────────────────────
        sm     = max(0.0, math.sin(_TAU * (t + t_off_m) / Tm))
        medium = _AMED * sm ** _POW

        # ── Slow swell — bell-strike envelope ────────────────────────────
        slow_raw = math.sin(_TAU * (t + t_off_s) / Ts)
        if slow_raw > 0 and _was_silent[i]:   # rising zero-crossing → strike
            _ring_amp[i] = _ASLO
        _was_silent[i] = slow_raw <= 0
        _ring_amp[i]  *= _RING_DECAY           # exponential decay each frame

        # ── Combine, smooth, write ────────────────────────────────────────
        target  = min(1.0, noise + medium + _ring_amp[i])
        _br[i]  = _ALPHA * target + (1.0 - _ALPHA) * _br[i]
        v = _br[i]
        np[i] = (int(_PEAK[0] * v), int(_PEAK[1] * v), int(_PEAK[2] * v))

    np.write()


t    = 0.0
dt   = _FRAME_MS / 1000.0
tick = 0

print("Flicker + bell-strike  (Ctrl-C to stop)")
print(f"  noise mu={_MU} sigma={_SIGMA}  amed={_AMED} pow={_POW}")
print(f"  bell aslo={_ASLO} decay={_RING_DECAY}/frame  alpha={_ALPHA}")
print()

try:
    while True:
        _show(t)
        if tick % 20 == 0:
            print(f"  t={t:7.1f}s   px0={_br[0]:.2f}  px1={_br[1]:.2f}  px2={_br[2]:.2f}  ring={[round(r,2) for r in _ring_amp]}")
        t    += dt
        tick += 1
        time.sleep_ms(_FRAME_MS)

except KeyboardInterrupt:
    for i in range(_NUM):
        np[i] = (0, 0, 0)
    np.write()
