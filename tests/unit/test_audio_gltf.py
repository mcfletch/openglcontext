"""Reading ``KHR_audio_emitter`` out of a glTF document into the scenegraph.

The point of choosing a published extension rather than inventing a format is
that a scene authored in Blender or Godot arrives with its sound intact.  These
tests build documents by hand -- no sample assets, so nothing here depends on a
download -- and check what comes out the other end.
"""

import base64
import io
import json
import wave

import numpy as np
import pytest

from omi_audio import synth
from omi_audio.clip import decoder_available
from omi_audio.device import NullDevice
from omi_audio.engine import AudioEngine

from OpenGLContext.scenegraph import audio as audionodes

pygltflib = pytest.importorskip('pygltflib')

from OpenGLContext.loaders.gltf import loader          # noqa: E402

needs_decoder = pytest.mark.skipif(
    not decoder_available(),
    reason='miniaudio is not installed; embedded audio cannot be decoded')


@pytest.fixture
def engine():
    """An engine on a silent device, so a clip can be asked for and measured."""
    made = AudioEngine(device=NullDevice(sample_rate=8000), voices=4)
    try:
        yield made
    finally:
        made.close()


def wav_bytes(seconds=0.05, rate=8000):
    """A real ``.wav``, so the decode path under test is the real one."""
    samples = synth.tone(440.0, seconds, sample_rate=rate, fade=0.0).samples
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype('<i2')
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


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


class TestAudioInsideTheDocument:
    """A ``.glb`` embeds its audio in a buffer view, and that is the common case.

    A ``uri`` beside the document is the exception rather than the rule for
    shipped content, so an emitter whose audio has no name to open must still
    end up with samples.
    """

    def embedded(self, audio_entry, **buffers):
        """A document whose one source names ``audio_entry``."""
        wav = wav_bytes()
        body = {
            'nodes': [{'name': 'Speaker',
                       'extensions': {'KHR_audio_emitter': {'emitters': [0]}}}],
            'extensions': {'KHR_audio_emitter': {
                'emitters': [{'name': 'Fountain', 'type': 'positional',
                              'sources': [0]}],
                'sources': [{'name': 'Water', 'audio': 0, 'autoplay': True}],
                'audio': [audio_entry(wav)],
            }},
        }
        body.update(buffers)
        return document(**body), wav

    def buffer_view_document(self):
        wav = wav_bytes()
        encoded = base64.b64encode(wav).decode('ascii')
        return self.embedded(
            lambda data: {'bufferView': 0, 'mimeType': 'audio/wav'},
            buffers=[{'uri': 'data:application/octet-stream;base64,' + encoded,
                      'byteLength': len(wav)}],
            bufferViews=[{'buffer': 0, 'byteOffset': 0, 'byteLength': len(wav)}],
        )

    def test_a_source_backed_by_a_buffer_view_still_reaches_the_scenegraph(self):
        body, _ = self.buffer_view_document()
        scene = loader.load_gltf(body, base_url='http://example/scene.gltf')
        assert len(emitters_in(scene)) == 1
        assert len(emitters_in(scene)[0].sources) == 1

    @needs_decoder
    def test_the_buffer_views_audio_actually_decodes(self, engine):
        body, wav = self.buffer_view_document()
        scene = loader.load_gltf(body, base_url='http://example/scene.gltf')
        source = emitters_in(scene)[0].sources[0]
        clip = source.clip(engine)
        assert clip is not None, 'a .glb audio source produced no samples'
        assert clip.frames > 0

    @needs_decoder
    def test_a_data_uri_source_decodes_too(self, engine):
        """glTF permits the audio inline; the loader already unpacks images so."""
        wav = wav_bytes()
        encoded = base64.b64encode(wav).decode('ascii')
        body = dict(EMITTERS)
        body['nodes'] = [{'name': 'Speaker',
                          'extensions': {'KHR_audio_emitter': {'emitters': [0]}}}]
        block = json.loads(json.dumps(EMITTERS['extensions']['KHR_audio_emitter']))
        block['audio'] = [{'uri': 'data:audio/wav;base64,' + encoded}]
        block['sources'] = [{'name': 'Water', 'audio': 0, 'autoplay': True}]
        block['emitters'] = [{'name': 'Fountain', 'type': 'positional',
                              'sources': [0]}]
        body['extensions'] = {'KHR_audio_emitter': block}
        scene = loader.load_gltf(document(**body),
                                 base_url='http://example/scene.gltf')
        clip = emitters_in(scene)[0].sources[0].clip(engine)
        assert clip is not None and clip.frames > 0


class TestSceneEmittersMustBeGlobal:
    """The extension says a scene may reference only ``global`` emitters.

    A scene has no transform, so a positional emitter attached to one has no
    place to be heard from -- it would be built into the scenegraph as a sound
    with nowhere to come from.
    """

    def scene_naming(self, index):
        body = dict(EMITTERS)
        body['scenes'] = [{'nodes': [0],
                           'extensions': {'KHR_audio_emitter': {'emitters': [index]}}}]
        return loader.load_gltf(document(**body),
                                base_url='http://example/scene.gltf')

    def test_a_positional_emitter_on_a_scene_is_dropped(self):
        assert emitters_in(self.scene_naming(0)) == []

    def test_a_global_emitter_on_a_scene_is_kept(self):
        assert len(emitters_in(self.scene_naming(1))) == 1


class TestAudioThatWillNotResolve:
    """Content is not always well formed, and not always well meant.

    Every one of these costs the sound and nothing else: the scene still
    loads, the emitter is still there, and the source is simply silent.
    """

    def one_audio(self, entry, **extra):
        body = {
            'nodes': [{'name': 'Speaker',
                       'extensions': {'KHR_audio_emitter': {'emitters': [0]}}}],
            'extensions': {'KHR_audio_emitter': {
                'emitters': [{'type': 'positional', 'sources': [0]}],
                'sources': [{'audio': 0, 'autoplay': True}],
                'audio': [entry],
            }},
        }
        body.update(extra)
        return loader.load_gltf(document(**body),
                                base_url='http://example/assets/scene.gltf')

    def only_source(self, scene):
        emitters = emitters_in(scene)
        assert len(emitters) == 1
        assert len(emitters[0].sources) == 1
        return emitters[0].sources[0]

    def test_a_uri_the_document_may_not_reach_costs_the_sound_not_the_scene(self, engine):
        """Cross-origin is what the resolver exists to refuse; a hostile
        document must not be able to stop the scene from loading."""
        source = self.only_source(self.one_audio({'uri': 'http://evil.example/x.mp3'}))
        assert source.url == [], 'an out-of-bounds uri was recorded as a location'
        assert source.clip(engine) is None

    def test_an_entry_with_neither_uri_nor_buffer_view_is_a_silence(self, engine):
        source = self.only_source(self.one_audio({'mimeType': 'audio/mpeg'}))
        assert source.clip(engine) is None

    def test_a_buffer_view_index_that_points_at_nothing_is_a_silence(self, engine):
        source = self.only_source(
            self.one_audio({'bufferView': 7, 'mimeType': 'audio/wav'}))
        assert source.clip(engine) is None

    def test_asking_twice_does_not_look_twice(self, engine):
        """A missing sound must warn once, not once a frame."""
        source = self.only_source(self.one_audio({'mimeType': 'audio/mpeg'}))
        assert source.clip(engine) is None
        assert source.clip(engine) is None

    def test_a_document_with_no_scenes_still_loads(self):
        """`scenes` is optional, and the scene-level emitter lookup must cope."""
        body = dict(EMITTERS)
        body['nodes'] = [{'name': 'Speaker',
                          'extensions': {'KHR_audio_emitter': {'emitters': [0]}}}]
        body['scenes'] = []
        body.pop('scene', None)
        scene = loader.load_gltf(document(**body),
                                 base_url='http://example/scene.gltf')
        assert scene is not None


def test_every_emitter_in_a_document_shares_one_audio_library():
    """One document is one library, so a clip behind two emitters is fetched once."""
    body = dict(EMITTERS)
    body['nodes'] = [
        {'name': 'A', 'extensions': {'KHR_audio_emitter': {'emitters': [0]}}},
        {'name': 'B', 'extensions': {'KHR_audio_emitter': {'emitters': [0]}}},
    ]
    body['scenes'] = [{'nodes': [0, 1]}]
    scene = loader.load_gltf(document(**body), base_url='http://example/scene.gltf')
    emitters = emitters_in(scene)
    assert len(emitters) == 2
    libraries = {id(emitter.sources[0]._library) for emitter in emitters}
    assert len(libraries) == 1
