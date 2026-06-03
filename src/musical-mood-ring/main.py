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
#
# Graceful degradation: after a sustained Spotify outage (no successful poll for
# ~15 min) the ring calms to idle sparkle rather than holding stale colours. This
# looks like "no music," but the failure is not hidden — every poll outcome is
# recorded to the poll log (#57) and surfaced over HTTP (#58).

import gc

import config
import pixel
import spotify
import wifi
from config_server import ConfigServer
from mmar          import load as mmar_load
from mood_engine   import MoodEngine
from poller        import Poller
from runtime_state import RuntimeState
from lights        import StartupFlare, IdleSparkle, MoodTransition, ErrorIndicator, ApiErrorBlip

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
_SETUP_GRACE_MS        = 300_000  # 5 min after boot: config endpoints open, then lock to read-only


def should_degrade_to_idle(poller, error_mode, in_idle, now_ms):
    """True when polls have failed long enough to calmly fall back to idle.

    Must be checked once per loop iteration — NOT only after a poll. That
    placement is the whole point of the fix: is_persistent_failure() can only be
    True while an error streak is active, and on_success() zeroes that streak, so
    a check nested in the success path is dead code that never fires.

    Guarded so it never overrides an active error overlay (WIFI_LOST / AUTH_FAIL)
    and doesn't re-trigger once already idle.
    """
    return (error_mode is None
            and not in_idle
            and poller.is_persistent_failure(now_ms))


def next_animator(animator, in_idle, new_colors, degrade):
    """Compute the next (animator, in_idle) for one loop iteration — pure.

    Owns only the mood↔idle animator. Error overlays (WIFI_LOST/AUTH_FAIL
    indicators, the ApiErrorBlip, error_mode) stay in the loop; this composes
    the two mood-relevant decisions so both are unit-testable off the board:

        degrade=True            → calm to idle sparkle (persistent-failure
                                  graceful degradation; takes precedence).
        new_colors set (a poll  → advance the mood animation: flare out of idle
        succeeded this iter)      on the first hit, hand the finished flare to a
                                  MoodTransition, then retarget it on later hits.
        new_colors is None       → no successful poll this iteration; leave the
        and not degrading          animator untouched.

    degrade and a successful poll are mutually exclusive in practice:
    run_poll_cycle calls on_success() on the success path, which zeroes the
    error streak, so should_degrade_to_idle() is False that same iteration. The
    precedence here just makes the helper total.
    """
    if degrade:
        return IdleSparkle(), True
    if new_colors is None:
        return animator, in_idle
    if in_idle:
        return StartupFlare(new_colors), False
    if isinstance(animator, StartupFlare) and animator.done:
        return MoodTransition(new_colors, new_colors), False
    if isinstance(animator, MoodTransition):
        animator.update_target(new_colors)
        return animator, False
    return animator, False


def run_poll_cycle(state, poller, access_token, expires_at, now_ms, wdt=None):
    """Run one Spotify poll and record the outcome to the poll log (#57).

    Refreshes the access token when due, fetches recently-played, pushes hits
    through the engine, and appends exactly one poll-log record on every outcome
    path — auth-fail, network error, and success alike.

    Extracted from main()'s loop so the poll-and-record wiring is importable and
    unit-testable on its own (main() only auto-runs under __main__). This
    function deliberately touches no animation state: it returns what the caller
    needs to drive the animator, and the caller owns that mapping.

    Returns a dict:
        access_token, expires_at — carried forward; refreshed when due
        poll_error  — None | "auth_fail" | "network"
        new_colors  — engine.update() output on success, else None
    """
    poll_error     = None
    poll_track_ids = []
    poll_results   = []
    new_colors     = None

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
            poller.on_error(now_ms)
            poll_error = "auth_fail"
        if wdt:
            wdt.feed()   # token call may have consumed several seconds

    if poll_error is None and access_token:
        track_ids = spotify.recently_played(access_token)
        if track_ids is None:
            # Network or API error
            poller.on_error(now_ms)
            poll_error = "network"
        else:
            new_colors = state.engine.update(track_ids)
            poller.on_success(now_ms)
            poll_track_ids = [tid for tid, _aid in track_ids]
            # (v, e) per track, order-aligned to track_ids; None on a full miss
            # (no bundle hit) so the record matches the issue's "(v,e) or null"
            # schema rather than storing a [null, null] pair.
            # OUTCOME_FIELDS = (track_id, artist_id, source, v, e).
            poll_results = [None if o[2] == "miss" else (o[3], o[4])
                            for o in state.engine.last_poll_outcomes()]
            state.last_track_ids   = poll_track_ids
            state.last_poll_ms     = now_ms
            state.last_mood_colors = new_colors

    # Log this poll regardless of outcome (#57). colors_after is the engine's
    # mood output (last_mood_colors) — None until the first successful poll, not
    # the animator overlay.
    state.record_poll(now_ms, poll_track_ids, poll_results,
                      state.last_mood_colors,
                      state.engine.snapshot()["confidence"], poll_error)

    return {
        "access_token": access_token,
        "expires_at":   expires_at,
        "poll_error":   poll_error,
        "new_colors":   new_colors,
    }


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

    state        = RuntimeState()
    state.engine = MoodEngine(bundle, artist_bundle)
    poller       = Poller()
    # Open the config server in setup mode for a bounded window after boot, then
    # lock it to read-only runtime. The owner is physically present right after
    # power-on, so this is when re-configuration (Spotify OAuth, mock host) is
    # legitimate; for the rest of the device's uptime only read-only endpoints
    # are served. See ConfigServer.lock_runtime() and _SETUP_GRACE_MS.
    cfg_server   = ConfigServer(mode="setup", state=state)
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
    _setup_deadline = prev_ms + _SETUP_GRACE_MS   # lock config server to read-only after this
    pixel.write([(0, 16, 0)] * 3)   # dim green: ready

    while True:
        now_ms = _now_ms()
        dt_ms  = max(0, now_ms - prev_ms)
        prev_ms = now_ms

        # ── Housekeeping ─────────────────────────────────────────────────
        if _wdt:
            _wdt.feed()
        if now_ms >= _setup_deadline:
            cfg_server.lock_runtime()   # one-way; idempotent
        cfg_server.step()
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
        # run_poll_cycle does the fetch + engine update + poll-log record (#57).
        # Here we map its outcome onto error overlays and capture new_colors for
        # the mood animation; token state is threaded back out across iterations.
        # The mood↔idle animator itself is computed once below via next_animator.
        new_colors = None   # set only when a poll succeeds this iteration
        if error_mode is None and config.SPOTIFY_REFRESH_TOKEN and poller.should_poll(now_ms):
            result       = run_poll_cycle(state, poller, access_token, expires_at, now_ms, _wdt)
            access_token = result["access_token"]
            expires_at   = result["expires_at"]
            poll_error   = result["poll_error"]

            if poll_error == "auth_fail":
                animator   = ErrorIndicator(ErrorIndicator.AUTH_FAIL)
                error_mode = ErrorIndicator.AUTH_FAIL
            elif poll_error == "network":
                # Brief overlay only; error_mode stays None so a sustained
                # network outage can fall through to graceful degradation below.
                if _blip is None:
                    _blip = ApiErrorBlip(_last_colors)
            else:
                # poll_error is None ⟺ run_poll_cycle called on_success(), so
                # new_colors is the fresh mood and the error streak is now zero.
                new_colors = result["new_colors"]

        # ── Mood↔idle animator ────────────────────────────────────────────
        # Computed every iteration (not just after a poll). The degrade flag is
        # only ever True mid-error-streak, which — because on_success() zeroed
        # the streak above — never coincides with new_colors being set. This is
        # where the network/silent-outage case finally calms to idle once the
        # 15-min window elapses; the AUTH_FAIL path reaches idle via its own
        # dismissal below instead.
        animator, in_idle = next_animator(
            animator, in_idle, new_colors,
            should_degrade_to_idle(poller, error_mode, in_idle, now_ms))

        # ── Auth-fail overlay: dismiss when done ──────────────────────────
        if (error_mode == ErrorIndicator.AUTH_FAIL
                and isinstance(animator, ErrorIndicator)
                and animator.done):
            animator   = IdleSparkle()
            error_mode = None
            in_idle    = True   # mirror WIFI_LOST recovery so the next hit flares

        # ── Handoff: startup flare → mood transition ──────────────────────
        if isinstance(animator, StartupFlare) and animator.done:
            last = state.engine.update([])   # get current colours without a poll
            state.last_mood_colors = last
            animator = MoodTransition(last, last)

        # ── Advance animation and write pixels ────────────────────────────
        colors = animator.step(dt_ms)
        if _blip is not None:
            blip_out = _blip.step(dt_ms)
            if _blip.done:
                _blip = None
            else:
                colors = blip_out
        _last_colors      = colors
        state.last_colors = colors
        pixel.write(colors)

        _sleep_ms(FRAME_MS)


# MicroPython auto-runs main.py as the top-level boot script (__name__ ==
# "__main__"); guarding the call lets CPython unit tests `import main` to reach
# run_poll_cycle() without launching the infinite loop.
if __name__ == "__main__":
    try:
        main()
    except Exception:
        if _HW:
            _machine.reset()
