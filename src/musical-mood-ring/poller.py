# poller.py
#
# Poll-timing and error back-off state machine for musical-mood-ring.
#
# Poller tracks when the next Spotify poll should fire and how long to wait
# after each flavour of failure. It carries no network logic itself — the
# caller (main.py) does the HTTP work and reports the outcome back via
# on_success / on_error / on_rate_limit.
#
# Pure Python — no hardware dependencies.

_INTERVAL_MS      = 3 * 60 * 1000   # normal poll cadence
_BACKOFF_BASE_MS  = 1 * 60 * 1000   # first back-off step (1 min)
_BACKOFF_MAX_STEP = 2                # steps: 1 min, 2 min, 4 min
_PERSISTENT_MS    = 15 * 60 * 1000  # failure window for graceful degradation


class Poller:
    """
    Tracks when the next poll should fire and manages exponential back-off.

    Intended usage in the main loop:

        if poller.should_poll(now_ms):
            try:
                data = fetch(...)
                poller.on_success(now_ms)
            except RateLimited as e:
                poller.on_rate_limit(now_ms, e.retry_after_ms)
            except Exception:
                poller.on_error(now_ms)

        if poller.is_persistent_failure(now_ms):
            # degrade gracefully — show idle sparkle
    """

    def __init__(self, interval_ms=_INTERVAL_MS):
        self._interval_ms        = interval_ms
        self._next_poll_ms       = 0       # fire immediately on first check
        self._consecutive_errors = 0
        self._last_success_ms    = None
        self._first_error_ms     = None    # when the current error streak began

    def should_poll(self, now_ms):
        """Return True if it is time to attempt a poll."""
        return now_ms >= self._next_poll_ms

    def on_success(self, now_ms):
        """Call after a successful poll. Resets back-off and records the time."""
        self._last_success_ms    = now_ms
        self._next_poll_ms       = now_ms + self._interval_ms
        self._consecutive_errors = 0
        self._first_error_ms     = None

    def on_rate_limit(self, now_ms, retry_after_ms):
        """Call when Spotify returns 429. Waits exactly retry_after_ms."""
        self._next_poll_ms = now_ms + retry_after_ms

    def on_error(self, now_ms):
        """
        Call on any non-429 failure (5xx, timeout, network error).
        Applies exponential back-off: 1 min → 2 min → 4 min (capped).
        """
        if self._consecutive_errors == 0:
            self._first_error_ms = now_ms
        self._consecutive_errors += 1
        step    = min(self._consecutive_errors - 1, _BACKOFF_MAX_STEP)
        backoff = _BACKOFF_BASE_MS * (2 ** step)
        self._next_poll_ms = now_ms + backoff

    def is_persistent_failure(self, now_ms):
        """
        Return True if there has been no successful poll for _PERSISTENT_MS.
        Used to decide whether to show idle sparkle as graceful degradation.
        """
        if self._consecutive_errors == 0:
            return False
        ref = (self._last_success_ms
               if self._last_success_ms is not None
               else self._first_error_ms)
        return (now_ms - ref) >= _PERSISTENT_MS
