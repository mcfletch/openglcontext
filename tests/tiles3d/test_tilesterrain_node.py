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


def test_the_node_pages_tiles_in_and_out_as_the_camera_travels(tmp_path):
    """Streaming is on-demand in both directions: the node loads what the camera
    reaches, and releases what it leaves behind once the budget is spent.

    This is the path the viewer mounts, so it is the one that has to keep paging:
    a dataset larger than the memory budget must not simply accumulate.
    """
    import numpy as np
    from OpenGLContext.loaders.tiles3d import procedural
    from OpenGLContext.loaders.tiles3d.frustum import view_projection
    from OpenGLContext.loaders.tiles3d.gltf_uploader import GLTileUploader

    counts = {"uploaded": 0, "released": 0}

    class Counting(GLTileUploader):
        def upload(self, tile, payload):
            counts["uploaded"] += 1
            return super().upload(tile, payload)

        def release(self, drawable):
            counts["released"] += 1
            return super().release(drawable)

    # 85 tiles over 2 km, with a budget that holds a moving window of them.
    budget = 700 * 1024
    path = procedural.build_terrain_tileset(str(tmp_path), extent=2048, levels=4,
                                            tile_res=17)
    terrain = TilesTerrain(path, fovy=math.radians(50.0), workers=4, max_sse=10.0,
                           memory_budget=budget)
    terrain.runtime.uploader = Counting()
    try:
        for z in np.linspace(-820, 820, 12):
            surface = max(float(procedural.terrain_height(
                np.array([0.0]), np.array([z]))[0]), procedural.WATER_LEVEL)
            eye = (0.0, surface + 55.0, float(z))
            # The viewer hands the runtime a view projection every frame; without
            # one every tile counts as wanted, and wanted tiles are never evicted.
            vp = view_projection(eye, (0.0, surface, float(z) + 200.0), up=(0, 1, 0),
                                 fovy=math.radians(50.0), aspect=1.4,
                                 near=1.0, far=1400.0)
            for _ in range(3):
                terrain.update_for_camera(eye, 800, view_projection=vp)
                terrain.wait_for_loads(timeout=8.0)
        resident = terrain.runtime.residency.resident_bytes
    finally:
        terrain.shutdown()

    total = sum(1 for _ in terrain.tileset.iter_tiles())
    assert counts["uploaded"] > 0, "nothing streamed in"
    assert counts["released"] > 0, "nothing was ever unloaded"
    # More tiles passed through than the budget could ever hold at once.
    assert counts["uploaded"] > counts["released"]
    assert counts["uploaded"] <= total * 2
    # The budget is a target rather than a wall -- tiles the current view wants are
    # never evicted -- so allow headroom while still ruling out "kept everything".
    assert resident <= budget * 3, resident
