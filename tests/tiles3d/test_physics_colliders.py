"""Per-tile physics colliders (no GL).

The runtime fires on_renderable/on_evicted around a tile's drawable lifecycle; the
collider sink turns a resident tile's mesh into a static trimesh body in a real
physics world. Both are GL-free, so this runs end to end without a context.
"""
import math
import os
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d.runtime import TilesetRuntime
from OpenGLContext.loaders.tiles3d.gltf_uploader import (
    file_tile_loader, GLTileUploader,
)
from OpenGLContext.loaders.tiles3d.physics_colliders import TerrainColliders
from omi_physics.world import PhysicsWorld
from omi_physics import model
import json


def _runtime(tmp_path, **kw):
    path = build_sample_tileset(str(tmp_path))
    with open(path) as fh:
        doc = json.load(fh)
    ts = build_runtime_tileset(doc, base_uri=str(tmp_path) + os.sep)
    return TilesetRuntime(ts, file_tile_loader, GLTileUploader(),
                          memory_budget=100 * 1024 * 1024,
                          fovy=math.radians(45.0), workers=3, **kw)


def test_runtime_fires_renderable_callback(tmp_path):
    seen = []
    rt = _runtime(tmp_path, on_renderable=lambda tile, drawable: seen.append(tile))
    try:
        for _ in range(6):
            rt.update(camera=(0, 300, 0), viewport_height=800)
            rt.wait_for_loads(timeout=5.0)
        assert len(seen) >= 1  # at least one tile became drawable and fired the hook
    finally:
        rt.shutdown()


def test_collider_added_for_resident_tile(tmp_path):
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    colliders = TerrainColliders(world)
    rt = _runtime(tmp_path, on_renderable=colliders.on_renderable,
                  on_evicted=colliders.on_evicted)
    try:
        for _ in range(6):
            rt.update(camera=(0, 300, 0), viewport_height=800)
            rt.wait_for_loads(timeout=5.0)
        assert colliders.collider_count >= 1
        assert len(world.bodies) >= 1
    finally:
        rt.shutdown()


class _Tile:
    """Minimal stand-in for a tile (identity is by id())."""


def test_on_evicted_does_not_grow_unbounded_without_removal_api():
    """A world with no remove_body must not leave on_evicted accumulating a handle
    per eviction; the handle is dropped, and the list stays bounded."""
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    colliders = TerrainColliders(world)
    assert not hasattr(world, "remove_body")
    for i in range(2000):
        tile = _Tile()
        colliders._bodies[id(tile)] = i     # pretend a collider was added
        colliders.on_evicted(tile, None)
    assert colliders.collider_count == 0
    assert len(colliders.pending_removals) == 0


def test_on_evicted_uses_remove_body_when_available():
    """When the world exposes remove_body, on_evicted removes the body and forgets
    the handle."""
    class RemovableWorld:
        def __init__(self):
            self.removed = []

        def remove_body(self, body):
            self.removed.append(body)

    world = RemovableWorld()
    colliders = TerrainColliders(world)
    tile = _Tile()
    colliders._bodies[id(tile)] = 7
    colliders.on_evicted(tile, None)
    assert world.removed == [7]
    assert colliders.collider_count == 0
    assert colliders.pending_removals == []


def test_extracted_collider_has_triangles(tmp_path):
    path = build_sample_tileset(str(tmp_path))
    with open(path) as fh:
        doc = json.load(fh)
    ts = build_runtime_tileset(doc, base_uri=str(tmp_path) + os.sep)
    from OpenGLContext.physics import gltf_world
    scene, _ = file_tile_loader(ts.root)
    points, indices = gltf_world.extract_trimesh(scene.group)
    assert len(points) > 0
    assert len(indices) > 0
