"""Layer toolkit for the AD loading screens. Geometry is specified in 1920x1080 "design px"
and scaled to the actual canvas size; colour is accumulated in linear light."""
import numpy as np

import fx
import logo


class Canvas:
    def __init__(self, w, h, logo_h=300, logo_cy=540):
        self.w, self.h = w, h
        self.u = w / 1920.0
        self.cx, self.cy = w / 2, logo_cy * self.u
        height = logo_h * self.u
        self.letters, self.swoosh = logo.masks(w, h, self.cx, self.cy, height)
        self.logo_mask = np.maximum(self.letters, self.swoosh)
        s, _, ty = logo.transform(self.cx, self.cy, height)
        self.logo_top, self.logo_bottom = ty, ty + logo.BH * s
        self.sw = logo.Swoosh(self.cx, self.cy, height)
        self.X, self.Y = fx.grid(w, h)
        self.img = np.zeros((h, w, 3), np.float32)
        self._clear = None

    # ---------------- helpers ----------------
    def frame(self, origin, direction):
        """(along, across) coordinates in design px for a line through origin."""
        d = np.asarray(direction, np.float64)
        d = d / np.linalg.norm(d)
        dx, dy = self.X - origin[0], self.Y - origin[1]
        return (dx * d[0] + dy * d[1]) / self.u, (-dx * d[1] + dy * d[0]) / self.u

    def logo_clear_mask(self):
        """Soft halo around the logo: light effects fade out inside it so the mark stays clean."""
        if self._clear is None:
            m = np.clip(fx.blur(self.logo_mask, 60 * self.u) * 6, 0, 1)
            self._clear = np.clip(fx.blur(m, 90 * self.u) * 1.4, 0, 1)
        return self._clear

    # ---------------- background ----------------
    def base(self, center, edge, rx=1.25, ry=0.95):
        r = np.sqrt(((self.X - self.cx) / (rx * self.h)) ** 2 + ((self.Y - self.cy) / (ry * self.h)) ** 2)
        t = fx.smoothstep(0.0, 1.0, r)[..., None]
        self.img[:] = fx.hex2lin(center) * (1 - t) + fx.hex2lin(edge) * t

    def spotlight(self, color, gain, rx=620, ry=360, haze=0.0, seed=3):
        u = self.u
        a = np.exp(-(((self.X - self.cx) / (rx * u)) ** 2 + ((self.Y - self.cy) / (ry * u)) ** 2))
        if haze:
            n = fx.lowfreq_noise(self.w, self.h, seed, scales=(90 * u, 220 * u, 520 * u))
            a = a * np.clip(1 + haze * n, 0, None)
        self.img += (gain * a)[..., None] * color

    def light_leak(self, color, gain, pos, radius):
        u = self.u
        g = np.exp(-((self.X - pos[0] * u) ** 2 + (self.Y - pos[1] * u) ** 2) / (2 * (radius * u) ** 2))
        self.img += (gain * g)[..., None] * color

    # ---------------- light ----------------
    def beam(self, color, gain, width=42, length=620, core=0.0, core_color=None, core_w=1.0, clear=0.0):
        """Soft band of light along the swoosh axis, optionally with a thin bright core line."""
        a, c = self.frame(*self.sw.axis())
        along = np.exp(-(a / length) ** 2)
        val = gain * along * np.exp(-(c / width) ** 2)
        if clear:
            val = val * (1 - clear * self.logo_clear_mask())
        self.img += val[..., None] * color
        if core:
            v = core * along ** 1.5 * np.exp(-(c / core_w) ** 2)
            if clear:
                v = v * (1 - self.logo_clear_mask())
            self.img += v[..., None] * (color if core_color is None else core_color)

    def ribbon(self, colors=("#5EEAD4", "#60A5FA"), gain=0.5, n=36, pinch=5, spread=175, L=460, fade=1000,
               amp=44, wave_len=1250, twist=0.9, twist_len=1500, twist_phase=0.6, twist_depth=0.45,
               sheen=0.55, seed=21, core_w=0.55, glow_w=5.0, glow_gain=0.16, defocus_every=5,
               amp_asym=0.35, angle_offset=0.0, offset=(0, 0)):
        """Ribbon of fine light lines that pinches into the swoosh and opens up away from it,
        with a 3D twist: it narrows and brightens where it turns edge-on."""
        rng = np.random.default_rng(seed)
        o, d = self.sw.axis()
        if angle_offset:
            r = np.radians(angle_offset)
            d = np.array([d[0] * np.cos(r) - d[1] * np.sin(r), d[0] * np.sin(r) + d[1] * np.cos(r)])
        a, cr = self.frame(o + np.array(offset) * self.u, d)
        t = fx.smoothstep(-1000, 1000, a)[..., None]
        col = fx.hex2lin(colors[0]) * (1 - t) + fx.hex2lin(colors[1]) * t
        open_ = 1 - np.exp(-(a / L) ** 2)
        th = 2 * np.pi * a / twist_len + twist_phase
        width_mod = (1 - twist_depth) + twist_depth * np.cos(th)
        spread_a = pinch + (spread - pinch) * open_ * width_mod
        A = amp * open_ ** 1.3 * (1 + amp_asym * np.tanh(a / 600))
        dens = 1 / np.sqrt(np.clip(np.abs(width_mod), 0.25, None))
        acc = np.zeros(a.shape, np.float32)
        for i, k in enumerate(np.linspace(-1, 1, n)):
            phase = twist * k + rng.normal(0, 0.05)
            off = (k * spread_a + A * np.sin(2 * np.pi * a / wave_len + phase)
                   + 0.3 * A * np.sin(2 * np.pi * a / (wave_len * 0.52) + 2.1 + 0.6 * phase))
            dist = np.abs(cr - off)
            bright = (0.4 + 0.6 * np.exp(-(k / 0.8) ** 2)) * rng.uniform(0.8, 1.0) * (1 + sheen * k * np.sin(th))
            defocus = defocus_every and i % defocus_every == 2
            cw = core_w * (3.0 if defocus else 1.0)
            acc += bright * (0.5 if defocus else 1.0) * (np.exp(-(dist / cw) ** 2)
                                                          + glow_gain * np.exp(-(dist / glow_w) ** 2))
        val = gain * np.exp(-(a / fade) ** 2) * dens * acc * (1 - self.logo_clear_mask())
        self.img += val[..., None] * col

    def particles(self, n, color_a, color_b, gain, spread=150, length=900, seed=5, sizes=(0.5, 1.7)):
        """Fine sparkles scattered along the swoosh axis (kept away from the logo)."""
        rng = np.random.default_rng(seed)
        u = self.u
        o, d = self.sw.axis()
        nrm = np.array([-d[1], d[0]])
        acc = np.zeros_like(self.img)
        for _ in range(n):
            t = rng.normal(0, length * 0.55)
            s = rng.normal(0, spread) * (0.5 + abs(t) / length)
            p = o + (t * d + s * nrm) * u
            r = rng.uniform(*sizes) * u
            inten = min(gain * rng.pareto(2.2) * 0.35 * np.exp(-(t / (length * 1.1)) ** 2), gain * 2.5)
            mix = rng.random()
            R = int(np.ceil(4 * r)) + 2
            x0, y0 = int(p[0]) - R, int(p[1]) - R
            xs = slice(max(x0, 0), min(x0 + 2 * R + 1, self.w))
            ys = slice(max(y0, 0), min(y0 + 2 * R + 1, self.h))
            if xs.start >= xs.stop or ys.start >= ys.stop:
                continue
            g = np.exp(-((self.X[ys, xs] - p[0]) ** 2 + (self.Y[ys, xs] - p[1]) ** 2) / (2 * r * r))
            acc[ys, xs] += (inten * g)[..., None] * (color_a * (1 - mix) + color_b * mix)
        self.img += acc * ((1 - self.logo_mask) * (1 - 0.9 * self.logo_clear_mask()))[..., None]

    def glow(self, mask, color, levels):
        for sigma, g in levels:
            self.img += (fx.blur(mask, sigma * self.u) * g)[..., None] * color

    def glint(self, color, gain, ray_a=22, ray_b=9):
        """Small four-point sparkle on the swoosh's sharp tip."""
        a, b = self.frame(self.sw.tip_r, self.sw.head_direction())
        rr = np.sqrt(a ** 2 + b ** 2)
        star = (np.exp(-(b / 0.6) ** 2) * np.exp(-np.abs(a) / ray_a)
                + 0.55 * np.exp(-(a / 0.6) ** 2) * np.exp(-np.abs(b) / ray_b))
        blob = np.exp(-(rr / 1.8) ** 2) + 0.18 * np.exp(-(rr / 12) ** 2)
        self.img += (gain * (0.8 * star + blob))[..., None] * color

    # ---------------- logo ----------------
    def draw_logo(self, top="#FFFFFF", bottom="#DCE3E8", sw_tail="#5EEAD4", sw_head="#E9FFFB", sw_tail_gain=0.85):
        lt = np.clip((self.Y - self.logo_top) / (self.logo_bottom - self.logo_top), 0, 1)[..., None]
        col = fx.hex2lin(top) * (1 - lt) + fx.hex2lin(bottom) * lt
        m = self.letters[..., None]
        self.img = self.img * (1 - m) + col * m
        tl, tr = self.sw.tip_l, self.sw.tip_r
        v = tr - tl
        L = np.linalg.norm(v)
        st = fx.smoothstep(0.0, 1.0, np.clip(((self.X - tl[0]) * v[0] + (self.Y - tl[1]) * v[1]) / L ** 2, 0, 1))
        st = st[..., None]
        scol = fx.hex2lin(sw_tail) * sw_tail_gain * (1 - st) + fx.hex2lin(sw_head) * st
        m = self.swoosh[..., None]
        self.img = self.img * (1 - m) + scol * m

    def vignette(self, amount, inner=0.55, outer=1.45):
        vr = np.sqrt(((self.X - self.cx) / (0.5 * self.w)) ** 2 + ((self.Y - self.cy) / (0.5 * self.h)) ** 2)
        self.img *= (1 - amount * fx.smoothstep(inner, outer, vr))[..., None]
