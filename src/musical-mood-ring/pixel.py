# pixel.py
#
# NeoPixel driver for musical-mood-ring.
#
# Thin hardware wrapper. On ESP32 (MicroPython) drives a 3-pixel WS2812B strip
# via the neopixel module. On CPython (tests/PC) silently no-ops — import and
# call freely without any hardware present.
#
# GPIO pin: set _PIN to match your wiring before flashing.
#
# Transfer function. color.py emits sRGB — what the ring should look like.
# A WS2812B's PWM duty is linear in the byte it is given, so handing it an
# sRGB byte directly over-brightens every mid-tone and washes the palette
# pale: #70AFC4 would emit as if it were (0.44, 0.69, 0.77) of full power
# instead of (0.15, 0.43, 0.56). That flattens exactly the pastels the
# calibrated palette depends on, so _GAMMA is applied here, once, on the way
# out. Set _GAMMA_CORRECT = False on the bench to see the raw bytes.

_NUM_PIXELS = 3
_PIN        = 4   # GPIO number — adjust for final wiring

_GAMMA_CORRECT = True

# sRGB byte → linear-light byte. Table built once; 256 entries is cheaper
# than a pow() per channel per write on the ESP32.
def _build_gamma_table():
    table = []
    for i in range(256):
        c = i / 255.0
        lin = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        table.append(int(lin * 255.0 + 0.5))
    return table


_GAMMA = _build_gamma_table()

try:
    import machine
    import neopixel as _neopixel
    _np = _neopixel.NeoPixel(machine.Pin(_PIN), _NUM_PIXELS)
    _HW = True
except ImportError:
    _np = None
    _HW = False


def to_duty(rgb):
    """One sRGB (r, g, b) → the (r, g, b) duty bytes the WS2812B is given.

    Channels are clamped to [0, 255] first. Exposed so the offline harness
    and tests can see exactly what the strip would receive.
    """
    out = []
    for c in rgb:
        c = max(0, min(255, int(c)))
        out.append(_GAMMA[c] if _GAMMA_CORRECT else c)
    return tuple(out)


def write(colors):
    """
    Write three (r, g, b) sRGB tuples to the NeoPixels.
    colors: iterable of 3 (r, g, b) tuples, each channel 0–255.
    Channels are clamped and gamma-corrected via to_duty() before writing.
    No-ops silently when hardware is unavailable.
    """
    if not _HW:
        return
    for i, rgb in enumerate(colors):
        _np[i] = to_duty(rgb)
    _np.write()


def off():
    """Turn all pixels off."""
    write([(0, 0, 0)] * _NUM_PIXELS)
