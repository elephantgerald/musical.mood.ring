#!/usr/bin/env python3
"""
dev/fake_board.py — run the firmware poll loop in CPython against the
musical-radio-station mock Spotify server. No hardware, no real Spotify.

This is the "fake board": it imports the *real* firmware modules (config,
spotify, mood_engine, runtime_state, poller) and drives main.run_poll_cycle()
in a loop — the same code path the ESP32 runs — printing simulated NeoPixels
and engine state after each poll. It closes the M10 software loop (mock Spotify
↔ engine) before any hardware is involved.

Prereqs (in another shell):
    dev/start.sh                                              # mock on :5000
    curl -X PUT "http://localhost:5000/control/playlist?name=mood_journey"

Run:
    .venv/bin/python dev/fake_board.py                        # loop until Ctrl-C
    .venv/bin/python dev/fake_board.py --polls 8 --advance 3  # 8 polls, step scenario

The firmware reaches the mock because spotify.py honours SPOTIFY_MOCK_HOST for
loopback/RFC1918 targets; we set it to 127.0.0.1:5000 in-process below.
"""

import argparse
import glob
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE  = os.path.join(REPO_ROOT, "src", "musical-mood-ring")
BUNDLE_DIR = os.path.join(REPO_ROOT, "data", "musical-memory-bundle")

sys.path.insert(0, FIRMWARE)


def _newest(pattern):
    """Newest bundle matching pattern in BUNDLE_DIR, or None."""
    hits = sorted(glob.glob(os.path.join(BUNDLE_DIR, pattern)))
    return hits[-1] if hits else None


def _swatch(rgb):
    """Render one pixel as a truecolor block plus its RGB triple."""
    r, g, b = rgb
    return "\033[48;2;{};{};{}m   \033[0m {:>3},{:>3},{:>3}".format(r, g, b, r, g, b)


def _http_control(mock, method, path):
    """Best-effort call to a mock /control endpoint (scenario stepping)."""
    import requests
    try:
        requests.request(method, "http://{}{}".format(mock, path), timeout=4)
    except Exception as e:
        print("  (control {} {} failed: {})".format(method, path, e))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", default="127.0.0.1:5000",
                    help="mock Spotify host:port (default 127.0.0.1:5000)")
    ap.add_argument("--polls", type=int, default=0,
                    help="number of polls then exit; 0 = loop until Ctrl-C")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="real seconds to sleep between polls (default 2)")
    ap.add_argument("--sim-interval", type=float, default=180.0,
                    help="SIMULATED seconds the engine clock advances per poll "
                         "(default 180 = nominal 3-min cadence). Raise it to cross "
                         "the 1h/4h pixel tiers in a handful of polls.")
    ap.add_argument("--advance", type=int, default=0,
                    help="fast-forward the mock by N tracks between polls (shows motion)")
    ap.add_argument("--bundle", default=None, help="memory-bundle.bin (default: newest in data/)")
    ap.add_argument("--artist-bundle", default=None, help="artist-bundle.bin (default: newest in data/)")
    args = ap.parse_args()

    # ── Point the firmware at the mock (loopback ⇒ _mock_host_ok) ───────────────
    import config
    config.SPOTIFY_MOCK_HOST     = args.mock
    config.SPOTIFY_REFRESH_TOKEN = "mock"   # mock /api/token accepts anything
    config.SPOTIFY_CLIENT_ID     = "mock"
    config.SPOTIFY_CLIENT_SECRET = "mock"

    from clock         import FakeClock
    from mmar          import load as mmar_load
    from mood_engine   import MoodEngine
    from poller        import Poller
    from runtime_state import RuntimeState
    import main as firmware_main

    bundle_path = args.bundle or _newest("memory-bundle-*.bin")
    artist_path = args.artist_bundle or _newest("artist-bundle-*.bin")
    if not bundle_path:
        sys.exit("No memory bundle found in {} — run src/musical-bottler/bottle.py".format(BUNDLE_DIR))

    bundle        = mmar_load(bundle_path)
    artist_bundle = mmar_load(artist_path) if artist_path else None

    sim_clock    = FakeClock()   # engine time advances by --sim-interval per poll
    state        = RuntimeState()
    state.engine = MoodEngine(bundle, artist_bundle, clock=sim_clock)
    poller       = Poller()
    access_token = None
    expires_at   = 0
    sim_step_ms  = int(args.sim_interval * 1000)

    print("fake board → mock {}".format(args.mock))
    print("  bundle:        {}".format(os.path.basename(bundle_path)))
    print("  artist bundle: {}".format(os.path.basename(artist_path) if artist_path else "(none)"))
    print("  pixels: [1]=now  [2]=1h EWMA  [3]=4h EWMA\n")

    n = 0
    try:
        while args.polls == 0 or n < args.polls:
            n += 1
            now_ms = sim_clock.now_ms()
            result = firmware_main.run_poll_cycle(state, poller, access_token, expires_at, now_ms)
            access_token = result["access_token"]
            expires_at   = result["expires_at"]
            err          = result["poll_error"]

            snap = state.engine.snapshot()
            elapsed_min = now_ms / 60000.0
            print("── poll {} (sim t+{:.0f} min) ───────────────────────".format(n, elapsed_min))
            if err:
                print("  outcome: ERROR ({})".format(err))
            else:
                colors = result["new_colors"] or [(0, 0, 0)] * 3
                outcomes = state.engine.last_poll_outcomes()
                hits = sum(1 for o in outcomes if o[2] != "miss")
                print("  outcome: ok — {}/{} tracks hit bundle, confidence={:.2f}"
                      .format(hits, len(outcomes), snap["confidence"]))
                tier = ("now/now/now (<1h)"   if elapsed_min < 60
                        else "now/1h/1h (1-4h)" if elapsed_min < 240
                        else "now/1h/4h (>4h)")
                print("    tier: {}".format(tier))
                for i, c in enumerate(colors, 1):
                    print("    pixel {}: {}".format(i, _swatch(c)))
                print("    now_ve={}  ewma_1h={}  ewma_4h={}".format(
                    snap["now_ve"],
                    [round(x, 3) for x in snap["ewma_1h"]],
                    [round(x, 3) for x in snap["ewma_4h"]]))
                # show the tracks that drove this poll (first few)
                for o in outcomes[:4]:
                    tid, aid, src, v, e = o
                    ve = "({:.2f},{:.2f})".format(v, e) if v is not None else "—"
                    print("      {:<24} {:<6} {}".format(tid, src, ve))

            if args.advance and (args.polls == 0 or n < args.polls):
                _http_control(args.mock, "POST", "/control/fast-forward")
            sim_clock.advance(sim_step_ms)   # advance simulated engine time
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
