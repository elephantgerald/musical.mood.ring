#!/usr/bin/env python3
"""
twinkle_waveform.py — Visualise the IdleSparkle additive-synthesis waveforms.

Plots brightness over a configurable window for all 3 pixels, plus the
individual wave contributions.  All key parameters are tunable via CLI flags;
final values can be copied back into lights.py.

Run from the repo root:
    python src/mood-model/twinkle_waveform.py [options]

Examples:
    python src/mood-model/twinkle_waveform.py
    python src/mood-model/twinkle_waveform.py --smooth 0.15 --pow 4
    python src/mood-model/twinkle_waveform.py --med-period 90 --slow-period 480
    python src/mood-model/twinkle_waveform.py --amed 0.4 --aslo 0.7 --dc 0.06
    python src/mood-model/twinkle_waveform.py --no-texture --duration 30
"""

import argparse
import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# ── Defaults (mirrors lights.py) ─────────────────────────────────────────────

_TAU = 2.0 * math.pi

_D_DC          = 0.04
_D_A1, _D_A2, _D_A3 = 0.05, 0.04, 0.03
_D_AMED        = 0.56
_D_ASLO        = 0.86
_D_POW         = 6
_D_SMOOTH      = 0.3
_D_MED_SCALE   = 1.0   # multiplier on per-pixel T_med values
_D_SLOW_SCALE  = 1.0   # multiplier on per-pixel T_slow values
_D_DURATION    = 20    # minutes

# Per-pixel base parameters (phi, T1, T2, T3, T_med, t_off_med, T_slow, t_off_slow)
_PIXELS_BASE = (
    (0.0,  5.1,  7.7, 11.9,  67.0,  40.2,  331.0, 198.6),
    (2.1,  5.3,  8.1, 12.7,  71.0,  49.7,  349.0, 244.3),
    (4.2,  4.9,  7.3, 11.3,  61.0,  48.8,  313.0, 250.4),
)

# ── CLI ───────────────────────────────────────────────────────────────────────

p = argparse.ArgumentParser(description="Visualise IdleSparkle waveform")
p.add_argument("--smooth",      type=float, default=_D_SMOOTH,
               metavar="α",     help=f"EWMA alpha 0–1 (default {_D_SMOOTH}); 0=max smooth, 1=raw")
p.add_argument("--pow",         type=float, default=_D_POW,
               metavar="N",     help=f"swell power (default {_D_POW}); lower=broader peaks")
p.add_argument("--amed",        type=float, default=_D_AMED,
               metavar="A",     help=f"medium swell amplitude (default {_D_AMED})")
p.add_argument("--aslo",        type=float, default=_D_ASLO,
               metavar="A",     help=f"slow swell amplitude (default {_D_ASLO})")
p.add_argument("--dc",          type=float, default=_D_DC,
               metavar="V",     help=f"DC floor (default {_D_DC})")
p.add_argument("--med-period",  type=float, default=None,
               metavar="S",     help="override medium swell period in seconds (default ~67s)")
p.add_argument("--slow-period", type=float, default=None,
               metavar="S",     help="override slow swell period in seconds (default ~330s)")
p.add_argument("--no-texture",  action="store_true",
               help="zero out fast texture waves (isolate swells)")
p.add_argument("--duration",    type=float, default=_D_DURATION,
               metavar="MIN",   help=f"plot window in minutes (default {_D_DURATION})")
p.add_argument("--out",         default="src/mood-model/twinkle_waveform.png",
               help="output PNG path")
args = p.parse_args()

# ── Build per-pixel params with any overrides ─────────────────────────────────

def _make_pixels(med_override, slow_override):
    out = []
    for phi, T1, T2, T3, Tm, t_off_m, Ts, t_off_s in _PIXELS_BASE:
        if med_override is not None:
            # Keep relative detuning (±3%) around the new centre
            ratio = Tm / 67.0
            Tm = med_override * ratio
            t_off_m = Tm * 0.6  # reset t_off proportionally
        if slow_override is not None:
            ratio = Ts / 331.0
            Ts = slow_override * ratio
            t_off_s = Ts * 0.6
        out.append((phi, T1, T2, T3, Tm, t_off_m, Ts, t_off_s))
    return out

_PIXELS = _make_pixels(args.med_period, args.slow_period)

A1 = 0.0 if args.no_texture else _D_A1
A2 = 0.0 if args.no_texture else _D_A2
A3 = 0.0 if args.no_texture else _D_A3

# ── Waveform functions ────────────────────────────────────────────────────────

def brightness(t, phi, T1, T2, T3, Tm, t_off_m, Ts, t_off_s):
    b  = args.dc
    b += A1 * math.sin(_TAU * t / T1 + phi)
    b += A2 * math.sin(_TAU * t / T2 + phi * 1.3)
    b += A3 * math.sin(_TAU * t / T3 + phi * 0.7)
    sm = max(0.0, math.sin(_TAU * (t + t_off_m) / Tm))
    b += args.amed * sm ** args.pow
    ss = max(0.0, math.sin(_TAU * (t + t_off_s) / Ts))
    b += args.aslo * ss ** args.pow
    return max(0.0, min(1.0, b))


def contributions(t, phi, T1, T2, T3, Tm, t_off_m, Ts, t_off_s):
    fast = (args.dc
            + A1 * math.sin(_TAU * t / T1 + phi)
            + A2 * math.sin(_TAU * t / T2 + phi * 1.3)
            + A3 * math.sin(_TAU * t / T3 + phi * 0.7))
    sm   = max(0.0, math.sin(_TAU * (t + t_off_m) / Tm))
    ss   = max(0.0, math.sin(_TAU * (t + t_off_s) / Ts))
    med  = args.amed * sm ** args.pow
    slow = args.aslo * ss ** args.pow
    return fast, med, slow


def smooth(raw_arr, alpha):
    """Causal EWMA — matches IdleSparkle._SMOOTH logic."""
    out = np.empty_like(raw_arr)
    s = 0.0
    for j, v in enumerate(raw_arr):
        s = alpha * v + (1.0 - alpha) * s
        out[j] = s
    return out

# ── Generate data ─────────────────────────────────────────────────────────────

DURATION_S = int(args.duration * 60)
SAMPLE_HZ  = 4
t_arr = np.linspace(0, DURATION_S, DURATION_S * SAMPLE_HZ)

# ── Plot ──────────────────────────────────────────────────────────────────────

title_parts = [f"pow={args.pow}", f"α={args.smooth}",
               f"dc={args.dc}", f"amed={args.amed}", f"aslo={args.aslo}"]
if args.med_period:
    title_parts.append(f"med={args.med_period}s")
if args.slow_period:
    title_parts.append(f"slow={args.slow_period}s")
if args.no_texture:
    title_parts.append("no-texture")

fig, axes = plt.subplots(3, 1, figsize=(16, 9), sharex=True)
fig.suptitle(f"IdleSparkle — {args.duration:.0f} min  [{', '.join(title_parts)}]",
             fontsize=11, y=0.98)

px_colors = ["#d95f02", "#1b9e77", "#7570b3"]
ref_lines  = [
    (0.9, "--", 0.35, "#999", "0.90 rare peak target"),
    (0.6, "--", 0.45, "#999", "0.60 medium peak target"),
    (0.2, ":",  0.55, "#aaa", "0.20 floor target"),
]

for i, (ax, params) in enumerate(zip(axes, _PIXELS)):
    br    = np.array([brightness(t, *params) for t in t_arr])
    fast  = np.array([contributions(t, *params)[0] for t in t_arr])
    med   = np.array([contributions(t, *params)[1] for t in t_arr])
    slow  = np.array([contributions(t, *params)[2] for t in t_arr])
    br_sm = smooth(br, args.smooth)

    ax.fill_between(t_arr / 60, 0, np.clip(fast, 0, None),
                    alpha=0.25, color=px_colors[i], label="fast texture")
    ax.fill_between(t_arr / 60, np.clip(fast, 0, None),
                    np.clip(fast + med, 0, None),
                    alpha=0.30, color="steelblue", label="medium swell")
    ax.fill_between(t_arr / 60, np.clip(fast + med, 0, None),
                    np.clip(fast + med + slow, 0, None),
                    alpha=0.35, color="gold", label="slow swell")

    ax.plot(t_arr / 60, br, color=px_colors[i], linewidth=0.6, alpha=0.35,
            label="raw" if i == 0 else None)
    ax.plot(t_arr / 60, br_sm, color=px_colors[i], linewidth=1.2, alpha=0.95,
            label=f"smoothed (α={args.smooth})" if i == 0 else None)

    for y, ls, alpha, color, label in ref_lines:
        ax.axhline(y, linestyle=ls, color=color, alpha=alpha, linewidth=1.0,
                   label=label if i == 0 else None)

    ax.set_ylim(-0.02, 1.08)
    ax.set_ylabel(f"Pixel {i}", fontsize=10)
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.2))
    ax.yaxis.set_minor_locator(ticker.MultipleLocator(0.1))
    ax.grid(True, which="major", alpha=0.15)
    ax.tick_params(labelsize=8)

x_step = max(1, int(args.duration / 10))
axes[-1].set_xlabel("Time (minutes)", fontsize=10)
axes[-1].xaxis.set_major_locator(ticker.MultipleLocator(x_step))
axes[-1].xaxis.set_minor_locator(ticker.MultipleLocator(x_step / 4))

axes[0].legend(loc="upper right", fontsize=8, framealpha=0.85, ncol=5)

plt.tight_layout()
plt.savefig(args.out, dpi=150, bbox_inches="tight")
print(f"Saved: {args.out}")
plt.show()
