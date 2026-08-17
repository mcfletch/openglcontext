"""A streamed world that carries its forest as a table rather than as tiles.

Trees baked into tiles arrive and leave with the tile they are in, which means
the tile decides the level of detail and the tile's textures are carried in
every copy of it. A forest does not work that way: what a tree is drawn as
depends on how far it is from the camera, not on which tile it stands in.

So a world writes its trees once -- a table of positions beside the tileset, and
the species they are drawn from -- and the terrain node builds a
:class:`~OpenGLContext.scenegraph.vegetation.field.VegetationField` from it.
"""
import json
import os

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
from OpenGLContext.scenegraph.vegetation.field import VegetationField

COUNT = 300


def _trees(directory, count=COUNT, kinds=2, seed=5):
    rng = np.random.default_rng(seed)
    np.savez(os.path.join(str(directory), 'trees.npz'),
             positions=np.stack([rng.uniform(-800, 800, count),
                                 np.zeros(count),
                                 rng.uniform(-800, 800, count)],
                                axis=-1).astype('f4'),
             yaws=rng.uniform(0, 6.283, count).astype('f4'),
             heights=rng.uniform(9.0, 18.0, count).astype('f4'),
             species=rng.integers(0, kinds, count).astype('i4'))
    return [{'name': 'kind%d' % i, 'mesh': 'kind%d.npz' % i,
             'solidTexture': 'bark%d.png' % i,
             'foliageTexture': 'leaf%d.png' % i,
             'impostor': 'card%d.png' % i}
            for i in range(kinds)]


def _world(directory, vegetation=True, **named):
    from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
    path = build_sample_tileset(str(directory))
    document = json.load(open(path))
    if vegetation:
        record = {'trees': 'trees.npz', 'species': _trees(directory, **named)}
        document.setdefault('extras', {})['vegetation'] = record
    json.dump(document, open(path, 'w'))
    return path


class TestMountingTheForest:
    def test_a_world_that_carries_one_gets_it(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            assert isinstance(terrain.vegetation, VegetationField)
            assert terrain.vegetation.tree_count == COUNT
        finally:
            terrain.shutdown()

    def test_a_world_without_one_has_none(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path, vegetation=False), workers=1)
        try:
            assert terrain.vegetation is None
        finally:
            terrain.shutdown()

    def test_the_species_files_are_found_beside_the_tileset(self, tmp_path) -> None:
        """A world is self-contained: its trees are its own files, not paths
        into whatever machine baked it."""
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            found = terrain.vegetation.species[0]
            assert found.mesh == os.path.join(str(tmp_path), 'kind0.npz')
            assert found.impostor == os.path.join(str(tmp_path), 'card0.png')
        finally:
            terrain.shutdown()

    def test_every_species_named_is_built(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path, kinds=3), workers=1)
        try:
            assert len(terrain.vegetation.species) == 3
        finally:
            terrain.shutdown()

    def test_the_forest_is_a_child_and_stays_one(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            terrain.update_for_camera(np.array([0.0, 200.0, 0.0]), 720.0)
            terrain.update_for_camera(np.array([90.0, 200.0, 90.0]), 720.0)
            assert terrain.vegetation in list(terrain.children)
        finally:
            terrain.shutdown()

    def test_streaming_moves_the_forest_with_the_camera(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            terrain.update_for_camera(np.array([0.0, 50.0, 0.0]), 720.0)
            chosen = terrain.vegetation.selections
            terrain.update_for_camera(np.array([600.0, 50.0, 600.0]), 720.0)
            assert terrain.vegetation.selections > chosen
        finally:
            terrain.shutdown()

    def test_it_can_be_turned_off(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1, vegetation=False)
        try:
            assert terrain.vegetation is None
        finally:
            terrain.shutdown()


class TestWhenItIsWrong:
    def test_a_record_naming_no_species_is_refused(self, tmp_path) -> None:
        path = _world(tmp_path)
        document = json.load(open(path))
        document['extras']['vegetation']['species'] = []
        json.dump(document, open(path, 'w'))
        with pytest.raises(ValueError):
            TilesTerrain(path, workers=1).shutdown()

    def test_a_record_whose_table_is_missing_is_reported(self, tmp_path) -> None:
        path = _world(tmp_path)
        os.remove(os.path.join(str(tmp_path), 'trees.npz'))
        with pytest.raises(Exception):
            TilesTerrain(path, workers=1).shutdown()


class TestWhichWayTheCameraLooks:
    """The cards are chosen in a cone about the view, so the heading taken from
    the view-projection has to be the one the camera actually has -- backwards
    and the forest is behind you."""

    def _facing(self, eye, look):
        from OpenGLContext.loaders.tiles3d.frustum import view_projection
        from OpenGLContext.scenegraph.tilesterrain import _facing
        return _facing(view_projection(eye, look, (0, 1, 0), 0.8, 1.6, 1.0, 5000.0))

    def test_it_points_where_the_camera_points(self) -> None:
        for eye, look in (((0, 0, 0), (100, 0, 0)),
                          ((10, 5, 10), (-90, 5, 10)),
                          ((0, 0, 0), (30, 0, 40)),
                          ((0, 0, 0), (0, 0, 100))):
            want = np.asarray(look, 'd') - np.asarray(eye, 'd')
            want /= np.linalg.norm(want)
            assert np.allclose(self._facing(eye, look), want, atol=1e-6)

    def test_no_matrix_is_no_heading(self) -> None:
        from OpenGLContext.scenegraph.tilesterrain import _facing
        assert _facing(None) is None

    def test_the_forest_faces_the_way_the_camera_does(self, tmp_path) -> None:
        from OpenGLContext.loaders.tiles3d.frustum import view_projection
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            eye = np.array([0.0, 30.0, 0.0])
            for look in ((0.0, 30.0, 900.0), (0.0, 30.0, -900.0)):
                terrain.update_for_camera(
                    eye, 720.0,
                    view_projection=view_projection(eye, look, (0, 1, 0),
                                                    0.8, 1.6, 1.0, 5000.0))
                drawn = np.concatenate([node.pos for node
                                        in terrain.vegetation.impostors])
                far = drawn[np.hypot(drawn[:, 0], drawn[:, 2]) > 300.0]
                assert len(far)
                assert np.sign(far[:, 2]).mean() == pytest.approx(
                    np.sign(look[2]), abs=0.1)
        finally:
            terrain.shutdown()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
