# lights.py
#
# Animation state machines for musical-mood-ring.
#
# Each animator is a non-blocking state machine driven by the main loop:
#
#     animator.step(dt_ms)  →  [(r,g,b), (r,g,b), (r,g,b)]
#
# No hardware calls are made here — pixel.write() is the caller's job.
# Pure Python, fully testable in CPython without a board.
#
# Animators:
#   StartupFlare    — linear brightness fade from black to target (~3 s)
#   IdleSparkle     — per-pixel random cool-white flickers at dim brightness
#   MoodTransition  — smooth HSV interpolation between mood colours (~60 s)
#   ErrorIndicator  — dim red pulse (WiFi lost) or 3 red flashes (auth fail)
#   ApiErrorBlip    — brief complementary double-flash on transient API error

import math

try:
    import urandom as _rmod
    def _default_randint(a, b): return _rmod.randint(a, b)
except ImportError:
    import random as _rmod
    def _default_randint(a, b): return _rmod.randint(a, b)


# ── HSV ↔ RGB helpers ──────────────────────────────────────────────────────

def _rgb_to_hsv(r, g, b):
    """RGB ints (0–255) → (hue_deg, saturation, value) floats."""
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn  = max(r, g, b), min(r, g, b)
    diff    = mx - mn
    v       = mx
    s       = 0.0 if mx == 0 else diff / mx
    if diff == 0:
        h = 0.0
    elif mx == r:
        h = (60.0 * ((g - b) / diff)) % 360.0
    elif mx == g:
        h = 60.0 * ((b - r) / diff) + 120.0
    else:
        h = 60.0 * ((r - g) / diff) + 240.0
    return h, s, v


def _hsv_to_rgb_int(h, s, v):
    """(hue_deg, saturation, value) floats → RGB ints (0–255)."""
    v = max(0.0, min(1.0, v))
    s = max(0.0, min(1.0, s))
    if s == 0.0:
        c = int(v * 255)
        return (c, c, c)
    h = (h % 360) / 60.0
    i = int(h)
    f = h - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    rv, gv, bv = [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)][i % 6]
    return (int(rv * 255), int(gv * 255), int(bv * 255))


def _lerp_hue(h0, h1, frac):
    """Interpolate hue, always taking the shorter arc around the wheel."""
    diff = (h1 - h0 + 180) % 360 - 180
    return (h0 + diff * frac) % 360


# ── StartupFlare ───────────────────────────────────────────────────────────

class StartupFlare:
    """
    Linear brightness fade from black to target_colors over duration_ms.
    Triggered once when the engine transitions from idle to active.
    Check .done to know when to hand off to MoodTransition.
    """

    def __init__(self, target_colors, duration_ms=3000):
        self._target   = list(target_colors)
        self._duration = duration_ms
        self._elapsed  = 0
        self.done      = False

    def step(self, dt_ms):
        self._elapsed += dt_ms
        if self._elapsed >= self._duration:
            self.done = True
            return list(self._target)
        frac = self._elapsed / self._duration
        return [(int(r * frac), int(g * frac), int(b * frac))
                for r, g, b in self._target]


# ── IdleSparkle ────────────────────────────────────────────────────────────

_IDLE_OFF  = (0, 0, 0)
_IDLE_PEAK = (6, 7, 10)   # cool dim white — ~4% of NeoPixel ceiling


class IdleSparkle:
    """
    Per-pixel independent random flicker of cool dim white.

    Each pixel has its own countdown timer. When it fires the pixel shows
    _IDLE_PEAK briefly, then resets to a new random interval. Timing is
    intentionally aperiodic — no two pixels share a schedule.

    Pass randint_fn in tests to make behaviour deterministic.
    """

    MIN_MS     = 2000
    MAX_MS     = 8000
    FLICKER_MS = 250

    def __init__(self, num_pixels=3, randint_fn=None):
        self._rng  = randint_fn or _default_randint
        self._px   = [{"countdown":  self._rng(0, self.MAX_MS),
                        "flickering": False,
                        "flicker_left": 0}
                      for _ in range(num_pixels)]
        self.done  = False   # cleared externally when new mood data arrives

    def step(self, dt_ms):
        out = []
        for px in self._px:
            if px["flickering"]:
                px["flicker_left"] -= dt_ms
                if px["flicker_left"] <= 0:
                    px["flickering"] = False
                    px["countdown"]  = self._rng(self.MIN_MS, self.MAX_MS)
                out.append(_IDLE_PEAK)
            else:
                px["countdown"] -= dt_ms
                if px["countdown"] <= 0:
                    px["flickering"]    = True
                    px["flicker_left"]  = self.FLICKER_MS
                    out.append(_IDLE_PEAK)
                else:
                    out.append(_IDLE_OFF)
        return out


# ── MoodTransition ─────────────────────────────────────────────────────────

class MoodTransition:
    """
    Smooth HSV interpolation from from_colors to to_colors over duration_ms.

    Hue always takes the shorter arc around the wheel (never the long way).
    Call update_target() when the mood engine produces a new target
    mid-transition — the new fade starts from the currently displayed colour.
    """

    def __init__(self, from_colors, to_colors, duration_ms=60_000):
        self._from     = [_rgb_to_hsv(*c) for c in from_colors]
        self._to       = [_rgb_to_hsv(*c) for c in to_colors]
        self._duration = duration_ms
        self._elapsed  = 0
        self.done      = False

    def _frame_at(self, frac):
        frac = max(0.0, min(1.0, frac))
        return [_hsv_to_rgb_int(_lerp_hue(h0, h1, frac),
                                s0 + (s1 - s0) * frac,
                                v0 + (v1 - v0) * frac)
                for (h0, s0, v0), (h1, s1, v1) in zip(self._from, self._to)]

    def step(self, dt_ms):
        self._elapsed += dt_ms
        if self._elapsed >= self._duration:
            self._elapsed = self._duration
            self.done     = True
        return self._frame_at(self._elapsed / self._duration)

    def update_target(self, new_target_colors):
        """Restart from the currently displayed colour toward a new target."""
        current    = self._frame_at(self._elapsed / self._duration)
        self._from = [_rgb_to_hsv(*c) for c in current]
        self._to   = [_rgb_to_hsv(*c) for c in new_target_colors]
        self._elapsed = 0
        self.done     = False


# ── ErrorIndicator ─────────────────────────────────────────────────────────

class ErrorIndicator:
    """
    Dim-red error animations. Two modes:

    WIFI_LOST  — slow sinusoidal red pulse, runs indefinitely until cleared.
    AUTH_FAIL  — three short red flashes, then .done = True (caller reverts
                 to idle sparkle per spec).

    Both modes respect the ambient brightness ceiling.
    """

    WIFI_LOST = "wifi_lost"
    AUTH_FAIL = "auth_fail"

    _PULSE_PERIOD_MS = 2000   # full breath cycle for WIFI_LOST
    _FLASH_ON_MS     = 700    # on-time per AUTH_FAIL flash
    _FLASH_OFF_MS    = 500    # gap between flashes
    _NUM_FLASHES     = 3

    def __init__(self, mode):
        self._mode    = mode
        self._elapsed = 0
        self.done     = False

    def step(self, dt_ms):
        self._elapsed += dt_ms

        if self._mode == self.WIFI_LOST:
            phase = (self._elapsed % self._PULSE_PERIOD_MS) / self._PULSE_PERIOD_MS
            v = int(20 * (0.5 - 0.5 * math.cos(2 * math.pi * phase)))
            return [(v, 0, 0)] * 3

        if self._mode == self.AUTH_FAIL:
            cycle_ms  = self._FLASH_ON_MS + self._FLASH_OFF_MS
            flash_num = int(self._elapsed / cycle_ms)
            if flash_num >= self._NUM_FLASHES:
                self.done = True
                return [(0, 0, 0)] * 3
            within = self._elapsed % cycle_ms
            color  = (28, 0, 0) if within < self._FLASH_ON_MS else (0, 0, 0)
            return [color] * 3

        return [(0, 0, 0)] * 3   # unknown mode — safe default


# ── BootStatus ──────────────────────────────────────────────────────────────

class BootStatus:
    """
    Boot-sequence animations. Non-blocking, driven by step(dt_ms).
    All modes respect a 50% brightness ceiling (channel values ≤ 128).

    Modes:
      CONNECTING  — slow white comet rotating across the 3 pixels (WiFi attempt)
      CONFIG_WAIT — slow blue sinusoidal pulse (AP up, waiting for user)
      SUCCESS     — brief green flash that fades out; done=True when finished
      FAIL        — 3 red flashes (reuses ErrorIndicator.AUTH_FAIL)
    """

    CONNECTING  = "connecting"
    CONFIG_WAIT = "config_wait"
    SUCCESS     = "success"
    FAIL        = "fail"

    _ROTATE_PERIOD_MS = 1200   # one full comet rotation
    _PULSE_PERIOD_MS  = 2000   # one full breath cycle
    _SUCCESS_MS       = 1500   # green fade-out duration

    def __init__(self, mode):
        self._mode    = mode
        self._elapsed = 0
        self.done     = False
        self._fail    = ErrorIndicator(ErrorIndicator.AUTH_FAIL) if mode == self.FAIL else None

    def step(self, dt_ms):
        self._elapsed += dt_ms

        if self._mode == self.CONNECTING:
            # Comet: one pixel bright, neighbours dim, rotates around 3 pixels
            pos = (self._elapsed % self._ROTATE_PERIOD_MS) / self._ROTATE_PERIOD_MS * 3
            colors = []
            for i in range(3):
                d = (pos - i) % 3
                if d > 1.5:
                    d = 3.0 - d
                v = max(0.0, 1.0 - d) * 128
                c = int(v)
                colors.append((c, c, c))
            return colors

        if self._mode == self.CONFIG_WAIT:
            phase = (self._elapsed % self._PULSE_PERIOD_MS) / self._PULSE_PERIOD_MS
            v = int(64 * (1.0 - math.cos(2 * math.pi * phase)))  # 0 → 128
            return [(0, 0, v)] * 3

        if self._mode == self.SUCCESS:
            if self._elapsed >= self._SUCCESS_MS:
                self.done = True
                return [(0, 0, 0)] * 3
            frac = 1.0 - self._elapsed / self._SUCCESS_MS  # fade out
            v = int(128 * frac)
            return [(0, v, 0)] * 3

        if self._mode == self.FAIL:
            out = self._fail.step(dt_ms)
            if self._fail.done:
                self.done = True
            return out

        return [(0, 0, 0)] * 3   # unknown mode — safe default


# ── ApiErrorBlip ─────────────────────────────────────────────────────────────

class ApiErrorBlip:
    """
    Brief double-flash of the complementary colour on a transient API error.

    Computes the complementary hue of the currently displayed colours, then:

        300 ms on  →  300 ms off  →  300 ms on  →  done=True

    All three pixels show the same complementary colour. Brightness is capped
    at 50% and floored at 25% so the blip is always visible but never harsh.
    The caller resumes its normal animator after done=True.
    """

    _PHASE_MS = 300

    def __init__(self, current_colors):
        self._comp    = self._complementary(current_colors)
        self._elapsed = 0
        self.done     = False

    @staticmethod
    def _complementary(colors):
        """Average input pixels, shift hue 180°, enforce visibility."""
        n = len(colors) or 1
        r = sum(c[0] for c in colors) // n
        g = sum(c[1] for c in colors) // n
        b = sum(c[2] for c in colors) // n
        h, s, v = _rgb_to_hsv(r, g, b)
        h = (h + 180.0) % 360.0
        s = max(s, 0.6)              # ensure visibly saturated
        v = max(min(v, 0.5), 0.25)  # cap at 50%; floor at 25%
        return _hsv_to_rgb_int(h, s, v)

    def step(self, dt_ms):
        self._elapsed += dt_ms
        if self._elapsed >= self._PHASE_MS * 3:
            self.done = True
            return [(0, 0, 0)] * 3
        phase = self._elapsed // self._PHASE_MS   # 0, 1, or 2
        if phase == 1:                             # middle: off
            return [(0, 0, 0)] * 3
        return [self._comp] * 3
