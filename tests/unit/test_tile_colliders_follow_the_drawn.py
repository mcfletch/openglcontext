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
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d.physics_colliders import TerrainColliders


class _Tile:
    """As much of a runtime tile as the colliders read."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return 'Tile(%s)' % (self.name,)


class _World:
    """A physics world that counts what it is asked to hold."""

    def __init__(self, removable=True):
        self.shapes = []
        self.bodies = {}
        self._next = 0
        if not removable:
            self.remove_body = None

    def add_shape(self, shape):
        self.shapes.append(shape)
        return len(self.shapes) - 1

    def add_body(self, motion, collider=None, position=None):
        self._next += 1
        self.bodies[self._next] = collider
        return self._next

    def remove_body(self, body):
        self.bodies.pop(body, None)


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
    from OpenGLContext.physics import gltf_world
    monkeypatch.setattr(
        gltf_world, 'extract_trimesh',
        lambda drawable, min_hull_size=0.0: (drawable.points, drawable.indices))


def _pair(name, offset=0.0):
    return _Tile(name), _Drawable(offset)


@pytest.mark.usefixtures('_extractable')
class TestTheDrawnSetIsTheColliderSet:
    def test_a_drawn_tile_gets_a_collider(self) -> None:
        world = _World()
        ground = TerrainColliders(world)
        ground.on_drawn([_pair('a')])
        assert ground.collider_count == 1

    def test_a_tile_that_stops_being_drawn_loses_it(self) -> None:
        world = _World()
        ground = TerrainColliders(world)
        coarse = _pair('coarse')
        ground.on_drawn([coarse])
        ground.on_drawn([_pair('fine')])
        assert ground.collider_count == 1
        assert len(world.bodies) == 1

    def test_a_tile_still_drawn_keeps_the_one_it_had(self) -> None:
        """Rebuilding a trimesh every frame would cost more than the physics."""
        world = _World()
        ground = TerrainColliders(world)
        held = _pair('held')
        ground.on_drawn([held])
        shapes = len(world.shapes)
        ground.on_drawn([held, _pair('new')])
        assert len(world.shapes) == shapes + 1

    def test_drawing_nothing_holds_nothing(self) -> None:
        world = _World()
        ground = TerrainColliders(world)
        ground.on_drawn([_pair('a'), _pair('b')])
        ground.on_drawn([])
        assert ground.collider_count == 0

    def test_a_tile_drawn_again_gets_a_collider_again(self) -> None:
        world = _World()
        ground = TerrainColliders(world)
        back = _pair('back')
        ground.on_drawn([back])
        ground.on_drawn([])
        ground.on_drawn([back])
        assert ground.collider_count == 1

    def test_a_drawable_with_no_triangles_is_no_collider(self) -> None:
        world = _World()
        ground = TerrainColliders(world)
        empty = _Drawable()
        empty.points, empty.indices = np.zeros((0, 3)), np.zeros((0, 3), 'i')
        ground.on_drawn([(_Tile('empty'), empty)])
        assert ground.collider_count == 0

    def test_a_world_that_cannot_remove_says_so_once(self, caplog) -> None:
        world = _World(removable=False)
        ground = TerrainColliders(world)
        ground.on_drawn([_pair('a')])
        with caplog.at_level('WARNING'):
            ground.on_drawn([])
            ground.on_drawn([_pair('b')])
            ground.on_drawn([])
        assert sum('remove_body' in record.message
                   for record in caplog.records) == 1


class TestTheStreamerDrivesIt:
    def test_the_runtime_reports_what_it_drew(self, tmp_path) -> None:
        from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
        from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
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

    def test_a_streamed_world_holds_only_what_it_draws(self, tmp_path) -> None:
        from omi_physics.world import PhysicsWorld

        from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
        from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
        path = build_sample_tileset(str(tmp_path))
        world = PhysicsWorld()
        terrain = TilesTerrain(path, physics_world=world, workers=1)
        try:
            for _ in range(6):
                terrain.update_for_camera(np.array([0.0, 60.0, 0.0]), 720.0)
                terrain.wait_for_loads(timeout=5.0)
            drawn = terrain.update_for_camera(np.array([0.0, 60.0, 0.0]), 720.0)
            assert terrain.colliders.collider_count <= len(drawn)
        finally:
            terrain.shutdown()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
