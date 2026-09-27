"""AD logo: clean vector paths (logo.json), SVG output and raster masks via headless Chromium."""
import hashlib
import json
import os
import re
import subprocess

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "logo.json")) as _f:
    _DATA = json.load(_f)
PATHS = _DATA["paths"]          # "A", "D", "swoosh" in logo units
BW, BH = _DATA["size"]          # logo bounding box in logo units
CACHE = os.path.join(HERE, ".cache")
_TOKENS = re.compile(r"[MLCZ]|-?\d+\.?\d*")


def parse(d):
    """'M x y L x y C ... Z' -> [(command, [numbers]), ...]"""
    out, cmd, nums = [], None, []
    for t in _TOKENS.findall(d):
        if t in "MLCZ":
            if cmd:
                out.append((cmd, nums))
            cmd, nums = t, []
        else:
            nums.append(float(t))
    out.append((cmd, nums))
    return out


def svg(fill="#000", swoosh_fill=None, defs="", pad=0.0, width_px=None):
    """Standalone SVG of the logo (optionally sized to width_px pixels)."""
    w, h = BW + 2 * pad, BH + 2 * pad
    pw = width_px or w
    o = f"{-pad:g}" if pad else "0"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{o} {o} {w:g} {h:g}" '
        f'width="{pw:g}" height="{pw * h / w:g}">\n'
        + (f"  <defs>{defs}</defs>\n" if defs else "")
        + f'  <path fill="{fill}" d="{PATHS["A"]}"/>\n'
        f'  <path fill="{fill}" d="{PATHS["D"]}"/>\n'
        f'  <path fill="{swoosh_fill or fill}" d="{PATHS["swoosh"]}"/>\n'
        "</svg>\n"
    )


def rasterize(svg_markup, w, h):
    """Render SVG markup onto a transparent w x h canvas; returns an RGBA uint8 array."""
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.md5(f"{w}x{h}:{svg_markup}".encode()).hexdigest()[:16]
    png = os.path.join(CACHE, f"{key}.png")
    if not os.path.exists(png):
        html = os.path.join(CACHE, f"{key}.html")
        with open(html, "w") as f:
            f.write("<!doctype html><html><head><style>html,body{margin:0;background:transparent}"
                    "svg{display:block}</style></head><body>" + svg_markup + "</body></html>")
        subprocess.run(["node", os.path.join(HERE, "render.js"), html, png, str(w), str(h), "1"], check=True)
    return np.array(Image.open(png).convert("RGBA"))


def transform(cx, cy, height):
    """Scale and offset that place a logo of `height` px centred on (cx, cy)."""
    s = height / BH
    return s, cx - BW * s / 2, cy - BH * s / 2


def masks(w, h, cx, cy, height):
    """Anti-aliased alpha masks (float32, 0..1): letters (A+D) and swoosh."""
    s, tx, ty = transform(cx, cy, height)
    out = []
    for keys in (("A", "D"), ("swoosh",)):
        body = "".join(f'<path fill="#fff" d="{PATHS[k]}"/>' for k in keys)
        markup = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                  f'<g transform="translate({tx:.4f} {ty:.4f}) scale({s:.6f})">{body}</g></svg>')
        out.append(rasterize(markup, w, h)[..., 3].astype(np.float32) / 255)
    return out


def _bezier(P, t):
    t = np.atleast_1d(t)[:, None]
    mt = 1 - t
    return mt ** 3 * P[0] + 3 * mt ** 2 * t * P[1] + 3 * mt * t ** 2 * P[2] + t ** 3 * P[3]


class Swoosh:
    """Swoosh geometry in canvas pixels: tips, edges and the directions the light effects follow."""

    def __init__(self, cx, cy, height):
        s, tx, ty = transform(cx, cy, height)
        to_px = lambda p: np.asarray(p, np.float64) * s + np.array([tx, ty])
        (_, m), (_, k), (_, c1), (_, c2), _ = parse(PATHS["swoosh"])
        c1, c2 = np.reshape(c1, (3, 2)), np.reshape(c2, (3, 2))
        self.tip_l, self.kink, self.tip_r = to_px(m), to_px(k), to_px(c1[2])
        self.lower = to_px([k, *c1])        # kink -> right tip
        self.upper = to_px([c1[2], *c2])    # right tip -> left tip (the long outer curve)

    def axis(self):
        """A point in the middle of the swoosh and its overall direction (left tip -> right tip)."""
        v = self.tip_r - self.tip_l
        mid = _bezier(self.upper, 0.5)[0] * 0.5 + (self.tip_l + self.tip_r) * 0.25
        return mid, v / np.linalg.norm(v)

    def head_direction(self):
        """Direction the sharp right tip points to."""
        a = self.upper[0] - self.upper[1]
        b = self.lower[3] - self.lower[2]
        v = a / np.linalg.norm(a) + b / np.linalg.norm(b)
        return v / np.linalg.norm(v)
