"""Choosing how to open a source, and opening it
(:mod:`OpenGLContext.viewer.adapters`).

The viewer knows how to *show* a scene and nothing about file formats; an
adapter knows one format and nothing about showing.  These check the join: that
a source picks the right adapter by suffix, content type or content, that an
unrecognised one says what it does know, and that each adapter produces the same
shape of scene from a real file on disk.
"""
import os

import pytest

from OpenGLContext.scenegraph.viewpoint import Viewpoint
from OpenGLContext.testing.paths import tests_root
from OpenGLContext.viewer.adapters import (
    SceneAdapter, UnknownSourceType, ViewerScene, adapter_for, adapter_named,
    known_sources,
)
from OpenGLContext.viewer.adapters.gltf import GLTFAdapter
from OpenGLContext.viewer.adapters.vrml import VRMLAdapter

WRLS = os.path.join(str(tests_root(__file__)), 'wrls')
GLTF_MODEL = os.path.join(WRLS, 'instanced_lattice.gltf')
VRML_MODEL = os.path.join(WRLS, '3shapes.wrl')
VRML_CAMERAS = os.path.join(WRLS, 'viewpoints.wrl')


class TestChoosingAnAdapter:
    """A source names its own format, one way or another."""

    @pytest.mark.parametrize('source', [
        'model.gltf', 'model.glb', 'MODEL.GLB', '/a/b/c.gltf',
        'https://example.com/x/model.glb',
        'https://example.com/model.glb?token=abc',
    ])
    def test_gltf_suffixes_choose_the_gltf_adapter(self, source):
        assert isinstance(adapter_for(source), GLTFAdapter)

    @pytest.mark.parametrize('source', [
        'scene.wrl', 'scene.WRL', 'scene.wrz', 'scene.vrml', 'scene.wrl.gz',
        'https://example.com/world.wrl',
    ])
    def test_vrml_suffixes_choose_the_vrml_adapter(self, source):
        assert isinstance(adapter_for(source), VRMLAdapter)

    def test_a_content_type_decides_when_the_name_cannot(self):
        """A served resource is named by its type, not by a suffix."""
        assert isinstance(adapter_for('/download', contentType='model/gltf-binary'),
                          GLTFAdapter)
        assert isinstance(adapter_for('/download', contentType='model/vrml'),
                          VRMLAdapter)

    def test_a_content_type_with_parameters_still_matches(self):
        assert isinstance(
            adapter_for('/download', contentType='model/vrml; charset=utf-8'),
            VRMLAdapter)

    def test_an_unknown_source_says_what_it_does_know(self):
        with pytest.raises(UnknownSourceType) as raised:
            adapter_for('holiday.jpg')
        message = str(raised.value)
        assert 'holiday.jpg' in message
        assert '.glb' in message and '.wrl' in message

    def test_adapters_are_reachable_by_name(self):
        assert isinstance(adapter_named('gltf'), GLTFAdapter)
        assert isinstance(adapter_named('vrml97'), VRMLAdapter)

    def test_an_unknown_name_is_an_error_not_a_silent_none(self):
        with pytest.raises(UnknownSourceType):
            adapter_named('postscript')

    def test_known_sources_lists_every_registered_key(self):
        known = known_sources()
        assert '.glb' in known and '.wrl' in known
        assert known == tuple(sorted(known)), "listed for a human to read"

    def test_each_call_gets_its_own_adapter(self):
        """An adapter may hold per-scene state, so it is not a singleton."""
        assert adapter_for('a.glb') is not adapter_for('b.glb')

    def test_the_longest_matching_key_wins(self):
        """``tileset.json`` has to beat ``.json``, whatever the registry order."""
        from OpenGLContext import plugins

        class Broad(SceneAdapter):
            name = 'broad'

        class Narrow(SceneAdapter):
            name = 'narrow'

        registered = [
            plugins.Adapter('test-broad', 'nowhere.Broad', ['.json']),
            plugins.Adapter('test-narrow', 'nowhere.Narrow', ['tileset.json']),
        ]
        for entry, cls in zip(registered, (Broad, Narrow), strict=True):
            entry.load = lambda cls=cls: cls
        try:
            assert isinstance(adapter_for('/data/tileset.json'), Narrow)
            assert isinstance(adapter_for('/data/other.json'), Broad)
        finally:
            for entry in registered:
                plugins.Adapter.registry.remove(entry)


class TestTheGLTFAdapter:
    def test_it_loads_a_real_model(self):
        scene = GLTFAdapter().load(GLTF_MODEL)
        assert scene.radius > 0
        assert scene.group is not None

    def test_a_model_may_be_moved_to_the_origin_to_be_framed(self):
        """An asset's coordinates are arbitrary, so centring it is free."""
        assert GLTFAdapter.recentres is True


class TestTheVRMLAdapter:
    def test_it_loads_a_real_world(self):
        scene = VRMLAdapter().load(VRML_MODEL)
        assert scene.radius > 0, "a framing radius, computed from the geometry"
        assert scene.group.children, "the world's nodes hang from the group"

    def test_the_radius_covers_the_geometry(self):
        """3shapes.wrl is a metre-ish pile of primitives near the origin."""
        scene = VRMLAdapter().load(VRML_MODEL)
        assert 1.0 < scene.radius < 4.0, scene.radius
        assert abs(scene.center[1] - 1.04) < 0.2, scene.center

    def test_a_world_is_shown_where_it_was_authored(self):
        """Its ground is at y=0 and its coordinates mean something."""
        assert VRMLAdapter.recentres is False

    def test_the_worlds_own_viewpoints_become_cameras(self):
        scene = VRMLAdapter().load(VRML_CAMERAS)
        assert len(scene.viewpoints) == 5
        assert all(isinstance(v, Viewpoint) for v in scene.viewpoints)
        assert [c['name'] for c in scene.cameras][:2] == ['cam1', 'cam02']

    def test_viewpoints_are_not_left_in_the_group_as_well(self):
        """Mounted twice, binding one would fight the copy under the model."""
        scene = VRMLAdapter().load(VRML_CAMERAS)
        assert not [c for c in scene.group.children if isinstance(c, Viewpoint)]

    def test_a_world_without_viewpoints_offers_no_cameras(self):
        scene = VRMLAdapter().load(VRML_MODEL)
        assert scene.viewpoints == []
        assert scene.cameras == []

    def test_the_worlds_own_background_and_lights_are_kept(self):
        """3shapes.wrl lights itself; the viewer must not rig over the top."""
        from OpenGLContext.scenegraph.background import Background
        from OpenGLContext.viewer.environment import count_lights
        scene = VRMLAdapter().load(VRML_MODEL)
        assert count_lights(scene.group) == 2
        assert [c for c in scene.group.children if isinstance(c, Background)]

    def test_a_world_has_no_animations_to_offer(self):
        scene = VRMLAdapter().load(VRML_MODEL)
        assert scene.animations == []
        assert scene.player() is None

    def test_a_world_with_no_geometry_still_frames(self, tmp_path):
        """Nothing measurable must give a usable radius, not a division by it."""
        world = tmp_path / 'sky_only.wrl'
        world.write_text('#VRML V2.0 utf8\n'
                         'Background { skyColor [ 0 0 0.5 ] }\n')
        scene = VRMLAdapter().load(str(world))
        assert scene.radius > 0
        assert scene.center == (0.0, 0.0, 0.0)


class TestTheSceneShape:
    """Every adapter answers the same questions, so the viewer asks once."""

    ATTRIBUTES = ('group', 'center', 'radius', 'viewpoints', 'cameras',
                  'animations', 'exposure')

    @pytest.mark.parametrize('adapter, source', [
        (GLTFAdapter, GLTF_MODEL),
        (VRMLAdapter, VRML_MODEL),
    ])
    def test_every_adapter_answers_the_same_questions(self, adapter, source):
        scene = adapter().load(source)
        for name in self.ATTRIBUTES:
            assert hasattr(scene, name), name
        assert callable(scene.player)

    def test_a_bare_scene_is_framed_at_the_origin(self):
        scene = ViewerScene(group=None)
        assert scene.center == (0.0, 0.0, 0.0)
        assert scene.radius == 1.0
        assert scene.exposure == 1.0
        assert scene.player(0) is None
