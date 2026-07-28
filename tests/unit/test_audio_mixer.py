"""The mixer: a fixed pool of voices summed into stereo blocks.

Every assertion here is about an array of numbers, so the whole of the audio
path below the device is tested with no device, no thread and no hardware.
"""

import threading

import numpy as np
import pytest

from OpenGLContext.audio import synth
from OpenGLContext.audio.clip import Clip
from OpenGLContext.audio.mixer import Mixer


def constant(value=1.0, frames=1000, sample_rate=8000):
    """A clip that is the same sample all the way through."""
    return Clip(np.full(frames, value, dtype='f'), sample_rate)


#: Step between successive samples of :func:`ramp`.  Small enough that a whole
#: ramp stays inside full scale, so the mixer's output clipping never hides the
#: cursor the test is watching.
STEP = 0.1


def ramp(frames=8, sample_rate=8000):
    """A clip whose samples climb by :data:`STEP`, so a cursor is readable."""
    return Clip(np.arange(frames, dtype='f') * STEP, sample_rate)


class TestEmptyMixer:
    def test_a_mixer_with_no_voices_produces_silence(self):
        mixer = Mixer(sample_rate=8000)
        assert not mixer.mix(64).any()

    def test_the_output_block_is_stereo(self):
        assert Mixer(sample_rate=8000).mix(64).shape == (64, 2)

    def test_the_output_is_float32(self):
        assert Mixer(sample_rate=8000).mix(64).dtype == np.float32

    def test_no_voices_are_active(self):
        assert Mixer(sample_rate=8000).active_voices == 0


class TestOneVoice:
    def test_a_centred_voice_appears_equally_in_both_channels(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(constant(0.5), gain=1.0)
        block = mixer.mix(16)
        assert np.allclose(block[:, 0], block[:, 1])
        assert block[0, 0] > 0.0

    def test_a_centred_voice_is_attenuated_by_equal_power_panning(self):
        """Centre is -3 dB in each ear so the total power is the source's."""
        mixer = Mixer(sample_rate=8000)
        mixer.play(constant(1.0), gain=1.0)
        block = mixer.mix(16)
        assert block[0, 0] == pytest.approx(np.sqrt(0.5), rel=1e-3)

    def test_gain_scales_the_output(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(constant(1.0), gain=0.25)
        assert mixer.mix(16)[0, 0] == pytest.approx(0.25 * np.sqrt(0.5), rel=1e-3)

    def test_panning_hard_right_silences_the_left_channel(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(constant(1.0), pan=1.0)
        block = mixer.mix(16)
        assert block[0, 0] == pytest.approx(0.0, abs=1e-6)
        assert block[0, 1] == pytest.approx(1.0, rel=1e-3)

    def test_the_samples_come_out_in_order(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(ramp(8), gain=1.0, pan=1.0)
        assert mixer.mix(8)[:, 1] == pytest.approx(np.arange(8) * STEP, rel=1e-4)

    def test_playing_continues_across_blocks(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(ramp(8), gain=1.0, pan=1.0)
        mixer.mix(4)
        assert mixer.mix(4)[:, 1] == pytest.approx(np.arange(4, 8) * STEP, rel=1e-4)


class TestVoiceLifetime:
    def test_a_voice_stops_at_the_end_of_a_clip_that_does_not_loop(self):
        mixer = Mixer(sample_rate=8000)
        voice = mixer.play(constant(1.0, frames=4))
        mixer.mix(4)
        assert not voice.playing
        assert mixer.active_voices == 0

    def test_the_tail_of_the_block_past_the_end_is_silent(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(constant(1.0, frames=4), pan=1.0)
        block = mixer.mix(8)
        assert block[:4, 1].min() > 0.0
        assert not block[4:, 1].any()

    def test_a_looping_voice_wraps_and_keeps_playing(self):
        mixer = Mixer(sample_rate=8000)
        voice = mixer.play(ramp(4), gain=1.0, pan=1.0, loop=True)
        assert mixer.mix(8)[:, 1] == pytest.approx(
            np.array([0, 1, 2, 3, 0, 1, 2, 3]) * STEP, rel=1e-4)
        assert voice.playing

    def test_stopping_a_voice_frees_its_slot(self):
        mixer = Mixer(sample_rate=8000, voices=1)
        voice = mixer.play(constant(1.0, frames=10_000, sample_rate=8000), loop=True)
        voice.stop()
        assert mixer.active_voices == 0
        assert mixer.mix(8).max() == pytest.approx(0.0)

    def test_stop_all_silences_everything(self):
        mixer = Mixer(sample_rate=8000, voices=4)
        for _ in range(4):
            mixer.play(constant(1.0, frames=10_000), loop=True)
        mixer.stop_all()
        assert mixer.active_voices == 0

    def test_an_empty_clip_is_never_started(self):
        mixer = Mixer(sample_rate=8000)
        assert mixer.play(Clip([], 8000)) is None
        assert mixer.active_voices == 0


class TestPlaybackRate:
    def test_double_rate_consumes_the_clip_twice_as_fast(self):
        mixer = Mixer(sample_rate=8000)
        voice = mixer.play(constant(1.0, frames=8), rate=2.0)
        mixer.mix(4)
        assert not voice.playing

    def test_half_rate_stretches_the_clip(self):
        mixer = Mixer(sample_rate=8000)
        voice = mixer.play(constant(1.0, frames=8), rate=0.5)
        mixer.mix(8)
        assert voice.playing

    def test_a_clip_at_another_rate_is_resampled_to_the_mixer_rate(self):
        """The mixer runs at one rate; a clip's own rate is a playback ratio."""
        mixer = Mixer(sample_rate=16000)
        voice = mixer.play(constant(1.0, frames=8, sample_rate=8000))
        mixer.mix(15)
        assert voice.playing                    # 8 frames at half speed = 16
        mixer.mix(2)
        assert not voice.playing

    def test_interpolation_between_samples_is_linear(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(ramp(8), gain=1.0, pan=1.0, rate=0.5)
        assert mixer.mix(4)[:, 1] == pytest.approx(
            np.array([0.0, 0.5, 1.0, 1.5]) * STEP, rel=1e-4)

    def test_a_non_positive_rate_is_refused_rather_than_looping_forever(self):
        mixer = Mixer(sample_rate=8000)
        assert mixer.play(constant(1.0), rate=0.0) is None


class TestGainRamping:
    """A gain that jumps between blocks is a click; the mixer ramps instead."""

    def test_a_changed_gain_is_reached_by_the_end_of_the_block(self):
        mixer = Mixer(sample_rate=8000)
        voice = mixer.play(constant(1.0, frames=10_000), gain=1.0, pan=1.0)
        mixer.mix(16)
        voice.set_gain(0.0, 0.0)
        block = mixer.mix(16)
        assert block[0, 1] > 0.0                        # not an instant jump
        assert block[-1, 1] == pytest.approx(0.0, abs=1e-6)

    def test_the_ramp_is_monotonic_rather_than_a_step(self):
        mixer = Mixer(sample_rate=8000)
        voice = mixer.play(constant(1.0, frames=10_000), gain=0.0, pan=1.0)
        mixer.mix(8)
        voice.set_gain(0.0, 1.0)
        channel = mixer.mix(8)[:, 1]
        assert np.all(np.diff(channel) > 0)

    def test_a_new_voice_starts_at_its_gain_without_a_ramp(self):
        """Ramping in would soften the transient that makes an impact read."""
        mixer = Mixer(sample_rate=8000)
        mixer.play(constant(1.0), gain=1.0, pan=1.0)
        assert mixer.mix(16)[0, 1] == pytest.approx(1.0, rel=1e-3)


class TestSumming:
    def test_two_voices_add(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(constant(0.25), pan=1.0)
        mixer.play(constant(0.25), pan=1.0)
        assert mixer.mix(8)[0, 1] == pytest.approx(0.5, rel=1e-3)

    def test_the_master_gain_scales_the_whole_mix(self):
        mixer = Mixer(sample_rate=8000, master_gain=0.5)
        mixer.play(constant(1.0), pan=1.0)
        assert mixer.mix(8)[0, 1] == pytest.approx(0.5, rel=1e-3)

    def test_the_output_is_clipped_rather_than_allowed_to_wrap(self):
        mixer = Mixer(sample_rate=8000, voices=8)
        for _ in range(8):
            mixer.play(constant(1.0), pan=1.0)
        assert mixer.mix(8).max() == pytest.approx(1.0)


class TestVoicePool:
    """A fixed pool, so a scene that fires a thousand sounds costs a fixed amount."""

    def test_the_pool_size_is_the_limit_on_simultaneous_sounds(self):
        mixer = Mixer(sample_rate=8000, voices=3)
        for _ in range(3):
            assert mixer.play(constant(1.0, frames=10_000), priority=0.5) is not None
        assert mixer.active_voices == 3

    def test_a_higher_priority_sound_steals_the_lowest_priority_voice(self):
        mixer = Mixer(sample_rate=8000, voices=2)
        quiet = mixer.play(constant(1.0, frames=10_000), priority=0.1)
        mixer.play(constant(1.0, frames=10_000), priority=0.9)
        assert mixer.play(constant(1.0, frames=10_000), priority=0.5) is not None
        assert not quiet.playing

    def test_a_lower_priority_sound_is_refused_when_the_pool_is_full(self):
        mixer = Mixer(sample_rate=8000, voices=1)
        mixer.play(constant(1.0, frames=10_000), priority=0.8)
        assert mixer.play(constant(1.0, frames=10_000), priority=0.2) is None

    def test_among_equal_priorities_the_quietest_voice_is_stolen(self):
        """Stealing the least audible sound is the least audible theft."""
        mixer = Mixer(sample_rate=8000, voices=2)
        faint = mixer.play(constant(1.0, frames=10_000), priority=0.5, gain=0.01)
        mixer.play(constant(1.0, frames=10_000), priority=0.5, gain=1.0)
        assert mixer.play(constant(1.0, frames=10_000), priority=0.5, gain=0.9) is not None
        assert not faint.playing

    def test_an_equal_priority_quieter_sound_is_refused(self):
        mixer = Mixer(sample_rate=8000, voices=1)
        mixer.play(constant(1.0, frames=10_000), priority=0.5, gain=1.0)
        assert mixer.play(constant(1.0, frames=10_000), priority=0.5, gain=0.001) is None

    def test_a_finished_voice_is_reused_rather_than_stolen_from(self):
        mixer = Mixer(sample_rate=8000, voices=1)
        mixer.play(constant(1.0, frames=4), priority=0.9)
        mixer.mix(8)
        assert mixer.play(constant(1.0, frames=4), priority=0.0) is not None

    def test_voices_report_themselves_for_a_debug_overlay(self):
        mixer = Mixer(sample_rate=8000, voices=4)
        mixer.play(constant(1.0, frames=10_000))
        assert mixer.active_voices == 1
        assert len(mixer.voices) == 4


class TestAllocationDiscipline:
    """The audio thread must not allocate; the buffers are made once."""

    def test_every_block_is_a_view_of_the_same_buffer(self):
        mixer = Mixer(sample_rate=8000)
        assert mixer.mix(64).base is mixer.mix(32).base

    def test_a_block_larger_than_the_maximum_is_refused(self):
        mixer = Mixer(sample_rate=8000, max_block=128)
        with pytest.raises(ValueError):
            mixer.mix(129)

    def test_mixing_a_full_pool_allocates_nothing_measurable(self):
        import tracemalloc

        mixer = Mixer(sample_rate=8000, voices=16, max_block=512)
        for _ in range(16):
            mixer.play(constant(0.1, frames=100_000), loop=True)
        mixer.mix(256)                                  # warm any lazy state
        tracemalloc.start()
        before = tracemalloc.take_snapshot()
        for _ in range(20):
            mixer.mix(256)
        after = tracemalloc.take_snapshot()
        tracemalloc.stop()
        grew = sum(entry.size_diff for entry in after.compare_to(before, 'filename'))
        assert grew < 4096, 'mixing allocated %d bytes' % (grew,)


class TestDeviceGenerator:
    """The pull generator a playback device drives."""

    def test_the_generator_yields_a_block_of_the_requested_size(self):
        mixer = Mixer(sample_rate=8000, max_block=512)
        blocks = mixer.blocks()
        next(blocks)
        data = blocks.send(64)
        assert len(memoryview(data).cast('B')) == 64 * 2 * 4

    def test_the_generator_keeps_producing(self):
        mixer = Mixer(sample_rate=8000)
        blocks = mixer.blocks()
        next(blocks)
        for _ in range(4):
            assert blocks.send(32) is not None

    def test_a_request_larger_than_the_maximum_is_served_as_silence(self):
        """A device asking for more than the mixer prepared must not raise
        inside the audio callback; it gets silence and a logged warning."""
        mixer = Mixer(sample_rate=8000, max_block=64)
        blocks = mixer.blocks()
        next(blocks)
        data = np.asarray(blocks.send(128))
        assert not data.any()


class TestThreadSafety:
    """Starting sounds from several threads must not hand out one slot twice."""

    def test_concurrent_plays_never_share_a_voice(self):
        """Sixty-four sounds into a sixty-four voice pool must all survive.

        Two threads handed the same slot would leave fewer playing, since the
        second would silently overwrite the first.
        """
        mixer = Mixer(sample_rate=8000, voices=64)
        barrier = threading.Barrier(8)

        def start():
            barrier.wait()
            for _ in range(8):
                mixer.play(constant(1.0, frames=100_000), loop=True)

        threads = [threading.Thread(target=start) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert mixer.active_voices == 64


class TestStolenVoices:
    """A handle whose slot was recycled must steer nothing, not somebody else."""

    def test_a_stolen_handle_reports_that_it_has_stopped(self):
        mixer = Mixer(sample_rate=8000, voices=1)
        quiet = mixer.play(constant(1.0, frames=10_000), priority=0.1, loop=True)
        mixer.play(constant(1.0, frames=10_000), priority=0.9, loop=True)
        assert not quiet.playing

    def test_a_stolen_handle_cannot_change_the_new_sounds_gain(self):
        mixer = Mixer(sample_rate=8000, voices=1)
        quiet = mixer.play(constant(1.0, frames=10_000), priority=0.1, loop=True)
        loud = mixer.play(constant(1.0, frames=10_000), priority=0.9, loop=True,
                          gain=1.0, pan=1.0)
        quiet.set_gain(0.0, 0.0)
        assert mixer.mix(8)[0, 1] == pytest.approx(1.0, rel=1e-3)
        assert loud.playing

    def test_a_stolen_handle_cannot_stop_the_new_sound(self):
        mixer = Mixer(sample_rate=8000, voices=1)
        quiet = mixer.play(constant(1.0, frames=10_000), priority=0.1, loop=True)
        mixer.play(constant(1.0, frames=10_000), priority=0.9, loop=True)
        quiet.stop()
        assert mixer.active_voices == 1

    def test_a_finished_handle_is_inert_rather_than_an_error(self):
        mixer = Mixer(sample_rate=8000)
        handle = mixer.play(constant(1.0, frames=4))
        mixer.mix(8)
        handle.set_gain(1.0, 1.0)
        handle.set_gain_pan(1.0, 0.5)
        handle.stop()
        assert not handle.playing
        assert handle.elapsed == 0.0

    def test_a_playing_handle_reports_how_far_it_has_got(self):
        mixer = Mixer(sample_rate=8000)
        handle = mixer.play(constant(1.0, frames=8000, sample_rate=8000))
        mixer.mix(800)
        assert handle.elapsed == pytest.approx(0.1, rel=1e-3)


def test_a_synthesised_clip_plays_through_the_same_path_as_a_decoded_one():
    mixer = Mixer(sample_rate=8000)
    mixer.play(synth.tone(440.0, 0.1, sample_rate=8000), gain=1.0, pan=1.0)
    assert np.abs(mixer.mix(256)[:, 1]).max() > 0.1


class TestMuffle:
    """A low-pass on the master bus: what being underwater sounds like."""

    def test_a_dry_mixer_leaves_the_signal_alone(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(ramp(8), gain=1.0, pan=1.0)
        assert mixer.mix(8)[:, 1] == pytest.approx(np.arange(8) * STEP, rel=1e-4)

    def test_muffling_removes_the_high_frequencies(self):
        """A 3 kHz tone at 8 kHz is near Nyquist, so a low-pass eats it."""
        loud = synth.tone(3000.0, 0.5, sample_rate=8000, amplitude=0.9, fade=0.0)
        dry, wet = [], []
        for muffle, out in ((0.0, dry), (1.0, wet)):
            mixer = Mixer(sample_rate=8000, muffle=muffle)
            mixer.play(loud, gain=1.0, pan=1.0)
            mixer.mix(512)                              # let the filter settle
            out.append(float(np.abs(mixer.mix(512)[:, 1]).max()))
        assert wet[0] < dry[0] * 0.25

    def test_muffling_leaves_the_low_frequencies_alone(self):
        quiet = synth.tone(100.0, 0.5, sample_rate=8000, amplitude=0.9, fade=0.0)
        levels = []
        for muffle in (0.0, 1.0):
            mixer = Mixer(sample_rate=8000, muffle=muffle)
            mixer.play(quiet, gain=1.0, pan=1.0)
            mixer.mix(512)
            levels.append(float(np.abs(mixer.mix(512)[:, 1]).max()))
        assert levels[1] == pytest.approx(levels[0], rel=0.15)

    def test_the_muffle_can_be_changed_while_playing(self):
        mixer = Mixer(sample_rate=8000)
        mixer.play(synth.tone(3000.0, 1.0, sample_rate=8000, fade=0.0),
                   gain=1.0, pan=1.0, loop=True)
        mixer.mix(256)
        mixer.muffle = 1.0
        mixer.mix(256)
        assert float(np.abs(mixer.mix(256)[:, 1]).max()) < 0.2

    def test_the_muffle_is_clamped_to_a_sensible_range(self):
        mixer = Mixer(sample_rate=8000)
        mixer.muffle = 5.0
        assert mixer.muffle == 1.0
        mixer.muffle = -3.0
        assert mixer.muffle == 0.0

    def test_muffling_does_not_break_the_allocation_discipline(self):
        import tracemalloc

        mixer = Mixer(sample_rate=8000, voices=4, max_block=512, muffle=0.6)
        for _ in range(4):
            mixer.play(constant(0.1, frames=100_000), loop=True)
        mixer.mix(256)
        tracemalloc.start()
        before = tracemalloc.take_snapshot()
        for _ in range(20):
            mixer.mix(256)
        after = tracemalloc.take_snapshot()
        tracemalloc.stop()
        grew = sum(entry.size_diff for entry in after.compare_to(before, 'filename'))
        assert grew < 4096, 'muffled mixing allocated %d bytes' % (grew,)

    def test_the_filter_carries_across_block_boundaries(self):
        """A filter reset each block would tick at the seam."""
        mixer = Mixer(sample_rate=8000, muffle=1.0)
        mixer.play(constant(1.0, frames=10_000), gain=1.0, pan=1.0)
        first = mixer.mix(32)[:, 1].copy()
        second = mixer.mix(32)[:, 1]
        assert second[0] == pytest.approx(first[-1], abs=0.05)
