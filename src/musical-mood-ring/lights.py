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
import random


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

_IDLE_PEAK = (28, 30, 45)   # cool white at full brightness

_IDLE_TAU  = 2.0 * math.pi

# Per-pixel swell parameters: (phi, T_med, t_off_med, T_slow, t_off_slow)
# Slightly detuned so pixels breathe independently.
# Slow periods ~360 s → bell strikes roughly once per 6 min per pixel.
_IDLE_PX = (
    (0.0,  67.0,  40.2,  360.0, 216.0),   # pixel 0
    (2.1,  71.0,  49.7,  379.0, 265.3),   # pixel 1
    (4.2,  61.0,  48.8,  341.0, 272.8),   # pixel 2
)

# Noise baseline (candle flicker texture)
_IDLE_MU         = 0.08   # noise centre — dim glow, leaves headroom for swells
_IDLE_SIGMA      = 0.06   # std dev — 68% of noise in [0.02, 0.14]
_IDLE_FLOOR      = 0.01   # hard floor
_IDLE_NOISE_CEIL = 0.20   # noise hard cap — swells push above this

# Medium swell (sin^6, ~67 s) → ~0.60 total peak roughly once/min
_IDLE_AMED = 0.52
_IDLE_POW  = 6

# Slow swell — bell-strike envelope (~360 s) → ~0.90 total peak ~once/6 min
_IDLE_ASLO       = 0.82
_IDLE_RING_DECAY = 0.977   # per-frame at 50 ms — half-life ~1.5 s

_IDLE_ALPHA = 0.15         # EWMA output smoothing


def _idle_gauss():
    """Box-Muller normal sample (MicroPython has no random.gauss)."""
    u1 = random.random() or 1e-9
    u2 = random.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(_IDLE_TAU * u2)


class IdleSparkle:
    """
    Idle animation: Gaussian noise candle baseline + deterministic swells.

      baseline  Gaussian noise → organic candle flicker texture
      medium    sin^6 swell (~67 s)   → ~0.60 peak roughly once/min
      slow      bell-strike envelope  → ~0.90 peak roughly once/6 min,
                instantaneous attack at swell zero-crossing, exponential decay

    Each pixel is independent: slightly detuned swell periods, independent
    noise streams.  EWMA smooths the combined output frame-to-frame.
    """

    def __init__(self, num_pixels=3):
        self._n          = num_pixels
        self._t          = 0.0
        self._br         = [_IDLE_MU] * num_pixels   # smoothed output
        self._ring_amp   = [0.0]      * num_pixels   # decaying bell amplitude
        self._was_silent = [True]     * num_pixels   # slow swell zero last frame?
        self.done        = False

    def step(self, dt_ms):
        self._t += dt_ms / 1000.0
        out = []
        for i in range(self._n):
            phi, Tm, t_off_m, Ts, t_off_s = _IDLE_PX[i % len(_IDLE_PX)]

            noise  = min(_IDLE_NOISE_CEIL, max(_IDLE_FLOOR,
                         _IDLE_MU + _IDLE_SIGMA * _idle_gauss()))

            sm     = max(0.0, math.sin(_IDLE_TAU * (self._t + t_off_m) / Tm))
            medium = _IDLE_AMED * sm ** _IDLE_POW

            slow_raw = math.sin(_IDLE_TAU * (self._t + t_off_s) / Ts)
            if slow_raw > 0 and self._was_silent[i]:
                self._ring_amp[i] = _IDLE_ASLO
            self._was_silent[i] = slow_raw <= 0
            self._ring_amp[i]  *= _IDLE_RING_DECAY

            target      = min(1.0, noise + medium + self._ring_amp[i])
            self._br[i] = _IDLE_ALPHA * target + (1.0 - _IDLE_ALPHA) * self._br[i]
            br = self._br[i]
            out.append((
                int(_IDLE_PEAK[0] * br),
                int(_IDLE_PEAK[1] * br),
                int(_IDLE_PEAK[2] * br),
            ))
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
