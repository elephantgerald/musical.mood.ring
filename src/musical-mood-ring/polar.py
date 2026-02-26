# polar.py
#
# Polar coordinate transform for the musical-mood-ring colour model.
#
# The mood space is centred at (0.5, 0.5). Polar coordinates:
#   r     = distance from centre → mood intensity (0 = neutral, ~0.71 = corner)
#   theta = direction in degrees [0, 360), 0° = east (high valence, mid energy)
#
# Pure Python — no hardware dependencies.

import math


def to_polar(valence, energy):
    """
    Convert (valence, energy) → (r, theta_deg).

    Both inputs are floats in [0, 1].
    r is in [0, ~0.71] for inputs in [0, 1].
    theta is in [0, 360).
    """
    v     = valence - 0.5
    e     = energy  - 0.5
    r     = math.sqrt(v * v + e * e)
    theta = math.degrees(math.atan2(e, v)) % 360
    return r, theta
