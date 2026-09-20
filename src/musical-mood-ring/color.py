# color.py
#
# Colour mapping for musical-mood-ring.
#
# Converts (valence, energy) → (R, G, B) via the polar colour model:
#   1. Polar transform:  (v, e) → (r, θ)
#   2. Anchor colour:    Lab = interpolate(color_map, θ)   [CIELAB, not hue]
#   3. Energy tilt:      L *= 1 + energy_tilt * (2*energy - 1)
#   4. Master dim:       linear RGB *= master_brightness
#   5. Lab → sRGB
#
# Mood intensity r is deliberately NOT used. The anchor colour is the whole
# statement of mood direction; letting r pull toward neutral is how the
# previous model collapsed the centrist zones into brown (issue #9).
#
# Why Lab and not hue. Interpolating between anchors in hue space pins
# saturation high across the whole sweep, so the bands BETWEEN anchors
# reproduce other zones' colours — shoegaze→darkwave passed through the
# vivid violet that IS fun/dance. Lab passes near the neutral axis instead,
# so midpoints desaturate: a dusty orchid cannot be mistaken for #BA01FF.
#
# Output is sRGB — what the ring should look like, not what the LED driver
# should be handed. WS2812B duty is linear in the byte, so pixel.py applies
# the sRGB transfer function on the way out.
#
# apply_confidence(rgb, confidence) scales Lab chroma by a [0,1] confidence
# scalar to signal lookup precision: 1.0 = track bundle (vivid), ~0.6 =
# artist bundle (washed), →0.0 = neutral grey at the same lightness.
#
# Pure Python — no hardware dependencies.
# Depends on synaesthesia.py (also pure Python / try-except compatible).

import synaesthesia
from polar import to_polar

# D65 white point, and the CIELAB f() knee.
_WP    = (0.95047, 1.0, 1.08883)
_EPS   = 0.008856
_KAPPA = 7.787


def _srgb_to_linear(c8):
    """One 0–255 sRGB channel → linear light in [0, 1]."""
    c = c8 / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(x):
    """Linear light → one 0–255 sRGB channel, clamped."""
    if x <= 0.0:
        return 0
    if x >= 1.0:
        return 255
    if x <= 0.0031308:
        v = 12.92 * x
    else:
        v = 1.055 * (x ** (1.0 / 2.4)) - 0.055
    return int(v * 255.0 + 0.5)


def _f(t):
    return t ** (1.0 / 3.0) if t > _EPS else (_KAPPA * t + 16.0 / 116.0)


def _f_inv(t):
    c = t * t * t
    return c if c > _EPS else (t - 16.0 / 116.0) / _KAPPA


def _rgb_to_lab(rgb):
    """(r, g, b) sRGB bytes → (L, a, b) in CIELAB."""
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / _WP[0]
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / _WP[1]
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / _WP[2]
    fx, fy, fz = _f(x), _f(y), _f(z)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def _lab_to_rgb(lab, scale=1.0):
    """(L, a, b) → (r, g, b) sRGB bytes, after scaling linear light by `scale`.

    Scaling all three channels equally preserves chromaticity exactly, so
    master_brightness dims the ring without moving any colour in the palette
    relative to its neighbours.
    """
    L, a, b = lab
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    x = _f_inv(fx) * _WP[0]
    y = _f_inv(fy) * _WP[1]
    z = _f_inv(fz) * _WP[2]
    rl =  3.2406 * x - 1.5372 * y - 0.4986 * z
    gl = -0.9689 * x + 1.8758 * y + 0.0415 * z
    bl =  0.0557 * x - 0.2040 * y + 1.0570 * z
    return (_linear_to_srgb(rl * scale),
            _linear_to_srgb(gl * scale),
            _linear_to_srgb(bl * scale))


def _hex_to_rgb(s):
    """"#RRGGBB" → (r, g, b) bytes."""
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _lab_at(theta_deg):
    """Interpolate the color_map anchors in CIELAB at a mood direction.

    Piecewise linear over the anchor table, with circular wraparound between
    the last and first entries. Only the two bracketing anchors are converted,
    so the profile stays editable as hex and nothing is precomputed at import
    (dev/fake_board.py swaps synaesthesia._p at runtime).
    """
    cm = synaesthesia.color_map()
    n  = len(cm)
    t  = theta_deg % 360

    for i in range(n):
        t0, hex0 = cm[i]
        t1, hex1 = cm[(i + 1) % n]
        if i == n - 1:
            # Wraparound segment: last entry → first entry through 360°/0°
            t1 += 360
            if t < t0:
                t += 360
        if t0 <= t < t1:
            frac = (t - t0) / (t1 - t0)
            lab0 = _rgb_to_lab(_hex_to_rgb(hex0))
            lab1 = _rgb_to_lab(_hex_to_rgb(hex1))
            return tuple(c0 + frac * (c1 - c0) for c0, c1 in zip(lab0, lab1))

    return _rgb_to_lab(_hex_to_rgb(cm[0][1]))   # unreachable, but safe


def mood_to_rgb(valence, energy):
    """
    Map (valence, energy) → (r, g, b) as integers in [0, 255].
    Uses the active synaesthesia profile for all colour parameters.
    """
    _, theta = to_polar(valence, energy)

    L, a, b = _lab_at(theta)
    tilt    = synaesthesia.energy_tilt()
    L      *= 1.0 + tilt * (2.0 * max(0.0, min(1.0, energy)) - 1.0)

    return _lab_to_rgb((L, a, b), synaesthesia.master_brightness())


def apply_confidence(rgb, confidence):
    """
    Scale the Lab chroma of an RGB colour by confidence ∈ [0.0, 1.0].

    confidence = 1.0  →  identity (vivid, track-bundle hit)
    confidence ≈ 0.6  →  washed  (artist-bundle hit)
    confidence → 0.0  →  neutral grey at the same lightness (persistent miss)

    Lightness is preserved; only chroma changes. Done in Lab rather than HSV
    so that a fully-desaturated colour lands on a mid grey matching its own
    lightness, instead of the near-white that scaling HSV saturation gives.
    """
    c = max(0.0, min(1.0, confidence))
    if c == 1.0:
        return tuple(rgb)
    L, a, b = _rgb_to_lab(rgb)
    return _lab_to_rgb((L, a * c, b * c))
