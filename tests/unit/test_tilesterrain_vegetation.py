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


def _landscape(directory, **named):
    """A world with a field terrain *and* a forest standing on it."""
    from OpenGLContext.scenegraph.terrain import (
        HeightField, LayerRule, control_map,
    )
    path = _world(directory, **named)
    document = json.load(open(path))
    document.setdefault('extras', {})
    field = HeightField.from_function(
        lambda x, z: np.zeros(np.shape(np.asarray(x))), res=33, extent=2048.0)
    field.save_image(os.path.join(str(directory), 'g-height.png'))
    control_map(field, [LayerRule()], size=32).save(
        os.path.join(str(directory), 'g-control.png'))
    document['extras']['terrain'] = {
        'height': 'g-height.png', 'control': 'g-control.png',
        'extent': 2048.0, 'base': field.base, 'relief': max(field.relief, 1.0),
        'resolution': 33, 'layers': ['grass'],
    }
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


class TestTheForestShadesTheGroundUnderIt:
    """A splat terrain bakes a canopy term into its static shading, and a world
    that carries both a landscape and a forest knows where the trees are. Left
    unwired the ground under a wood is lit like an open field, which is most of
    why a forest reads as trees standing on a lawn."""

    def _both(self, directory, **named):
        return _landscape(directory, **named)

    def test_the_ground_is_told_where_the_trees_are(self, tmp_path) -> None:
        terrain = TilesTerrain(self._both(tmp_path), workers=1)
        try:
            assert terrain.ground.canopy is not None
            assert len(terrain.ground.canopy) == COUNT
        finally:
            terrain.shutdown()

    def test_it_is_the_forest_s_own_trunks(self, tmp_path) -> None:
        terrain = TilesTerrain(self._both(tmp_path), workers=1)
        try:
            assert np.allclose(terrain.ground.canopy,
                               terrain.vegetation.positions)
        finally:
            terrain.shutdown()

    def test_a_world_with_no_forest_shades_nothing(self, tmp_path) -> None:
        terrain = TilesTerrain(self._both(tmp_path, vegetation=False), workers=1)
        try:
            assert terrain.ground is not None
            assert terrain.ground.canopy is None
        finally:
            terrain.shutdown()

    def test_a_world_with_no_landscape_is_not_an_error(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            assert terrain.ground is None
            assert terrain.vegetation is not None
        finally:
            terrain.shutdown()


class TestTheGroundCoverAWorldCarries:
    """A world that names ground cover gets it, growing where its own splat
    control map says the grass is -- which is also where the road is not."""

    def _covered(self, directory, cover=True, **named):
        import json

        from OpenGLContext.scenegraph.terrain import (
            HeightField, LayerRule, control_map,
        )
        path = _world(directory, **named)
        document = json.load(open(path))
        document.setdefault('extras', {})
        field = HeightField.from_function(
            lambda x, z: np.zeros(np.shape(np.asarray(x))), res=33,
            extent=2048.0)
        field.save_image(os.path.join(str(directory), 'g-height.png'))
        control_map(field, [LayerRule(), LayerRule(weight=0.0)], size=32).save(
            os.path.join(str(directory), 'g-control.png'))
        document['extras']['terrain'] = {
            'height': 'g-height.png', 'control': 'g-control.png',
            'extent': 2048.0, 'base': field.base, 'relief': max(field.relief, 1.0),
            'resolution': 33, 'layers': ['grass', 'dirt'],
        }
        if cover:
            document['extras']['vegetation']['cover'] = {
                'name': 'grass', 'card': 'blade.png', 'clump': None,
                'density': 1.5, 'height': 0.5, 'on': ['grass'],
            }
        json.dump(document, open(path, 'w'))
        return path

    def test_a_world_that_names_it_gets_it(self, tmp_path) -> None:
        terrain = TilesTerrain(self._covered(tmp_path), workers=1)
        try:
            assert terrain.cover is not None
            assert terrain.cover.species.card.endswith('blade.png')
        finally:
            terrain.shutdown()

    def test_a_world_that_does_not_has_none(self, tmp_path) -> None:
        terrain = TilesTerrain(self._covered(tmp_path, cover=False), workers=1)
        try:
            assert terrain.cover is None
        finally:
            terrain.shutdown()

    def test_it_needs_a_landscape_to_grow_on(self, tmp_path) -> None:
        """Cover sits on a height field; a world whose ground is tiles has
        none to sit on."""
        import json
        path = _world(tmp_path)
        document = json.load(open(path))
        document['extras']['vegetation']['cover'] = {
            'name': 'grass', 'card': 'blade.png'}
        json.dump(document, open(path, 'w'))
        terrain = TilesTerrain(path, workers=1)
        try:
            assert terrain.cover is None
        finally:
            terrain.shutdown()

    def test_it_grows_where_the_control_map_says_grass(self, tmp_path) -> None:
        terrain = TilesTerrain(self._covered(tmp_path), workers=1)
        try:
            assert terrain.cover.mask is not None
            assert float(terrain.cover.mask(np.array([0.0]),
                                            np.array([0.0]))[0]) > 0.9
        finally:
            terrain.shutdown()

    def test_streaming_moves_it_with_the_camera(self, tmp_path) -> None:
        terrain = TilesTerrain(self._covered(tmp_path), workers=1)
        try:
            terrain.update_for_camera(np.array([0.0, 2.0, 0.0]), 720.0)
            chosen = terrain.cover.selections
            terrain.update_for_camera(np.array([300.0, 2.0, 0.0]), 720.0)
            assert terrain.cover.selections > chosen
        finally:
            terrain.shutdown()

    def test_it_is_drawn(self, tmp_path) -> None:
        terrain = TilesTerrain(self._covered(tmp_path), workers=1)
        try:
            assert terrain.cover in list(terrain.children)
        finally:
            terrain.shutdown()


class TestTheForestIsLitByTheGroundItStandsOn:
    """One world, one answer about where the light is.

    The terrain works out the canopy's shade from the trunks it is given; the
    trees, the grass and the ground then all read that same figure, so a
    clearing and a forest floor differ for every one of them at once.
    """

    def test_the_trees_are_told_how_much_sun_they_stand_in(self, tmp_path) -> None:
        terrain = TilesTerrain(_landscape(tmp_path), workers=1)
        try:
            assert terrain.vegetation.shades is not None
            assert len(terrain.vegetation.shades) == COUNT
        finally:
            terrain.shutdown()

    def test_it_is_the_ground_s_own_answer(self, tmp_path) -> None:
        terrain = TilesTerrain(_landscape(tmp_path), workers=1)
        try:
            trees = terrain.vegetation.positions
            assert np.allclose(
                terrain.vegetation.shades,
                terrain.ground.shade(trees[:, 0], trees[:, 2]), atol=1e-6)
        finally:
            terrain.shutdown()

    def test_a_forest_with_no_landscape_stands_in_full_sun(self, tmp_path) -> None:
        terrain = TilesTerrain(_world(tmp_path), workers=1)
        try:
            assert terrain.vegetation.shades is None
        finally:
            terrain.shutdown()
