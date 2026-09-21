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
# pale: indie-melancholy's #7EC2F2 would emit as if it were (0.49, 0.76, 0.95)
# of full power instead of (0.21, 0.54, 0.89). That flattens exactly the
# pastels the calibrated palette depends on, so _GAMMA is applied here, once,
# on the way out. Set _GAMMA_CORRECT = False on the bench to see the raw bytes.

_NUM_PIXELS = 3
_PIN        = 4   # GPIO number — adjust for final wiring

# Leave this ON. It looks like a taste flag and is not one -- it exists so the
# bench can A/B it, and the bench settled the question (issue #9, on a XIAO C3
# behind diffusion):
#
#   - Turning it off shifts every knot's CHROMATICITY, by up to 0.237
#     (fun/dance) and 0.196 (darkwave) -- more than the 0.20 floor the whole
#     palette is spaced on. Observed as darkwave going "a nice clean blue,
#     then more of a purple": with no correction the near-off red channel
#     rises 5 -> 39 and drags the hue violet.
#   - It also collapses the margin against the zero-confidence grey.
#     indie-melancholy sits 0.291 from that grey with gamma on and 0.149
#     without -- under the 0.25 floor, so a CONFIDENT colour would read as a
#     miss. Observed as "sky blue then basically white".
#
# So gamma is load-bearing twice over: hue fidelity at the dark end, and
# keeping real colours distinct from the miss colour.
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
