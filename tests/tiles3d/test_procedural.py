"""Procedural terrain: deterministic, has real features, bakes a coherent quadtree.

Checks the height field is deterministic, spans a large relief (mountains vs valleys),
clamps a lake at water level, produces natural per-vertex colours, and bakes a
multi-level tileset whose tile count matches the quadtree depth.
"""
import os
import json
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d import procedural as P
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset


def test_height_is_deterministic():
    a = P.terrain_height(np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]))
    b = P.terrain_height(np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]))
    assert np.array_equal(a, b)


def test_terrain_has_large_relief():
    xs = np.linspace(-1024, 1024, 200)
    zs = np.linspace(-1024, 1024, 200)
    gx, gz = np.meshgrid(xs, zs)
    h = np.maximum(P.terrain_height(gx, gz), P.WATER_LEVEL)
    # A real landscape: valleys at/below water and peaks well above 120m.
    assert h.min() <= P.WATER_LEVEL + 1e-6
    assert h.max() > 120.0


def test_patch_clamps_water_and_colors_it_blue():
    pos, nrm, col, idx = P.terrain_patch(-1024, 1024, -1024, 1024, 65)
    assert pos[:, 1].min() >= P.WATER_LEVEL - 1e-4
    water = pos[:, 1] <= P.WATER_LEVEL + 0.5
    if water.any():
        # water vertices are bluish: blue channel dominant.
        wc = col[water]
        assert (wc[:, 2] > wc[:, 0]).mean() > 0.8


def test_patch_normals_unit_length():
    pos, nrm, col, idx = P.terrain_patch(0, 512, 0, 512, 17)
    lens = np.linalg.norm(nrm, axis=1)
    assert np.allclose(lens, 1.0, atol=1e-3)


def test_tileset_quadtree_tile_count(tmp_path):
    path = P.build_terrain_tileset(str(tmp_path), extent=1024, levels=3, tile_res=17)
    with open(path) as fh:
        doc = json.load(fh)
    ts = build_runtime_tileset(doc, base_uri=str(tmp_path) + os.sep)
    n = sum(1 for _ in ts.iter_tiles())
    assert n == 1 + 4 + 16      # levels 0,1,2
    # Deeper tiles have smaller geometric error (finer detail).
    assert ts.root.geometric_error > ts.root.children[0].geometric_error


def test_glb_files_written(tmp_path):
    path = P.build_terrain_tileset(str(tmp_path), extent=512, levels=2, tile_res=17)
    glbs = [f for f in os.listdir(str(tmp_path)) if f.endswith(".glb")]
    assert len(glbs) == 1 + 4
