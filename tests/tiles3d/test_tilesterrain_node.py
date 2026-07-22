"""TilesTerrain node integration, without a GL context.

Drives the node over the sample tileset through the full stack (traversal, background
glTF load, mount, residency) and checks that the visible children update as the
camera moves: coarse root from afar, finer quadrant tiles up close.
"""
import math
import os
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain


def _terrain(tmp_path, **kw):
    path = build_sample_tileset(str(tmp_path))
    return TilesTerrain(path, fovy=math.radians(45.0), workers=3, **kw)


def _settle(terrain, camera, vh=800, frames=6):
    drawn = []
    for _ in range(frames):
        drawn = terrain.update_for_camera(camera, vh)
        terrain.wait_for_loads(timeout=5.0)
    return drawn


def test_distant_camera_shows_coarse_root(tmp_path):
    terrain = _terrain(tmp_path)
    try:
        drawn = _settle(terrain, camera=(0, 1000, 4000))  # far above and back
        assert len(terrain.children) == 1
        assert len(drawn) == 1
    finally:
        terrain.shutdown()


def test_close_camera_refines_to_children(tmp_path):
    terrain = _terrain(tmp_path, max_sse=8.0)
    try:
        # Low over the surface: the root's error is too high, refine to quadrants.
        drawn = _settle(terrain, camera=(0, 15, 0))
        assert len(drawn) >= 2  # multiple quadrant tiles visible
    finally:
        terrain.shutdown()


def test_children_are_mountable_nodes(tmp_path):
    terrain = _terrain(tmp_path)
    try:
        _settle(terrain, camera=(0, 400, 900))
        for child in terrain.children:
            assert hasattr(child, "children") or hasattr(child, "render")
    finally:
        terrain.shutdown()


def test_terrain_populates_physics_world(tmp_path):
    import math as _m
    from omi_physics.world import PhysicsWorld
    from omi_physics import model
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    path = build_sample_tileset(str(tmp_path))
    terrain = TilesTerrain(path, fovy=_m.radians(45.0), workers=3, physics_world=world)
    try:
        _settle(terrain, camera=(0, 300, 0))
        assert terrain.colliders.collider_count >= 1
        assert len(world.bodies) >= 1
    finally:
        terrain.shutdown()
