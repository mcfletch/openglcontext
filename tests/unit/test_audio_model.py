"""The ``KHR_audio_emitter`` data model, and reading it out of a glTF document."""

import math

import pytest

from OpenGLContext.audio import model, spatial


TAU = 2.0 * math.pi


class TestDefaults:
    """Every default is the one the extension writes down."""

    def test_audio_source_defaults(self):
        source = model.AudioSource()
        assert source.gain == 1.0
        assert source.playbackRate == 1.0
        assert source.loop is False
        assert source.autoplay is False
        assert source.audio is None

    def test_emitter_defaults(self):
        emitter = model.AudioEmitter()
        assert emitter.type == 'positional'
        assert emitter.gain == 1.0
        assert emitter.sources == []

    def test_positional_defaults(self):
        positional = model.PositionalProperties()
        assert positional.shapeType == 'omnidirectional'
        assert positional.coneInnerAngle == pytest.approx(TAU)
        assert positional.coneOuterAngle == pytest.approx(TAU)
        assert positional.coneOuterGain == 0.0
        assert positional.distanceModel == 'inverse'
        assert positional.maxDistance == 0.0
        assert positional.refDistance == 1.0
        assert positional.rolloffFactor == 1.0

    def test_a_positional_emitter_gets_default_positional_properties(self):
        """Nothing downstream should have to test for a missing sub-object."""
        assert model.AudioEmitter().positional == model.PositionalProperties()


class TestPositionalGain:
    """Distance and cone combined, which is what an emitter is asked for."""

    def test_omnidirectional_emitter_ignores_the_angle(self):
        positional = model.PositionalProperties(shapeType='omnidirectional',
                                                coneInnerAngle=0.1,
                                                coneOuterAngle=0.2,
                                                coneOuterGain=0.0)
        assert positional.gain(1.0, math.pi) == pytest.approx(1.0)

    def test_cone_emitter_applies_the_cone(self):
        positional = model.PositionalProperties(shapeType='cone',
                                                coneInnerAngle=math.pi / 2,
                                                coneOuterAngle=math.pi,
                                                coneOuterGain=0.0)
        assert positional.gain(1.0, math.pi) == pytest.approx(0.0)
        assert positional.gain(1.0, 0.0) == pytest.approx(1.0)

    def test_distance_and_cone_multiply(self):
        positional = model.PositionalProperties(shapeType='cone',
                                                coneInnerAngle=0.0,
                                                coneOuterAngle=math.pi,
                                                coneOuterGain=0.0)
        distance_only = spatial.distance_gain(2.0, 'inverse', ref_distance=1.0)
        cone_only = spatial.cone_gain(math.pi / 4, 0.0, math.pi, 0.0)
        assert positional.gain(2.0, math.pi / 4) == pytest.approx(
            distance_only * cone_only)


class TestGlobalEmitters:
    """A global emitter is heard the same wherever the listener stands."""

    def test_global_emitter_has_no_positional_properties(self):
        assert model.AudioEmitter(type='global').positional is None

    def test_global_emitter_is_not_positional(self):
        assert model.AudioEmitter(type='global').positional_audio is False
        assert model.AudioEmitter(type='positional').positional_audio is True


class TestFromGltf:
    """Reading the extension block a glTF document carries."""

    DOCUMENT = {
        'emitters': [
            {'name': 'Positional Emitter', 'type': 'positional', 'gain': 0.8,
             'sources': [0, 1],
             'positional': {'shapeType': 'cone', 'distanceModel': 'linear',
                            'maxDistance': 10.0, 'refDistance': 1.0,
                            'rolloffFactor': 0.8, 'coneInnerAngle': 1.0,
                            'coneOuterAngle': 2.0, 'coneOuterGain': 0.1}},
            {'name': 'Global Emitter', 'type': 'global', 'gain': 0.5,
             'sources': [1]},
        ],
        'sources': [
            {'name': 'Clip 1', 'gain': 0.6, 'autoplay': True, 'loop': True,
             'audio': 0},
            {'name': 'Clip 2', 'audio': 1, 'playbackRate': 2.0},
        ],
        'audio': [
            {'uri': 'audio1.mp3'},
            {'bufferView': 0, 'mimeType': 'audio/mpeg'},
        ],
    }

    def test_reads_every_array(self):
        document = model.from_gltf(self.DOCUMENT)
        assert len(document.emitters) == 2
        assert len(document.sources) == 2
        assert len(document.audio) == 2

    def test_reads_emitter_fields(self):
        emitter = model.from_gltf(self.DOCUMENT).emitters[0]
        assert emitter.name == 'Positional Emitter'
        assert emitter.gain == pytest.approx(0.8)
        assert emitter.sources == [0, 1]
        assert emitter.positional.distanceModel == 'linear'
        assert emitter.positional.maxDistance == pytest.approx(10.0)
        assert emitter.positional.coneOuterGain == pytest.approx(0.1)

    def test_a_global_emitter_reads_back_without_positional_properties(self):
        emitter = model.from_gltf(self.DOCUMENT).emitters[1]
        assert emitter.type == 'global'
        assert emitter.positional is None

    def test_reads_source_fields_and_supplies_missing_defaults(self):
        first, second = model.from_gltf(self.DOCUMENT).sources
        assert (first.gain, first.autoplay, first.loop, first.audio) == (0.6, True, True, 0)
        assert (second.gain, second.autoplay, second.loop) == (1.0, False, False)
        assert second.playbackRate == pytest.approx(2.0)

    def test_reads_audio_data_by_uri_and_by_buffer_view(self):
        by_uri, by_view = model.from_gltf(self.DOCUMENT).audio
        assert by_uri.uri == 'audio1.mp3'
        assert by_uri.bufferView is None
        assert by_view.bufferView == 0
        assert by_view.mimeType == 'audio/mpeg'

    def test_an_empty_block_reads_as_an_empty_document(self):
        document = model.from_gltf({})
        assert (document.emitters, document.sources, document.audio) == ([], [], [])

    def test_unknown_keys_are_ignored_rather_than_raising(self):
        """A document using an extension we do not implement must still load."""
        document = model.from_gltf({'sources': [{'gain': 0.5, 'somethingNew': 3}]})
        assert document.sources[0].gain == pytest.approx(0.5)


class TestRoundTrip:
    """The model writes back what it read, so a scene can be re-exported."""

    def test_gltf_round_trip_is_the_identity(self):
        document = model.from_gltf(TestFromGltf.DOCUMENT)
        assert model.from_gltf(model.to_gltf(document)) == document

    def test_defaults_are_omitted_from_the_written_block(self):
        """A written document should be no larger than it needs to be."""
        document = model.AudioDocument(sources=[model.AudioSource(audio=0)])
        assert model.to_gltf(document)['sources'] == [{'audio': 0}]


class TestResolvingSources:
    """An emitter names sources by index; the document resolves them."""

    def test_sources_for_an_emitter(self):
        document = model.from_gltf(TestFromGltf.DOCUMENT)
        assert [s.name for s in document.sources_for(document.emitters[0])] == [
            'Clip 1', 'Clip 2']

    def test_audio_for_a_source(self):
        document = model.from_gltf(TestFromGltf.DOCUMENT)
        assert document.audio_for(document.sources[0]).uri == 'audio1.mp3'

    def test_a_source_with_no_audio_resolves_to_nothing(self):
        document = model.AudioDocument(sources=[model.AudioSource()])
        assert document.audio_for(document.sources[0]) is None

    def test_an_out_of_range_index_is_skipped_rather_than_raising(self):
        """Content is not always well formed, and a bad index is not fatal."""
        document = model.AudioDocument(
            sources=[model.AudioSource()],
            emitters=[model.AudioEmitter(sources=[0, 7])])
        assert len(document.sources_for(document.emitters[0])) == 1
