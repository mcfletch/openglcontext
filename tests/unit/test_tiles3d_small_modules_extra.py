"""Targeted coverage for the tiles3d modules with only a line or two uncovered:
fetch, loadmanager, scatter, geomorph, boundingvolume, runtime, tileset.
"""
import json
import os
import types

import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d import fetch
from OpenGLContext.loaders.tiles3d.loadmanager import LoadQueue
from OpenGLContext.loaders.tiles3d.scatter import scatter_on_mesh
from OpenGLContext.loaders.tiles3d.geomorph import morph_factor
from OpenGLContext.loaders.tiles3d.boundingvolume import SphereBV
from OpenGLContext.loaders.tiles3d.runtime import TilesetRuntime
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset


# --- fetch.default_cache_dir --------------------------------------------------

def test_default_cache_dir_honours_xdg(monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", "/somewhere/cache")
    assert fetch.default_cache_dir() == os.path.join(
        "/somewhere/cache", "openglcontext", "tiles3d")


def test_default_cache_dir_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    d = fetch.default_cache_dir()
    assert d.endswith(os.path.join("openglcontext", "tiles3d"))
    assert os.path.expanduser("~/.cache") in d


# --- loadmanager LoadQueue dedupe ---------------------------------------------

def test_load_queue_ignores_duplicate_push():
    q = LoadQueue()
    tile = object()
    q.push(tile, 1.0)
    q.push(tile, 0.5)          # same tile already present -> ignored
    assert len(q) == 1
    assert q.pop() is tile
    assert q.pop() is None


# --- scatter zero-count -------------------------------------------------------

def test_scatter_on_mesh_zero_density_is_empty():
    p = np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1]], "f4")
    t = np.array([[0, 1, 2]], "u4")
    s = scatter_on_mesh(p, t, density=0.0, seed=1)   # count rounds to 0
    assert len(s) == 0
    assert s.positions.shape == (0, 3)


# --- geomorph zero-band -------------------------------------------------------

def test_morph_factor_zero_band_is_a_hard_step():
    # band <= 0 collapses the ramp to a step at coarsen_sse.
    assert morph_factor(sse=10.0, coarsen_sse=5.0, band=0.0) == 0.0   # above -> detail
    assert morph_factor(sse=2.0, coarsen_sse=5.0, band=0.0) == 1.0    # below -> parent


# --- boundingvolume SphereBV.bounding_sphere ----------------------------------

def test_sphere_bv_reports_its_own_center_and_radius():
    bv = SphereBV(center=(1.0, 2.0, 3.0), radius=4.0)
    center, radius = bv.bounding_sphere()
    assert np.allclose(center, [1.0, 2.0, 3.0])
    assert radius == 4.0


# --- runtime eviction fires on_evicted ----------------------------------------

def test_evict_releases_drawable_and_fires_callback():
    evicted = []
    released = []
    uploader = types.SimpleNamespace(
        upload=lambda tile, payload: (None, 0),
        release=lambda drawable: released.append(drawable))
    tileset = types.SimpleNamespace(root=None)
    rt = TilesetRuntime(tileset, loader_fn=lambda t: None, uploader=uploader,
                        memory_budget=0.0, fovy=1.0, workers=1,
                        on_evicted=lambda tile, drawable: evicted.append((tile, drawable)))
    try:
        tile = types.SimpleNamespace(name="t")
        drawable = object()
        rt.residency.set_renderable(tile, 100)     # 100 bytes, budget 0 -> over
        rt._drawables[id(tile)] = drawable
        rt._evict(want=[], pinned=[])
        assert released == [drawable]
        assert evicted == [(tile, drawable)]
        assert id(tile) not in rt._drawables
    finally:
        rt.shutdown()


# --- tileset branches ---------------------------------------------------------

def _tileset(root):
    return {"asset": {}, "geometricError": 100.0, "root": root}


def test_unsupported_bounding_volume_raises():
    with pytest.raises(NotImplementedError):
        build_runtime_tileset(_tileset({
            "boundingVolume": {"capsule": [0, 0, 0, 1]},
            "geometricError": 10.0,
        }))


def test_recenter_uses_root_transform_translation():
    # A root transform translated far out in ECEF; recenter brings it home.
    T = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 6.0e6, 0, 0, 1]
    ts = build_runtime_tileset(_tileset({
        "transform": T,
        "boundingVolume": {"box": [0, 0, 0, 5, 0, 0, 0, 5, 0, 0, 0, 5]},
        "geometricError": 10.0,
    }), recenter=True)
    # The box center absorbs the offset through the tile matrix -> near origin.
    assert np.linalg.norm(ts.root.bounding_volume.center) < 1.0


def test_default_external_resolver_reads_json_file(tmp_path):
    external = {"asset": {}, "geometricError": 5.0,
                "root": {"boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
                         "geometricError": 5.0, "content": {"uri": "leaf.b3dm"}}}
    ext_path = tmp_path / "sub.json"
    ext_path.write_text(json.dumps(external))
    # No custom resolver: the default resolver reads the file off disk.
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "geometricError": 100.0,
        "content": {"uri": "sub.json"},
    }), base_uri=str(tmp_path) + os.sep)
    assert len(ts.root.children) == 1
    assert ts.root.children[0].content_uri.endswith("leaf.b3dm")
