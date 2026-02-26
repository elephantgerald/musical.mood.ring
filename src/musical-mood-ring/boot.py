# boot.py
#
# ESP32 boot sequence for musical-mood-ring.
# MicroPython runs boot.py before main.py on every power-up.
#
# Responsibilities:
#   1. Show a "connecting" dim-white status on the pixels
#   2. Load WiFi credentials from config and connect
#   3. On failure: blink red indefinitely (needs reconfiguration)
#
# TODO (M2): add config_server entry point for first-boot setup mode.

import config
import pixel
import wifi


def _blink_error():
    """Slow red blink — WiFi credentials missing or unreachable."""
    try:
        import utime
        while True:
            pixel.write([(48, 0, 0)] * 3)
            utime.sleep_ms(600)
            pixel.off()
            utime.sleep_ms(600)
    except Exception:
        pass


pixel.write([(16, 16, 16)] * 3)   # dim white: connecting

if not config.WIFI_SSID:
    _blink_error()

if not wifi.connect(config.WIFI_SSID, config.WIFI_PASSWORD):
    _blink_error()

# WiFi up — main.py takes over
