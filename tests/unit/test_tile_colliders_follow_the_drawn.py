"""Colliders for the tiles that are *drawn*, not for the tiles in memory.

A streamer keeps tiles it is not drawing: a coarse parent stays resident so it
can be shown again the moment the camera pulls back, and siblings hang around
until the budget wants their space. Their geometry is the same ground at a
different resolution, half a metre from the ground actually on screen.

Built into the physics world they are a second surface under everything -- and a
car at speed catches the step between them, which reads as hitting a wall in the
middle of an open road. So the set of colliders is the set of drawn tiles, and
nothing else.
"""
import gc
import weakref

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d.physics_colliders import TerrainColliders
from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
from OpenGLContext.physics import gltf_world
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain


class _Tile:
    """As much of a runtime tile as the colliders read."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return 'Tile(%s)' % (self.name,)


@pytest.fixture
def physics():
    """A service with no scenery of its own, stepped by hand."""
    service = Physics(PhysicsDefinition(mode='inline', colliders='none'))
    yield service
    service.close()


def _held(physics):
    """How many bodies the world is carrying."""
    return physics.counts.bodies


def _patch(offset=0.0, side=3):
    """A little square of ground, as a tile's drawable holds it."""
    axis = np.linspace(-10.0, 10.0, side)
    gx, gz = np.meshgrid(axis, axis, indexing='ij')
    points = np.stack([gx.ravel(), np.full(gx.size, offset), gz.ravel()],
                      axis=-1)
    faces = []
    for i in range(side - 1):
        for j in range(side - 1):
            a = i * side + j
            faces += [(a, a + 1, a + side), (a + 1, a + side + 1, a + side)]
    return points, np.asarray(faces, dtype='i')


class _Drawable:
    """Something ``extract_trimesh`` can read a patch out of."""

    def __init__(self, offset=0.0):
        self.points, self.indices = _patch(offset)


@pytest.fixture
def _extractable(monkeypatch):
    """Read a patch straight off the stand-in drawable, with no glTF involved."""
    monkeypatch.setattr(
        gltf_world, 'extract_trimesh',
        lambda drawable, min_hull_size=0.0: (drawable.points, drawable.indices))  # noqa: ARG005 extract_trimesh's signature


def _pair(name, offset=0.0):
    return _Tile(name), _Drawable(offset)


@pytest.mark.usefixtures('_extractable')
class TestTheDrawnSetIsTheColliderSet:
    def test_a_drawn_tile_gets_a_collider(self, physics) -> None:
        ground = TerrainColliders(physics)
        ground.on_drawn([_pair('a')])
        assert ground.collider_count == 1
        hit = physics.raycast((0.0, 5.0, 0.0), (0.0, -1.0, 0.0), 10.0)
        assert hit is not None and hit.body is ground.bodies()[0]

    def test_a_tile_that_stops_being_drawn_loses_it(self, physics) -> None:
        ground = TerrainColliders(physics)
        coarse = _pair('coarse')
        ground.on_drawn([coarse])
        ground.on_drawn([_pair('fine')])
        assert ground.collider_count == 1
        assert _held(physics) == 1

    def test_a_tile_still_drawn_keeps_the_one_it_had(self, physics) -> None:
        """Rebuilding a trimesh every frame would cost more than the physics."""
        ground = TerrainColliders(physics)
        held = _pair('held')
        ground.on_drawn([held])
        (body,) = ground.bodies()
        ground.on_drawn([held, _pair('new')])
        assert ground.bodies()[0] is body and body.alive
        assert _held(physics) == 2

    def test_drawing_nothing_holds_nothing(self, physics) -> None:
        ground = TerrainColliders(physics)
        ground.on_drawn([_pair('a'), _pair('b')])
        ground.on_drawn([])
        assert ground.collider_count == 0
        assert _held(physics) == 0

    def test_a_tile_drawn_again_gets_a_collider_again(self, physics) -> None:
        ground = TerrainColliders(physics)
        back = _pair('back')
        ground.on_drawn([back])
        ground.on_drawn([])
        ground.on_drawn([back])
        assert ground.collider_count == 1

    def test_a_drawable_with_no_triangles_is_no_collider(self, physics) -> None:
        ground = TerrainColliders(physics)
        empty = _Drawable()
        empty.points, empty.indices = np.zeros((0, 3)), np.zeros((0, 3), 'i')
        ground.on_drawn([(_Tile('empty'), empty)])
        assert ground.collider_count == 0

    def test_a_tile_with_a_collider_outlives_every_other_reference(self, physics) -> None:
        """A collider is found by its tile, not by where the tile was allocated.

        A collected tile's address is handed to the next object of its size,
        so a table keyed on addresses would answer a newcomer with the old
        tile's body. Holding the tile keeps its address from being reused.
        """
        ground = TerrainColliders(physics)
        tile = _Tile('held')
        ground.on_renderable(tile, _Drawable())
        held = weakref.ref(tile)
        del tile
        gc.collect()
        assert held() is not None
        ground.on_drawn([])
        gc.collect()
        assert held() is None


class TestTheStreamerDrivesIt:
    def test_the_runtime_reports_what_it_drew(self, tmp_path) -> None:
        path = build_sample_tileset(str(tmp_path))
        seen = []
        terrain = TilesTerrain(path, workers=1)
        terrain.runtime.on_drawn = lambda pairs: seen.append(len(pairs))
        try:
            terrain.update_for_camera(np.array([0.0, 200.0, 0.0]), 720.0)
            terrain.wait_for_loads(timeout=5.0)
            terrain.update_for_camera(np.array([0.0, 200.0, 0.0]), 720.0)
            assert seen and max(seen) > 0
        finally:
            terrain.shutdown()

    def test_a_streamed_world_holds_only_what_it_draws(self, tmp_path, physics) -> None:
        path = build_sample_tileset(str(tmp_path))
        terrain = TilesTerrain(path, physics=physics, workers=1)
        try:
            for _ in range(6):
                terrain.update_for_camera(np.array([0.0, 60.0, 0.0]), 720.0)
                terrain.wait_for_loads(timeout=5.0)
            drawn = terrain.update_for_camera(np.array([0.0, 60.0, 0.0]), 720.0)
            assert terrain.colliders.collider_count <= len(drawn)
            assert _held(physics) == terrain.colliders.collider_count
        finally:
            terrain.shutdown()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
