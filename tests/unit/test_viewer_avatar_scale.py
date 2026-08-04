"""How big a person is in the world the viewer opened
(:mod:`OpenGLContext.viewer.sceneviewer`).

A model arrives in units nobody declared, so the avatar is sized against it --
a bolt and a cathedral both get someone who can walk around them. A geospatial
dataset is not like that: 3D Tiles places its content in metres, so the person
is 1.8 m however many kilometres across the dataset is. Sized off the extent
instead, walking a city spawns a 300-metre giant standing above the rooftops,
which is what "it will not let me drop down and explore" looks like.
"""
import pytest

from OpenGLContext.viewer import ViewerOptions
from OpenGLContext.viewer.adapters.base import ViewerScene
from OpenGLContext.viewer.sceneviewer import ViewerContext


def _viewer(scene=None):
    viewer = ViewerContext.__new__(ViewerContext)
    viewer.options = ViewerOptions(source='x.glb')
    if scene is not None:
        viewer.scene = scene
    return viewer


class TestAvatarScale:
    def test_a_model_sizes_the_avatar_against_itself(self):
        """Unchanged for every scene that does not declare its units."""
        viewer = _viewer(ViewerScene(group=None))
        assert viewer.physicsAvatarScale((0, 0, 0), (40, 40, 40)) == pytest.approx(1.0)
        assert viewer.physicsAvatarScale((0, 0, 0), (400, 40, 40)) == pytest.approx(10.0)

    def test_a_scene_in_metres_gets_a_person(self):
        viewer = _viewer(ViewerScene(group=None, metric=True))
        assert viewer.physicsAvatarScale((-6000, 0, -6000), (6000, 550, 6000)) \
            == pytest.approx(1.0)

    def test_no_scene_at_all_still_answers(self):
        assert _viewer().physicsAvatarScale((0, 0, 0), (80, 80, 80)) == pytest.approx(2.0)


class TestTheTilesAdapterDeclaresIt:
    def test_a_geospatial_tileset_is_metric(self, tmp_path):
        """An Earth-centred tileset is in metres by specification."""
        import json
        import math
        from OpenGLContext.loaders.tiles3d.boundingvolume import geodetic_to_ecef
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter

        origin = geodetic_to_ecef(-1.3856, 0.7617, 0.0)
        matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, *origin, 1]
        (tmp_path / 'tileset.json').write_text(json.dumps({
            'asset': {'version': '1.1'},
            'geometricError': 100.0,
            'root': {
                'boundingVolume': {'box': [0, 0, 0, 300, 0, 0, 0, 300, 0, 0, 0, 40]},
                'geometricError': 0.0,
                'transform': matrix,
            },
        }))
        adapter = TilesAdapter()
        try:
            scene = adapter.load(str(tmp_path / 'tileset.json'))
            assert scene.metric is True
        finally:
            adapter.shutdown()

    def test_a_local_tileset_is_left_undeclared(self, tmp_path):
        """A tileset that is not on the globe is in units of its own."""
        import json
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter

        (tmp_path / 'tileset.json').write_text(json.dumps({
            'asset': {'version': '1.1'},
            'geometricError': 100.0,
            'root': {
                'boundingVolume': {'box': [0, 0, 0, 300, 0, 0, 0, 300, 0, 0, 0, 40]},
                'geometricError': 0.0,
            },
        }))
        adapter = TilesAdapter()
        try:
            assert adapter.load(str(tmp_path / 'tileset.json')).metric is False
        finally:
            adapter.shutdown()
