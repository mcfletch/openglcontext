"""Procedural ceramic PBR texture set for the teapot demo.

Generates a celadon glaze with subtle blemishes and a traditional *arare*
(hailstone) raised-dot relief in the normal (bump) map, entirely in code so the
demo carries no binary assets.  Deterministic (fixed seed).

``ceramic_textures(size)`` returns a dict of PIL images keyed by glTF channel:
``baseColor`` (sRGB), ``metallicRoughness`` (linear, G=roughness B=metallic=0),
and ``normal`` (linear tangent-space).

The Utah injective UV layout is strongly anisotropic on the body (a texel step in
v spans ~10x the world distance of a step in u), so an isotropic pattern is
unavoidably stretched there -- the dot rows read as the horizontal throwing-rings
of a wheel-thrown pot, while staying rounder on the less-distorted lid, spout and
handle.  The bump is deliberately shallow so the stretch stays subtle.
"""
import numpy as np
from PIL import Image


def _value_noise(rng, res, size):
    g = (rng.random((res, res)) * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(g).resize((size, size), Image.BICUBIC),
                      np.float32) / 255.0


def _fbm(rng, size, octaves=(4, 8, 16, 32), weights=(0.5, 0.25, 0.15, 0.1)):
    acc = np.zeros((size, size), np.float32)
    for res, w in zip(octaves, weights):
        acc += w * _value_noise(rng, res, size)
    return acc / sum(weights)


def ceramic_textures(size=1024, seed=20260712):
    rng = np.random.default_rng(seed)

    # --- height field: arare dot lattice + faint glaze undulation ------------
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    period = size / 16.0
    row = np.floor(yy / period)
    xoff = (row % 2) * (period * 0.5)          # hex-offset alternate rows
    cx = np.round((xx - xoff) / period) * period + xoff
    cy = np.round(yy / period) * period
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    dot = np.clip(1.0 - dist / (period * 0.34), 0.0, 1.0)
    dot = 0.5 - 0.5 * np.cos(np.pi * dot)      # smooth dome
    glaze = _fbm(rng, size) - 0.5
    height = dot + glaze * 0.05

    # --- normal map from height (tangent space) -----------------------------
    bump = 0.6
    gy, gx = np.gradient(height * bump)
    nx, ny, nz = -gx, -gy, np.ones_like(height)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.stack([nx / norm, ny / norm, nz / norm], -1)
    normal_img = Image.fromarray(((normal * 0.5 + 0.5) * 255).astype(np.uint8), 'RGB')

    # --- albedo: celadon glaze with sparse iron-speckle blemishes -----------
    base = np.array([0.80, 0.86, 0.80])        # pale celadon
    mottle = _fbm(rng, size, octaves=(3, 6, 12), weights=(0.6, 0.3, 0.1))
    speck = (_value_noise(rng, 72, size) > 0.94).astype(np.float32)
    albedo = np.empty((size, size, 3), np.float32)
    for c in range(3):
        a = base[c] * (0.90 + 0.11 * mottle)
        albedo[..., c] = a * (1.0 - 0.28 * speck)
    albedo[..., 0] += 0.10 * speck             # warm the iron speckles
    albedo[..., 1] += 0.04 * speck
    albedo += dot[..., None] * 0.03            # raised dots read slightly lighter
    albedo_img = Image.fromarray((np.clip(albedo, 0, 1) * 255).astype(np.uint8), 'RGB')

    # --- packed metallic-roughness (G=roughness, B=metallic=0 dielectric) ---
    rough = 0.30 + 0.18 * mottle + 0.25 * speck
    edge = np.clip(np.abs(np.gradient(dot)[0]) + np.abs(np.gradient(dot)[1]), 0, 1)
    rough = np.clip(rough + 0.15 * edge, 0.08, 0.9)
    mr = np.zeros((size, size, 3), np.float32)
    mr[..., 1] = rough
    mr_img = Image.fromarray((mr * 255).astype(np.uint8), 'RGB')

    return {'baseColor': albedo_img, 'metallicRoughness': mr_img, 'normal': normal_img}
