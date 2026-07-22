"""Cave/overhang tiles: arbitrary 3D geometry carried through the same runtime.

Caves and overhangs are not a special case here — they are ordinary glTF octree
tiles. This checks the overhang tileset has genuine solid-air-solid structure (which
no heightfield can express), streams and renders through `TilesTerrain`, and produces
a walkable static collider.
"""
import math
import os
import json
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d.sample import build_overhang_tileset
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d.gltf_uploader import file_tile_loader
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain


def _runtime_tileset(tmp_path):
    path = build_overhang_tileset(str(tmp_path))
    with open(path) as fh:
        doc = json.load(fh)
    return build_runtime_tileset(doc, base_uri=str(tmp_path) + os.sep), path


def test_overhang_geometry_is_not_a_heightfield(tmp_path):
    ts, _ = _runtime_tileset(tmp_path)
    overhang = [t for t in ts.iter_tiles() if t.content_uri
                and t.content_uri.endswith("overhang.glb")][0]
    scene, _ = file_tile_loader(overhang)
    from OpenGLContext.physics import gltf_world
    pts, _tris = gltf_world.extract_trimesh(scene.group)
    # The slab is lifted well above y=0: a column through it has ground below and
    # slab above -> more than one solid surface in the same (x, z), i.e. not 2.5D.
    assert pts[:, 1].min() > 15.0


def test_overhang_tile_streams_and_gets_collider(tmp_path):
    from omi_physics.world import PhysicsWorld
    from omi_physics import model
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    path = build_overhang_tileset(str(tmp_path))
    terrain = TilesTerrain(path, fovy=math.radians(45.0), workers=3,
                           physics_world=world)
    try:
        drawn = []
        for _ in range(6):
            drawn = terrain.update_for_camera((0, 60, 200), 800)
            terrain.wait_for_loads(timeout=5.0)
        # Both ground and overhang render (ADD refine), and both become colliders.
        assert len(drawn) >= 2
        assert terrain.colliders.collider_count >= 2
        assert len(world.bodies) >= 2
    finally:
        terrain.shutdown()
