# runtime_state.py
#
# Shared runtime state for musical-mood-ring.
#
# main.py owns and mutates a RuntimeState. ConfigServer receives a reference
# and reads from it to serve the introspection endpoints (#58). The point of
# this module: config_server and mood_engine never import each other —
# runtime_state imports OUTCOME_FIELDS from mood_engine (one direction only,
# no cycle), and config_server only imports runtime_state. That keeps the
# engine's hot path free of HTTP/server code and lets ConfigServer remain
# ignorant of MoodEngine's internals.
#
# Convention: ConfigServer treats every field as read-only. Python doesn't
# enforce this without a type checker — discipline lives in the docstring
# and in code review.
#
# Pure Python — no hardware dependencies. Safe to import in CPython tests.


from mood_engine import OUTCOME_FIELDS

# Depth of the rolling poll log (#57). recently_played() returns ≤10 tracks, so
# a record is ~350 B typical, ~580 B worst case (10 IDs + their (v,e) pairs).
# 20 records covers the last hour at the default 3-minute cadence. The whole log
# is a handful of KB of small dicts in RAM — well within the ESP32 budget; only
# the transient JSON of a full /poll-log response approaches ~12 KB, which the
# board serves without trouble.
_POLL_LOG_SIZE = 20


class RuntimeState:
    """Aggregate of mutable runtime state observable via HTTP.

    Writer:  main.py — sets engine on startup; updates last_* fields per poll
             and per frame.
    Reader:  config_server.py — calls snapshot() inside request handlers.

    All fields are intended to be read-only from the reader's perspective.
    snapshot() returns a JSON-serializable view; values are copied so callers
    can mutate the returned dict without affecting state.

    last_colors vs. last_mood_colors:
        last_colors      — what was most recently written to the pixels.
                           Includes animation overlays (idle sparkle, startup
                           flare, WIFI_LOST pulse, ApiErrorBlip), not just
                           the engine's mood output.
        last_mood_colors — the most recent return value from engine.update().
                           None until the engine has run at least once. Use
                           this when diagnosing the engine in isolation.
    """

    def __init__(self):
        self.engine           = None             # MoodEngine | None
        self.last_track_ids   = []               # [str, ...] — input to last poll
        self.last_poll_ms     = 0                # ticks_ms of last successful poll
        self.last_colors      = [(0, 0, 0)] * 3  # last colors written to pixels
        self.last_mood_colors = None             # last engine.update() return; None until first call
        self.poll_log         = []               # rolling list of the last _POLL_LOG_SIZE poll records
        self.animator         = None             # active lights animator (main.py writes each frame)
        self.error_mode       = None             # None | "wifi_lost" | "auth_fail"

    def snapshot(self):
        """JSON-serializable view of all runtime state.

        Engine outcomes are stored internally as tuples for memory efficiency
        on the ESP32; here at the HTTP boundary we rehydrate them to dicts so
        curl users get a self-describing response. Tuples become lists so
        json.dumps/loads round-trips cleanly.

        The animator descriptor's "done" is tri-state: True/False for animators
        that have a `done` flag, or None for those that run indefinitely (e.g. a
        WIFI_LOST pulse) — read alongside "error_mode" to disambiguate.
        """
        if self.engine is not None:
            outcomes = [dict(zip(OUTCOME_FIELDS, o))
                        for o in self.engine.last_poll_outcomes()]
            engine_snap = self.engine.snapshot()
        else:
            outcomes    = []
            engine_snap = None
        return {
            "engine":             engine_snap,
            "last_track_ids":     list(self.last_track_ids),
            "last_track_results": outcomes,
            "last_poll_ms":       self.last_poll_ms,
            "last_colors":        [list(c) for c in self.last_colors],
            "last_mood_colors":   ([list(c) for c in self.last_mood_colors]
                                   if self.last_mood_colors is not None else None),
            "animator":           (None if self.animator is None else
                                   {"class": type(self.animator).__name__,
                                    "done":  getattr(self.animator, "done", None)}),
            "error_mode":         self.error_mode,
        }

    def record_poll(self, time_ms, track_ids, track_results, colors_after,
                    confidence_after, error):
        """Append one poll outcome to the rolling log (#57), capped at _POLL_LOG_SIZE.

        Called once per poll from main.py on every outcome path — success,
        network error, and auth-fail alike — so the log is a faithful trace of
        what the device actually did, not just its successes.

        The record is built fully-owned and json.dumps()-able: input sequences
        are copied (a caller mutating them later can't corrupt a stored record)
        and tuples are flattened to lists. colors_after is the engine's mood
        output (last_mood_colors), not the animator's last_colors overlay.

        Note: this `error` vocabulary (None | "network" | "auth_fail") is a
        poll-outcome label and is deliberately distinct from the animator-overlay
        `error_mode` (None | "wifi_lost" | "auth_fail") above — they are not the
        same enum and are intentionally not unified.

            time_ms          — ticks_ms when the poll ran
            track_ids        — [str, ...] polled (empty on auth/network failure)
            track_results    — [(v, e) | None, ...], order-aligned to track_ids
            colors_after     — 3 (r, g, b) engine mood colors, or None before the
                               first successful poll. Stored as None rather than
                               black so a reader can tell "engine never produced a
                               mood" apart from a genuine all-black output — the
                               same distinction snapshot() preserves.
            confidence_after — engine confidence scalar after the poll
            error            — None | "network" | "auth_fail"
        """
        record = {
            "time_ms":          time_ms,
            "track_ids":        list(track_ids),
            "track_results":    [list(r) if r is not None else None
                                 for r in track_results],
            "colors_after":     ([list(c) for c in colors_after]
                                 if colors_after is not None else None),
            "confidence_after": confidence_after,
            "error":            error,
        }
        self.poll_log.append(record)
        if len(self.poll_log) > _POLL_LOG_SIZE:
            self.poll_log.pop(0)   # evict oldest; plain list keeps MicroPython happy

    def poll_log_snapshot(self):
        """JSON-serializable copy of the poll log, oldest first.

        Each record is rebuilt with fresh nested lists so a reader can't mutate
        the live log — the same deep-copy-to-JSON-ready discipline snapshot()
        applies to last_colors. Kept separate from snapshot() so /state stays
        lean and #58's /poll-log endpoint serves this buffer on its own.
        """
        return [
            {
                "time_ms":          r["time_ms"],
                "track_ids":        list(r["track_ids"]),
                "track_results":    [list(x) if x is not None else None
                                     for x in r["track_results"]],
                "colors_after":     ([list(c) for c in r["colors_after"]]
                                     if r["colors_after"] is not None else None),
                "confidence_after": r["confidence_after"],
                "error":            r["error"],
            }
            for r in self.poll_log
        ]
