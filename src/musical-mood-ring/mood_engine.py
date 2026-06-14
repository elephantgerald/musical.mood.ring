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
# Transitions are gated on elapsed wall-clock time since the first track hit —
# NOT on a count of polls. Poll count is a poor proxy for time: exponential
# back-off stretches the gap between polls, and the count freezes during silence
# while time keeps passing. Time is read through an injected clock (see clock.py)
# so it stays deterministic and fakable in tests and dev/fake_board.py.
#
# Pure Python — no hardware dependencies.

import synaesthesia
import miss_log
from mmar  import MMARBundle
from ewma  import EWMA, tau_from_alpha
from clock import Clock
from color import mood_to_rgb, apply_confidence

# Wall-clock thresholds for pixel-tier transitions.
_MS_1H = 60 * 60 * 1000        # 1 hr of data → pixel 1 splits off to the 1h avg
_MS_4H = 4 * 60 * 60 * 1000    # 4 hr of data → pixel 2 splits off to the 4h avg

# Reference cadence the profile's EWMA alphas were calibrated against (the nominal
# 3-min poll). tau_from_alpha() maps those alphas to time constants so the decay
# is correct at any real interval while staying identical at the nominal cadence.
_REF_INTERVAL_MS = 3 * 60 * 1000

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

    def __init__(self, bundle, artist_bundle=None, clock=None):
        self._bundle         = bundle
        self._artist_bundle  = artist_bundle
        self._clock          = clock if clock is not None else Clock()
        self._ewma_1h        = EWMA(tau_from_alpha(synaesthesia.ewma_alpha("1h"), _REF_INTERVAL_MS))
        self._ewma_4h        = EWMA(tau_from_alpha(synaesthesia.ewma_alpha("4h"), _REF_INTERVAL_MS))
        self._now_ve         = None   # most recent track-bundle (v, e) for pixel 0
        self._hit_poll_count = 0      # polls with ≥1 track-bundle hit (diagnostic only)
        self._first_hit_ms   = None   # wall-clock of first track hit — tier gate origin
        self._last_ewma_ms   = None   # wall-clock of last EWMA feed — for dt weighting
        self._confidence     = 1.0   # saturation scalar; decays on artist/miss polls
        self._last_outcomes  = []     # per-track outcomes from most recent update()

    def update(self, track_pairs, now_ms=None):
        """
        Process a list of (track_id, artist_id) tuples (newest first).

        now_ms is the current wall-clock time (ms) from the injected clock; when
        omitted it is read from the clock. It drives both the pixel-tier gate
        (elapsed since the first track hit) and the time-weighted EWMA decay.

        Track-bundle hits update _now_ve, _hit_poll_count, and both EWMAs.
        Artist-bundle hits feed only the EWMAs (coarser signal; no _now_ve update).
        Both artist hits and full misses are appended to miss_log.

        Each poll contributes a single time-weighted EWMA observation — the mean
        of the (v, e) hits seen this poll — rather than one update per track. That
        keeps the dt weighting well-defined and avoids double-counting tracks that
        linger across overlapping recently-played windows.

        Returns a 3-tuple of (r, g, b) for [pixel_0, pixel_1, pixel_2].
        """
        if now_ms is None:
            now_ms = self._clock.now_ms()

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
            if self._first_hit_ms is None:
                self._first_hit_ms = now_ms

        # One time-weighted observation per poll: the mean (v, e) of everything we
        # recognised this poll (track + artist hits). dt_ms is the gap since the
        # last feed, so decay reflects real elapsed time, not poll count.
        hits = track_hits + artist_hits
        if hits:
            obs_v = sum(h[0] for h in hits) / len(hits)
            obs_e = sum(h[1] for h in hits) / len(hits)
            dt_ms = 0 if self._last_ewma_ms is None else (now_ms - self._last_ewma_ms)
            self._ewma_1h.update(obs_v, obs_e, dt_ms)
            self._ewma_4h.update(obs_v, obs_e, dt_ms)
            self._last_ewma_ms = now_ms

        return self._pixel_outputs(now_ms)

    def _tier_sources(self, now_ms=None):
        """The (v, e) source feeding each pixel — the single source of truth for
        the pixel state machine that both _pixel_outputs() and pixel_sources()
        branch on, so the tier ladder is defined exactly once. Gated on elapsed
        wall-clock since the first track hit (now_ms from the clock when omitted):
            no track hit yet → (None, None, None)
            < 1h elapsed     → (now,  now, now)
            1h–4h elapsed    → (now,  1h,  1h)
            ≥ 4h elapsed     → (now,  1h,  4h)
        The idle (None, None, None) is deliberate: idle pixels show a synthetic
        placeholder colour, not a (v, e) the engine actually observed — so there
        is no "source" to report. _pixel_outputs() handles that one special case.
        """
        if self._now_ve is None:
            return (None, None, None)
        if now_ms is None:
            now_ms = self._clock.now_ms()
        elapsed = now_ms - self._first_hit_ms
        now = self._now_ve
        if elapsed < _MS_1H:
            return (now, now, now)
        h1 = self._ewma_1h.value
        if elapsed < _MS_4H:
            return (now, h1, h1)
        return (now, h1, self._ewma_4h.value)

    def _pixel_outputs(self, now_ms=None):
        sources = self._tier_sources(now_ms)
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
        self._first_hit_ms   = None
        self._last_ewma_ms   = None
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
