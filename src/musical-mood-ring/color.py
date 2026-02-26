# color.py
#
# Colour mapping for musical-mood-ring.
#
# Converts (valence, energy) → (R, G, B) via the polar colour model:
#   1. Polar transform:  (v, e) → (r, θ)
#   2. Hue:              H = synaesthesia.hue(θ)        [piecewise-linear over hue_map]
#   3. Saturation:       S = min(1.0, r * saturation_k)
#   4. Brightness:       V = brightness_floor + brightness_range * energy
#   5. HSV → RGB        (inline — avoids colorsys dependency on MicroPython)
#
# Pure Python — no hardware dependencies.
# Depends on synaesthesia.py (also pure Python / try-except compatible).

import synaesthesia
from polar import to_polar


def mood_to_rgb(valence, energy):
    """
    Map (valence, energy) → (r, g, b) as integers in [0, 255].
    Uses the active synaesthesia profile for all colour parameters.
    """
    r, theta = to_polar(valence, energy)

    H = synaesthesia.hue(theta) / 360.0
    S = min(1.0, r * synaesthesia.saturation_k())
    V = synaesthesia.brightness_floor() + synaesthesia.brightness_range() * energy
    V = max(0.0, min(1.0, V))

    # HSV → RGB (inline)
    if S == 0.0:
        rv = gv = bv = V
    else:
        i = int(H * 6.0)
        f = H * 6.0 - i
        p = V * (1.0 - S)
        q = V * (1.0 - S * f)
        t = V * (1.0 - S * (1.0 - f))
        i %= 6
        if   i == 0: rv, gv, bv = V, t, p
        elif i == 1: rv, gv, bv = q, V, p
        elif i == 2: rv, gv, bv = p, V, t
        elif i == 3: rv, gv, bv = p, q, V
        elif i == 4: rv, gv, bv = t, p, V
        else:        rv, gv, bv = V, p, q

    return int(rv * 255), int(gv * 255), int(bv * 255)
