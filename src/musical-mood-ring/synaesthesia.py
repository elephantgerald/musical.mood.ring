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
# This module is a pure profile accessor: it holds no colour maths. The
# interpolation over color_map lives in color.py, which is where the Lab
# conversions are. Field lookups fall back to _DEFAULT key by key, so a
# stale v1 profile left on flash degrades to the built-in palette rather
# than raising.
#
# Usage:
#   import synaesthesia
#   anchors = synaesthesia.color_map()
#   b       = synaesthesia.master_brightness()

try:
    import ujson as json          # MicroPython
except ImportError:
    import json                   # CPython (PC-side testing)

_PATH = "synaesthesia.json"

# ── Built-in default profile ───────────────────────────────────────────────
#
# color_map: list of [theta_deg, "#RRGGBB"] pairs, sorted ascending by theta.
# color.py interpolates between adjacent pairs in CIELAB, with circular
# wraparound between the last and first entries.
#
# Eight of the nine knots are the calibrated palette (issue #9): one colour
# per zone, chosen for a minimum pairwise Lab dE of 35.6, every zone at
# V>=0.55 and S>=0.15 so that none of them lands in the brown/mud band or
# collides with the near-grey the ring shows at zero confidence.
#
# The ninth, at 95 degrees, belongs to no zone. It steers the interpolation:
# theta 75-120 is the densest region of the listening corpus and the widest
# gap in the table, and run straight from fun/dance to industrial it passed
# within dE 6 of shoegaze -- 15% of the library reading as a zone it was not.

_DEFAULT = {
    "version": 2,
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

    # Angle → colour anchor table, sorted by theta.
    # theta: mood direction in degrees (atan2(energy-0.5, valence-0.5) % 360)
    # hex:   the colour that direction should read as, as sRGB
    "color_map": [
        [ 50.2, "#BA01FF"],   # fun/dance         violet
        [ 95.0, "#3FD34A"],   # (steering knot)   grass green
        [135.0, "#FC284F"],   # industrial        vivid rose-red
        [153.4, "#FF00AA"],   # shoegaze          hot magenta
        [168.7, "#0E4EAD"],   # darkwave          cobalt
        [180.0, "#70AFC4"],   # indie-melancholy  pale blue
        [206.6, "#D8900B"],   # zone-out          ginger ale
        [270.0, "#AFF2D4"],   # ambient           mint
        [323.1, "#A03738"],   # americana         brick red
    ],

    # Energy tilts the anchor's Lab lightness by +/- this fraction:
    # L *= (1 - tilt) at energy 0, L *= (1 + tilt) at energy 1.
    # Keeps "loud is brighter" without letting energy restate the colour.
    # Mood intensity r does NOT modulate the output — the anchor colour is
    # the whole statement of direction (issue #9).
    "energy_tilt": 0.15,

    # Fraction of full LED output, applied last, in linear light.
    # Scaling all three channels equally preserves chromaticity exactly, so
    # this dims the ring without disturbing the palette's separation.
    "master_brightness": 0.65,

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


def _get(key):
    """Read a profile field, falling back to the built-in default.

    Per-key rather than per-profile so that a profile written against an
    older schema still contributes the fields it does carry.
    """
    try:
        return _p[key]
    except KeyError:
        return _DEFAULT[key]


# ── Public interface ───────────────────────────────────────────────────────

def color_map():
    """List of [theta_deg, "#RRGGBB"] anchors, sorted ascending by theta."""
    return _get("color_map")


def energy_tilt():
    """Fractional Lab-lightness swing applied across energy 0 → 1."""
    return _get("energy_tilt")


def master_brightness():
    """Fraction of full LED output (0–1), applied last in linear light."""
    return _get("master_brightness")


def ewma_alpha(window):
    """EWMA decay factor for '1h' or '4h' pixel time window."""
    return _get("ewma_alpha_1h") if window == "1h" else _get("ewma_alpha_4h")


def zone_anchors():
    """Dict of zone name → [valence, energy] anchor positions."""
    return _get("zone_anchors")


def profile_name():
    """Human-readable name of the loaded profile."""
    return _p.get("name", "unknown")
