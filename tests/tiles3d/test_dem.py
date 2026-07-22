"""DEM ingest: a heightmap image becomes a streamable terrain tileset.

Validates bilinear sampling of a raster into a world-space height field (a peak in
the image becomes a peak in the world), edge clamping, and that a DEM bakes a valid
multi-level tileset the runtime can load.
"""
import os
import json
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d import dem
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset


def test_height_from_array_samples_and_scales():
    # A 3x3 raster with a central peak.
    raster = np.array([[0.0, 0.0, 0.0],
                       [0.0, 1.0, 0.0],
                       [0.0, 0.0, 0.0]])
    fn = dem.height_function_from_array(raster, extent=200.0, height_scale=100.0)
    centre = float(fn(np.array([0.0]), np.array([0.0]))[0])
    corner = float(fn(np.array([-100.0]), np.array([-100.0]))[0])
    assert centre == pytest.approx(100.0)     # peak * scale
    assert corner == pytest.approx(0.0)


def test_height_clamps_outside_the_raster():
    raster = np.array([[0.2, 0.2], [0.2, 0.2]])
    fn = dem.height_function_from_array(raster, extent=100.0, height_scale=50.0)
    inside = float(fn(np.array([0.0]), np.array([0.0]))[0])
    outside = float(fn(np.array([9999.0]), np.array([9999.0]))[0])
    assert outside == pytest.approx(inside)   # clamped to the edge value


def test_dem_bakes_a_loadable_tileset(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    # Synthetic DEM: a bright ridge across a dark field.
    a = np.zeros((64, 64), "uint8")
    a[:, 28:36] = 255
    img_path = str(tmp_path / "dem.png")
    Image.fromarray(a, mode="L").save(img_path)

    path = dem.build_dem_tileset(img_path, str(tmp_path / "out"),
                                 extent=1024, height_scale=300, base=-20,
                                 levels=2, tile_res=17)
    with open(path) as fh:
        doc = json.load(fh)
    ts = build_runtime_tileset(doc, base_uri=os.path.dirname(path) + os.sep)
    assert sum(1 for _ in ts.iter_tiles()) == 1 + 4
    glbs = [f for f in os.listdir(os.path.dirname(path)) if f.endswith(".glb")]
    assert len(glbs) == 5
