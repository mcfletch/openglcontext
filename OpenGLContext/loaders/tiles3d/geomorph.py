"""Geomorphing between LOD levels to remove popping.

A fine tile carries, per vertex, the position that vertex would have on its coarser
parent; as the tile nears its coarsen threshold the vertices lerp toward the parent
positions, so the LOD switch is continuous rather than a pop. These are the data and
blend primitives; the morph factor is driven by screen-space error.
"""
import numpy as np


def morph_factor(sse, coarsen_sse, band):
    """0 (full detail) .. 1 (matches parent) as sse drops through the transition band.

    `coarsen_sse` is the error at which the tile would coarsen; `band` is how wide the
    morph ramp is above it. Above `coarsen_sse + band` the tile is fully detailed;
    below `coarsen_sse` it fully matches the parent surface.
    """
    if band <= 0:
        return 0.0 if sse > coarsen_sse else 1.0
    t = (coarsen_sse + band - sse) / band
    return float(np.clip(t, 0.0, 1.0))


def morphed_positions(fine, parent, factor):
    """Lerp vertex positions from `fine` toward `parent` by `factor` (0..1)."""
    fine = np.asarray(fine, dtype="f4")
    parent = np.asarray(parent, dtype="f4")
    return (fine * (1.0 - factor) + parent * factor).astype("f4")


def parent_heightfield(height_fn, x0, x1, z0, z1, res):
    """Sample `height_fn` at half the resolution then upsample to `res` — the surface
    the coarser parent tile would present over this footprint. Vertices lerp toward
    this to morph into the parent LOD without a seam."""
    coarse_res = max(2, res // 2 + 1)
    xs = np.linspace(x0, x1, coarse_res)
    zs = np.linspace(z0, z1, coarse_res)
    gx, gz = np.meshgrid(xs, zs, indexing="ij")
    coarse = np.asarray(height_fn(gx, gz), dtype="f4")
    # Bilinear upsample to the fine resolution.
    fi = np.linspace(0, coarse_res - 1, res)
    fj = np.linspace(0, coarse_res - 1, res)
    i0 = np.floor(fi).astype(int)
    j0 = np.floor(fj).astype(int)
    i1 = np.minimum(i0 + 1, coarse_res - 1)
    j1 = np.minimum(j0 + 1, coarse_res - 1)
    ti = (fi - i0)[:, None]
    tj = (fj - j0)[None, :]
    top = coarse[i0][:, j0] * (1 - tj) + coarse[i0][:, j1] * tj
    bot = coarse[i1][:, j0] * (1 - tj) + coarse[i1][:, j1] * tj
    return (top * (1 - ti) + bot * ti).astype("f4")
