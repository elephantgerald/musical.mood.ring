# boot.py
#
# ESP32 boot sequence for musical-mood-ring.
# MicroPython runs boot.py before main.py on every power-up.
#
# Two branches:
#
#   First-boot (no wifi_ssid in config):
#     Bring up AP, serve the config web page, wait for the user to submit
#     WiFi credentials (or the 5-minute window to expire), then reboot.
#
#   Normal-boot (wifi_ssid present):
#     Connect to WiFi with a CONNECTING animation; on success start mDNS
#     and hand off to main.py. On failure pulse dim red indefinitely.

import config
import pixel
import wifi
import ap
import mdns
from lights import BootStatus, ErrorIndicator

FRAME_MS = 50   # animation frame interval in ms

try:
    import utime
    import machine
    def _sleep_ms(ms): utime.sleep_ms(ms)
    def _reset():      machine.reset()
    _HW = True
except ImportError:
    def _sleep_ms(ms): pass
    def _reset():      pass
    _HW = False


if not config.WIFI_SSID:
    # ── First-boot: no WiFi credentials ─────────────────────────────────────

    from config_server import ConfigServer

    ap.allow_configure()
    server   = ConfigServer()
    animator = BootStatus(BootStatus.CONFIG_WAIT)

    # 5-minute ONE_SHOT timer — stops the server when the config window expires
    if _HW:
        def _timeout_cb(t):
            server.stop()
        _timer = machine.Timer(-1)
        _timer.init(mode=machine.Timer.ONE_SHOT, period=300_000, callback=_timeout_cb)

    while not server.done:
        server.step()
        pixel.write(animator.step(FRAME_MS))
        _sleep_ms(FRAME_MS)

    ap.disallow_configure()
    _reset()   # reboots into normal-boot with the saved config

else:
    # ── Normal-boot: connect to WiFi ─────────────────────────────────────────

    animator = BootStatus(BootStatus.CONNECTING)
    pixel.write(animator.step(0))   # show first frame immediately

    connected = wifi.connect(config.WIFI_SSID, config.WIFI_PASSWORD)

    if connected:
        mdns.start()
        success = BootStatus(BootStatus.SUCCESS)
        pixel.write(success.step(0))
        _sleep_ms(BootStatus._SUCCESS_MS)
        # Fall through — MicroPython runs main.py next
    else:
        error = ErrorIndicator(ErrorIndicator.WIFI_LOST)
        while True:
            pixel.write(error.step(FRAME_MS))
            _sleep_ms(FRAME_MS)
