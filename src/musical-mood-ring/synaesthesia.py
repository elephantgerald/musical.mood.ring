# synaesthesia.py
#
# Colour synaesthesia profile for musical-mood-ring.
#
# Loads synaesthesia.json from the ESP32's flash filesystem. Falls back to
# the built-in default profile if the file is absent — the device works
# out of the box without a personalised profile installed.
#
# A calibrated profile is produced by the M0 calibration notebook and
# flashed to the device alongside the MMAR track bundle. Each person can
# have their own; the mapping from mood direction to colour is personal.
#
# Usage:
#   import synaesthesia
#   h = synaesthesia.hue(theta_deg)
#   k = synaesthesia.saturation_k()

import math

try:
    import ujson as json          # MicroPython
except ImportError:
    import json                   # CPython (PC-side testing)

_PATH = "synaesthesia.json"

# ── Built-in default profile ───────────────────────────────────────────────
#
# hue_map: list of [theta_deg, hue_deg] pairs, sorted ascending by theta.
# The firmware does piecewise-linear interpolation between pairs, with
# circular wraparound between the last and first entries.
#
# Values below are derived from the design anchor positions in DESIGN.md §7.
# They are reasonable placeholders. Replace by flashing a synaesthesia.json
# produced by the M0 calibration notebook after H(θ) is fitted in issue #6.

_DEFAULT = {
    "version": 1,
    "name": "default",

    # Zone anchor positions in (valence, energy) space.
    # Used by the mood engine to label incoming tracks when the MMAR bundle
    # has no entry for a given track ID.
    "zone_anchors": {
        "industrial":       [0.15, 0.85],
        "darkwave":         [0.25, 0.55],
        "shoegaze":         [0.30, 0.60],
        "zone-out":         [0.40, 0.45],
        "indie-melancholy": [0.35, 0.50],
        "ambient":          [0.50, 0.15],
        "americana":        [0.70, 0.35],
        "fun/dance":        [0.75, 0.80],
    },

    # Angle → hue anchor table. Firmware interpolates between these points.
    # theta: mood direction in degrees (atan2(energy-0.5, valence-0.5) % 360)
    # hue:   target HSV hue in degrees (0=red, 120=green, 240=blue)
    "hue_map": [
        [ 50.2, 112.0],   # fun/dance      → electric green
        [135.0,   0.0],   # industrial     → blood crimson
        [153.4, 210.0],   # shoegaze       → blue jeans  (placeholder)
        [168.7, 231.0],   # darkwave       → ice blue
        [180.0, 270.0],   # indie-melancholy → deep violet
        [206.6,  32.0],   # zone-out       → phosphor amber
        [270.0, 180.0],   # ambient        → evening teal
        [323.1,  16.0],   # americana      → root beer
    ],

    # Saturation: S = min(1.0, r * saturation_k)
    # r is the polar distance from mood-space centre (0 = neutral, ~0.71 = extreme)
    "saturation_k": 2.0,

    # Brightness: V = brightness_floor + brightness_range * energy
    # Ceiling = floor + range ≈ 0.50 (50% of NeoPixel ceiling, per design spec)
    "brightness_floor": 0.15,
    "brightness_range": 0.35,

    # EWMA decay factors for the 1-hour and 4-hour pixel windows.
    # Derived from: alpha = 1 - 0.5 ^ (1 / half_life_in_polls)
    # at 3-minute poll interval: 1h = 20 polls, 4h = 80 polls.
    "ewma_alpha_1h": 0.034,
    "ewma_alpha_4h": 0.009,
}


# ── Profile loading ────────────────────────────────────────────────────────

def _load():
    try:
        with open(_PATH) as f:
            return json.load(f)
    except OSError:
        return _DEFAULT


_p = _load()


# ── Public interface ───────────────────────────────────────────────────────

def hue(theta_deg):
    """Map a mood direction angle to a hue (both in degrees, 0–360).

    Uses piecewise linear interpolation over the hue_map anchor table,
    with circular wraparound between the last and first entries.
    Interpolation takes the shortest angular path for hue transitions.
    """
    hm = _p["hue_map"]
    n  = len(hm)
    t  = theta_deg % 360

    for i in range(n):
        t0, h0 = hm[i]
        t1, h1 = hm[(i + 1) % n]
        if i == n - 1:
            # Wraparound segment: last entry → first entry through 360°/0°
            t1 += 360
            if t < t0:
                t += 360
        if t0 <= t < t1:
            frac = (t - t0) / (t1 - t0)
            dh = (h1 - h0 + 180) % 360 - 180   # shortest angular distance
            return (h0 + frac * dh) % 360

    return hm[0][1]   # unreachable with a well-formed hue_map, but safe


def saturation_k():
    """Scale factor for saturation: S = min(1.0, r * k)."""
    return _p["saturation_k"]


def brightness_floor():
    """Minimum brightness (0–1). LEDs never go fully dark."""
    return _p["brightness_floor"]


def brightness_range():
    """Brightness range above the floor. Maximum = floor + range."""
    return _p["brightness_range"]


def ewma_alpha(window):
    """EWMA decay factor for '1h' or '4h' pixel time window."""
    return _p["ewma_alpha_1h"] if window == "1h" else _p["ewma_alpha_4h"]


def zone_anchors():
    """Dict of zone name → [valence, energy] anchor positions."""
    return _p["zone_anchors"]


def profile_name():
    """Human-readable name of the loaded profile."""
    return _p.get("name", "unknown")
