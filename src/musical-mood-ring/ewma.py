# ewma.py
#
# Exponentially weighted moving average (EWMA) over (valence, energy) pairs.
#
# One accumulator per pixel time-window. Holds a running (v, e) average;
# no history log is stored — only the current state survives.
#
# A fresh accumulator starts at the neutral mood (0.5, 0.5) and drifts
# toward the actual listening mood as updates arrive.
#
# Pure Python — no hardware dependencies.

_NEUTRAL_V = 0.5
_NEUTRAL_E = 0.5


class EWMA:
    """
    Running EWMA over (valence, energy) observations.

    alpha:  decay factor (0 < alpha ≤ 1).
            Higher alpha = faster response to new observations.
            Loaded from synaesthesia profile: ewma_alpha("1h") / ewma_alpha("4h").
    """

    def __init__(self, alpha):
        self.alpha   = alpha
        self._v      = _NEUTRAL_V
        self._e      = _NEUTRAL_E
        self._seeded = False

    def update(self, valence, energy):
        """Incorporate a new (valence, energy) observation."""
        if not self._seeded:
            # First real observation: snap to it rather than blending from neutral.
            self._v      = valence
            self._e      = energy
            self._seeded = True
        else:
            a       = self.alpha
            self._v = a * valence + (1.0 - a) * self._v
            self._e = a * energy  + (1.0 - a) * self._e

    @property
    def value(self):
        """Current (valence, energy) estimate as a (float, float) tuple."""
        return self._v, self._e

    def reset(self):
        """Reset to neutral. Called on Spotify sign-out or bundle reload."""
        self._v      = _NEUTRAL_V
        self._e      = _NEUTRAL_E
        self._seeded = False
