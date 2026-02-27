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
# apply_confidence(rgb, confidence) scales saturation by a [0,1] confidence
# scalar to signal lookup precision: 1.0 = track bundle (vivid), ~0.6 = artist
# bundle (washed), →0.0 = persistent miss (near-greyscale).
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


def apply_confidence(rgb, confidence):
    """
    Scale the saturation of an RGB colour by confidence ∈ [0.0, 1.0].

    confidence = 1.0  →  identity (vivid, track-bundle hit)
    confidence ≈ 0.6  →  washed  (artist-bundle hit)
    confidence → 0.0  →  greyscale (persistent miss)

    Hue and brightness are preserved; only saturation changes.
    """
    ri, gi, bi = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    mx, mn = max(ri, gi, bi), min(ri, gi, bi)
    diff = mx - mn
    v = mx
    s = 0.0 if mx == 0.0 else diff / mx

    if diff == 0.0:
        h = 0.0
    elif mx == ri:
        h = (60.0 * ((gi - bi) / diff)) % 360.0
    elif mx == gi:
        h = 60.0 * ((bi - ri) / diff) + 120.0
    else:
        h = 60.0 * ((ri - gi) / diff) + 240.0

    s = s * max(0.0, min(1.0, confidence))

    if s == 0.0:
        c = int(v * 255)
        return (c, c, c)
    h_norm = (h % 360) / 60.0
    i = int(h_norm)
    f = h_norm - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    rv, gv, bv = [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)][i % 6]
    return (int(rv * 255), int(gv * 255), int(bv * 255))
