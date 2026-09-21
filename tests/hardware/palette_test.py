"""
palette_test.py — Show the calibrated palette on real LEDs

Answers the questions CIELAB dE cannot: dE models a reflective patch under D65,
but a NeoPixel is emissive behind diffusion. Everything here drives the actual
firmware path — color.mood_to_rgb -> pixel.write -> pixel.to_duty — so what the
strip shows is what the ring will show.

Needs the firmware modules and synaesthesia.json on flash:
    ./build/deploy.sh --chip esp32c3 --no-reset
    mpremote connect /dev/ttyACM0 run tests/hardware/palette_test.py

Six stages, announced on serial as they run. Ctrl-C to stop.

  1. knot walk        each colour in the table, alone, in theta order
  2. tightest pairs   the two closest in DUTY CHROMATICITY, side by side
                      (not Lab dE — dE ranked the bench results backwards)
  3. confidence       a track-hit colour decaying to a zero-confidence grey
  4. gamma A/B        the LED transfer function on, then off  <-- the big one
  5. brightness       master_brightness 0.40 / 0.65 / 1.00
  6. theta sweep      the continuous ring, to see the bands between knots
"""

import math
import time

import color
import pixel
import synaesthesia

_HOLD  = 4.0     # seconds per colour in the walk stages
_LABEL = {
    50.2:  "fun/dance",
    135.0: "industrial",
    153.4: "shoegaze",
    168.7: "darkwave",
    180.0: "indie-melancholy",
    206.6: "zone-out",
    270.0: "ambient",
    323.1: "americana",
}


def _ve(theta, r=0.35):
    """The (valence, energy) at distance r along mood direction theta."""
    return (0.5 + r * math.cos(math.radians(theta)),
            0.5 + r * math.sin(math.radians(theta)))


def _all(rgb):
    pixel.write([rgb, rgb, rgb])


def _show(rgb, label, hold=_HOLD):
    _all(rgb)
    print("    {:<34} sRGB {:>4},{:>4},{:>4}   duty {:>4},{:>4},{:>4}".format(
        label, rgb[0], rgb[1], rgb[2], *pixel.to_duty(rgb)))
    time.sleep(hold)


def _banner(n, title, question):
    print("")
    print("=" * 66)
    print("  STAGE {} — {}".format(n, title))
    print("  {}".format(question))
    print("=" * 66)


def knot_walk():
    _banner(1, "knot walk", "Does each one read as the mood it names?")
    for theta, hexcode in synaesthesia.color_map():
        label = "{:>5.1f}  {}  {}".format(theta, hexcode, _LABEL.get(theta, "?"))
        _show(color.mood_to_rgb(*_ve(theta)), label)


def tightest_pairs():
    _banner(2, "tightest pairs", "Can you tell them apart? Pixel 2 is dark.")
    pairs = (
        ((50.2, "fun/dance"), (135.0, "industrial"),
         "chromaticity 0.251 — the tightest in the palette"),
        ((168.7, "darkwave"), (180.0, "indie-melancholy"),
         "0.361 — second tightest, and only 11.3 deg apart in theta"),
    )
    for (t0, n0), (t1, n1), note in pairs:
        a = color.mood_to_rgb(*_ve(t0))
        b = color.mood_to_rgb(*_ve(t1))
        print("    {} (pixel 1)  vs  {} (pixel 3)".format(n0, n1))
        print("      {}".format(note))
        pixel.write([a, (0, 0, 0), b])
        time.sleep(_HOLD * 2)


def confidence_ladder():
    _banner(3, "confidence", "Does a miss read as 'washed out' or as 'broken'?")
    base = color.mood_to_rgb(*_ve(135.0))
    tier = {1.0: "track hit", 0.6: "artist tier", 0.0: "persistent miss"}
    for c in (1.0, 0.85, 0.6, 0.3, 0.0):
        _show(color.apply_confidence(base, c),
              "industrial @ c={:.2f}  {:<16}".format(c, tier.get(c, "")),
              hold=3.0)


def gamma_ab():
    _banner(4, "gamma A/B", "ON should look RIGHT; OFF should look washed/pale.")
    print("    WS2812B duty is linear in the byte, so feeding it sRGB directly")
    print("    over-brightens every mid-tone. If OFF looks better to your eye,")
    print("    say so — that is a real finding and the flag exists for it.")
    saved = pixel._GAMMA_CORRECT
    try:
        for theta in (180.0, 270.0, 206.6, 135.0):
            name = _LABEL.get(theta, "?")
            for on in (True, False):
                pixel._GAMMA_CORRECT = on
                _show(color.mood_to_rgb(*_ve(theta)),
                      "{:<18} gamma {}".format(name, "ON " if on else "OFF"))
    finally:
        pixel._GAMMA_CORRECT = saved


def brightness_ladder():
    _banner(5, "brightness", "Which is right for a dark room? 0.65 is current.")
    saved = synaesthesia._p
    try:
        for b in (0.40, 0.65, 1.00):
            synaesthesia._p = dict(saved, master_brightness=b)
            for theta in (135.0, 270.0):
                _show(color.mood_to_rgb(*_ve(theta)),
                      "{:<18} master_brightness {:.2f}".format(
                          _LABEL.get(theta, "?"), b))
    finally:
        synaesthesia._p = saved


def theta_sweep(seconds=60.0, step=2.0):
    _banner(6, "theta sweep", "Does any band read as a zone it sits between?")
    print("    Hue runs monotonically around theta, so every band should sit")
    print("    between its two neighbours in colour as well as in angle.")
    n = int(360.0 / step)
    delay = seconds / n
    for i in range(n):
        t = i * step
        _all(color.mood_to_rgb(*_ve(t)))
        if i % 15 == 0:
            print("    theta {:>5.1f}".format(t))
        time.sleep(delay)


def main():
    print("")
    print("palette_test — profile '{}', {} knots, master_brightness {}".format(
        synaesthesia.profile_name(),
        len(synaesthesia.color_map()),
        synaesthesia.master_brightness()))
    print("gamma correction is {}".format(
        "ON" if pixel._GAMMA_CORRECT else "OFF"))
    if not pixel._HW:
        print("")
        print("  WARNING: no neopixel hardware — pixel.write() is a no-op here.")
        print("  Run this on the board, not in CPython.")
    try:
        while True:
            knot_walk()
            tightest_pairs()
            confidence_ladder()
            gamma_ab()
            brightness_ladder()
            theta_sweep()
            print("")
            print("  --- looping; Ctrl-C to stop ---")
    except KeyboardInterrupt:
        pass
    finally:
        pixel.off()
        print("")
        print("pixels off.")


# Importable so a stage can be run on its own — stepping through them one at a
# time is how you actually judge a colour, and a 3-minute loop is not that:
#     mpremote connect /dev/ttyACM0 cp tests/hardware/palette_test.py :/
#     mpremote connect /dev/ttyACM0 exec "import palette_test; palette_test.knot_walk()"
STAGES = (knot_walk, tightest_pairs, confidence_ladder,
          gamma_ab, brightness_ladder, theta_sweep)

if __name__ == "__main__":
    main()
