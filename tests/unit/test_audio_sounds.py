"""OpenGLContext.audio.sounds: clips made in code, and how far a sound carries."""
from __future__ import annotations

import numpy as np
import pytest
from omi_audio import model, synth
from omi_audio.clip import Clip

from OpenGLContext.audio import sounds


@pytest.mark.parametrize('name', ['tone', 'chirp', 'noise', 'impact', 'rumble', 'silence',
                                  'surf', 'birdsong', 'reverberated', 'echoed'])
def test_each_maker_is_the_synth_function_of_that_name(name):
    assert getattr(sounds, name) is getattr(synth, name)
    assert name in sounds.__all__


def test_clip_is_the_engine_clip():
    assert sounds.Clip is Clip


def test_a_sequence_plays_its_clips_one_after_another():
    first = sounds.tone(440.0, 0.1, sample_rate=8000)
    second = sounds.tone(880.0, 0.2, sample_rate=8000)
    joined = sounds.sequence(first, second, name='two')
    assert joined.sample_rate == 8000
    assert joined.name == 'two'
    assert len(joined.samples) == len(first.samples) + len(second.samples)
    assert np.array_equal(joined.samples[len(first.samples):], second.samples)


def test_a_sequence_of_clips_at_different_rates_is_refused():
    with pytest.raises(ValueError, match='sample rate'):
        sounds.sequence(sounds.tone(440.0, 0.1, sample_rate=8000),
                        sounds.tone(440.0, 0.1, sample_rate=16000))


def test_an_empty_sequence_is_refused():
    with pytest.raises(ValueError, match='at least one'):
        sounds.sequence()


def test_positional_is_an_emitter_that_falls_off_past_near():
    emitter = sounds.positional(near=3.0, rolloff=0.8)
    assert isinstance(emitter, model.AudioEmitter)
    assert emitter.type == 'positional'
    assert emitter.positional.refDistance == 3.0
    assert emitter.positional.rolloffFactor == 0.8
    assert emitter.positional.gain(2.0) == pytest.approx(1.0)
    assert emitter.positional.gain(30.0) < emitter.positional.gain(10.0) < 1.0


def test_positional_takes_a_far_limit_and_a_curve():
    emitter = sounds.positional(near=2.0, far=20.0, curve='linear')
    assert emitter.positional.maxDistance == 20.0
    assert emitter.positional.distanceModel == 'linear'
    assert emitter.positional.gain(20.0) == pytest.approx(0.0)


@pytest.mark.parametrize('bad', [{'near': 0.0}, {'near': -1.0}, {'rolloff': -0.1},
                                 {'far': -1.0}, {'curve': 'cubic'}])
def test_positional_refuses_what_no_curve_means(bad):
    with pytest.raises(ValueError):
        sounds.positional(**bad)
