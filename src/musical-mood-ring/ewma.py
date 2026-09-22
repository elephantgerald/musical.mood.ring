# ewma.py
#
# Time-aware exponentially weighted moving average (EWMA) over (valence, energy).
#
# One accumulator per pixel time-window. Holds a running (v, e) average; no
# history log is stored — only the current state survives.
#
# Time-aware decay: each update is weighted by the elapsed time since the last
# one, not by a fixed per-poll factor. The smoothing factor is
#
#       alpha = 1 - exp(-dt_ms / tau_ms)
#
# where tau_ms is the window's time constant. This keeps the "1h" / "4h" horizons
# honest no matter how irregular the polling is — exponential back-off after
# Spotify errors, or gaps while no music plays, no longer distort the average the
# way a fixed-alpha-per-poll scheme did (it silently assumed an exact 3-min cadence).
#
# A fresh accumulator starts at the neutral mood (0.5, 0.5) and snaps to the
# first real observation; subsequent observations blend by the time-weighted alpha.
#
# Pure Python — no hardware dependencies.

import math

_NEUTRAL_V = 0.5
_NEUTRAL_E = 0.5


def tau_from_alpha(alpha, ref_ms):
    """Time constant (ms) equivalent to applying a fixed `alpha` every `ref_ms`.

    Lets a profile keep expressing smoothing as a per-poll alpha calibrated for a
    reference cadence (the nominal 3-min poll), while the engine runs the correct
    time-weighted decay. By construction, an update with dt_ms == ref_ms yields
    exactly `alpha`, so behaviour at the nominal cadence is unchanged.
    """
    if alpha >= 1.0:
        return 0.0              # always-snap: any dt gives alpha 1
    if alpha <= 0.0:
        return float("inf")     # never decays
    return -ref_ms / math.log(1.0 - alpha)


class EWMA:
    """
    Time-weighted running EWMA over (valence, energy) observations.

    tau_ms: decay time constant in milliseconds (tau_ms > 0).
            Larger tau = slower response / longer memory. 0 means always snap to
            the latest observation; float('inf') means never decay.
            Derive from a profile alpha via tau_from_alpha().
    """

    def __init__(self, tau_ms):
        self.tau_ms  = tau_ms
        self._v      = _NEUTRAL_V
        self._e      = _NEUTRAL_E
        self._seeded = False

    def update(self, valence, energy, dt_ms):
        """Incorporate a new (valence, energy), decayed by elapsed dt_ms.

        dt_ms is the time since the previous update. dt_ms <= 0 leaves the
        estimate unchanged (no time has passed); a large dt_ms decays the old
        value toward the new observation.
        """
        if not self._seeded:
            # First real observation: snap to it rather than blending from neutral.
            self._v      = valence
            self._e      = energy
            self._seeded = True
            return
        if dt_ms <= 0:
            return
        if self.tau_ms <= 0:
            a = 1.0
        elif self.tau_ms == float("inf"):
            a = 0.0
        else:
            a = 1.0 - math.exp(-dt_ms / self.tau_ms)
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
