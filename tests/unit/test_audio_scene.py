"""Attaching sound to a context, and driving it once a frame.

This is the seam the render pass uses: it has the collected ``Auditory`` node
paths and a context; everything else is here.
"""

import numpy as np
import pytest

from OpenGLContext.audio import scene as audioscene
from OpenGLContext.audio import synth
from OpenGLContext.audio.settings import AudioSettings
from OpenGLContext.audio.device import NullDevice
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import viewplatform
from OpenGLContext.scenegraph import audio as audionodes


class FakePath(list):
    """Stands in for a ``NodePath``: a node and the transform above it."""

    def __init__(self, node, matrix=None):
        super().__init__([node])
        self.matrix = np.identity(4) if matrix is None else matrix

    def transformMatrix(self):
        return self.matrix


class FakeContext:
    """The parts of a context the audio seam touches, and nothing else."""

    def __init__(self, **audio):
        self.contextDefinition = ContextDefinition()
        if audio:
            self.contextDefinition.audio = AudioSettings(**audio)
        self.platform = viewplatform.ViewPlatform(position=(0.0, 0.0, 0.0))

    def getViewPlatform(self):
        return self.platform


@pytest.fixture(autouse=True)
def silent_devices(monkeypatch):
    """Never open real hardware from a unit test."""
    monkeypatch.setattr(audioscene, 'open_device',
                        lambda **named: NullDevice(**named))


@pytest.fixture
def context():
    made = FakeContext()
    yield made
    audioscene.close(made)


def emitter():
    return audionodes.AudioEmitter(
        sources=[audionodes.AudioSource(url=['beep'], loop=True)])


class TestEngineLifetime:
    def test_no_engine_exists_until_something_asks_for_one(self, context):
        assert audioscene.existing_engine(context) is None

    def test_asking_makes_one_and_keeps_it(self, context):
        first = audioscene.engine_for(context)
        assert first is not None
        assert audioscene.engine_for(context) is first

    def test_a_scene_with_no_sounds_never_opens_a_device(self, context):
        """Silence should cost nothing at all, not merely produce nothing."""
        audioscene.update(context, [], now=0.0)
        assert audioscene.existing_engine(context) is None

    def test_a_scene_with_sounds_opens_one(self, context):
        audioscene.update(context, [FakePath(emitter())], now=0.0)
        assert audioscene.existing_engine(context) is not None

    def test_closing_releases_the_engine(self, context):
        audioscene.engine_for(context)
        audioscene.close(context)
        assert audioscene.existing_engine(context) is None

    def test_closing_a_context_that_never_had_one_is_harmless(self, context):
        audioscene.close(context)

    def test_two_contexts_get_two_engines(self):
        first, second = FakeContext(), FakeContext()
        try:
            assert audioscene.engine_for(first) is not audioscene.engine_for(second)
        finally:
            audioscene.close(first)
            audioscene.close(second)


class TestDisabled:
    def test_audio_switched_off_never_opens_a_device(self):
        context = FakeContext(enabled=False)
        try:
            audioscene.update(context, [FakePath(emitter())], now=0.0)
            assert audioscene.existing_engine(context) is None
        finally:
            audioscene.close(context)

    def test_switching_it_off_does_not_break_the_update(self):
        context = FakeContext(enabled=False)
        try:
            assert audioscene.update(context, [FakePath(emitter())], now=0.0) == 0
        finally:
            audioscene.close(context)


class TestUpdating:
    def test_updating_starts_the_scenes_sounds(self, context):
        engine = audioscene.engine_for(context)
        engine.clips.put('beep', synth.tone(440.0, 5.0, sample_rate=44100))
        audioscene.update(context, [FakePath(emitter())], now=0.0)
        assert engine.active_voices == 1

    def test_it_reports_how_many_nodes_it_drove(self, context):
        audioscene.engine_for(context).clips.put('beep', synth.tone(440.0, 5.0))
        paths = [FakePath(emitter()), FakePath(emitter())]
        assert audioscene.update(context, paths, now=0.0) == 2

    def test_a_path_whose_node_makes_no_sound_is_skipped(self, context):
        from vrml.vrml97 import basenodes

        assert audioscene.update(
            context, [FakePath(basenodes.AudioClip())], now=0.0) == 0

    def test_the_listener_follows_the_contexts_view_platform(self, context):
        context.platform.setPosition((3.0, 4.0, 5.0))
        audioscene.update(context, [FakePath(emitter())], now=0.0)
        engine = audioscene.existing_engine(context)
        assert np.allclose(engine.listener.position, (3.0, 4.0, 5.0))

    def test_the_master_volume_comes_from_the_definition(self):
        context = FakeContext(volume=0.25)
        try:
            audioscene.update(context, [FakePath(emitter())], now=0.0)
            assert audioscene.existing_engine(context).volume == pytest.approx(0.25)
        finally:
            audioscene.close(context)

    def test_changing_the_volume_takes_effect_on_the_next_frame(self, context):
        audioscene.update(context, [FakePath(emitter())], now=0.0)
        context.contextDefinition.audio.volume = 0.5
        audioscene.update(context, [FakePath(emitter())], now=0.02)
        assert audioscene.existing_engine(context).volume == pytest.approx(0.5)

    def test_a_context_with_no_view_platform_still_updates(self):
        class Bare:
            contextDefinition = ContextDefinition()

        bare = Bare()
        try:
            audioscene.update(bare, [FakePath(emitter())], now=0.0)
        finally:
            audioscene.close(bare)


class TestDefinitionSubNode:
    """Sound is a sub-node of the definition, and a settings screen shows it."""

    def test_a_definition_has_audio_settings(self):
        assert isinstance(ContextDefinition().audio, AudioSettings)

    def test_audio_is_on_by_default(self):
        assert ContextDefinition().audio.enabled

    def test_the_volume_starts_at_full(self):
        assert ContextDefinition().audio.volume == pytest.approx(1.0)

    def test_there_is_a_default_voice_budget(self):
        assert ContextDefinition().audio.voices > 0

    def test_the_environment_can_switch_audio_off(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_AUDIO', '0')
        assert not AudioSettings().enabled

    def test_the_environment_can_set_the_volume(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_AUDIO_VOLUME', '0.3')
        assert AudioSettings().volume == pytest.approx(0.3)

    def test_every_field_is_offered_by_a_settings_screen(self):
        for name in AudioSettings.FIELDS:
            assert name in AudioSettings.UI_HINTS, name

    def test_the_definition_points_the_screen_at_them(self):
        assert ContextDefinition.AUDIO_FIELDS == AudioSettings.FIELDS

    def test_a_context_with_no_definition_still_has_settings(self):
        """A bare test double has none, and a scene with sound must still run."""
        from OpenGLContext.audio.settings import settings_for

        assert isinstance(settings_for(object()), AudioSettings)

    def test_the_voice_budget_reaches_the_pool(self, monkeypatch):
        monkeypatch.setattr(audioscene, 'open_device',
                            lambda **named: NullDevice(**named))
        context = FakeContext(voices=6)
        try:
            assert len(audioscene.engine_for(context).mixer.voices) == 6
        finally:
            audioscene.close(context)


class TestVolumeOwnership:
    """Two different volumes, and neither may quietly overwrite the other.

    ``ContextDefinition.audioVolume`` is the *player's* control -- the slider on
    the settings screen.  ``AudioEngine.master_gain`` is the *application's* mix
    level: how loud this scene was authored to be.  Writing the player's value
    over the application's every frame makes the application's setting last
    exactly one frame, and makes a volume key appear not to work at all.
    """

    def test_the_definition_drives_the_player_volume(self, context):
        context.contextDefinition.audio.volume = 0.4
        audioscene.update(context, [FakePath(emitter())], now=0.0)
        assert audioscene.existing_engine(context).volume == pytest.approx(0.4)

    def test_an_application_mix_level_survives_the_next_frame(self, context):
        engine = audioscene.engine_for(context)
        engine.master_gain = 0.2
        audioscene.update(context, [FakePath(emitter())], now=0.0)
        audioscene.update(context, [FakePath(emitter())], now=0.02)
        assert engine.master_gain == pytest.approx(0.2)

    def test_the_two_multiply(self, context):
        engine = audioscene.engine_for(context)
        engine.master_gain = 0.5
        context.contextDefinition.audio.volume = 0.5
        audioscene.update(context, [FakePath(emitter())], now=0.0)
        assert engine.mixer.master_gain == pytest.approx(0.25)

    def test_moving_the_player_volume_takes_effect_on_the_next_frame(self, context):
        engine = audioscene.engine_for(context)
        audioscene.update(context, [FakePath(emitter())], now=0.0)
        context.contextDefinition.audio.volume = 0.25
        audioscene.update(context, [FakePath(emitter())], now=0.02)
        assert engine.mixer.master_gain == pytest.approx(0.25)

    def test_the_player_volume_is_clamped_into_range(self, context):
        engine = audioscene.engine_for(context)
        engine.volume = 5.0
        assert engine.volume == pytest.approx(1.0)
        engine.volume = -1.0
        assert engine.volume == pytest.approx(0.0)
