# mood_engine.py
#
# Mood engine for musical-mood-ring.
#
# Orchestrates the full pipeline each poll cycle:
#   recently-played track IDs → MMAR lookup → EWMA update → RGB per pixel
#
# Returns three (r, g, b) tuples ready for pixel.py, following the pixel
# state machine from DESIGN.md §6:
#
#   Listening history  │ Pixel 0    │ Pixel 1    │ Pixel 2
#   ───────────────────┼────────────┼────────────┼────────────
#   Inactive           │ idle       │ idle       │ idle
#   < 1 hr data        │ recent     │ recent     │ recent
#   1 hr – 4 hr data   │ recent     │ 1h avg     │ 1h avg
#   > 4 hr data        │ recent     │ 1h avg     │ 4h avg
#
# Transitions are gated on the count of polls that returned ≥1 bundle hit,
# so the EWMA windows fill up gradually without any timing hardware.
#
# Pure Python — no hardware dependencies.

import synaesthesia
from mmar  import MMARBundle
from ewma  import EWMA
from color import mood_to_rgb

# Poll thresholds for state transitions (at the default 3-minute poll interval)
_POLLS_1H = 20   # 60 min / 3 min
_POLLS_4H = 80   # 240 min / 3 min


class MoodEngine:
    """
    Stateful mood engine. Construct once at startup; call update() each poll.

    bundle:  MMARBundle loaded by the caller — decouples file I/O from logic,
             which makes testing straightforward without touching the filesystem.
    """

    def __init__(self, bundle):
        self._bundle         = bundle
        self._ewma_1h        = EWMA(synaesthesia.ewma_alpha("1h"))
        self._ewma_4h        = EWMA(synaesthesia.ewma_alpha("4h"))
        self._now_ve         = None   # most recent known (v, e) for pixel 0
        self._hit_poll_count = 0      # polls that returned ≥1 bundle hit

    def update(self, track_ids):
        """
        Process a list of recently-played Spotify track IDs (newest first).

        Looks up each ID in the MMAR bundle. All hits are fed into the EWMA
        accumulators oldest-to-newest. The newest hit becomes the "now" mood
        for pixel 0 and is remembered across polls so the pixel doesn't flicker
        back to neutral on a miss poll.

        Returns a 3-tuple of (r, g, b) for [pixel_0, pixel_1, pixel_2].
        """
        hits = []
        for tid in track_ids:
            result = self._bundle.lookup(tid)
            if result is not None:
                hits.append(result)

        if hits:
            self._now_ve = hits[0]    # most recently played known track
            self._hit_poll_count += 1
            for v, e in reversed(hits):   # feed EWMA oldest → newest
                self._ewma_1h.update(v, e)
                self._ewma_4h.update(v, e)

        return self._pixel_outputs()

    def _pixel_outputs(self):
        n = self._hit_poll_count

        if n == 0:
            # Inactive — no bundle hits yet. Placeholder for idle sparkle (#36).
            idle = mood_to_rgb(0.5, synaesthesia.brightness_floor() /
                               (synaesthesia.brightness_floor() + synaesthesia.brightness_range()))
            return (idle, idle, idle)

        now = mood_to_rgb(*self._now_ve)

        if n <= _POLLS_1H:
            # < 1 hr: all three share the most recent track
            return (now, now, now)

        h1 = mood_to_rgb(*self._ewma_1h.value)

        if n <= _POLLS_4H:
            # 1–4 hr: pixel 2 follows pixel 1 until the 4h window fills
            return (now, h1, h1)

        # > 4 hr: full three-window discrimination
        return (now, h1, mood_to_rgb(*self._ewma_4h.value))

    def reset(self):
        """Reset all state. Called on bundle reload or sign-out."""
        self._ewma_1h.reset()
        self._ewma_4h.reset()
        self._now_ve         = None
        self._hit_poll_count = 0
