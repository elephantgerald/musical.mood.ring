# mood_engine.py
#
# Mood engine for musical-mood-ring.
#
# Orchestrates the full pipeline each poll cycle:
#   recently-played track IDs → MMAR lookup → EWMA update → RGB per pixel
#
# Returns three (r, g, b) tuples ready for pixel.py:
#   pixel 0 — most recently known track (direct lookup, no averaging)
#   pixel 1 — 1-hour EWMA
#   pixel 2 — 4-hour EWMA
#
# Pure Python — no hardware dependencies. The bundle is passed in as an
# MMARBundle object so the caller (main.py or a test) handles file I/O.

import synaesthesia
from mmar  import MMARBundle
from ewma  import EWMA
from color import mood_to_rgb


class MoodEngine:
    """
    Stateful mood engine. Construct once at startup; call update() each poll.

    bundle:  MMARBundle loaded by the caller — decouples file I/O from logic,
             which makes testing straightforward without touching the filesystem.
    """

    def __init__(self, bundle):
        self._bundle  = bundle
        self._ewma_1h = EWMA(synaesthesia.ewma_alpha("1h"))
        self._ewma_4h = EWMA(synaesthesia.ewma_alpha("4h"))
        self._now_ve  = None   # most recent known (v, e) for pixel 0

    def update(self, track_ids):
        """
        Process a list of recently-played Spotify track IDs (newest first).

        Looks up each ID in the MMAR bundle. All hits are fed into the EWMA
        accumulators oldest-to-newest. The newest hit becomes the "now" mood
        for pixel 0 and is remembered across polls so the pixel doesn't flicker
        back to neutral on an empty-result poll.

        Returns a 3-tuple of (r, g, b) for [pixel_now, pixel_1h, pixel_4h].
        """
        hits = []
        for tid in track_ids:
            result = self._bundle.lookup(tid)
            if result is not None:
                hits.append(result)

        if hits:
            self._now_ve = hits[0]   # most recently played known track
            for v, e in reversed(hits):  # feed EWMA oldest → newest
                self._ewma_1h.update(v, e)
                self._ewma_4h.update(v, e)

        # pixel 0: direct lookup; fall back to 1h EWMA if we've never seen a hit
        now_ve = self._now_ve if self._now_ve is not None else self._ewma_1h.value

        return (
            mood_to_rgb(*now_ve),
            mood_to_rgb(*self._ewma_1h.value),
            mood_to_rgb(*self._ewma_4h.value),
        )

    def reset(self):
        """Reset all state. Called on bundle reload or sign-out."""
        self._ewma_1h.reset()
        self._ewma_4h.reset()
        self._now_ve = None
