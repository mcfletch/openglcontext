"""A streamed world whose ground is one field rather than a tree of tiles.

A world of a few kilometres can carry its whole landscape as a height image and
a splat control map beside the tileset, and say so in the tileset's ``extras``.
Everything else about it is unchanged -- the road, its structures and anything
placed still stream as tiles -- so the terrain node mounts the field and streams
the rest, and every consumer of a baked world gets it without knowing.
"""
import json
import os

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.scenegraph.terrain import HeightField, LayerRule, control_map
from OpenGLContext.scenegraph.terrain.splat import SplatTerrain
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain

EXTENT = 512.0


def _hilly(x, z):
    return 25.0 * np.sin(np.asarray(x, 'd') / 90.0) \
        - 15.0 * np.cos(np.asarray(z, 'd') / 70.0)


def _world(directory, terrain=True, layers=('grass', 'rock')):
    """A tileset with one empty root and, optionally, a field terrain."""
    from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
    path = build_sample_tileset(str(directory))
    document = json.load(open(path))
    if terrain:
        field = HeightField.from_function(_hilly, res=65, extent=EXTENT)
        field.save_image(os.path.join(str(directory), 'ground-height.png'))
        control_map(field, [LayerRule() for _ in layers], size=64).save(
            os.path.join(str(directory), 'ground-control.png'))
        document.setdefault('extras', {})['terrain'] = {
            'height': 'ground-height.png', 'control': 'ground-control.png',
            'extent': EXTENT, 'base': field.base, 'relief': field.relief,
            'resolution': 65, 'layers': list(layers),
        }
        json.dump(document, open(path, 'w'))
    return path


def _mounted(terrain):
    return [child for child in terrain.children
            if isinstance(getattr(child, 'geometry', None), SplatTerrain)]


class TestMountingTheField:
    def test_a_world_that_carries_one_gets_it(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            assert terrain.field is not None
            assert len(_mounted(terrain)) == 1
        finally:
            terrain.shutdown()

    def test_a_world_without_one_has_none(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path, terrain=False), workers=1)
        try:
            assert terrain.field is None
            assert _mounted(terrain) == []
        finally:
            terrain.shutdown()

    def test_the_field_is_the_landscape_that_was_baked(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            x = np.linspace(-200.0, 200.0, 21)
            found = np.asarray(terrain.field.sample(x, x))
            assert np.abs(found - _hilly(x, x)).max() < 2.0
        finally:
            terrain.shutdown()

    def test_it_survives_a_streaming_tick(self, tmp_path) -> None:
        """The splat terrain is not a streamed tile and must not be swept away
        when the visible set changes."""
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            terrain.update_for_camera(np.array([0.0, 200.0, 0.0]), 720.0)
            terrain.update_for_camera(np.array([100.0, 200.0, 100.0]), 720.0)
            assert len(_mounted(terrain)) == 1
        finally:
            terrain.shutdown()

    def test_the_tiles_still_stream_beside_it(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            terrain.update_for_camera(np.array([0.0, 200.0, 0.0]), 720.0)
            terrain.wait_for_loads(timeout=5.0)
            terrain.update_for_camera(np.array([0.0, 200.0, 0.0]), 720.0)
            assert len(terrain.children) > len(_mounted(terrain))
        finally:
            terrain.shutdown()

    def test_the_materials_named_are_the_ones_used(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path, layers=('grass', 'rock', 'dirt')),
                               workers=1)
        try:
            assert _mounted(terrain)[0].geometry.layers == ['grass', 'rock', 'dirt']
        finally:
            terrain.shutdown()

    def test_it_can_be_turned_off(self, tmp_path) -> None:
        """A tool that wants only what streams -- an inspector, a validator --
        should not pay to decode a landscape."""
        terrain = TilesTerrain(_world(tmp_path), workers=1, field_terrain=False)
        try:
            assert terrain.field is None
        finally:
            terrain.shutdown()


class TestWhatAGameDoesWithIt:
    def test_the_ground_under_a_point_comes_from_the_field(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            assert terrain.field.height_at(30.0, -40.0) == pytest.approx(
                float(_hilly(30.0, -40.0)), abs=1.0)
        finally:
            terrain.shutdown()

    def test_colliders_can_be_built_from_it(self, tmp_path) -> None:
        from omi_physics.raycast import raycast
        from omi_physics.world import PhysicsWorld

        from OpenGLContext.physics.heightfield import HeightFieldColliders
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            world = PhysicsWorld()
            ground = HeightFieldColliders(world, terrain.field, reach=200.0)
            ground.update((0.0, 0.0, 0.0))
            hit = raycast(world, (0.0, 300.0, 0.0), (0.0, -1.0, 0.0),
                          max_distance=600.0)
            assert hit is not None
            assert float(hit.point[1]) == pytest.approx(float(_hilly(0.0, 0.0)),
                                                        abs=1.0)
        finally:
            terrain.shutdown()


class TestWhenItIsWrong:
    def test_a_record_missing_its_image_is_reported(self, tmp_path) -> None:
        path = _world(tmp_path)
        os.remove(os.path.join(str(tmp_path), 'ground-height.png'))
        with pytest.raises(Exception):
            TilesTerrain(path, workers=1).shutdown()

    def test_a_record_with_no_layers_is_refused(self, tmp_path) -> None:
        path = _world(tmp_path)
        document = json.load(open(path))
        document['extras']['terrain']['layers'] = []
        json.dump(document, open(path, 'w'))
        with pytest.raises(ValueError):
            TilesTerrain(path, workers=1).shutdown()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
