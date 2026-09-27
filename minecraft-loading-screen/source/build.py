"""Render the AD loading-screen backgrounds and the logo files.

    python build.py            # everything
    python build.py aurora     # one design (aurora | blade | logo)

Each design is rendered once at 3840x2160 in linear light and area-downscaled to the smaller
sizes, so thin lines stay smooth at 1080p. Output goes to the folder above this one.
"""
import os
import sys
import time

import cv2
import numpy as np
from PIL import Image

import fx
import logo
from designs import DESIGNS, MINT, TEAL

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SIZES = [(3840, 2160), (2560, 1440), (1920, 1080)]


def export_design(name, grain=0.011):
    t0 = time.time()
    c = DESIGNS[name](*SIZES[0])
    clean = 1 - 0.85 * c.logo_mask                     # no grain on the logo itself
    for w, h in SIZES:
        img, gm = c.img, clean
        if (w, h) != SIZES[0]:
            img = cv2.resize(c.img, (w, h), interpolation=cv2.INTER_AREA)
            gm = cv2.resize(clean, (w, h), interpolation=cv2.INTER_AREA)
        path = os.path.join(OUT, f"ad-loading-{name}-{w}x{h}.png")
        Image.fromarray(fx.to_8bit(img, grain=grain, seed=11, grain_mask=gm)).save(path, optimize=True)
        print(f"  {os.path.relpath(path, OUT)}  {os.path.getsize(path) / 1e6:.1f} MB")
    print(f"{name}: {time.time() - t0:.0f}s")


def _swoosh_gradient():
    """Same teal -> mint ramp the backgrounds use, as an SVG gradient along the swoosh."""
    sw = logo.Swoosh(logo.BW / 2, logo.BH / 2, logo.BH)      # identity transform
    stops = []
    for t in np.linspace(0, 1, 5):
        s = t * t * (3 - 2 * t)
        rgb = np.round(fx.lin2srgb(TEAL * 0.85 * (1 - s) + MINT * s) * 255).astype(int)
        stops.append(f'<stop offset="{t:g}" stop-color="#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"/>')
    (x1, y1), (x2, y2) = sw.tip_l, sw.tip_r
    return (f'<linearGradient id="swoosh" gradientUnits="userSpaceOnUse" x1="{x1:.3f}" y1="{y1:.3f}" '
            f'x2="{x2:.3f}" y2="{y2:.3f}">{"".join(stops)}</linearGradient>')


def export_logo(width=2048):
    d = os.path.join(OUT, "logo")
    os.makedirs(d, exist_ok=True)
    grad = _swoosh_gradient()
    with open(os.path.join(d, "ad-logo.svg"), "w") as f:
        f.write(logo.svg("#000000"))
    with open(os.path.join(d, "ad-logo-accent.svg"), "w") as f:
        f.write(logo.svg("#FFFFFF", "url(#swoosh)", defs=grad))
    pad = logo.BW * 0.04
    variants = {
        "ad-logo-black": ("#000000", None, ""),
        "ad-logo-white": ("#FFFFFF", None, ""),
        "ad-logo-accent": ("#FFFFFF", "url(#swoosh)", grad),
    }
    h = int(round(width * (logo.BH + 2 * pad) / (logo.BW + 2 * pad)))
    for name, (fill, sfill, defs) in variants.items():
        markup = logo.svg(fill, sfill, defs=defs, pad=pad, width_px=width)
        path = os.path.join(d, f"{name}.png")
        Image.fromarray(logo.rasterize(markup, width, h)).save(path, optimize=True)
        print(f"  logo/{name}.png  {width}x{h}")


if __name__ == "__main__":
    targets = sys.argv[1:] or [*DESIGNS, "logo"]
    for t in targets:
        export_logo() if t == "logo" else export_design(t)
