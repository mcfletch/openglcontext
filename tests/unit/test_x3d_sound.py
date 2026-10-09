"""X3D's Sound component on omi_audio's processing graph.

Each test builds the X3D nodes, hands the roots to a
:class:`~OpenGLContext.audio.x3dgraph.SoundGraph` as the render pass does once
a frame, and reads what the mixer produces. The engine's device is silent, so
the mix is pulled here, a block at a time.
"""

import math

import numpy as np
import pytest

from omi_audio import synth
from omi_audio.device import NullCapture, NullDevice
from omi_audio.engine import AudioEngine
from omi_audio.graph import convolver
from omi_audio.graph.panner import SPEED_OF_SOUND
from omi_audio.spatial import Listener

from OpenGLContext.audio import x3dgraph
from OpenGLContext.scenegraph import x3dsound as snd

RATE = 8000


@pytest.fixture
def engine():
    made = AudioEngine(device=NullDevice(sample_rate=RATE), voices=8)
    made.clips.put('beep', synth.tone(440.0, 1.0, sample_rate=RATE, fade=0.0,
                                      amplitude=1.0))
    made.clips.put('blip', synth.tone(880.0, 0.25, sample_rate=RATE, fade=0.0,
                                      amplitude=1.0))
    yield made
    made.close()


@pytest.fixture
def graph(engine):
    made = x3dgraph.SoundGraph(engine)
    yield made
    made.close()


def translation(x=0.0, y=0.0, z=0.0):
    matrix = np.identity(4)
    matrix[3, :3] = (x, y, z)
    return matrix


def frame(graph, *roots, now=1.0, **named):
    """One frame: each root at the origin unless given as ``(node, matrix)``."""
    placed = [root if isinstance(root, tuple) else (root, translation()) for root in roots]
    return graph.update(placed, now, **named)


def mix(engine, frames=2048):
    """The next ``frames`` of the mix, ``(frames, 2)``."""
    return engine.mixer.mix(frames).copy()


def power(block):
    return float(np.sqrt(np.mean(np.square(block))))


def strongest(samples, rate=RATE):
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return np.argmax(spectrum) * rate / len(samples)


def tone(frequency=440.0, **named):
    return snd.OscillatorSource(frequency=frequency, **named)


class TestDestinations:
    def test_a_source_in_a_destination_is_heard(self, engine, graph):
        frame(graph, snd.AudioDestination(children=[tone()]))
        block = mix(engine)
        assert power(block) > 0.1
        assert strongest(block[:, 0]) == pytest.approx(440.0, abs=8.0)

    def test_a_source_in_no_destination_is_not_heard(self, engine, graph):
        frame(graph, tone())
        assert power(mix(engine)) == 0.0

    def test_a_stream_destination_is_heard(self, engine, graph):
        frame(graph, snd.StreamAudioDestination(children=[tone()]))
        assert power(mix(engine)) > 0.1

    def test_a_disabled_destination_is_silent(self, engine, graph):
        destination = snd.AudioDestination(children=[tone()], enabled=False)
        frame(graph, destination)
        assert power(mix(engine)) == 0.0
        assert destination.isActive is False

    def test_a_heard_destination_is_active(self, graph):
        destination = snd.AudioDestination(children=[tone()])
        frame(graph, destination)
        assert destination.isActive is True

    def test_the_destination_gain_scales_the_output(self, engine, graph):
        destination = snd.AudioDestination(children=[tone()])
        frame(graph, destination)
        full = power(mix(engine))
        destination.gain = 0.5
        frame(graph, destination, now=1.1)
        mix(engine)
        assert power(mix(engine)) == pytest.approx(full / 2, rel=0.02)

    def test_no_roots_silences_what_was_heard(self, engine, graph):
        frame(graph, snd.AudioDestination(children=[tone()]))
        frame(graph, now=1.1)
        assert power(mix(engine)) == 0.0

    def test_a_node_shared_by_two_destinations_is_rendered_once(self, engine, graph):
        shared = tone(gain=0.25)
        frame(graph, snd.AudioDestination(children=[shared]))
        single = power(mix(engine))
        frame(graph, snd.AudioDestination(children=[shared]),
              snd.AudioDestination(children=[shared]), now=1.1)
        mix(engine)
        assert power(mix(engine)) == pytest.approx(2 * single, rel=0.02)
        assert graph.audioNode(shared) is not None


class TestProcessing:
    def test_gain_scales_its_input(self, engine, graph):
        frame(graph, snd.AudioDestination(children=[snd.Gain(children=[tone()])]))
        full = power(mix(engine))
        graph.clear()
        frame(graph, snd.AudioDestination(children=[snd.Gain(gain=0.25, children=[tone()])]))
        assert power(mix(engine)) == pytest.approx(full / 4, rel=0.02)

    def test_a_lowpass_filter_takes_out_a_high_tone(self, engine, graph):
        frame(graph, snd.AudioDestination(children=[snd.BiquadFilter(
            type='LOWPASS', frequency=200.0, children=[tone(2000.0)])]))
        mix(engine)
        assert power(mix(engine)) < 0.05

    def test_a_disabled_processing_node_passes_its_input(self, engine, graph):
        frame(graph, snd.AudioDestination(children=[snd.BiquadFilter(
            type='LOWPASS', frequency=200.0, enabled=False, children=[tone(2000.0)])]))
        assert power(mix(engine)) > 0.5

    def test_a_filters_gain_is_its_boost_in_decibels(self, graph):
        node = snd.BiquadFilter(type='PEAKING', gain=6.0, children=[tone()])
        frame(graph, snd.AudioDestination(children=[node]))
        made = graph.audioNode(node)
        assert made.filter_gain == 6.0
        assert made.gain == 1.0

    def test_the_filter_fields_reach_the_filter(self, graph):
        node = snd.BiquadFilter(type='HIGHSHELF', frequency=900.0, qualityFactor=2.0,
                                detune=100.0, children=[tone()])
        frame(graph, snd.AudioDestination(children=[node]))
        made = graph.audioNode(node)
        assert (made.kind, made.frequency, made.q, made.detune) == (
            'highshelf', 900.0, 2.0, 100.0)

    def test_a_delay_delays(self, engine, graph):
        impulse = snd.BufferAudioSource(buffer=[1.0] + [0.0] * 99, sampleRate=RATE,
                                         startTime=1.0)
        frame(graph, snd.AudioDestination(children=[snd.Delay(
            delayTime=0.005, children=[impulse])]))
        block = mix(engine, 100)
        assert int(np.argmax(np.abs(block[:, 0]))) == 40

    def test_a_wave_shaper_maps_through_its_curve(self, engine, graph):
        frame(graph, snd.AudioDestination(children=[snd.WaveShaper(
            curve=[0.5, 0.5], children=[tone()])]))
        block = mix(engine, 64)
        assert np.allclose(block[:, 0], 0.5)

    def test_a_convolver_convolves(self, engine, graph):
        impulse = snd.BufferAudioSource(buffer=[1.0] + [0.0] * 511, sampleRate=RATE,
                                         startTime=1.0)
        node = snd.Convolver(buffer=[0.0, 0.0, 1.0], children=[impulse])
        frame(graph, snd.AudioDestination(children=[node]))
        block = mix(engine, 512)
        assert int(np.argmax(np.abs(block[:, 0]))) == convolver.PARTITION + 2

    def test_a_compressor_reports_its_reduction(self, engine, graph):
        node = snd.DynamicsCompressor(threshold=-40.0, attack=0.0, children=[tone()])
        frame(graph, snd.AudioDestination(children=[node]))
        mix(engine)
        frame(graph, snd.AudioDestination(children=[node]), now=1.1)
        assert node.reduction < -1.0

    def test_an_analyser_finds_the_tone(self, engine, graph):
        node = snd.Analyser(fftSize=1024, children=[tone(1000.0)])
        frame(graph, snd.AudioDestination(children=[node]))
        mix(engine)
        spectrum = node.frequencyData()
        assert spectrum.shape == (512,)
        assert int(np.argmax(spectrum)) == pytest.approx(1000.0 * 1024 / RATE, abs=1)
        assert node.frequencyBinCount == 512
        assert node.timeDomainData().shape == (1024,)
        assert node.byteFrequencyData().dtype == np.uint8
        assert node.byteTimeDomainData().shape == (1024,)

    def test_an_analyser_not_heard_has_nothing_to_show(self):
        node = snd.Analyser()
        assert node.frequencyData().shape == (0,)
        assert node.timeDomainData().shape == (0,)

    def test_a_node_reports_its_channel_count(self, engine, graph):
        node = snd.Gain(children=[tone()])
        frame(graph, snd.AudioDestination(children=[node]))
        mix(engine, 64)
        frame(graph, snd.AudioDestination(children=[node]), now=1.1)
        assert node.channelCount == 1

    def test_channel_modes_reach_the_graph(self, graph):
        node = snd.Gain(channelCountMode='CLAMPED_MAX', channelInterpretation='DISCRETE',
                        children=[tone()])
        frame(graph, snd.AudioDestination(children=[node]))
        made = graph.audioNode(node)
        assert (made.channel_count_mode, made.channel_interpretation) == (
            'clamped-max', 'discrete')


class TestSources:
    def test_a_periodic_wave_shapes_the_oscillator(self, engine, graph):
        square = tone(500.0, periodicWave=snd.PeriodicWave(type='SQUARE'))
        frame(graph, snd.AudioDestination(children=[square]))
        spectrum = np.abs(np.fft.rfft(mix(engine)[:, 0] * np.hanning(2048)))
        third = int(round(1500.0 * 2048 / RATE))
        fundamental = int(round(500.0 * 2048 / RATE))
        assert spectrum[third] > 0.2 * spectrum[fundamental]

    def test_an_oscillator_with_no_wave_is_a_sine(self, engine, graph):
        frame(graph, snd.AudioDestination(children=[tone(500.0)]))
        spectrum = np.abs(np.fft.rfft(mix(engine)[:, 0] * np.hanning(2048)))
        third = int(round(1500.0 * 2048 / RATE))
        assert spectrum[third] < 1e-3 * spectrum.max()

    def test_a_custom_wave_reads_its_coefficients(self, graph):
        wave = snd.PeriodicWave(type='CUSTOM', optionsImag=[0.0, 0.0, 1.0])
        source = tone(periodicWave=wave)
        frame(graph, snd.AudioDestination(children=[source]))
        made = graph.audioNode(source)
        assert made.wave.imag[2] == 1.0

    def test_the_oscillator_fields_reach_it(self, graph):
        source = tone(300.0, detune=1200.0, gain=0.5)
        frame(graph, snd.AudioDestination(children=[source]))
        made = graph.audioNode(source)
        assert made.pitch == pytest.approx(600.0)
        assert made.gain == 0.5

    def test_a_source_waits_for_its_start_time(self, engine, graph):
        destination = snd.AudioDestination(children=[tone(startTime=5.0)])
        frame(graph, destination, now=1.0)
        assert power(mix(engine)) == 0.0
        frame(graph, destination, now=6.0)
        assert power(mix(engine)) > 0.1

    def test_a_paused_source_is_silent(self, engine, graph):
        source = tone(pauseTime=2.0)
        destination = snd.AudioDestination(children=[source])
        frame(graph, destination, now=1.0)
        frame(graph, destination, now=3.0)
        assert source.isPaused is True
        assert power(mix(engine)) == 0.0

    def test_a_disabled_source_is_silent(self, engine, graph):
        frame(graph, snd.AudioDestination(children=[tone(enabled=False)]))
        assert power(mix(engine)) == 0.0

    def test_a_buffer_plays_its_channels(self, engine, graph):
        source = snd.BufferAudioSource(buffer=[0.25] * 4 + [0.75] * 4,
                                       numberOfChannels=2, sampleRate=RATE, startTime=1.0)
        frame(graph, snd.AudioDestination(children=[source]))
        block = mix(engine, 4)
        assert np.allclose(block[:, 0], 0.25) and np.allclose(block[:, 1], 0.75)
        assert source.channelCount == 2
        assert source.length == 4

    def test_a_buffer_with_no_rate_is_at_the_engines(self, graph):
        source = snd.BufferAudioSource(buffer=[0.5] * RATE)
        frame(graph, snd.AudioDestination(children=[source]))
        assert source.bufferDuration == pytest.approx(1.0)

    def test_a_buffer_may_be_read_from_a_url(self, graph):
        source = snd.BufferAudioSource(url=['blip'], loop=True)
        frame(graph, snd.AudioDestination(children=[source]))
        assert source.bufferDuration == pytest.approx(0.25)
        assert source.isActive is True

    def test_a_changed_buffer_is_played(self, engine, graph):
        source = snd.BufferAudioSource(buffer=[0.25] * 64, sampleRate=RATE, loop=True)
        destination = snd.AudioDestination(children=[source])
        frame(graph, destination)
        source.buffer = [0.5] * 64
        frame(graph, destination, now=1.1)
        assert np.allclose(graph.audioNode(source).buffer, 0.5)

    def test_the_buffer_fields_reach_the_source(self, graph):
        source = snd.BufferAudioSource(buffer=[0.0] * 80, sampleRate=RATE, loop=True,
                                       loopStart=0.001, loopEnd=0.005,
                                       playbackRate=2.0, detune=-1200.0)
        frame(graph, snd.AudioDestination(children=[source]))
        made = graph.audioNode(source)
        assert (made.loop, made.loop_start, made.loop_end, made.playback_rate,
                made.detune) == (True, 0.001, 0.005, 2.0, -1200.0)

    def test_an_audio_clip_plays_and_reports_its_duration(self, engine, graph):
        clip = snd.AudioClip(url=['blip'], loop=True)
        frame(graph, snd.AudioDestination(children=[clip]))
        assert clip.duration_changed == pytest.approx(0.25)
        assert clip.isActive is True
        assert strongest(mix(engine)[:, 0]) == pytest.approx(880.0, abs=8.0)

    def test_an_audio_clip_that_will_not_read_reports_no_duration(self, graph):
        clip = snd.AudioClip(url=['nowhere.wav'])
        frame(graph, snd.AudioDestination(children=[clip]))
        assert clip.duration_changed == -1.0
        assert clip.running() is False

    def test_a_looping_clip_started_earlier_plays_from_where_it_has_reached(
            self, engine, graph):
        clip = snd.AudioClip(url=['blip'], loop=True, startTime=1.0)
        frame(graph, snd.AudioDestination(children=[clip]), now=1.6)
        mix(engine, 1)
        assert graph.audioNode(clip).position == pytest.approx(0.1 * RATE + 1, abs=2)

    def test_a_clips_pitch_is_its_rate(self, graph):
        clip = snd.AudioClip(url=['blip'], pitch=2.0, loop=True)
        frame(graph, snd.AudioDestination(children=[clip]))
        assert graph.audioNode(clip).playback_rate == 2.0

    def test_a_clip_that_has_ended_is_silent(self, engine, graph):
        clip = snd.AudioClip(url=['blip'], startTime=1.0)
        destination = snd.AudioDestination(children=[clip])
        frame(graph, destination, now=1.0)
        frame(graph, destination, now=2.0)
        assert clip.isActive is False
        assert power(mix(engine)) == 0.0


class TestChannels:
    def test_a_selector_picks_a_channel_of_a_splitter(self, engine, graph):
        stereo = snd.BufferAudioSource(buffer=[0.25] * 8 + [0.75] * 8,
                                       numberOfChannels=2, sampleRate=RATE, loop=True)
        splitter = snd.ChannelSplitter(children=[stereo])
        right = snd.ChannelSelector(channelSelection=1, children=[splitter])
        frame(graph, snd.AudioDestination(children=[right]))
        block = mix(engine, 8)
        assert np.allclose(block[:, 0], 0.75) and np.allclose(block[:, 1], 0.75)

    def test_a_merger_puts_each_input_in_its_own_channel(self, engine, graph):
        left = snd.BufferAudioSource(buffer=[0.25] * 8, sampleRate=RATE, loop=True)
        right = snd.BufferAudioSource(buffer=[0.75] * 8, sampleRate=RATE, loop=True)
        frame(graph, snd.AudioDestination(children=[snd.ChannelMerger(children=[left, right])]))
        block = mix(engine, 8)
        assert np.allclose(block[:, 0], 0.25) and np.allclose(block[:, 1], 0.75)

    def test_a_splitters_outputs_each_take_one_channel(self, engine, graph):
        stereo = snd.BufferAudioSource(buffer=[0.25] * 8 + [0.75] * 8,
                                       numberOfChannels=2, sampleRate=RATE, loop=True)
        first, second = snd.Gain(), snd.Gain(gain=0.5)
        splitter = snd.ChannelSplitter(children=[stereo], outputs=[first, second])
        frame(graph, snd.AudioDestination(children=[second]), splitter)
        block = mix(engine, 8)
        assert np.allclose(block[:, 0], 0.375)


class TestSpatialSound:
    def spatial(self, **named):
        named.setdefault('children', [tone()])
        return snd.SpatialSound(**named)

    def ears(self, engine):
        block = mix(engine)
        return power(block[:, 0]), power(block[:, 1])

    def test_a_spatial_sound_on_its_own_is_heard(self, engine, graph):
        frame(graph, self.spatial())
        assert power(mix(engine)) > 0.1

    def test_a_sound_on_the_right_is_louder_on_the_right(self, engine, graph):
        frame(graph, (self.spatial(), translation(5.0)))
        left, right = self.ears(engine)
        assert right > 4 * left

    def test_the_location_is_in_the_nodes_frame(self, engine, graph):
        frame(graph, (self.spatial(location=(-5.0, 0.0, 0.0)), translation(10.0)))
        left, right = self.ears(engine)
        assert right > 4 * left

    def test_it_falls_off_with_distance(self, engine, graph):
        near = self.spatial()
        frame(graph, (near, translation(0.0, 0.0, -1.0)))
        mix(engine)
        loud = power(mix(engine))
        frame(graph, (near, translation(0.0, 0.0, -4.0)), now=1.1)
        mix(engine)
        assert power(mix(engine)) == pytest.approx(loud / 4, rel=0.05)

    def test_its_cone_quietens_what_is_behind_it(self, engine, graph):
        node = self.spatial(direction=(0.0, 0.0, -1.0), coneInnerAngle=1.0,
                            coneOuterAngle=1.5, coneOuterGain=0.0)
        frame(graph, (node, translation(0.0, 0.0, -1.0)))
        assert power(mix(engine)) == 0.0

    def test_spatialize_false_centres_it(self, engine, graph):
        frame(graph, (self.spatial(spatialize=False), translation(5.0)))
        left, right = self.ears(engine)
        assert left == pytest.approx(right, rel=1e-3)

    def test_doppler_delays_it_by_its_distance(self, graph):
        node = self.spatial(dopplerEnabled=True)
        frame(graph, (node, translation(0.0, 0.0, -34.3)))
        assert graph.audioNode(node).propagation_delay == pytest.approx(34.3 / SPEED_OF_SOUND)

    def test_intensity_and_gain_scale_it(self, engine, graph):
        frame(graph, self.spatial())
        full = power(mix(engine))
        graph.clear()
        frame(graph, self.spatial(intensity=0.5, gain=0.5))
        mix(engine)
        assert power(mix(engine)) == pytest.approx(full / 4, rel=0.05)

    def test_in_a_destination_it_is_heard_once(self, engine, graph):
        node = self.spatial()
        frame(graph, node)
        alone = power(mix(engine))
        frame(graph, snd.AudioDestination(children=[node]), node, now=1.1)
        mix(engine)
        assert power(mix(engine)) == pytest.approx(alone, rel=0.02)

    def test_it_is_heard_from_a_listening_point(self, engine, graph):
        point = snd.ListenerPointSource(position=(10.0, 0.0, 0.0))
        frame(graph, (self.spatial(), translation(5.0)), point)
        left, right = self.ears(engine)
        assert left > 4 * right

    def test_a_listening_point_tracking_the_view_is_the_camera(self, engine, graph):
        point = snd.ListenerPointSource(position=(10.0, 0.0, 0.0), trackCurrentView=True)
        frame(graph, (self.spatial(), translation(5.0)), point)
        left, right = self.ears(engine)
        assert right > 4 * left

    def test_a_listening_point_turned_round_swaps_the_ears(self, engine, graph):
        point = snd.ListenerPointSource(orientation=(0.0, 1.0, 0.0, math.pi))
        frame(graph, (self.spatial(), translation(5.0)), point)
        left, right = self.ears(engine)
        assert left > 4 * right

    def test_the_listener_given_is_used(self, engine, graph):
        frame(graph, (self.spatial(), translation(5.0)),
              listener=Listener(forward=(0.0, 0.0, 1.0)))
        left, right = self.ears(engine)
        assert left > 4 * right

    def test_priority_chooses_what_is_heard_past_the_budget(self, engine, graph):
        quiet = self.spatial(children=[tone(440.0)], priority=0.0)
        important = self.spatial(children=[tone(1000.0)], priority=1.0)
        frame(graph, quiet, important, budget=1)
        assert strongest(mix(engine)[:, 0]) == pytest.approx(1000.0, abs=8.0)

    def test_the_loudest_at_the_listener_wins_a_tie(self, engine, graph):
        far = self.spatial(children=[tone(440.0)])
        near = self.spatial(children=[tone(1000.0)])
        frame(graph, (far, translation(0, 0, -50.0)), (near, translation(0, 0, -2.0)),
              budget=1)
        assert strongest(mix(engine)[:, 0]) == pytest.approx(1000.0, abs=8.0)


class TestClassicSound:
    def sound(self, **named):
        named.setdefault('source', snd.AudioClip(url=['beep'], loop=True))
        return snd.Sound(**named)

    def test_it_plays_its_clip(self, engine, graph):
        frame(graph, self.sound())
        assert strongest(mix(engine)[:, 0]) == pytest.approx(440.0, abs=8.0)

    def test_outside_the_outer_ellipsoid_it_is_silent(self, engine, graph):
        frame(graph, (self.sound(), translation(0.0, 0.0, -100.0)))
        assert power(mix(engine)) == 0.0

    def test_inside_the_inner_ellipsoid_it_is_full(self, engine, graph):
        frame(graph, (self.sound(minFront=5.0, minBack=5.0), translation(0.0, 0.0, -1.0)))
        block = mix(engine)
        assert math.hypot(np.abs(block[:, 0]).max(), np.abs(block[:, 1]).max()) == \
            pytest.approx(1.0, rel=0.02)

    def test_intensity_scales_it(self, engine, graph):
        frame(graph, (self.sound(intensity=0.25, minFront=5.0, minBack=5.0),
                      translation(0.0, 0.0, -1.0)))
        block = mix(engine)
        assert math.hypot(np.abs(block[:, 0]).max(), np.abs(block[:, 1]).max()) == \
            pytest.approx(0.25, rel=0.02)

    def test_on_the_right_it_is_louder_on_the_right(self, engine, graph):
        frame(graph, (self.sound(minFront=50.0, minBack=50.0), translation(5.0)))
        block = mix(engine)
        assert power(block[:, 1]) > 4 * power(block[:, 0])

    def test_spatialize_false_keeps_it_centred(self, engine, graph):
        frame(graph, (self.sound(spatialize=False, minFront=50.0, minBack=50.0),
                      translation(5.0)))
        block = mix(engine)
        assert power(block[:, 0]) == pytest.approx(power(block[:, 1]), rel=1e-3)

    def test_the_ellipsoid_is_oriented_by_the_direction_field(self, engine, graph):
        """A sound facing the listener reaches further than one facing away."""
        facing = self.sound(direction=(0, 0, 1), maxFront=100.0, maxBack=2.0)
        frame(graph, (facing, translation(0.0, 0.0, -20.0)))
        mix(engine)
        ahead = power(mix(engine))
        graph.clear()
        away = self.sound(direction=(0, 0, -1), maxFront=100.0, maxBack=2.0)
        frame(graph, (away, translation(0.0, 0.0, -20.0)))
        mix(engine)
        assert ahead > 0.0 and power(mix(engine)) == 0.0

    def test_a_sound_with_no_direction_reaches_its_front_distance_every_way(
            self, engine, graph):
        frame(graph, (self.sound(direction=(0, 0, 0), maxFront=20.0, maxBack=2.0),
                      translation(0.0, 0.0, 10.0)))
        assert power(mix(engine)) > 0.0

    def test_the_location_is_in_the_nodes_frame(self, engine, graph):
        frame(graph, (self.sound(location=(0.0, 0.0, -1000.0)), translation()))
        assert power(mix(engine)) == 0.0

    def test_a_moving_sound_is_placed_again_not_restarted(self, engine, graph):
        sound = self.sound(maxFront=100.0, maxBack=100.0)
        frame(graph, (sound, translation(0.0, 0.0, -2.0)))
        made = graph.audioNode(sound)
        mix(engine)
        near = power(mix(engine))
        frame(graph, (sound, translation(0.0, 0.0, -60.0)), now=1.1)
        mix(engine)
        assert graph.audioNode(sound) is made
        assert power(mix(engine)) < near

    def test_a_stop_time_in_the_past_keeps_it_quiet(self, engine, graph):
        frame(graph, self.sound(source=snd.AudioClip(url=['beep'], loop=True,
                                                     startTime=0.5, stopTime=0.75)))
        assert power(mix(engine)) == 0.0

    def test_a_sound_with_no_source_is_silent(self, engine, graph):
        frame(graph, snd.Sound())
        assert power(mix(engine)) == 0.0

    def test_a_disabled_sound_is_silent(self, engine, graph):
        frame(graph, self.sound(enabled=False))
        assert power(mix(engine)) == 0.0


class Recorded(NullCapture):
    """A silent input that records whether it was started and closed."""

    started = closed = False

    def start(self):
        self.started = True

    def close(self):
        self.closed = True


class TestCapture:
    class Opened:
        def __init__(self):
            self.calls = []
            self.made = []

        def __call__(self, sample_rate, device='', ring=None):
            self.calls.append(device)
            capture = Recorded(sample_rate=sample_rate, ring=ring)
            self.made.append(capture)
            return capture

    @pytest.fixture
    def opened(self, monkeypatch):
        found = self.Opened()
        monkeypatch.setattr(x3dgraph, 'open_capture', found)
        return found

    def test_a_microphone_is_not_opened_unless_capture_is_allowed(self, graph, opened):
        frame(graph, snd.AudioDestination(children=[snd.MicrophoneSource()]))
        assert opened.calls == []

    def test_a_microphone_is_opened_by_its_device_name(self, graph, opened):
        frame(graph, snd.AudioDestination(children=[snd.MicrophoneSource(
            mediaDeviceID='USB')]), capture=True)
        assert opened.calls == ['USB']

    def test_what_it_captures_is_heard(self, engine, graph, opened):
        frame(graph, snd.AudioDestination(children=[snd.MicrophoneSource()]), capture=True)
        opened.made[0].ring.write(np.full(64, 0.5, dtype=np.float32))
        assert np.allclose(mix(engine, 64), 0.5)

    def test_a_stream_source_opens_the_device_it_names(self, graph, opened):
        frame(graph, snd.AudioDestination(children=[snd.StreamAudioSource(
            streamIdentifier=['Line In'])]), capture=True)
        assert opened.calls == ['Line In']

    def test_a_stopped_microphone_is_closed(self, graph, opened):
        microphone = snd.MicrophoneSource(stopTime=2.0)
        destination = snd.AudioDestination(children=[microphone])
        frame(graph, destination, capture=True)
        frame(graph, destination, now=3.0, capture=True)
        assert opened.made[0].closed
        assert len(opened.calls) == 1

    def test_closing_the_graph_closes_its_microphones(self, graph, opened):
        frame(graph, snd.AudioDestination(children=[snd.MicrophoneSource()]), capture=True)
        assert opened.made[0].started
        graph.close()
        assert opened.made[0].closed


class TestWiring:
    def test_changed_children_are_rewired(self, engine, graph):
        destination = snd.AudioDestination(children=[tone(440.0)])
        frame(graph, destination)
        destination.children = [tone(1000.0)]
        frame(graph, destination, now=1.1)
        mix(engine)
        assert strongest(mix(engine)[:, 0]) == pytest.approx(1000.0, abs=8.0)

    def test_a_cycle_is_reported_and_not_heard(self, engine, graph, caplog):
        first = snd.Gain(children=[tone()])
        second = snd.Gain(children=[first])
        first.children = [second]
        frame(graph, snd.AudioDestination(children=[second]))
        assert 'cycle' in caplog.text
        assert power(mix(engine)) == 0.0

    def test_it_reports_how_many_nodes_it_drove(self, graph):
        assert frame(graph, snd.AudioDestination(children=[snd.Gain(children=[tone()])])) == 3

    def test_nodes_no_longer_reached_are_let_go(self, graph):
        source = tone()
        destination = snd.AudioDestination(children=[source])
        frame(graph, destination)
        destination.children = []
        frame(graph, destination, now=1.1)
        assert graph.audioNode(source) is None


class TestDocuments:
    def test_an_x3d_document_builds_the_engines_nodes(self):
        from vrml import x3d as vrml_x3d
        from OpenGLContext.loaders.x3d import prototypes
        scene = vrml_x3d.loads(DOCUMENT, prototypes=prototypes())
        destination = scene.children[0]
        assert isinstance(destination, snd.AudioDestination)
        spatial = destination.children[0]
        assert isinstance(spatial, snd.SpatialSound)
        assert isinstance(spatial.children[0], snd.BiquadFilter)
        assert isinstance(spatial.children[0].children[0], snd.OscillatorSource)
        assert isinstance(spatial.children[0].children[0].periodicWave, snd.PeriodicWave)


DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile='Full' version='4.0'><Scene>
  <AudioDestination>
    <SpatialSound>
      <BiquadFilter type='LOWPASS'>
        <OscillatorSource frequency='220'>
          <PeriodicWave type='TRIANGLE'/>
        </OscillatorSource>
      </BiquadFilter>
    </SpatialSound>
  </AudioDestination>
</Scene></X3D>
"""


@pytest.mark.serial
def test_a_frame_grows_with_the_sounds(engine, check_scaling):
    """A still frame's work is linear in the sound nodes: no wiring is rebuilt."""
    def prepare(n):
        made = x3dgraph.SoundGraph(engine)
        roots = [(snd.SpatialSound(children=[snd.Gain(children=[tone()])]),
                  translation(float(index)))
                 for index in range(n)]
        made.update(roots, 1.0, budget=n // 2)
        return lambda: made.update(roots, 1.0, budget=n // 2)
    check_scaling(prepare, n=50, most=6.0)
