"""Sound in the scenegraph: emitters, sources and the VRML97 ``Sound`` node.

The nodes are driven here exactly as the render pass drives them -- a world
matrix and a time, once per frame -- so the whole of the scenegraph half is
tested with no window, no device and no thread.
"""

import math

import numpy as np
import pytest

from omi_audio import synth
from omi_audio.device import NullDevice
from omi_audio.engine import AudioEngine
from omi_audio.spatial import Listener

from OpenGLContext.scenegraph import audio as audionodes
from OpenGLContext.scenegraph import basenodes


def translation(x=0.0, y=0.0, z=0.0):
    """A row-vector 4x4 translation, as ``NodePath.transformMatrix`` returns."""
    matrix = np.identity(4, dtype='d')
    matrix[3, :3] = (x, y, z)
    return matrix


def y_rotation(radians):
    """A row-vector 4x4 rotation about +Y."""
    matrix = np.identity(4, dtype='d')
    cos, sin = math.cos(radians), math.sin(radians)
    matrix[0, 0], matrix[0, 2] = cos, -sin
    matrix[2, 0], matrix[2, 2] = sin, cos
    return matrix


@pytest.fixture
def engine():
    made = AudioEngine(device=NullDevice(sample_rate=8000), voices=8)
    # Full-scale tones, so a measured level reads directly as a fraction of
    # full scale rather than of the generator's own default amplitude.
    made.clips.put('beep', synth.tone(440.0, 10.0, sample_rate=8000, fade=0.0,
                                      amplitude=1.0))
    made.clips.put('blip', synth.tone(880.0, 0.01, sample_rate=8000, fade=0.0,
                                      amplitude=1.0))
    yield made
    made.close()


def level(engine):
    """Total power in the mix right now, as a single number.

    Power rather than peak amplitude, because equal-power panning trades one
    for the other: a centred sound peaks at ``sqrt(1/2)`` in each ear and a
    hard-panned one at 1.0 in one, and both are the same loudness.
    """
    block = engine.mixer.mix(64)
    left = float(np.abs(block[:, 0]).max())
    right = float(np.abs(block[:, 1]).max())
    return math.hypot(left, right)


class TestPose:
    """A node's world pose comes out of the matrix the pass hands it."""

    def test_position_is_the_matrix_translation(self):
        position, _ = audionodes.pose_from_matrix(translation(1.0, 2.0, 3.0))
        assert np.allclose(position, (1.0, 2.0, 3.0))

    def test_forward_is_minus_z_in_the_nodes_own_frame(self):
        _, forward = audionodes.pose_from_matrix(np.identity(4))
        assert np.allclose(forward, (0.0, 0.0, -1.0))

    def test_forward_turns_with_the_node(self):
        _, forward = audionodes.pose_from_matrix(y_rotation(math.pi / 2))
        assert np.allclose(forward, (-1.0, 0.0, 0.0), atol=1e-9)

    def test_a_local_point_is_carried_into_world_space(self):
        world = audionodes.point_to_world((1.0, 0.0, 0.0), translation(0.0, 5.0, 0.0))
        assert np.allclose(world, (1.0, 5.0, 0.0))

    def test_a_local_direction_ignores_the_translation(self):
        world = audionodes.direction_to_world((0.0, 0.0, -1.0), translation(9.0, 9.0, 9.0))
        assert np.allclose(world, (0.0, 0.0, -1.0))


class TestAudioSourceNode:
    """One clip and the settings it is played with."""

    def test_it_resolves_the_first_url_that_decodes(self, engine):
        source = audionodes.AudioSource(url=['nowhere.wav', 'beep'])
        assert source.clip(engine) is engine.clips.get('beep')

    def test_a_url_that_never_resolves_gives_no_clip(self, engine):
        assert audionodes.AudioSource(url=['nowhere.wav']).clip(engine) is None

    def test_no_url_gives_no_clip(self, engine):
        assert audionodes.AudioSource().clip(engine) is None

    def test_the_resolved_clip_is_remembered(self, engine):
        """Resolution walks a url list and may touch a disk; once is enough."""
        source = audionodes.AudioSource(url=['beep'])
        assert source.clip(engine) is source.clip(engine)

    def test_the_settings_read_back_as_a_khr_source_record(self):
        source = audionodes.AudioSource(gain=0.5, loop=True, playbackRate=2.0)
        record = source.record()
        assert (record.gain, record.loop, record.playbackRate) == (0.5, True, 2.0)

    def test_the_record_is_the_same_object_each_time(self):
        """Rebuilt in place, so a scene full of sources allocates nothing."""
        source = audionodes.AudioSource()
        assert source.record() is source.record()


class TestAudioEmitterNode:
    """``KHR_audio_emitter`` as something you can put in a scene."""

    def make(self, **named):
        named.setdefault('sources', [audionodes.AudioSource(url=['beep'], loop=True)])
        return audionodes.AudioEmitter(**named)

    def test_it_starts_its_sources_on_the_first_update(self, engine):
        emitter = self.make()
        emitter.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        assert engine.active_voices == 1

    def test_it_does_not_restart_a_source_that_is_already_playing(self, engine):
        emitter = self.make()
        for frame in range(5):
            emitter.updateAudio(engine, translation(0.0, 0.0, -1.0), frame / 60.0)
        assert engine.active_voices == 1

    def test_a_source_that_does_not_autoplay_stays_quiet(self, engine):
        emitter = self.make(sources=[audionodes.AudioSource(url=['beep'],
                                                            autoplay=False)])
        emitter.updateAudio(engine, translation(), 0.0)
        assert engine.active_voices == 0

    def test_a_distant_emitter_is_quieter_than_a_near_one(self, engine):
        near, far = self.make(), self.make()
        near.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        loud = level(engine)
        engine.stop_all()
        far.updateAudio(engine, translation(0.0, 0.0, -100.0), 0.0)
        assert level(engine) < loud

    def test_moving_the_emitter_re_aims_it_without_restarting(self, engine):
        emitter = self.make()
        emitter.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        engine.mixer.mix(64)
        emitter.updateAudio(engine, translation(0.0, 0.0, -1000.0), 0.02)
        engine.mixer.mix(64)                                # let the ramp finish
        assert engine.active_voices == 1
        assert level(engine) < 0.01

    def test_a_global_emitter_ignores_where_it_is(self, engine):
        emitter = self.make(type='global')
        emitter.updateAudio(engine, translation(0.0, 0.0, -1000.0), 0.0)
        assert level(engine) > 0.1

    def test_the_emitter_gain_is_applied(self, engine):
        loud, quiet = self.make(gain=1.0), self.make(gain=0.1)
        loud.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        full = level(engine)
        engine.stop_all()
        quiet.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        assert level(engine) == pytest.approx(full * 0.1, rel=0.05)

    def test_a_cone_emitter_facing_away_is_silent(self, engine):
        emitter = self.make(shapeType='cone', coneInnerAngle=math.pi / 4,
                            coneOuterAngle=math.pi / 2, coneOuterGain=0.0)
        # Emitter at -Z facing -Z, so its cone points away from the listener.
        emitter.updateAudio(engine, translation(0.0, 0.0, -2.0), 0.0)
        assert level(engine) == pytest.approx(0.0, abs=1e-6)

    def test_a_cone_emitter_facing_the_listener_is_heard(self, engine):
        emitter = self.make(shapeType='cone', coneInnerAngle=math.pi / 4,
                            coneOuterAngle=math.pi / 2, coneOuterGain=0.0)
        matrix = np.dot(y_rotation(math.pi), translation(0.0, 0.0, -2.0))
        emitter.updateAudio(engine, matrix, 0.0)
        assert level(engine) > 0.1

    def test_stopping_a_node_silences_its_sources(self, engine):
        emitter = self.make()
        emitter.updateAudio(engine, translation(), 0.0)
        emitter.stopAudio()
        assert engine.active_voices == 0

    def test_a_finished_one_shot_is_started_again_only_if_it_loops(self, engine):
        emitter = self.make(sources=[audionodes.AudioSource(url=['blip'])])
        emitter.updateAudio(engine, translation(), 0.0)
        engine.mixer.mix(512)                               # runs the clip out
        emitter.updateAudio(engine, translation(), 1.0)
        assert engine.active_voices == 0

    def test_a_finished_one_shot_stays_finished_over_many_frames(self, engine):
        """The frame that notices it ended must not be the only one that does.

        A scene is updated sixty times a second forever, so "finished" has to
        be a state the emitter keeps rather than something observed once.
        """
        emitter = self.make(sources=[audionodes.AudioSource(url=['blip'])])
        emitter.updateAudio(engine, translation(), 0.0)
        engine.mixer.mix(512)                               # runs the clip out
        for frame in range(5):
            emitter.updateAudio(engine, translation(), 1.0 + frame)
            engine.mixer.mix(8)
        assert engine.active_voices == 0

    def test_a_looping_source_takes_a_voice_again_after_losing_one(self, engine):
        """Nothing ends a loop but voice stealing, so it may come back.

        This is the one case where restarting is right, and it is what
        separates a loop from a one-shot: ambience silenced by a moment of
        voice pressure should return when the pressure passes, while a one-shot
        silenced the same way has simply been and gone.
        """
        emitter = self.make()                               # a looping source
        emitter.updateAudio(engine, translation(), 0.0)
        engine.stop_all()
        emitter.updateAudio(engine, translation(), 1.0)
        assert engine.active_voices == 1

    def test_a_repeating_one_shot_is_silent_until_its_interval_has_passed(self, engine):
        emitter = self.make(sources=[audionodes.AudioSource(url=['blip'],
                                                            repeatInterval=5.0)])
        emitter.updateAudio(engine, translation(), 0.0)
        engine.mixer.mix(512)                               # runs the clip out
        emitter.updateAudio(engine, translation(), 3.0)
        assert engine.active_voices == 0

    def test_a_repeating_one_shot_plays_again_once_its_interval_has_passed(self, engine):
        """A map's occasional distant noise: a one-shot on a slow timer.

        The interval is measured from the frame the clip was noticed to have
        ended, not from when it started, so a long clip and a short one both
        leave the same gap of quiet.
        """
        emitter = self.make(sources=[audionodes.AudioSource(url=['blip'],
                                                            repeatInterval=5.0)])
        emitter.updateAudio(engine, translation(), 0.0)
        engine.mixer.mix(512)
        emitter.updateAudio(engine, translation(), 1.0)     # notices it ended
        emitter.updateAudio(engine, translation(), 6.5)
        assert engine.active_voices == 1

    def test_the_variance_moves_the_next_repeat_within_its_spread(self, engine):
        """Two speakers of the same sound must not stay in lockstep for ever."""
        source = audionodes.AudioSource(url=['blip'], repeatInterval=10.0,
                                        repeatVariance=4.0)
        emitter = self.make(sources=[source])
        emitter.updateAudio(engine, translation(), 0.0)
        engine.mixer.mix(512)
        emitter.updateAudio(engine, translation(), 1.0)
        assert 6.0 <= emitter.repeatsAt(source) - 1.0 <= 14.0

    def test_a_source_with_no_interval_never_repeats(self, engine):
        source = audionodes.AudioSource(url=['blip'])
        emitter = self.make(sources=[source])
        emitter.updateAudio(engine, translation(), 0.0)
        engine.mixer.mix(512)
        emitter.updateAudio(engine, translation(), 1.0)
        assert emitter.repeatsAt(source) is None

    def test_a_looping_source_ignores_the_repeat_interval(self, engine):
        """A loop has no gaps to fill, so a timer on one means nothing."""
        source = audionodes.AudioSource(url=['beep'], loop=True,
                                        repeatInterval=1.0)
        emitter = self.make(sources=[source])
        emitter.updateAudio(engine, translation(), 0.0)
        for frame in range(5):
            emitter.updateAudio(engine, translation(), frame)
        assert engine.active_voices == 1

    def test_stopping_an_emitter_clears_its_repeat_timers(self, engine):
        """A scene put away and brought back is not mid-interval."""
        source = audionodes.AudioSource(url=['blip'], repeatInterval=5.0)
        emitter = self.make(sources=[source])
        emitter.updateAudio(engine, translation(), 0.0)
        engine.mixer.mix(512)
        emitter.updateAudio(engine, translation(), 1.0)
        emitter.stopAudio()
        assert emitter.repeatsAt(source) is None

    def test_an_emitter_with_no_sources_is_harmless(self, engine):
        audionodes.AudioEmitter(sources=[]).updateAudio(engine, translation(), 0.0)
        assert engine.active_voices == 0

    def test_the_record_reads_back_as_a_khr_emitter(self):
        emitter = audionodes.AudioEmitter(gain=0.5, refDistance=3.0,
                                          distanceModel='linear', maxDistance=20.0)
        record = emitter.record()
        assert record.gain == 0.5
        assert record.positional.refDistance == 3.0
        assert record.positional.distanceModel == 'linear'

    def test_a_global_emitters_record_has_no_positional_properties(self):
        assert audionodes.AudioEmitter(type='global').record().positional is None

    def test_the_record_is_rebuilt_in_place(self):
        emitter = audionodes.AudioEmitter()
        first = emitter.record()
        emitter.gain = 0.25
        assert emitter.record() is first
        assert first.gain == 0.25


class TestVRML97Sound:
    """The ``Sound`` node pyvrml97 has always declared, finally audible."""

    def make(self, **named):
        named.setdefault('source', basenodes.AudioClip(url=['beep'], loop=True))
        return audionodes.Sound(**named)

    def test_it_plays_its_audio_clip(self, engine):
        sound = self.make()
        sound.updateAudio(engine, translation(), 0.0)
        assert engine.active_voices == 1

    def test_a_sound_with_no_source_is_silent(self, engine):
        audionodes.Sound().updateAudio(engine, translation(), 0.0)
        assert engine.active_voices == 0

    def test_a_source_that_will_not_resolve_is_a_silence(self, engine):
        sound = audionodes.Sound(source=basenodes.AudioClip(url=['nowhere.wav']))
        sound.updateAudio(engine, translation(), 0.0)
        assert engine.active_voices == 0

    def test_inside_the_inner_ellipsoid_it_is_at_full_intensity(self, engine):
        sound = self.make(minFront=5.0, minBack=5.0, maxFront=50.0, maxBack=50.0)
        sound.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        assert level(engine) == pytest.approx(1.0, rel=0.02)

    def test_outside_the_outer_ellipsoid_it_is_silent(self, engine):
        sound = self.make(minFront=1.0, minBack=1.0, maxFront=10.0, maxBack=10.0)
        sound.updateAudio(engine, translation(0.0, 0.0, -100.0), 0.0)
        assert level(engine) == pytest.approx(0.0, abs=1e-6)

    def test_the_ellipsoid_is_oriented_by_the_direction_field(self, engine):
        """A forward-facing sound reaches further ahead of itself than behind."""
        ahead = self.make(direction=(0, 0, -1), minFront=1.0, minBack=1.0,
                          maxFront=100.0, maxBack=2.0)
        ahead.updateAudio(engine, translation(0.0, 0.0, 20.0), 0.0)
        behind_listener = level(engine)
        engine.stop_all()
        ahead2 = self.make(direction=(0, 0, -1), minFront=1.0, minBack=1.0,
                           maxFront=100.0, maxBack=2.0)
        ahead2.updateAudio(engine, translation(0.0, 0.0, -20.0), 0.0)
        assert behind_listener > level(engine)

    def test_a_moving_sound_is_re_aimed_rather_than_restarted(self, engine):
        """The voice follows the node without ever being started again --
        restarting it would retrigger the clip's attack every frame."""
        sound = self.make(minFront=1.0, minBack=1.0, maxFront=100.0, maxBack=100.0)
        sound.updateAudio(engine, translation(0.0, 0.0, -2.0), 0.0)
        near = level(engine)
        sound.updateAudio(engine, translation(0.0, 0.0, -60.0), 0.1)
        assert engine.active_voices == 1, 'the sound was restarted, not re-aimed'
        assert level(engine) < near

    def test_stopping_a_sound_silences_it(self, engine):
        sound = self.make()
        sound.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        sound.stopAudio()
        assert engine.active_voices == 0

    def test_stopping_a_sound_that_never_started_is_harmless(self, engine):
        audionodes.Sound().stopAudio()

    def test_a_sound_with_no_direction_is_heard_from_every_side(self, engine):
        """A zero ``direction`` has no front to tell from its back, so the
        ``front`` distances are what reach in every direction."""
        sound = self.make(direction=(0, 0, 0), minFront=1.0, minBack=1.0,
                          maxFront=20.0, maxBack=2.0)
        sound.updateAudio(engine, translation(0.0, 0.0, -10.0), 0.0)
        ahead = level(engine)
        engine.stop_all()
        behind = self.make(direction=(0, 0, 0), minFront=1.0, minBack=1.0,
                           maxFront=20.0, maxBack=2.0)
        behind.updateAudio(engine, translation(0.0, 0.0, 10.0), 0.0)
        assert ahead == pytest.approx(level(engine), rel=0.02)
        assert ahead > 0.0

    def test_a_sound_the_listener_is_standing_on_is_at_full_intensity(self, engine):
        """No offset means no angle to measure; the listener is inside it."""
        sound = self.make(minFront=1.0, minBack=1.0, maxFront=10.0, maxBack=10.0)
        sound.updateAudio(engine, translation(0.0, 0.0, 0.0), 0.0)
        assert level(engine) == pytest.approx(1.0, rel=0.02)

    def test_intensity_scales_the_level(self, engine):
        quiet = self.make(intensity=0.25, minFront=50.0, minBack=50.0)
        quiet.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        assert level(engine) == pytest.approx(0.25, rel=0.05)

    def test_a_sound_on_the_right_is_louder_in_the_right_ear(self, engine):
        sound = self.make(minFront=50.0, minBack=50.0)
        sound.updateAudio(engine, translation(10.0, 0.0, 0.0), 0.0)
        block = engine.mixer.mix(64)
        assert np.abs(block[:, 1]).max() > np.abs(block[:, 0]).max()

    def test_spatialize_false_centres_the_sound(self, engine):
        sound = self.make(spatialize=False, minFront=50.0, minBack=50.0)
        sound.updateAudio(engine, translation(10.0, 0.0, 0.0), 0.0)
        block = engine.mixer.mix(64)
        assert np.abs(block[:, 1]).max() == pytest.approx(
            float(np.abs(block[:, 0]).max()), rel=1e-3)

    def test_the_location_field_is_relative_to_the_nodes_transform(self, engine):
        far = self.make(location=(0.0, 0.0, -1000.0), minFront=1.0, minBack=1.0,
                        maxFront=10.0, maxBack=10.0)
        far.updateAudio(engine, translation(), 0.0)
        assert level(engine) == pytest.approx(0.0, abs=1e-6)

    def test_the_clips_pitch_becomes_the_playback_rate(self, engine):
        clip = basenodes.AudioClip(url=['blip'], pitch=4.0)
        sound = audionodes.Sound(source=clip, minFront=50.0, minBack=50.0)
        sound.updateAudio(engine, translation(), 0.0)
        engine.mixer.mix(24)                    # 0.003s: past a quartered blip
        assert engine.active_voices == 0

    def test_a_clip_that_does_not_loop_plays_once(self, engine):
        clip = basenodes.AudioClip(url=['blip'], loop=False)
        sound = audionodes.Sound(source=clip)
        sound.updateAudio(engine, translation(), 0.0)
        engine.mixer.mix(512)
        sound.updateAudio(engine, translation(), 1.0)
        assert engine.active_voices == 0

    def test_the_clip_reports_that_it_is_active(self, engine):
        clip = basenodes.AudioClip(url=['beep'], loop=True)
        sound = audionodes.Sound(source=clip)
        sound.updateAudio(engine, translation(), 0.0)
        assert clip.isActive

    def test_the_clip_reports_its_duration_once_decoded(self, engine):
        clip = basenodes.AudioClip(url=['blip'])
        audionodes.Sound(source=clip).updateAudio(engine, translation(), 0.0)
        assert clip.duration_changed == pytest.approx(0.01, rel=0.05)

    def test_a_stop_time_in_the_past_keeps_it_quiet(self, engine):
        clip = basenodes.AudioClip(url=['beep'], loop=True, startTime=0.0,
                                   stopTime=1.0)
        audionodes.Sound(source=clip).updateAudio(engine, translation(), 5.0)
        assert engine.active_voices == 0

    def test_a_start_time_in_the_future_keeps_it_quiet_until_then(self, engine):
        clip = basenodes.AudioClip(url=['beep'], loop=True, startTime=10.0)
        sound = audionodes.Sound(source=clip)
        sound.updateAudio(engine, translation(), 0.0)
        assert engine.active_voices == 0
        sound.updateAudio(engine, translation(), 11.0)
        assert engine.active_voices == 1

    def test_priority_reaches_the_voice_pool(self, engine):
        engine.mixer.voices = engine.mixer.voices[:1]
        important = self.make(priority=1.0)
        unimportant = self.make(priority=0.0)
        important.updateAudio(engine, translation(), 0.0)
        unimportant.updateAudio(engine, translation(), 0.0)
        assert engine.active_voices == 1
        assert level(engine) > 0.0


class TestEngineNotRequired:
    """A scene must build and run with no engine at all."""

    def test_updating_with_no_engine_does_nothing(self):
        emitter = audionodes.AudioEmitter(
            sources=[audionodes.AudioSource(url=['beep'])])
        emitter.updateAudio(None, translation(), 0.0)
        emitter.stopAudio()

    def test_a_sound_node_updates_with_no_engine(self):
        audionodes.Sound(source=basenodes.AudioClip(url=['x'])).updateAudio(
            None, translation(), 0.0)


class TestListenerFollowsTheCamera:
    def test_turning_the_listener_swaps_the_ears(self, engine):
        emitter = audionodes.AudioEmitter(
            sources=[audionodes.AudioSource(url=['beep'], loop=True)],
            refDistance=100.0)
        emitter.updateAudio(engine, translation(10.0, 0.0, 0.0), 0.0)
        right_ear = float(np.abs(engine.mixer.mix(64)[:, 1]).max())
        engine.listener = Listener(forward=(0.0, 0.0, 1.0))
        emitter.updateAudio(engine, translation(10.0, 0.0, 0.0), 0.02)
        engine.mixer.mix(64)
        block = engine.mixer.mix(64)
        assert float(np.abs(block[:, 0]).max()) == pytest.approx(right_ear, rel=0.05)


class TestBuildingEmittersFromADocument:
    """``emitters_from_document`` on its own, without a glTF file around it.

    The loader always passes every argument; these are the defaults a direct
    caller gets, and the shapes a malformed document produces.
    """

    def document(self, **audio):
        return audionodes.model.AudioDocument(
            audio=[audionodes.model.Audio(**audio)],
            sources=[audionodes.model.AudioSource(audio=0, gain=0.5)],
            emitters=[audionodes.model.AudioEmitter(name='One', sources=[0])])

    def test_it_builds_every_emitter_when_told_of_none_in_particular(self):
        nodes = audionodes.emitters_from_document(self.document(uri='a.wav'))
        assert len(nodes) == 1
        assert nodes[0].sources[0].gain == pytest.approx(0.5)

    def test_a_source_naming_no_audio_is_skipped(self):
        """It could never sound, and a node that cannot sound is noise."""
        document = audionodes.model.AudioDocument(
            sources=[audionodes.model.AudioSource()],
            emitters=[audionodes.model.AudioEmitter(sources=[0])])
        assert audionodes.emitters_from_document(document)[0].sources == []

    def test_without_a_library_a_source_falls_back_to_its_url(self, engine):
        """A hand-built document, or a VRML scene, has no library behind it."""
        source = audionodes.emitters_from_document(
            self.document(uri='beep'))[0].sources[0]
        assert source.url == ['beep']
        assert source.clip(engine) is not None

    def test_audio_inside_the_document_has_no_url_to_record(self):
        """A bufferView is not a location, so there is nothing honest to put here."""
        source = audionodes.emitters_from_document(
            self.document(bufferView=0, mimeType='audio/wav'))[0].sources[0]
        assert source.url == []

    def test_a_data_uri_is_content_rather_than_a_location(self):
        source = audionodes.emitters_from_document(
            self.document(uri='data:audio/wav;base64,AAAA'))[0].sources[0]
        assert source.url == []

    def test_a_uri_the_resolver_refuses_is_reported_and_dropped(self, caplog):
        """An out-of-bounds reference costs the sound, not the scene."""
        def refusing(uri):
            raise OSError('outside the document origin')

        with caplog.at_level('WARNING'):
            source = audionodes.emitters_from_document(
                self.document(uri='http://evil.example/x.mp3'),
                resolve=refusing)[0].sources[0]
        assert source.url == []
        assert any('evil.example' in record.getMessage()
                   for record in caplog.records)


class TestHowOftenAPlayingSoundIsReAimed:
    """Aiming is continuous and slow, so it is asked for at its own rate.

    Turning a position into two volumes costs a distance, a cone angle, an
    azimuth and a pan, and a level with a few dozen emitters asking every frame
    is a measurable part of the frame. What has to stay true is that a sound is
    placed before it is heard, and that it keeps up with a listener who moves.
    """

    def make(self, **named):
        named.setdefault('sources', [audionodes.AudioSource(url=['beep'],
                                                            loop=True)])
        return audionodes.AudioEmitter(**named)

    def aims(self, engine, emitter, times, at=(0.0, 0.0, -1.0)):
        """How many times ``engine.aim`` is called across ``times``."""
        counted = []
        original = engine.aim

        def aim(*args, **named):
            counted.append(1)
            return original(*args, **named)

        engine.aim = aim
        try:
            for now in times:
                emitter.updateAudio(engine, translation(*at), now)
        finally:
            engine.aim = original
        return len(counted)

    def test_a_playing_sound_is_not_re_aimed_every_frame(self, engine):
        emitter = self.make()
        emitter.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        frames = [frame / 60.0 for frame in range(1, 61)]   # a second at sixty
        assert self.aims(engine, emitter, frames) < len(frames)

    def test_it_is_re_aimed_often_enough_to_follow_a_listener(self, engine):
        """Over a second, about as often as the interval says."""
        emitter = self.make()
        emitter.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        frames = [frame / 60.0 for frame in range(1, 61)]
        counted = self.aims(engine, emitter, frames)
        expected = 1.0 / audionodes.AIM_INTERVAL
        assert expected * 0.5 <= counted <= expected + 2

    def test_the_first_look_at_a_playing_sound_aims_it(self, engine):
        """A sound is placed before it is heard, not an interval later."""
        emitter = self.make()
        emitter.updateAudio(engine, translation(0.0, 0.0, -1.0), 0.0)
        assert self.aims(engine, emitter, [1.0 / 60.0]) == 1

    def test_two_emitters_do_not_re_aim_on_the_same_frame(self, engine):
        """Spread on purpose: a level's worth landing together is a stutter."""
        phases = {self.make()._aimPhase for _ in range(20)}
        assert len(phases) > 1
