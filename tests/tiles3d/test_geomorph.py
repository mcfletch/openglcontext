"""Skirts and geomorph: hide LOD seams and remove popping."""
import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d import procedural as P
from OpenGLContext.loaders.tiles3d import geomorph as G


def test_skirt_adds_geometry_below_the_surface():
    plain = P.terrain_patch(0, 400, 0, 400, 17, skirt_depth=0.0)
    skirted = P.terrain_patch(0, 400, 0, 400, 17, skirt_depth=30.0)
    assert len(skirted[0]) > len(plain[0])          # more vertices
    assert len(skirted[3]) > len(plain[3])          # more indices (skirt quads)
    # The skirt reaches below the lowest surface vertex.
    assert skirted[0][:, 1].min() < plain[0][:, 1].min() - 1.0


def test_skirt_only_lowers_the_border():
    skirted = P.terrain_patch(0, 400, 0, 400, 17, skirt_depth=30.0)
    plain = P.terrain_patch(0, 400, 0, 400, 17, skirt_depth=0.0)
    # The original grid vertices are unchanged; only appended skirt verts are lower.
    assert np.allclose(skirted[0][:len(plain[0])], plain[0])


def test_morph_factor_ramps_across_the_band():
    assert G.morph_factor(sse=30, coarsen_sse=10, band=8) == 0.0   # full detail
    assert G.morph_factor(sse=10, coarsen_sse=10, band=8) == 1.0   # matches parent
    mid = G.morph_factor(sse=14, coarsen_sse=10, band=8)
    assert 0.0 < mid < 1.0


def test_morphed_positions_interpolate():
    fine = np.array([[0, 10, 0], [0, 20, 0]], "f4")
    parent = np.array([[0, 0, 0], [0, 0, 0]], "f4")
    half = G.morphed_positions(fine, parent, 0.5)
    assert np.allclose(half, [[0, 5, 0], [0, 10, 0]])


def test_parent_heightfield_is_smoother_than_fine():
    x0, x1, z0, z1, res = -256, 256, -256, 256, 33
    parent = G.parent_heightfield(P.terrain_height, x0, x1, z0, z1, res)
    xs = np.linspace(x0, x1, res)
    zs = np.linspace(z0, z1, res)
    gx, gz = np.meshgrid(xs, zs, indexing="ij")
    fine = np.asarray(P.terrain_height(gx, gz), "f4")
    # Parent (half-res upsample) varies less between adjacent samples than the fine.
    assert np.abs(np.diff(parent, axis=0)).mean() < np.abs(np.diff(fine, axis=0)).mean()
    assert parent.shape == fine.shape
