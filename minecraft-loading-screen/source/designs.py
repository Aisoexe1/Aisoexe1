"""The two loading-screen designs. Both return a Canvas whose .img holds linear-light RGB."""
import numpy as np

import fx
from canvas import Canvas

TEAL = fx.hex2lin("#5EEAD4")
TEAL_DEEP = fx.hex2lin("#0D9488")
MINT = fx.hex2lin("#E9FFFB")
BLUE = fx.hex2lin("#60A5FA")
INDIGO = fx.hex2lin("#3B4FD8")
WHITE = np.ones(3, np.float32)


def _backdrop(c, spot_gain):
    c.base("#0B0E12", "#030405")
    c.spotlight(0.6 * TEAL + 0.4 * TEAL_DEEP, spot_gain, rx=700, ry=380, haze=0.45)
    c.spotlight(WHITE, 0.010, rx=380, ry=240)


def _logo(c):
    c.glow(c.letters, 0.3 * TEAL + 0.7 * WHITE, [(16, 0.05), (60, 0.035)])
    c.glow(c.swoosh, TEAL, [(5, 0.55), (22, 0.32), (80, 0.16)])
    c.draw_logo()
    c.glint(0.6 * MINT + 0.4 * TEAL, 0.7)
    c.vignette(0.6)


def aurora(w, h):
    """A silky ribbon of light (teal -> blue) that flows through the swoosh."""
    c = Canvas(w, h)
    _backdrop(c, 0.020)
    c.light_leak(TEAL_DEEP, 0.026, (140, 1020), 420)
    c.light_leak(INDIGO, 0.022, (1800, 70), 460)
    c.beam(0.7 * TEAL + 0.3 * BLUE, 0.030, width=120, length=780)
    # a faint out-of-focus ribbon behind the main one, for depth
    c.ribbon(n=14, gain=0.09, core_w=2.4, glow_w=9, spread=230, amp=64, wave_len=1600, twist_phase=2.4,
             seed=5, defocus_every=0, angle_offset=6, offset=(0, 30), fade=900)
    c.ribbon(gain=0.29, angle_offset=3, fade=880, twist_phase=0.35, twist_len=1450)
    c.particles(130, TEAL, MINT, 0.5, spread=100, length=800)
    _logo(c)
    return c


def blade(w, h):
    """Minimal: one thin beam of light along the swoosh line and some star dust."""
    c = Canvas(w, h)
    _backdrop(c, 0.024)
    c.beam(0.75 * TEAL + 0.25 * BLUE, 0.042, width=64, length=760)
    c.beam(TEAL, 0.026, width=16, length=600, core=0.22, core_color=MINT, core_w=0.85, clear=1.0)
    c.particles(150, TEAL, MINT, 0.5, spread=110, length=820)
    _logo(c)
    return c


DESIGNS = {"aurora": aurora, "blade": blade}
