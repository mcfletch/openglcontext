"""TilesetRuntime: the per-frame tick tying traversal, loading, upload and eviction.

Uses a fake loader and fake uploader (no GL) so the streaming orchestration is
exercised directly: async load then upload, coarse-parent fallback while a finer
child streams, upload throttling, memory-budget eviction with resource release, and
graceful handling of a failed load.
"""
import math
import threading
import pytest

from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d.runtime import TilesetRuntime

FOVY = math.radians(60.0)


class Drawable:
    def __init__(self, tile):
        self.tile = tile


class FakeUploader:
    def __init__(self, nbytes=100):
        self.nbytes = nbytes
        self.uploaded = []
        self.released = []

    def upload(self, tile, payload):
        self.uploaded.append(tile)
        return Drawable(tile), self.nbytes

    def release(self, drawable):
        self.released.append(drawable)


def _loader(tile):
    return "data:" + (tile.content_uri or "")


def _nested():
    box = [0, 0, 0, 5, 0, 0, 0, 5, 0, 0, 0, 5]
    return build_runtime_tileset({
        "asset": {"version": "1.1"}, "geometricError": 400.0,
        "root": {
            "boundingVolume": {"box": box}, "geometricError": 200.0,
            "refine": "REPLACE", "content": {"uri": "root.glb"},
            "children": [{
                "boundingVolume": {"box": box}, "geometricError": 0.0,
                "content": {"uri": "leaf.glb"},
            }],
        },
    })


def _uris(drawables):
    return [d.tile.content_uri for d in drawables]


def test_far_camera_loads_and_draws_root():
    up = FakeUploader()
    rt = TilesetRuntime(_nested(), _loader, up, memory_budget=10_000,
                        fovy=FOVY, max_sse=16.0, workers=2)
    try:
        rt.update(camera=(30000, 0, 0), viewport_height=1000)  # schedules root load
        assert rt.wait_for_loads(timeout=5.0)
        drawn = rt.update(camera=(30000, 0, 0), viewport_height=1000)  # uploads + draws
        assert _uris(drawn) == ["root.glb"]
    finally:
        rt.shutdown()


def test_parent_fallback_while_child_loads():
    up = FakeUploader()
    rt = TilesetRuntime(_nested(), _loader, up, memory_budget=10_000,
                        fovy=FOVY, max_sse=16.0, prefetch_factor=1.0, workers=2)
    try:
        # Establish root resident from far away.
        rt.update(camera=(30000, 0, 0), viewport_height=1000)
        assert rt.wait_for_loads(timeout=5.0)
        rt.update(camera=(30000, 0, 0), viewport_height=1000)
        # Jump close: ideal render is the leaf, not yet resident -> draw root fallback.
        drawn = rt.update(camera=(0, 0, 0), viewport_height=1000)
        assert _uris(drawn) == ["root.glb"]
        # Once the leaf finishes, it replaces the fallback.
        assert rt.wait_for_loads(timeout=5.0)
        drawn = rt.update(camera=(0, 0, 0), viewport_height=1000)
        assert _uris(drawn) == ["leaf.glb"]
    finally:
        rt.shutdown()


def test_upload_is_throttled_per_update():
    box = [0, 0, 0, 5, 0, 0, 0, 5, 0, 0, 0, 5]
    ts = build_runtime_tileset({
        "asset": {"version": "1.1"}, "geometricError": 400.0,
        "root": {
            "boundingVolume": {"box": box}, "geometricError": 200.0, "refine": "ADD",
            "content": {"uri": "root.glb"},
            "children": [
                {"boundingVolume": {"box": box}, "geometricError": 0.0,
                 "content": {"uri": "c%d.glb" % i}} for i in range(6)
            ],
        },
    })
    up = FakeUploader()
    rt = TilesetRuntime(ts, _loader, up, memory_budget=10_000, fovy=FOVY,
                        max_sse=16.0, max_uploads_per_update=2, workers=4)
    try:
        rt.update(camera=(0, 0, 0), viewport_height=1000)
        assert rt.wait_for_loads(timeout=5.0)
        # Every update uploads at most the cap, even with all 7 tiles ready; it takes
        # several updates to drain them.
        counts = []
        for _ in range(6):
            before = len(up.uploaded)
            rt.update(camera=(0, 0, 0), viewport_height=1000)
            counts.append(len(up.uploaded) - before)
        assert max(counts) <= 2
        assert len(up.uploaded) == 7  # all eventually uploaded, just throttled
    finally:
        rt.shutdown()


def test_eviction_releases_gl_resources_and_respects_budget():
    box = [0, 0, 0, 5, 0, 0, 0, 5, 0, 0, 0, 5]
    ts = build_runtime_tileset({
        "asset": {"version": "1.1"}, "geometricError": 400.0,
        "root": {
            "boundingVolume": {"box": box}, "geometricError": 200.0, "refine": "ADD",
            "content": {"uri": "root.glb"},
            "children": [
                {"boundingVolume": {"box": box}, "geometricError": 0.0,
                 "content": {"uri": "c%d.glb" % i}} for i in range(4)
            ],
        },
    })
    up = FakeUploader(nbytes=100)
    # Budget only fits ~3 tiles; up close all 5 are wanted (over budget is allowed);
    # moving far drops the children from the want set, and *then* they are evictable.
    rt = TilesetRuntime(ts, _loader, up, memory_budget=300, fovy=FOVY,
                        max_sse=16.0, max_uploads_per_update=100, workers=4)
    try:
        for _ in range(3):  # fill: root + 4 children resident (500 bytes, over budget)
            rt.update(camera=(0, 0, 0), viewport_height=1000)
            rt.wait_for_loads(timeout=5.0)
        for _ in range(3):  # retreat: only root wanted, children now evictable
            rt.update(camera=(30000, 0, 0), viewport_height=1000)
            rt.wait_for_loads(timeout=5.0)
        assert rt.residency.resident_bytes <= 300  # back within budget
        assert len(up.released) >= 1  # evicted children released their GL resources
    finally:
        rt.shutdown()


def test_failed_load_does_not_crash_update():
    def bad_loader(tile):
        raise IOError("network down")

    up = FakeUploader()
    rt = TilesetRuntime(_nested(), bad_loader, up, memory_budget=10_000,
                        fovy=FOVY, max_sse=16.0, workers=2)
    try:
        rt.update(camera=(10000, 0, 0), viewport_height=1000)
        assert rt.wait_for_loads(timeout=5.0)
        drawn = rt.update(camera=(10000, 0, 0), viewport_height=1000)
        assert drawn == []  # nothing renderable, but no exception
        assert up.uploaded == []
    finally:
        rt.shutdown()
