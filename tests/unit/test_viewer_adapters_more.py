"""OBJ and 3D Tiles through the same viewer
(:mod:`OpenGLContext.viewer.adapters`).

An OBJ is a model with no lights, no cameras and no sky; a 3D Tiles dataset is
larger than memory and arrives while you look at it.  Both come to the viewer as
the same kind of scene, and these check the parts of that claim which do not
need a window: what the adapter produces, what it says about itself, and -- for
the streaming one -- that its per-frame work reaches the runtime.
"""
import json

import pytest

from OpenGLContext.viewer.adapters import adapter_for, adapter_named
from OpenGLContext.viewer.adapters.obj import OBJAdapter

#: A unit cube, the smallest OBJ that exercises vertices and faces.
CUBE = """\
# a unit cube
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 1.0 1.0 0.0
v 0.0 1.0 0.0
v 0.0 0.0 1.0
v 1.0 0.0 1.0
v 1.0 1.0 1.0
v 0.0 1.0 1.0
f 1 2 3 4
f 5 6 7 8
f 1 2 6 5
f 3 4 8 7
f 1 4 8 5
f 2 3 7 6
"""


@pytest.fixture
def cube(tmp_path):
    path = tmp_path / 'cube.obj'
    path.write_text(CUBE)
    return str(path)


class TestTheOBJLoaderReadsAFile:
    """The parser split its lines as bytes and compared them against text, so
    it raised ``TypeError`` on the first line of every file it was ever given."""

    def test_a_real_obj_parses(self, cube):
        from OpenGLContext.loaders.loader import Loader
        assert Loader.load(cube).children

    def test_a_comment_is_skipped_rather_than_read_as_geometry(self, cube):
        from OpenGLContext.loaders.loader import Loader
        scene = Loader.load(cube)
        assert len(scene.children) == 1, 'one anonymous transform, not two'


class TestTheOBJAdapter:
    def test_an_obj_source_chooses_it(self):
        assert isinstance(adapter_for('model.obj'), OBJAdapter)
        assert isinstance(adapter_named('obj'), OBJAdapter)

    def test_it_loads_a_real_model(self, cube):
        scene = OBJAdapter().load(cube)
        assert scene.group.children
        assert scene.radius > 0

    def test_the_bounds_cover_the_geometry(self, cube):
        """A unit cube from the origin: centred on (0.5, 0.5, 0.5)."""
        scene = OBJAdapter().load(cube)
        assert scene.center == pytest.approx((0.5, 0.5, 0.5))
        assert scene.radius == pytest.approx(0.866, abs=0.01)

    def test_a_model_may_be_moved_to_the_middle_of_the_frame(self):
        """Unlike a world: an OBJ is an object, in coordinates of its own."""
        assert OBJAdapter.recentres is True

    def test_it_carries_no_cameras_of_its_own(self, cube):
        """The format has none, so the viewer auto-frames instead."""
        scene = OBJAdapter().load(cube)
        assert scene.viewpoints == []
        assert scene.cameras == []


class TestTheTilesAdapter:
    """Chosen by content as well as by name, since a tileset is any ``.json``."""

    @pytest.fixture
    def tileset(self, tmp_path):
        path = tmp_path / 'tileset.json'
        path.write_text(json.dumps({
            'asset': {'version': '1.0'},
            'geometricError': 100.0,
            'root': {'boundingVolume': {'box': [0, 0, 0, 8, 0, 0,
                                                0, 8, 0, 0, 0, 8]},
                     'geometricError': 0.0, 'refine': 'REPLACE'},
        }))
        return str(path)

    def test_the_conventional_name_chooses_it(self, tileset):
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        assert isinstance(adapter_for(tileset), TilesAdapter)

    def test_a_tileset_under_any_name_is_recognised_by_its_content(self, tmp_path):
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        odd = tmp_path / 'new_york.json'
        odd.write_text(json.dumps({'asset': {'version': '1.0'},
                                   'root': {'geometricError': 0.0}}))
        assert isinstance(adapter_for(str(odd)), TilesAdapter)

    def test_some_other_json_is_not_a_tileset(self, tmp_path):
        from OpenGLContext.viewer.adapters import UnknownSourceType
        other = tmp_path / 'config.json'
        other.write_text('{"colour": "blue"}')
        with pytest.raises(UnknownSourceType):
            adapter_for(str(other))

    def test_a_dataset_is_shown_where_it_is(self, tileset):
        """Its coordinates are the world's; there is no 'middle' to move it to."""
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        assert TilesAdapter.recentres is False

    def test_it_loads_a_real_tileset(self, tileset):
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        scene = TilesAdapter().load(tileset)
        assert scene.group is not None
        assert scene.radius > 0, 'framed from the root bounding volume'

    def test_streaming_is_asked_for_every_frame(self, tileset):
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        adapter = TilesAdapter()
        adapter.load(tileset)
        asked = []
        adapter.terrain.update_for_camera = (
            lambda eye, height, view_projection=None: asked.append(eye))
        assert adapter.update(_Viewer()) is True
        assert asked, 'the runtime was told where the camera is'

    def test_nothing_loaded_means_nothing_to_stream(self):
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        assert TilesAdapter().update(_Viewer()) is False

    def test_the_runtime_is_shut_down_with_the_viewer(self, tileset):
        """It owns worker threads; leaving them is how a viewer fails to exit."""
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        adapter = TilesAdapter()
        adapter.load(tileset)
        stopped = []
        adapter.terrain.shutdown = lambda: stopped.append(True)
        adapter.shutdown()
        assert stopped == [True]

    def test_shutting_down_before_loading_is_harmless(self):
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        TilesAdapter().shutdown()


class TestAimingAtRealGeometry:
    """Framing on the bounding volume alone can aim at nothing.

    A tileset's root bounding volume says how *big* it is; its centre is not
    necessarily anywhere near the mesh.  The first tile that actually carries
    content gives an aim point that lands on geometry, and it is trusted only
    when it sits inside the extent -- otherwise a mis-transformed tile would
    throw the camera across the world.
    """

    @staticmethod
    def _root(center, radius, **named):
        import types
        return types.SimpleNamespace(
            bounding_volume=types.SimpleNamespace(
                bounding_sphere=lambda: (center, radius)),
            **named)

    @staticmethod
    def _leaf(center):
        import numpy as np
        import types
        return types.SimpleNamespace(
            content_uri='leaf.glb', children=[],
            world_transform=np.eye(4),
            _scene=types.SimpleNamespace(center=center))

    def test_it_descends_to_the_first_tile_with_content(self):
        import types
        from OpenGLContext.viewer.adapters.tiles import leaf_tile
        leaf = types.SimpleNamespace(content_uri='c.glb', children=[])
        middle = types.SimpleNamespace(content_uri=None, children=[leaf])
        root = types.SimpleNamespace(content_uri=None, children=[middle])
        assert leaf_tile(root) is leaf

    def test_a_tile_that_has_content_is_the_answer(self):
        import types
        from OpenGLContext.viewer.adapters.tiles import leaf_tile
        root = types.SimpleNamespace(content_uri='root.glb', children=[])
        assert leaf_tile(root) is root

    def test_a_childless_tile_is_the_answer(self):
        import types
        from OpenGLContext.viewer.adapters.tiles import leaf_tile
        root = types.SimpleNamespace(content_uri=None, children=[])
        assert leaf_tile(root) is root

    def test_the_aim_moves_onto_the_mesh(self):
        """A grouping root with the geometry a level below it: the usual shape."""
        import numpy as np
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        leaf = self._leaf((2.0, 0.0, 1.0))
        root = self._root((0.0, 0.0, 0.0), 10.0,
                          content_uri=None, children=[leaf])
        center, radius = TilesAdapter().boundsOf(
            root, lambda tile: (tile._scene, None))
        assert np.allclose(center, [2.0, 0.0, 1.0])
        assert radius == 10.0

    def test_an_aim_outside_the_extent_is_refused(self):
        import numpy as np
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        adapter = TilesAdapter()
        leaf = self._leaf((100.0, 0.0, 0.0))
        root = self._root((0.0, 0.0, 0.0), 1.0,
                          content_uri=None, children=[leaf])
        center, _ = adapter.boundsOf(root, lambda tile: (tile._scene, None))
        assert np.allclose(center, [0.0, 0.0, 0.0])

    def test_a_tile_that_will_not_load_leaves_the_bounding_centre(self):
        import numpy as np
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter

        def explode(tile):
            raise IOError('no such tile')
        adapter = TilesAdapter()
        root = self._root((3.0, 0.0, 0.0), 5.0, content_uri='c.glb', children=[])
        center, radius = adapter.boundsOf(root, explode)
        assert np.allclose(center, [3.0, 0.0, 0.0])
        assert radius == 5.0

    def test_a_tileset_with_no_extent_still_frames(self):
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        root = self._root((0.0, 0.0, 0.0), 0.0, content_uri=None, children=[])
        _center, radius = TilesAdapter().boundsOf(root, lambda tile: (None, None))
        assert radius == 1.0


class TestTuningAStream:
    """A streaming dataset has knobs the others do not, and they must reach it.

    ``oglc-tiles`` offered them; ``oglc-view tileset.json`` has to, or moving to
    the one viewer costs a user the controls they had.
    """

    def test_the_options_reach_the_adapter(self):
        from OpenGLContext.viewer.adapters.tiles import TilesAdapter
        from OpenGLContext.viewer.options import ViewerOptions
        adapter = TilesAdapter()
        adapter.configure(ViewerOptions(sse=4.0, memory=128, no_recenter=True,
                                        cache_dir='/tmp/tiles'))
        assert adapter.sse == 4.0
        assert adapter.memory == 128 * 1024 * 1024
        assert adapter.recenter is False
        assert adapter.cacheDirectory == '/tmp/tiles'

    def test_options_it_was_not_given_leave_the_defaults(self):
        from OpenGLContext.viewer.adapters.tiles import (
            DEFAULT_MEMORY, DEFAULT_SSE, TilesAdapter,
        )
        from OpenGLContext.viewer.options import ViewerOptions
        adapter = TilesAdapter()
        adapter.configure(ViewerOptions())
        assert adapter.sse == DEFAULT_SSE
        assert adapter.memory == DEFAULT_MEMORY
        assert adapter.recenter is True

    def test_every_adapter_can_be_configured_even_if_it_ignores_it(self):
        """The viewer offers its options to whichever adapter it picked."""
        from OpenGLContext.viewer.adapters.gltf import GLTFAdapter
        from OpenGLContext.viewer.options import ViewerOptions
        GLTFAdapter().configure(ViewerOptions())


class _Viewer:
    """The little of a viewer a streaming adapter reads: where and how big."""

    class _Platform:
        position = (0.0, 10.0, 40.0)
        quaternion = None

    platform = _Platform()
    radius = 10.0

    def getViewPort(self):
        return (800, 600)
