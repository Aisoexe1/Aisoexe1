"""Float image helpers. Everything is composed in linear light and only converted to sRGB at the end."""
import cv2
import numpy as np


def hex2lin(h):
    h = h.lstrip("#")
    c = np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def lin2srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def blur(img, sigma):
    """Gaussian blur; large radii are blurred on a downsampled copy."""
    if sigma < 0.3:
        return img
    h, w = img.shape[:2]
    f = int(max(1, sigma // 6))
    if f == 1:
        return cv2.GaussianBlur(img, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    small = cv2.resize(img, (max(1, w // f), max(1, h // f)), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sigma / f, borderType=cv2.BORDER_REFLECT)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def grid(w, h):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return x + 0.5, y + 0.5


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def lowfreq_noise(w, h, seed, scales, weights=(0.25, 0.35, 0.4)):
    """Soft cloudy noise (zero mean, unit variance) used to break up large glows."""
    rng = np.random.default_rng(seed)
    acc = np.zeros((h, w), np.float32)
    for s, wt in zip(scales, weights):
        n = blur(rng.standard_normal((h, w)).astype(np.float32), s)
        acc += wt * n / (n.std() + 1e-8)
    return acc / (acc.std() + 1e-8)


def to_8bit(lin_rgb, grain=0.0, seed=7, grain_mask=None):
    """Linear -> sRGB, fine film grain (less on highlights), triangular dither, 8-bit."""
    s = lin2srgb(lin_rgb).astype(np.float32)
    rng = np.random.default_rng(seed)
    h, w = s.shape[:2]
    if grain > 0:
        g = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), 0.55)
        g /= g.std()
        if grain_mask is not None:
            g = g * grain_mask
        s = s + grain * g[..., None] * (0.35 + 0.65 * (1 - s))
    dither = (rng.random((h, w, 1), dtype=np.float32) - rng.random((h, w, 1), dtype=np.float32)) / 255
    return np.clip(np.round((s + dither) * 255), 0, 255).astype(np.uint8)
