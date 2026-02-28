"""
intensity_test.py — Find the WS2812B minimum visible brightness threshold

Steps all 3 pixels through increasing cool-white values, printing each level
to the terminal. Watch for when the pixels first become visible — that's your
minimum threshold. Use the result to set _IDLE_PEAK in lights.py.

Run:
    mpremote connect /dev/ttyUSB0 run tests/hardware/intensity_test.py
"""

import machine
import neopixel
import time

_PIN  = 4   # GPIO 4 = A5 on HUZZAH32
_NUM  = 3

np = neopixel.NeoPixel(machine.Pin(_PIN), _NUM)

# Cool-white ratio — matches _IDLE_PEAK in lights.py (R : G : B ≈ 0.62 : 0.67 : 1.0)
_RATIO = (0.62, 0.67, 1.0)

STEPS = [1, 2, 3, 5, 8, 10, 12, 15, 18, 20, 25, 30, 35, 40, 50, 64, 80, 100, 128]


def _show(colors):
    for i, c in enumerate(colors):
        np[i] = c
    np.write()


def _off():
    _show([(0, 0, 0)] * _NUM)


try:
    print("Intensity sweep — blue channel value shown; R and G scale proportionally")
    print()
    for step in STEPS:
        color = (max(1, int(step * _RATIO[0])),
                 max(1, int(step * _RATIO[1])),
                 step)
        _show([color] * _NUM)
        print(f"  {step:3d}  →  RGB{color}")
        time.sleep_ms(1500)

    _off()

except KeyboardInterrupt:
    _off()
