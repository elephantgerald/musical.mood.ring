# main.py
#
# Main loop for musical-mood-ring.
#
# Runs after boot.py has established WiFi. Drives two interleaved concerns:
#
#   Poll cadence  — every 3 minutes, fetch recently-played from Spotify,
#                   push through the mood engine, get new target colours.
#                   Managed by Poller (handles back-off on errors).
#
#   Animation     — every FRAME_MS, advance the active animator and write
#                   the result to the NeoPixels. The animation loop is never
#                   blocked by polling — the poll is synchronous within one
#                   frame, accepted latency ~1–2 s on a slow network.
#
# Animation state machine:
#   idle sparkle  ← no bundle hits yet, or persistent API failure
#       ↓  first hit after idle
#   startup flare  (3 s fade-in)
#       ↓  flare done
#   mood transition  (60 s smooth HSV fade between mood targets)
#       ↑  new target each poll while music plays
#
# Error overlays (exit back to idle sparkle when condition clears):
#   wifi_lost  — slow dim red pulse + active reconnect every 60 s
#   auth_fail  — 3 red flashes, then idle sparkle

import gc

import config
import pixel
import spotify
import wifi
from mmar        import load as mmar_load
from mood_engine import MoodEngine
from poller      import Poller
from lights      import StartupFlare, IdleSparkle, MoodTransition, ErrorIndicator, ApiErrorBlip

FRAME_MS          = 100   # ~10 fps animation update rate
BUNDLE_PATH       = "memory-bundle.bin"
ARTIST_BUNDLE_PATH = "artist-bundle.bin"

try:
    import utime
    def _now_ms():    return utime.ticks_ms()
    def _sleep_ms(ms): utime.sleep_ms(ms)
except ImportError:
    import time
    def _now_ms():    return int(time.time() * 1000)
    def _sleep_ms(ms): time.sleep(ms / 1000)

try:
    import machine as _machine
    _HW = True
except ImportError:
    _machine = None
    _HW = False

_RECONNECT_INTERVAL_MS = 60_000   # retry WiFi connect every 60 s when lost
_GC_INTERVAL           = 10       # call gc.collect() every N loop iterations


def main():
    bundle = None
    try:
        bundle = mmar_load(BUNDLE_PATH)
    except OSError:
        pixel.write([(0, 8, 8)] * 3)   # dim teal: bundle missing
        return

    artist_bundle = None
    try:
        artist_bundle = mmar_load(ARTIST_BUNDLE_PATH)
    except OSError:
        pass   # artist bundle is optional — device works without it

    engine       = MoodEngine(bundle, artist_bundle)
    poller       = Poller()
    access_token = None
    expires_at   = 0

    # Start in idle sparkle until music data arrives
    animator     = IdleSparkle()
    in_idle      = True    # True while we've never had a mood hit this session
    error_mode   = None    # None | "wifi_lost" | "auth_fail"
    _blip        = None    # short complementary double-flash overlay
    _last_colors = [(0, 0, 0)] * 3

    _reconnect_at = 0      # timestamp for next WiFi reconnect attempt
    _loop_count   = 0

    # Watchdog: reboots the device if the loop stalls for > 8 s
    _wdt = _machine.WDT(timeout=8000) if _HW else None

    prev_ms = _now_ms()
    pixel.write([(0, 16, 0)] * 3)   # dim green: ready

    while True:
        now_ms = _now_ms()
        dt_ms  = max(0, now_ms - prev_ms)
        prev_ms = now_ms

        # ── Housekeeping ─────────────────────────────────────────────────
        if _wdt:
            _wdt.feed()
        _loop_count += 1
        if _loop_count % _GC_INTERVAL == 0:
            gc.collect()

        # ── WiFi watchdog ─────────────────────────────────────────────────
        if not wifi.is_connected():
            if error_mode != ErrorIndicator.WIFI_LOST:
                animator      = ErrorIndicator(ErrorIndicator.WIFI_LOST)
                error_mode    = ErrorIndicator.WIFI_LOST
                _reconnect_at = now_ms   # attempt reconnect immediately
            if now_ms >= _reconnect_at:
                wifi.connect(config.WIFI_SSID, config.WIFI_PASSWORD, timeout_ms=5000)
                _reconnect_at = now_ms + _RECONNECT_INTERVAL_MS
        elif error_mode == ErrorIndicator.WIFI_LOST:
            # WiFi recovered — return to idle sparkle
            animator   = IdleSparkle()
            error_mode = None
            in_idle    = True

        # ── Poll ──────────────────────────────────────────────────────────
        if error_mode is None and poller.should_poll(now_ms):
            # Refresh access token when absent or near expiry
            if access_token is None or now_ms >= expires_at:
                token, expires_in = spotify.refresh_token(
                    config.SPOTIFY_CLIENT_ID,
                    config.SPOTIFY_CLIENT_SECRET,
                    config.SPOTIFY_REFRESH_TOKEN,
                )
                if token:
                    access_token = token
                    expires_at   = now_ms + (expires_in - 60) * 1000
                else:
                    animator   = ErrorIndicator(ErrorIndicator.AUTH_FAIL)
                    error_mode = ErrorIndicator.AUTH_FAIL
                    poller.on_error(now_ms)

            if access_token and error_mode is None:
                track_ids = spotify.recently_played(access_token)
                if track_ids is None:
                    # Network or API error
                    poller.on_error(now_ms)
                    if _blip is None:
                        _blip = ApiErrorBlip(_last_colors)
                else:
                    new_colors = engine.update(track_ids)
                    poller.on_success(now_ms)

                    if poller.is_persistent_failure(now_ms):
                        # Graceful degradation — treat as idle, not an error
                        if not in_idle:
                            animator = IdleSparkle()
                            in_idle  = True
                    else:
                        was_idle = in_idle
                        in_idle  = False
                        if was_idle:
                            animator = StartupFlare(new_colors)
                        elif isinstance(animator, StartupFlare) and animator.done:
                            animator = MoodTransition(new_colors, new_colors)
                        elif isinstance(animator, MoodTransition):
                            animator.update_target(new_colors)

        # ── Auth-fail overlay: dismiss when done ──────────────────────────
        if (error_mode == ErrorIndicator.AUTH_FAIL
                and isinstance(animator, ErrorIndicator)
                and animator.done):
            animator   = IdleSparkle()
            error_mode = None

        # ── Handoff: startup flare → mood transition ──────────────────────
        if isinstance(animator, StartupFlare) and animator.done:
            last = engine.update([])   # get current colours without a poll
            animator = MoodTransition(last, last)

        # ── Advance animation and write pixels ────────────────────────────
        colors = animator.step(dt_ms)
        if _blip is not None:
            blip_out = _blip.step(dt_ms)
            if _blip.done:
                _blip = None
            else:
                colors = blip_out
        _last_colors = colors
        pixel.write(colors)

        _sleep_ms(FRAME_MS)


try:
    main()
except Exception:
    if _HW:
        _machine.reset()
