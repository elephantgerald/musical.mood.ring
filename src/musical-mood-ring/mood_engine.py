# mood_engine.py
#
# Mood engine for musical-mood-ring.
#
# Orchestrates the full pipeline each poll cycle:
#   (track_id, artist_id) pairs → two-tier MMAR lookup → EWMA update → RGB per pixel
#
# Lookup tiers:
#   1. Track bundle  (precise, from AcousticBrainz/Last.fm pipeline)
#   2. Artist bundle (approximate, artist-average v/e — optional)
#   Miss logged to miss_log for pipeline feedback regardless of tier reached.
#
# Confidence scalar (applied to saturation at display time):
#   Track hit  → 1.0  (vivid — device is certain)
#   Artist hit → decays max(0.6, ×0.95) — washed, arrests at 0.6
#   Full miss  → ×0.85 — fades toward greyscale
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
# Transitions are gated on the count of track-bundle hit polls only.
#
# Pure Python — no hardware dependencies.

import synaesthesia
import miss_log
from mmar  import MMARBundle
from ewma  import EWMA
from color import mood_to_rgb, apply_confidence

# Poll thresholds for state transitions (at the default 3-minute poll interval)
_POLLS_1H = 20   # 60 min / 3 min
_POLLS_4H = 80   # 240 min / 3 min

# _last_outcomes entries are plain tuples for tight ESP32 memory footprint
# (~64 B/entry vs ~150 B for dicts) and positional access cost. The field
# layout is exported so HTTP-boundary code can rehydrate to a dict on demand
# without redefining the schema.
OUTCOME_FIELDS = ("track_id", "artist_id", "source", "v", "e")


class MoodEngine:
    """
    Stateful mood engine. Construct once at startup; call update() each poll.

    bundle:        MMARBundle (track-level, required)
    artist_bundle: MMARBundle (artist-level, optional) — approximate fallback
    """

    def __init__(self, bundle, artist_bundle=None):
        self._bundle         = bundle
        self._artist_bundle  = artist_bundle
        self._ewma_1h        = EWMA(synaesthesia.ewma_alpha("1h"))
        self._ewma_4h        = EWMA(synaesthesia.ewma_alpha("4h"))
        self._now_ve         = None   # most recent track-bundle (v, e) for pixel 0
        self._hit_poll_count = 0      # polls with ≥1 track-bundle hit
        self._confidence     = 1.0   # saturation scalar; decays on artist/miss polls
        self._last_outcomes  = []     # per-track outcomes from most recent update()

    def update(self, track_pairs):
        """
        Process a list of (track_id, artist_id) tuples (newest first).

        Track-bundle hits update _now_ve, _hit_poll_count, and both EWMAs.
        Artist-bundle hits feed only the EWMAs (coarser signal; no _now_ve update).
        Both artist hits and full misses are appended to miss_log.

        Returns a 3-tuple of (r, g, b) for [pixel_0, pixel_1, pixel_2].
        """
        track_hits  = []   # precise (v, e) from track bundle
        artist_hits = []   # approximate (v, e) from artist bundle
        outcomes    = []   # per-track diagnostic record for last_poll_outcomes()

        for track_id, artist_id in track_pairs:
            result = self._bundle.lookup(track_id)
            if result is not None:
                track_hits.append(result)
                self._confidence = 1.0
                outcomes.append((track_id, artist_id, "track", result[0], result[1]))
            else:
                miss_log.append(track_id)
                if self._artist_bundle is not None:
                    result = self._artist_bundle.lookup(artist_id)
                if result is not None:
                    artist_hits.append(result)
                    self._confidence = max(0.6, self._confidence * 0.95)
                    outcomes.append((track_id, artist_id, "artist", result[0], result[1]))
                else:
                    self._confidence *= 0.85
                    outcomes.append((track_id, artist_id, "miss", None, None))

        self._last_outcomes = outcomes

        if track_hits:
            self._now_ve = track_hits[0]    # most recently played known track
            self._hit_poll_count += 1
            for v, e in reversed(track_hits):
                self._ewma_1h.update(v, e)
                self._ewma_4h.update(v, e)

        if artist_hits:
            for v, e in reversed(artist_hits):
                self._ewma_1h.update(v, e)
                self._ewma_4h.update(v, e)

        return self._pixel_outputs()

    def _tier_sources(self):
        """The (v, e) source feeding each pixel — the single source of truth for
        the pixel state machine that both _pixel_outputs() and pixel_sources()
        branch on, so the tier ladder is defined exactly once:
            idle (no hits) → (None, None, None)
            < 1h data      → (now,  now, now)
            1h–4h data     → (now,  1h,  1h)
            > 4h data      → (now,  1h,  4h)
        The idle (None, None, None) is deliberate: idle pixels show a synthetic
        placeholder colour, not a (v, e) the engine actually observed — so there
        is no "source" to report. _pixel_outputs() handles that one special case.
        """
        n = self._hit_poll_count
        if n == 0:
            return (None, None, None)
        now = self._now_ve
        if n <= _POLLS_1H:
            return (now, now, now)
        h1 = self._ewma_1h.value
        if n <= _POLLS_4H:
            return (now, h1, h1)
        return (now, h1, self._ewma_4h.value)

    def _pixel_outputs(self):
        sources = self._tier_sources()
        if sources[0] is None:
            # Inactive — no track-bundle hits yet. Synthetic idle colour (not
            # sourced from an observed (v, e); see _tier_sources()).
            idle = mood_to_rgb(0.5, synaesthesia.brightness_floor() /
                               (synaesthesia.brightness_floor() + synaesthesia.brightness_range()))
            idle = apply_confidence(idle, self._confidence)
            return (idle, idle, idle)
        return tuple(apply_confidence(mood_to_rgb(v, e), self._confidence)
                     for v, e in sources)

    def pixel_sources(self):
        """Per-pixel (v, e) that fed each pixel's colour, for HTTP introspection.

        Derived from _tier_sources() (the shared tier ladder), with tuples
        rendered as lists for JSON round-trip parity with snapshot(). Idle
        pixels report None — they have no observed source (see _tier_sources()).
        """
        return [list(s) if s is not None else None for s in self._tier_sources()]

    def reset(self):
        """Reset all state. Called on bundle reload or sign-out."""
        self._ewma_1h.reset()
        self._ewma_4h.reset()
        self._now_ve         = None
        self._hit_poll_count = 0
        self._confidence     = 1.0
        self._last_outcomes  = []

    def snapshot(self):
        """JSON-serializable view of internal state for HTTP introspection.

        Tuples become lists so the dict round-trips through json.dumps/loads
        cleanly (json decodes arrays to lists, so storing lists here keeps
        round-trip equality intact for tests and callers).
        """
        return {
            "now_ve":         list(self._now_ve) if self._now_ve is not None else None,
            "hit_poll_count": self._hit_poll_count,
            "confidence":     self._confidence,
            "ewma_1h":        list(self._ewma_1h.value),
            "ewma_4h":        list(self._ewma_4h.value),
        }

    def last_poll_outcomes(self):
        """Per-track outcomes from the most recent update() call.

        Each entry is a 5-tuple matching OUTCOME_FIELDS:
            (track_id, artist_id, source, v, e)
        source ∈ {"track", "artist", "miss"}; v/e are None for misses.
        Returns [] before the first poll and after reset().
        """
        return list(self._last_outcomes)
