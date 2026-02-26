# pixel.py
#
# NeoPixel driver for musical-mood-ring.
#
# Thin hardware wrapper. On ESP32 (MicroPython) drives a 3-pixel WS2812B strip
# via the neopixel module. On CPython (tests/PC) silently no-ops — import and
# call freely without any hardware present.
#
# GPIO pin: set _PIN to match your wiring before flashing.

_NUM_PIXELS = 3
_PIN        = 4   # GPIO number — adjust for final wiring

try:
    import machine
    import neopixel as _neopixel
    _np = _neopixel.NeoPixel(machine.Pin(_PIN), _NUM_PIXELS)
    _HW = True
except ImportError:
    _np = None
    _HW = False


def write(colors):
    """
    Write three (r, g, b) tuples to the NeoPixels.
    colors: iterable of 3 (r, g, b) tuples, each channel 0–255.
    No-ops silently when hardware is unavailable.
    """
    if not _HW:
        return
    for i, rgb in enumerate(colors):
        _np[i] = rgb
    _np.write()


def off():
    """Turn all pixels off."""
    write([(0, 0, 0)] * _NUM_PIXELS)
