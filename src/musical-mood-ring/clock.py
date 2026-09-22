# clock.py
#
# Pluggable monotonic millisecond clock for musical-mood-ring.
#
# Centralises the one place the firmware reads wall-clock time, so the rest of
# the code depends on a small interface (now_ms) rather than reaching for
# utime/time directly. That makes time injectable: production uses Clock, while
# tests and dev/fake_board.py use FakeClock to drive elapsed time deterministically.
#
# Why an accumulating counter (not raw ticks_ms): MicroPython's utime.ticks_ms()
# wraps roughly every 12.4 days, so plain subtraction across the wrap yields a
# bogus (often negative) delta. For a device meant to run forever, that matters.
# Clock folds each raw delta through utime.ticks_diff (which handles the wrap)
# into a 64-bit Python int that never wraps, so callers can subtract two now_ms()
# values safely. CPython has no wrap, so it simply tracks time.monotonic().
#
# Pure Python — no hardware dependencies.

try:
    import utime
    def _raw_ms():    return utime.ticks_ms()
    def _diff(a, b):  return utime.ticks_diff(a, b)   # wrap-aware (later, earlier)
except ImportError:
    import time
    def _raw_ms():    return int(time.monotonic() * 1000)
    def _diff(a, b):  return a - b


class Clock:
    """Real monotonic clock in milliseconds.

    now_ms() returns a non-wrapping, monotonically non-decreasing count of
    milliseconds since this Clock was constructed. Call it as often as you like;
    each call folds the elapsed raw ticks (wrap-aware) into the running total.
    """

    def __init__(self):
        self._last    = _raw_ms()
        self._elapsed = 0

    def now_ms(self):
        t = _raw_ms()
        self._elapsed += _diff(t, self._last)
        self._last     = t
        return self._elapsed


class FakeClock:
    """Deterministic clock for tests and dev/fake_board.py.

    Time only moves when you move it: advance(ms) steps forward, set(ms) jumps
    to an absolute value. now_ms() never advances on its own, so a test can
    reproduce any cadence — including the irregular intervals exponential
    back-off produces — exactly.
    """

    def __init__(self, start_ms=0):
        self._t = start_ms

    def now_ms(self):
        return self._t

    def advance(self, ms):
        self._t += ms
        return self._t

    def set(self, ms):
        self._t = ms
        return self._t
