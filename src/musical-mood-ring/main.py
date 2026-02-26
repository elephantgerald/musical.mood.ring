# main.py
#
# Main poll loop for musical-mood-ring.
# Runs after boot.py has established WiFi.
#
# Every POLL_INTERVAL_MS:
#   1. Refresh the Spotify access token if needed
#   2. Fetch recently-played track IDs
#   3. Run them through the mood engine (MMAR lookup + EWMA update)
#   4. Write the three resulting colours to the NeoPixels
#
# TODO (M4): implement full error handling and exponential back-off (#28).
# TODO (M6): add startup flare and idle sparkle animations (#35, #36).

import config
import pixel
import spotify
from mmar        import load as mmar_load
from mood_engine import MoodEngine

_POLL_INTERVAL_MS = 3 * 60 * 1000   # 3 minutes
_BUNDLE_PATH      = "memory-bundle.bin"

try:
    import utime
    def _sleep_ms(ms): utime.sleep_ms(ms)
except ImportError:
    import time
    def _sleep_ms(ms): time.sleep(ms / 1000)


def _load_bundle():
    try:
        return mmar_load(_BUNDLE_PATH)
    except OSError:
        return None


def main():
    bundle = _load_bundle()
    if bundle is None:
        pixel.write([(0, 8, 8)] * 3)   # dim teal: bundle missing
        return

    engine       = MoodEngine(bundle)
    access_token = None
    expires_at   = 0

    try:
        import utime
        now_ms = utime.ticks_ms
    except ImportError:
        import time
        now_ms = lambda: int(time.time() * 1000)

    pixel.write([(0, 16, 0)] * 3)   # dim green: ready

    while True:
        # Refresh token when missing or near expiry
        if access_token is None or now_ms() >= expires_at:
            token, expires_in = spotify.refresh_token(
                config.SPOTIFY_CLIENT_ID,
                config.SPOTIFY_CLIENT_SECRET,
                config.SPOTIFY_REFRESH_TOKEN,
            )
            if token:
                access_token = token
                expires_at   = now_ms() + (expires_in - 60) * 1000

        if access_token:
            track_ids = spotify.recently_played(access_token)
            colors    = engine.update(track_ids)
            pixel.write(colors)

        _sleep_ms(_POLL_INTERVAL_MS)


main()
