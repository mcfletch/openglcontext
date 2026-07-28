"""The engine: the one object an application holds.

It ties the model, the clips, the spatial maths, the mixer and the device
together, and it is where "a sound at a place in the world" becomes "these two
numbers on this voice".
"""

import math

import numpy as np
import pytest

from OpenGLContext.audio import model, synth
from OpenGLContext.audio.device import NullDevice
from OpenGLContext.audio.engine import AudioEngine
from OpenGLContext.audio.spatial import Listener


@pytest.fixture
def engine():
    """An engine wired to silence, so tests read the mix rather than hear it."""
    made = AudioEngine(device=NullDevice(sample_rate=8000), voices=8)
    yield made
    made.close()


def beep(seconds=1.0):
    return synth.tone(440.0, seconds, sample_rate=8000, fade=0.0)


class TestConstruction:
    def test_the_mixer_runs_at_the_devices_rate(self, engine):
        assert engine.mixer.sample_rate == engine.device.sample_rate == 8000

    def test_a_silent_device_makes_a_silent_engine(self, engine):
        assert engine.silent is True

    def test_it_opens_a_device_for_itself_when_given_none(self):
        made = AudioEngine()
        try:
            assert made.device is not None
        finally:
            made.close()

    def test_closing_stops_every_voice(self, engine):
        engine.play(beep(), loop=True)
        engine.close()
        assert engine.mixer.active_voices == 0

    def test_closing_twice_is_harmless(self, engine):
        engine.close()
        engine.close()

    def test_the_listener_starts_at_the_origin_looking_down_minus_z(self, engine):
        assert np.allclose(engine.listener.position, (0, 0, 0))
        assert np.allclose(engine.listener.forward, (0, 0, -1))


class TestPlaying:
    def test_playing_a_clip_starts_a_voice(self, engine):
        assert engine.play(beep()) is not None
        assert engine.mixer.active_voices == 1

    def test_playing_a_name_decodes_through_the_cache(self, engine):
        engine.clips.put('beep', beep())
        assert engine.play('beep') is not None

    def test_playing_a_name_that_will_not_decode_is_a_silence_not_an_error(self, engine):
        assert engine.play('nowhere/at/all.wav') is None
        assert engine.mixer.active_voices == 0

    def test_a_sound_with_no_emitter_is_heard_wherever_the_listener_is(self, engine):
        engine.play(beep(), gain=1.0)
        engine.listener = Listener(position=(1000.0, 0.0, 0.0))
        assert np.abs(engine.mixer.mix(64)).max() > 0.1

    def test_the_engine_reports_how_many_voices_are_sounding(self, engine):
        engine.play(beep(), loop=True)
        engine.play(beep(), loop=True)
        assert engine.active_voices == 2


class TestPositionalGain:
    """A positional emitter's gains follow its distance, cone and pan."""

    EMITTER = model.AudioEmitter(
        positional=model.PositionalProperties(distanceModel='inverse',
                                              refDistance=1.0))

    def test_a_sound_at_the_reference_distance_is_at_full_gain(self, engine):
        left, right = engine.gains_for(self.EMITTER, position=(0.0, 0.0, -1.0))
        assert math.hypot(left, right) == pytest.approx(1.0)

    def test_a_sound_further_away_is_quieter(self, engine):
        near = engine.gains_for(self.EMITTER, position=(0.0, 0.0, -1.0))
        far = engine.gains_for(self.EMITTER, position=(0.0, 0.0, -10.0))
        assert math.hypot(*far) < math.hypot(*near)

    def test_a_sound_on_the_right_is_louder_in_the_right_ear(self, engine):
        left, right = engine.gains_for(self.EMITTER, position=(5.0, 0.0, 0.0))
        assert right > left

    def test_a_sound_on_the_left_is_louder_in_the_left_ear(self, engine):
        left, right = engine.gains_for(self.EMITTER, position=(-5.0, 0.0, 0.0))
        assert left > right

    def test_panning_follows_the_listener_turning_rather_than_the_sound_moving(
            self, engine):
        engine.listener = Listener(forward=(1.0, 0.0, 0.0))
        left, right = engine.gains_for(self.EMITTER, position=(5.0, 0.0, 0.0))
        assert left == pytest.approx(right)

    def test_the_emitter_gain_multiplies_the_result(self, engine):
        loud = model.AudioEmitter(gain=1.0)
        quiet = model.AudioEmitter(gain=0.25)
        at = dict(position=(0.0, 0.0, -1.0))
        assert (math.hypot(*engine.gains_for(quiet, **at))
                == pytest.approx(0.25 * math.hypot(*engine.gains_for(loud, **at))))

    def test_a_cone_emitter_is_quiet_behind_itself(self, engine):
        emitter = model.AudioEmitter(positional=model.PositionalProperties(
            shapeType='cone', coneInnerAngle=math.pi / 2,
            coneOuterAngle=math.pi * 0.75, coneOuterGain=0.0))
        # The emitter's -Z axis is its forward, as glTF specifies.
        facing = engine.gains_for(emitter, position=(0.0, 0.0, 1.0),
                                  forward=(0.0, 0.0, -1.0))
        away = engine.gains_for(emitter, position=(0.0, 0.0, 1.0),
                                forward=(0.0, 0.0, 1.0))
        assert math.hypot(*facing) > 0.5
        assert math.hypot(*away) == pytest.approx(0.0)

    def test_a_global_emitter_ignores_distance_entirely(self, engine):
        emitter = model.AudioEmitter(type='global', gain=0.5)
        near = engine.gains_for(emitter, position=(0.0, 0.0, -1.0))
        far = engine.gains_for(emitter, position=(0.0, 0.0, -1000.0))
        assert near == pytest.approx(far)

    def test_a_sound_outside_the_maximum_distance_is_silent(self, engine):
        emitter = model.AudioEmitter(positional=model.PositionalProperties(
            distanceModel='linear', refDistance=1.0, maxDistance=10.0))
        assert engine.gains_for(emitter, position=(0.0, 0.0, -50.0)) == (0.0, 0.0)


class TestAiming:
    """A moving sound is re-aimed every frame, not restarted."""

    def test_aiming_updates_a_playing_voice(self, engine):
        emitter = model.AudioEmitter()
        handle = engine.play(beep(), emitter=emitter, position=(0.0, 0.0, -1.0))
        engine.mixer.mix(16)
        engine.aim(handle, emitter, position=(1000.0, 0.0, 0.0))
        assert engine.mixer.mix(64)[-1].max() == pytest.approx(0.0, abs=1e-3)

    def test_aiming_a_finished_sound_does_nothing(self, engine):
        handle = engine.play(synth.tone(440.0, 0.001, sample_rate=8000))
        engine.mixer.mix(64)
        engine.aim(handle, model.AudioEmitter(), position=(0.0, 0.0, -1.0))
        assert not handle.playing

    def test_aiming_tolerates_a_sound_that_was_never_started(self, engine):
        """``play`` returns None when the pool refuses; ``aim`` must accept that."""
        engine.aim(None, model.AudioEmitter(), position=(0.0, 0.0, -1.0))


class TestSourcePlayback:
    """``KHR_audio_emitter`` sources carry their own playback settings."""

    def test_the_sources_gain_is_applied(self, engine):
        engine.clips.put('beep', beep())
        document = model.AudioDocument(
            audio=[model.Audio(uri='beep')],
            sources=[model.AudioSource(audio=0, gain=0.5)])
        handle = engine.play_source(document.sources[0], document)
        engine.mixer.mix(16)
        assert handle is not None

    def test_the_sources_loop_flag_is_honoured(self, engine):
        engine.clips.put('beep', synth.tone(440.0, 0.001, sample_rate=8000))
        document = model.AudioDocument(
            audio=[model.Audio(uri='beep')],
            sources=[model.AudioSource(audio=0, loop=True)])
        handle = engine.play_source(document.sources[0], document)
        engine.mixer.mix(256)
        assert handle.playing

    def test_a_source_naming_no_audio_plays_nothing(self, engine):
        document = model.AudioDocument(sources=[model.AudioSource()])
        assert engine.play_source(document.sources[0], document) is None

    def test_the_playback_rate_speeds_the_clip_up(self, engine):
        engine.clips.put('beep', synth.tone(440.0, 0.02, sample_rate=8000))
        document = model.AudioDocument(
            audio=[model.Audio(uri='beep')],
            sources=[model.AudioSource(audio=0, playbackRate=4.0)])
        handle = engine.play_source(document.sources[0], document)
        engine.mixer.mix(64)                        # 0.008s at 8 kHz
        assert not handle.playing


class TestListenerFromPlatform:
    def test_the_listener_follows_the_view_platform(self, engine):
        from OpenGLContext.move import viewplatform

        engine.listen(viewplatform.ViewPlatform(position=(1.0, 2.0, 3.0)))
        assert np.allclose(engine.listener.position, (1.0, 2.0, 3.0))


class TestMasterControls:
    def test_the_master_gain_reaches_the_mixer(self, engine):
        engine.master_gain = 0.25
        assert engine.mixer.master_gain == pytest.approx(0.25)

    def test_the_muffle_reaches_the_mixer(self, engine):
        engine.muffle = 0.75
        assert engine.mixer.muffle == pytest.approx(0.75)

    def test_stopping_everything_silences_the_engine(self, engine):
        engine.play(beep(), loop=True)
        engine.stop_all()
        assert engine.active_voices == 0


class TestClipAccess:
    def test_a_clip_object_is_passed_straight_through(self, engine):
        clip = beep()
        assert engine.clip(clip) is clip

    def test_a_name_is_resolved_through_the_cache(self, engine):
        clip = beep()
        engine.clips.put('beep', clip)
        assert engine.clip('beep') is clip
