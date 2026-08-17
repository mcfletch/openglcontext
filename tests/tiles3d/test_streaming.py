"""Streaming/caching under a camera flythrough over a large tileset (headless).

Drives the runtime over a multi-level procedural tileset with a memory budget too
small to hold everything, flying the camera across the world. Validates that tiles
load as they are approached, memory stays bounded, tiles are evicted as they fall
behind, and far more distinct tiles stream over the flight than are ever resident at
once — i.e. it streams rather than loading the whole world.

Uses the real glTF loader + uploader (both GL-free — VBOs are lazy), so the full
paging path runs without a GL context.
"""
import os
import json
import math
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d import procedural as P
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d.runtime import TilesetRuntime
from OpenGLContext.loaders.tiles3d.gltf_uploader import file_tile_loader, GLTileUploader
from OpenGLContext.loaders.tiles3d.frustum import view_projection


def _vp(eye, look_at):
    return view_projection(eye, look_at, up=(0, 1, 0), fovy=math.radians(55),
                           aspect=1.3, near=1.0, far=1400.0)


class CountingUploader(GLTileUploader):
    def __init__(self):
        self.uploaded = []
        self.released = 0

    def upload(self, tile, payload):
        self.uploaded.append(tile.content_uri)
        return super().upload(tile, payload)

    def release(self, drawable):
        self.released += 1
        return super().release(drawable)


def _runtime(tmp_path, tiles_resident):
    """A runtime over an 85-tile world, budgeted to hold `tiles_resident` of them.

    The budget is derived from the tiles as baked rather than written down as a
    byte count: what a tile weighs is the writer's business, and a literal here
    would silently stop forcing eviction the next time the encoder improves.
    """
    path = P.build_terrain_tileset(str(tmp_path), extent=2048, levels=4, tile_res=17)
    with open(path) as fh:
        doc = json.load(fh)
    # As the viewer builds it: a dataset is turned into the frame it is drawn
    # in, and the camera path below is in that frame.
    ts = build_runtime_tileset(doc, base_uri=str(tmp_path) + os.sep, recenter=True)
    budget = int(_tile_bytes(ts) * tiles_resident)
    up = CountingUploader()
    rt = TilesetRuntime(ts, file_tile_loader, up, memory_budget=budget,
                        fovy=math.radians(50.0), max_sse=10.0, workers=4,
                        max_uploads_per_update=8, prefetch_factor=1.5)
    return rt, up, ts, budget


def _tile_bytes(ts):
    return max(os.path.getsize(t.content_uri)
               for t in ts.iter_tiles() if t.content_uri)


def _low_path(n):
    """A flight path skimming just above the terrain, so only nearby tiles refine."""
    pts = []
    for z in np.linspace(-820, 820, n):
        x = 200.0 * math.sin(z * 0.004)
        y = max(float(P.terrain_height(np.array([x]), np.array([z]))[0]),
                P.WATER_LEVEL) + 55.0
        pts.append((x, y, z))
    return pts


def test_flythrough_streams_within_budget_and_evicts(tmp_path):
    # 85 tiles (1+4+16+64); the budget holds a moving window, not the whole world.
    # 34 is a little above the ~31 tiles the flight has in view at once, which are
    # the ones eviction cannot touch, and well under the 50 the flight visits.
    rt, up, ts, budget = _runtime(tmp_path, tiles_resident=34)
    biggest = _tile_bytes(ts)
    total_tiles = sum(1 for _ in ts.iter_tiles())
    try:
        max_resident_bytes = 0
        max_resident_count = 0
        path = _low_path(16)
        for i, cam in enumerate(path):
            nxt = path[min(i + 1, len(path) - 1)]
            look = (nxt[0], cam[1] - 20, nxt[2])   # look ahead + slightly down
            vp = _vp(cam, look)
            for _ in range(3):
                rt.update(tuple(cam), viewport_height=720, view_projection=vp)
                rt.wait_for_loads(timeout=8.0)
            rt.update(tuple(cam), viewport_height=720, view_projection=vp)
            max_resident_bytes = max(max_resident_bytes, rt.residency.resident_bytes)
            max_resident_count = max(max_resident_count, len(rt._drawables))

        distinct_loaded = len(set(up.uploaded))
        # 1. Memory stayed bounded near the budget.
        assert max_resident_bytes <= budget + biggest, (max_resident_bytes, budget)
        # 2. Streamed far more distinct tiles than were ever resident at once.
        assert distinct_loaded > max_resident_count + 3, (distinct_loaded, max_resident_count)
        # 3. Eviction actually happened.
        assert up.released > 0
        # 4. Not the whole world resident at any time (budget forced streaming).
        assert max_resident_count < total_tiles
    finally:
        rt.shutdown()


def test_resident_tiles_are_near_the_camera(tmp_path):
    rt, up, ts, _budget = _runtime(tmp_path, tiles_resident=8)
    try:
        cam = (600.0, 120.0, 600.0)
        vp = _vp(cam, (0.0, 0.0, 0.0))          # look toward the world centre
        for _ in range(8):
            rt.update(cam, viewport_height=720, view_projection=vp)
            rt.wait_for_loads(timeout=8.0)
        rt.update(cam, viewport_height=720, view_projection=vp)
        # Every resident renderable tile's bounding volume is reasonably near the
        # camera (this corner of the world), not off on the far side.
        cam_np = np.array(cam)
        far = 0
        for tile in ts.iter_tiles():
            if id(tile) in rt._drawables:
                d = tile.bounding_volume.distance_to(cam_np)
                if d > 2200:
                    far += 1
        assert far == 0
        assert len(rt._drawables) >= 1
    finally:
        rt.shutdown()
