"""Extra coverage for tiles3d.vegetation: poisson_thin branches, disc edges.

Complements tests/tiles3d/test_vegetation.py and tests/unit/test_terrain_vegetation.py
by driving the branches those miss: the zero-radius short circuit, the scipy-free
spatial-hash fallback, empty/degenerate scatters, and the grass elevation band.
"""
import sys

import numpy as np

from OpenGLContext.loaders.tiles3d.scatter import Scatter
from OpenGLContext.loaders.tiles3d.vegetation import (
    poisson_thin, scatter_disc, partition_by_distance, build_grass_patch,
)
from OpenGLContext.scenegraph.basenodes import Shape, Box


def test_poisson_thin_zero_radius_keeps_everything():
    # maxr <= 0: no point owns a keep-out disc, so nothing is thinned.
    pos = np.array([[0, 0, 0], [0.01, 0, 0], [0.02, 0, 0]], "f4")
    keep = poisson_thin(pos, np.zeros(3))
    assert keep.tolist() == [True, True, True]


def test_poisson_thin_scipy_free_fallback_matches_spacing(monkeypatch):
    """With scipy unavailable, the spatial-hash fallback still enforces spacing."""
    # Force `from scipy.spatial import cKDTree` to raise ImportError.
    monkeypatch.setitem(sys.modules, "scipy.spatial", None)
    # Three points in a tight clump plus one far away; radius 1.0 -> the clump
    # collapses to a single kept point, the far point survives.
    pos = np.array([[0, 0, 0], [0.3, 0, 0], [0.6, 0, 0], [10, 0, 10]], "f4")
    rad = np.full(4, 1.0)
    keep = poisson_thin(pos, rad)
    kept = pos[keep]
    # No two kept points are closer than the pair-sum radius (2.0 here).
    for i in range(len(kept)):
        for j in range(i + 1, len(kept)):
            d = np.hypot(kept[i, 0] - kept[j, 0], kept[i, 2] - kept[j, 2])
            assert d >= 2.0 - 1e-6
    assert keep[3]              # the isolated point is always kept


def test_poisson_thin_fallback_uses_2d_positions(monkeypatch):
    monkeypatch.setitem(sys.modules, "scipy.spatial", None)
    pos = np.array([[0.0, 0.0], [0.1, 0.1]])   # 2-wide -> xz = the two columns
    keep = poisson_thin(pos, np.full(2, 1.0))
    assert keep.sum() == 1     # overlapping pair thinned to one


def test_scatter_disc_zero_density_is_empty():
    def hf(x, z):
        return np.zeros(np.shape(x))
    s = scatter_disc((0.0, 0.0, 0.0), radius=5.0, density=0.0, seed=1, height_fn=hf)
    assert len(s) == 0
    assert s.positions.shape == (0, 3)


def test_partition_by_distance_empty_scatter():
    empty = Scatter(np.zeros((0, 3), "f4"), np.zeros(0), np.zeros(0))
    near, far = partition_by_distance(empty, (0, 0, 0), near_distance=10.0)
    assert len(near) == 0 and len(far) == 0


def test_grass_patch_respects_elevation_band():
    # A ground plane whose height rises with x; keep only a mid elevation band.
    p = np.array([[0, 0, 0], [400, 60, 0], [400, 60, 400], [0, 0, 400]], "f4")
    t = np.array([[0, 1, 2], [0, 2, 3]], "u4")
    blade = Shape(geometry=Box(size=(0.1, 1.0, 0.1)))
    g = build_grass_patch(p, t, blade, camera=(200, 0, 200), radius=400.0,
                          density=0.02, seed=7, elevation=(20.0, 40.0))
    assert len(g.children) > 0
    ys = np.array([c.translation[1] for c in g.children])
    assert (ys >= 20.0).all() and (ys <= 40.0).all()
