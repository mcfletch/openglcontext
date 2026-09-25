"""Extra coverage for tiles3d.gltf_uploader: b3dm strip, combined scenes, and the
robustness branches of the GL-teardown helpers (no real GL context needed).
"""
import struct
import types
import json
import os

import numpy as np
import OpenGL.GL as gl
import pytest

from OpenGLContext.loaders.tiles3d import gltf_uploader as U
from OpenGLContext.loaders.tiles3d.gltf_uploader import (
    _strip_b3dm, _CombinedScene, _drawable_shapes, _mesh_vbos,
    _dispose_mesh_gpu, _dispose_material_textures, GLTileUploader,
)
from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.scenegraph.group import Group


def test_strip_b3dm_returns_embedded_glb():
    glb = b"glTFPAYLOAD-embedded"
    # b3dm header: magic, version, byteLength, ft_json, ft_bin, bt_json, bt_bin.
    header = b"b3dm" + struct.pack("<6I", 1, 28 + len(glb), 0, 0, 0, 0)
    assert _strip_b3dm(header + glb) == glb


def test_strip_b3dm_skips_feature_and_batch_tables():
    glb = b"the-real-glb"
    ft, bt = b'{"a":1}', b'{"b":2}'
    header = b"b3dm" + struct.pack("<6I", 1, 28 + len(ft) + len(bt), len(ft), 0,
                                   len(bt), 0)
    assert _strip_b3dm(header + ft + bt + glb) == glb


def test_strip_b3dm_passes_non_b3dm_through():
    assert _strip_b3dm(b"glTF....") == b"glTF...."


def test_combined_scene_wraps_children_and_bounds():
    a = types.SimpleNamespace(group=Group(), center=(0.0, 0.0, 0.0), radius=1.0)
    b = types.SimpleNamespace(group=Group(), center=(10.0, 0.0, 0.0), radius=2.0)
    combined = _CombinedScene([a, b])
    assert len(combined.group.children) == 2
    assert np.allclose(combined.center, [5.0, 0.0, 0.0])
    # radius encloses both sub-scenes: 5 (half-separation) + 2 (b's radius).
    assert combined.radius == 7.0


def test_combined_scene_loader_path(tmp_path):
    path = build_sample_tileset(str(tmp_path))
    with open(path) as fh:
        doc = json.load(fh)
    ts = build_runtime_tileset(doc, base_uri=str(tmp_path) + os.sep)
    # Force a two-content tile so the loader builds a _CombinedScene.
    tile = ts.root
    tile.content_uris = [tile.content_uris[0], tile.content_uris[0]]
    scene, nbytes = U.file_tile_loader(tile)
    assert isinstance(scene, _CombinedScene)
    assert nbytes > 0
    assert len(scene.group.children) == 2


def test_drawable_shapes_is_cycle_safe():
    # Build a cyclic graph: a -> b -> a. The walk must terminate.
    a = types.SimpleNamespace(geometry=None, children=[])
    b = types.SimpleNamespace(geometry=object(), children=[a])
    a.children.append(b)
    shapes = list(_drawable_shapes(a))
    assert shapes == [b]     # only b carries geometry, and no infinite loop


def test_mesh_vbos_collects_dyn_buffers():
    idx, dyn_buf, attr_buf = object(), object(), object()
    gpu = types.SimpleNamespace(
        idx_vbo=idx, _instance_vbo=None,
        attr_layout=[(attr_buf, 2, 3)], dyn={"velocity": dyn_buf})
    bufs = _mesh_vbos(gpu)
    assert set(map(id, bufs)) == {id(idx), id(dyn_buf), id(attr_buf)}


class _FakeCache:
    def __init__(self, data=None):
        self._data = data
        self.holders_asked = []

    def getData(self, geometry, key=""):
        return self._data

    def getHolder(self, geometry, key=""):
        self.holders_asked.append(geometry)
        return None


def test_dispose_mesh_gpu_no_entry_is_noop():
    # cache.getData returns None -> nothing to release and no entry to drop.
    cache = _FakeCache(None)
    assert _dispose_mesh_gpu(cache, object()) is None
    assert cache.holders_asked == []


def test_dispose_mesh_gpu_swallows_release_and_delete_errors():
    attempted = []

    class _BadVBO:
        def __init__(self, name):
            self.name = name

        def delete(self):
            attempted.append(self.name)
            raise RuntimeError("no gl")

    class _GPU:
        idx_vbo = _BadVBO('index')
        _instance_vbo = None
        attr_layout = ((_BadVBO('attribute'), 2, 3),)
        dyn = types.MappingProxyType({})

        def release(self):
            attempted.append('vao')
            raise RuntimeError("no gl")

    dropped = []
    cache = types.SimpleNamespace(
        getData=lambda _g, key="": _GPU(),  # noqa: ARG005 the context cache's getData/getHolder signature
        getHolder=lambda g, key="": lambda: dropped.append(g))  # noqa: ARG005 the context cache's getData/getHolder signature
    geometry = object()
    # One failure does not stop the rest: every buffer is still deleted and
    # the cache entry is still dropped.
    _dispose_mesh_gpu(cache, geometry)
    assert attempted == ['vao', 'index', 'attribute']
    assert dropped == [geometry]


def test_dispose_material_textures_skips_missing_and_swallows_gl_errors(monkeypatch):
    # One map with no per-context entry (skipped), one whose texture id is 0
    # (skipped), one that raises in glDeleteTextures (swallowed, then zeroed).
    class _Tex:
        def __init__(self, tid):
            self.texture = tid

    ctx = object()
    no_ctx = types.SimpleNamespace(_per_context={})
    zero_tid = types.SimpleNamespace(_per_context={ctx: _Tex(0)})
    boom_tex = _Tex(9)
    boom = types.SimpleNamespace(_per_context={ctx: boom_tex})
    material = types.SimpleNamespace(
        textures={"a": no_ctx, "b": zero_tid, "c": boom})

    def bad_delete(ids):
        raise RuntimeError("no context")

    monkeypatch.setattr(gl, "glDeleteTextures", bad_delete)
    _dispose_material_textures(material, ctx)   # must not raise
    assert boom_tex.texture == 0                # zeroed after the failed delete


def test_upload_applies_non_identity_transform():
    up = GLTileUploader()
    m = np.identity(4)
    m[0, 3] = 5.0        # translate +5 in x -> non-identity world transform
    tile = types.SimpleNamespace(world_transform=m, content_transform=m)
    group = Group()
    scene = types.SimpleNamespace(group=group)
    drawable, nbytes = up.upload(tile, (scene, 17))
    assert nbytes == 17
    # A MatrixTransform wrapper is inserted (drawable is not the bare group).
    assert drawable is not group
    assert group in drawable.children
