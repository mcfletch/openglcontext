"""Reading ``KHR_audio_emitter`` out of a glTF document into the scenegraph.

The point of choosing a published extension rather than inventing a format is
that a scene authored in Blender or Godot arrives with its sound intact.  These
tests build documents by hand -- no sample assets, so nothing here depends on a
download -- and check what comes out the other end.
"""

import json

import pytest

from OpenGLContext.scenegraph import audio as audionodes

pygltflib = pytest.importorskip('pygltflib')

from OpenGLContext.loaders.gltf import loader          # noqa: E402


def document(**extension):
    """A minimal valid glTF carrying a ``KHR_audio_emitter`` block."""
    body = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['KHR_audio_emitter'],
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'name': 'Speaker', 'translation': [1.0, 2.0, 3.0]}],
    }
    body.update(extension)
    return json.dumps(body).encode('utf-8')


EMITTERS = {
    'extensions': {
        'KHR_audio_emitter': {
            'emitters': [
                {'name': 'Fountain', 'type': 'positional', 'gain': 0.8,
                 'sources': [0],
                 'positional': {'distanceModel': 'linear', 'maxDistance': 25.0,
                                'refDistance': 2.0, 'rolloffFactor': 0.9}},
                {'name': 'Music', 'type': 'global', 'gain': 0.4, 'sources': [1]},
            ],
            'sources': [
                {'name': 'Water', 'audio': 0, 'loop': True, 'autoplay': True,
                 'gain': 0.7},
                {'name': 'Theme', 'audio': 1, 'loop': True, 'autoplay': True},
            ],
            'audio': [{'uri': 'water.ogg'}, {'uri': 'theme.mp3'}],
        }
    }
}


def emitters_in(scene):
    """Every :class:`AudioEmitter` node anywhere under ``scene``."""
    found = []
    todo = [scene.sceneGraph]
    while todo:
        node = todo.pop()
        if isinstance(node, audionodes.AudioEmitter):
            found.append(node)
        todo.extend(getattr(node, 'children', None) or [])
    return found


class TestNodeEmitters:
    def test_a_node_with_an_emitter_gets_one_in_the_scenegraph(self):
        body = dict(EMITTERS)
        body['nodes'] = [{'name': 'Speaker', 'translation': [1.0, 2.0, 3.0],
                          'extensions': {'KHR_audio_emitter': {'emitters': [0]}}}]
        scene = loader.load_gltf(document(**body), base_url='http://example/scene.gltf')
        assert len(emitters_in(scene)) == 1

    def test_the_emitters_settings_survive_the_trip(self):
        body = dict(EMITTERS)
        body['nodes'] = [{'name': 'Speaker',
                          'extensions': {'KHR_audio_emitter': {'emitters': [0]}}}]
        scene = loader.load_gltf(document(**body), base_url='http://example/scene.gltf')
        emitter = emitters_in(scene)[0]
        assert emitter.gain == pytest.approx(0.8)
        assert emitter.distanceModel == 'linear'
        assert emitter.maxDistance == pytest.approx(25.0)
        assert emitter.refDistance == pytest.approx(2.0)

    def test_the_source_settings_survive_the_trip(self):
        body = dict(EMITTERS)
        body['nodes'] = [{'name': 'Speaker',
                          'extensions': {'KHR_audio_emitter': {'emitters': [0]}}}]
        scene = loader.load_gltf(document(**body), base_url='http://example/scene.gltf')
        source = emitters_in(scene)[0].sources[0]
        assert source.gain == pytest.approx(0.7)
        assert source.loop
        assert source.url[0].endswith('water.ogg')

    def test_the_audio_uri_is_resolved_against_the_documents_own_location(self):
        body = dict(EMITTERS)
        body['nodes'] = [{'name': 'Speaker',
                          'extensions': {'KHR_audio_emitter': {'emitters': [0]}}}]
        scene = loader.load_gltf(document(**body),
                                 base_url='http://example/assets/scene.gltf')
        assert emitters_in(scene)[0].sources[0].url[0] == \
            'http://example/assets/water.ogg'

    def test_an_emitter_index_out_of_range_is_ignored(self):
        body = dict(EMITTERS)
        body['nodes'] = [{'name': 'Speaker',
                          'extensions': {'KHR_audio_emitter': {'emitters': [7]}}}]
        scene = loader.load_gltf(document(**body), base_url='http://example/scene.gltf')
        assert emitters_in(scene) == []

    def test_a_document_without_the_extension_gains_nothing(self):
        scene = loader.load_gltf(document(), base_url='http://example/scene.gltf')
        assert emitters_in(scene) == []


class TestSceneEmitters:
    def test_a_scene_level_global_emitter_lands_at_the_root(self):
        body = dict(EMITTERS)
        body['scenes'] = [{'nodes': [0],
                           'extensions': {'KHR_audio_emitter': {'emitters': [1]}}}]
        scene = loader.load_gltf(document(**body), base_url='http://example/scene.gltf')
        emitters = emitters_in(scene)
        assert len(emitters) == 1
        assert emitters[0].type == 'global'
        assert emitters[0].gain == pytest.approx(0.4)
