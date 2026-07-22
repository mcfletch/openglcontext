"""Vegetation scatter: deterministic, area-weighted placement on a tile surface.

Instances (trees/brush/grass) are scattered per tile from the tile's own mesh, so
they page with the terrain and sit on the surface (cave floors and ledges included,
since placement rides the mesh, not a height assumption). Placement is seeded by the
tile so it is reproducible for regression capture.
"""
import numpy as np

from OpenGLContext.loaders.tiles3d.scatter import scatter_on_mesh


def _quad(size=10.0):
    # A flat quad in the y=0 plane, two triangles.
    p = np.array([[0, 0, 0], [size, 0, 0], [size, 0, size], [0, 0, size]], "f4")
    tris = np.array([[0, 1, 2], [0, 2, 3]], "u4")
    return p, tris


def test_deterministic_for_same_seed():
    p, t = _quad()
    a = scatter_on_mesh(p, t, density=0.5, seed=7)
    b = scatter_on_mesh(p, t, density=0.5, seed=7)
    assert np.array_equal(a.positions, b.positions)
    assert np.array_equal(a.yaws, b.yaws)


def test_different_seed_differs():
    p, t = _quad()
    a = scatter_on_mesh(p, t, density=0.5, seed=1)
    b = scatter_on_mesh(p, t, density=0.5, seed=2)
    assert not np.array_equal(a.positions, b.positions)


def test_density_scales_count():
    p, t = _quad(size=10.0)  # area 100
    low = scatter_on_mesh(p, t, density=0.1, seed=3)
    high = scatter_on_mesh(p, t, density=1.0, seed=3)
    assert len(high.positions) > len(low.positions)
    assert abs(len(low.positions) - 10) <= 5   # ~area*density = 10


def test_positions_lie_on_surface():
    p, t = _quad(size=10.0)
    s = scatter_on_mesh(p, t, density=1.0, seed=5)
    assert len(s.positions) > 0
    # On the y=0 quad: every instance sits on the plane and inside the footprint.
    assert np.allclose(s.positions[:, 1], 0.0, atol=1e-4)
    assert s.positions[:, 0].min() >= -1e-4
    assert s.positions[:, 0].max() <= 10.0 + 1e-4
    assert s.positions[:, 2].min() >= -1e-4
    assert s.positions[:, 2].max() <= 10.0 + 1e-4


def test_yaws_and_scales_in_range():
    p, t = _quad()
    s = scatter_on_mesh(p, t, density=1.0, seed=9, scale_range=(0.8, 1.5))
    assert (s.yaws >= 0).all() and (s.yaws <= 2 * np.pi + 1e-6).all()
    assert (s.scales >= 0.8 - 1e-6).all() and (s.scales <= 1.5 + 1e-6).all()


def test_empty_mesh_scatters_nothing():
    s = scatter_on_mesh(np.zeros((0, 3), "f4"), np.zeros((0, 3), "u4"),
                        density=1.0, seed=1)
    assert len(s.positions) == 0


def test_keep_filter_restricts_placements():
    p, t = _quad(size=10.0)
    # Keep only instances in the far half (x > 5): a spatial restriction.
    s = scatter_on_mesh(p, t, density=2.0, seed=8,
                        keep=lambda pos: pos[:, 0] > 5.0)
    assert len(s.positions) > 0
    assert (s.positions[:, 0] > 5.0).all()
