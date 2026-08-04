"""glTF tile loading + mounting, without a GL context.

The worker-side loader parses a tile's glTF file into a scenegraph subtree (numpy
arrays; VBOs are created lazily at render), and the uploader mounts it as a drawable
node. Both are GL-free, so they are tested here directly; actual rendering is covered
by the offscreen demo render test.
"""
import os
import types

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d import gltf_uploader
from OpenGLContext.loaders.tiles3d.gltf_uploader import (
    file_tile_loader,
    GLTileUploader,
)
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
import json


def _tileset(tmp_path):
    path = build_sample_tileset(str(tmp_path))
    with open(path) as fh:
        doc = json.load(fh)
    return build_runtime_tileset(doc, base_uri=str(tmp_path) + os.sep), path


def test_sample_tileset_written(tmp_path):
    path = build_sample_tileset(str(tmp_path))
    assert os.path.exists(path)
    for name in ("root.glb", "c0.glb", "c1.glb", "c2.glb", "c3.glb"):
        assert os.path.exists(os.path.join(str(tmp_path), name))


def test_file_loader_parses_gltf_without_gl(tmp_path):
    ts, _ = _tileset(tmp_path)
    scene, nbytes = file_tile_loader(ts.root)
    assert nbytes > 0
    assert scene.group is not None  # a mountable scenegraph node


def test_uploader_mounts_a_drawable_node(tmp_path):
    ts, _ = _tileset(tmp_path)
    payload = file_tile_loader(ts.root)
    up = GLTileUploader()
    drawable, nbytes = up.upload(ts.root, payload)
    assert nbytes > 0
    assert hasattr(drawable, "render") or hasattr(drawable, "children")


def test_loader_reports_content_bytes(tmp_path):
    ts, _ = _tileset(tmp_path)
    _, nbytes = file_tile_loader(ts.root)
    disk = os.path.getsize(ts.root.content_uri)
    assert nbytes == disk


# --- release() / dispose() deterministic GL teardown (no real GL context) ------

class _FakeVBO:
    def __init__(self):
        self.deleted = False

    def delete(self):
        self.deleted = True


class _FakeGPU:
    """Stands in for a `_MeshGPU`: a VAO (freed by release) plus buffers."""

    def __init__(self):
        self.released = False
        self.idx_vbo = _FakeVBO()
        self._instance_vbo = None
        self.attr_layout = [(_FakeVBO(), 2, 3), (_FakeVBO(), 1, 3)]
        self.dyn = {}

    def release(self):
        self.released = True


class _FakeHolder:
    def __init__(self, cache, client, key):
        self._cache, self._client, self._key = cache, client, key

    def __call__(self, *a, **k):
        self._cache._data.pop((id(self._client), self._key), None)


class _FakeCache:
    def __init__(self):
        self._data = {}

    def put(self, client, key, data):
        self._data[(id(client), key)] = data

    def getData(self, client, key="", default=None):
        return self._data.get((id(client), key), default)

    def getHolder(self, client, key=""):
        if (id(client), key) in self._data:
            return _FakeHolder(self, client, key)
        return None


class _FakeContext:
    def __init__(self):
        self.cache = _FakeCache()


class _FakeTexture:
    def __init__(self, tid):
        self.texture = tid


class _FakePBRTexture:
    def __init__(self, tex, context):
        self._per_context = {id(context): tex}


class _FakeMaterial:
    def __init__(self, textures):
        self.textures = textures


class _FakeGeometry:
    def __init__(self, material=None):
        self.material = material


class _FakeShape:
    def __init__(self, geometry, appearance=None):
        self.geometry = geometry
        self.appearance = appearance


class _FakeGroup:
    def __init__(self, children):
        self.children = children


def _upload_group(group):
    up = GLTileUploader()
    tile = types.SimpleNamespace(world_transform=np.identity(4),
                                 content_transform=np.identity(4))
    scene = types.SimpleNamespace(group=group)
    drawable, nbytes = up.upload(tile, (scene, 42))
    return up, drawable, nbytes


def test_release_deletes_gl_buffers_and_textures(monkeypatch):
    """release() deletes the drawable's VAO, VBOs and textures via the current
    context, and drops the mesh's cache entry -- no reliance on GC."""
    import OpenGLContext.context as ctxmod
    import OpenGL.GL as gl

    ctx = _FakeContext()
    gpu = _FakeGPU()
    geo = _FakeGeometry(
        material=_FakeMaterial({'baseColor': _FakePBRTexture(_FakeTexture(11), ctx)}))
    ctx.cache.put(geo, PBRMesh._GPU_CACHE_KEY, gpu)
    group = _FakeGroup([_FakeShape(geo)])

    deleted_textures = []
    monkeypatch.setattr(gl, 'glDeleteTextures', lambda ids: deleted_textures.extend(ids))
    monkeypatch.setattr(ctxmod, 'getCurrentContext', lambda: ctx)

    up, drawable, nbytes = _upload_group(group)
    assert nbytes == 42
    assert drawable is group
    assert callable(drawable.dispose)

    up.release(drawable)

    assert gpu.released is True
    assert gpu.idx_vbo.deleted is True
    assert all(buf.deleted for buf, *_ in gpu.attr_layout)
    assert deleted_textures == [11]
    assert ctx.cache.getData(geo, key=PBRMesh._GPU_CACHE_KEY) is None


def test_dispose_is_idempotent(monkeypatch):
    """A second release() (or dispose()) does not delete a second time."""
    import OpenGLContext.context as ctxmod
    import OpenGL.GL as gl

    ctx = _FakeContext()
    gpu = _FakeGPU()
    geo = _FakeGeometry()
    ctx.cache.put(geo, PBRMesh._GPU_CACHE_KEY, gpu)
    group = _FakeGroup([_FakeShape(geo)])

    calls = []
    monkeypatch.setattr(gl, 'glDeleteTextures', lambda ids: calls.append(ids))
    monkeypatch.setattr(ctxmod, 'getCurrentContext', lambda: ctx)

    up, drawable, _ = _upload_group(group)
    up.release(drawable)
    gpu.released = False       # if a second pass ran, it would flip this back
    up.release(drawable)
    drawable.dispose()
    assert gpu.released is False


def test_release_without_context_is_safe_and_deletes_nothing(monkeypatch):
    """With no current context, dispose cannot touch GL; it must not raise and must
    leave resources for GC rather than crashing the eviction pass."""
    import OpenGLContext.context as ctxmod

    ctx = _FakeContext()
    gpu = _FakeGPU()
    geo = _FakeGeometry()
    ctx.cache.put(geo, PBRMesh._GPU_CACHE_KEY, gpu)
    group = _FakeGroup([_FakeShape(geo)])

    monkeypatch.setattr(ctxmod, 'getCurrentContext', lambda: None)
    gltf_uploader._warned_no_context = False

    up, drawable, _ = _upload_group(group)
    up.release(drawable)       # must not raise

    assert gpu.released is False
    assert ctx.cache.getData(geo, key=PBRMesh._GPU_CACHE_KEY) is gpu
    assert gltf_uploader._warned_no_context is True
