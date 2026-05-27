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

    def snapshot(self):
        """JSON-serializable view of all runtime state.

        Engine outcomes are stored internally as tuples for memory efficiency
        on the ESP32; here at the HTTP boundary we rehydrate them to dicts so
        curl users get a self-describing response. Tuples become lists so
        json.dumps/loads round-trips cleanly.
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
        }
