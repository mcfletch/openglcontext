"""Sounds made out of arithmetic rather than out of files.

Demonstrations and tests need something audible.  Shipping audio files would
mean shipping their licences, so the sounds here are generated: a tone, a noise
burst, a swept chirp and a percussive impact are enough to hear a distance
curve, a pan and a voice pool working, and they cost nothing to redistribute.

They are also useful in their own right as placeholders while real content is
being made -- a game with a synthesised gunshot is a game that can be played and
tuned, which is the point of a placeholder.

Every function returns a :class:`~OpenGLContext.audio.clip.Clip`, so a
synthesised sound is played by exactly the same path as a decoded one.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from OpenGLContext.audio.clip import DEFAULT_SAMPLE_RATE, Clip

#: Seconds of fade at each end of a generated tone.  A waveform that starts at
#: full amplitude starts with a step, and a step is a click.
DEFAULT_FADE = 0.01


def _time_base(duration: float, sample_rate: int) -> np.ndarray:
    """Sample times in seconds for a clip of ``duration``."""
    return np.arange(max(0, int(duration * sample_rate)), dtype=np.float64) / sample_rate


def _fade_window(frames: int, sample_rate: int, fade: float) -> np.ndarray:
    """A 1.0 envelope with linear ramps of ``fade`` seconds at each end."""
    window = np.ones(frames, dtype=np.float32)
    ramp = min(int(fade * sample_rate), frames // 2)
    if ramp > 0:
        edge = np.linspace(0.0, 1.0, ramp, endpoint=False, dtype=np.float32)
        window[:ramp] = edge
        window[frames - ramp:] = edge[::-1]
    return window


def silence(duration: float, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Clip:
    """A clip of nothing.  Useful as a placeholder that occupies real time."""
    return Clip(np.zeros(max(0, int(duration * sample_rate)), dtype=np.float32),
                sample_rate, name='silence')


def tone(frequency: float, duration: float, sample_rate: int = DEFAULT_SAMPLE_RATE,
         amplitude: float = 0.5, fade: float = DEFAULT_FADE) -> Clip:
    """A sine wave, faded in and out so it starts and stops without clicking."""
    times = _time_base(duration, sample_rate)
    samples = (amplitude * np.sin(2.0 * np.pi * frequency * times)).astype(np.float32)
    if samples.size:
        samples *= _fade_window(samples.size, sample_rate, fade)
    return Clip(samples, sample_rate, name='tone %gHz' % (frequency,))


def chirp(start: float, end: float, duration: float,
          sample_rate: int = DEFAULT_SAMPLE_RATE, amplitude: float = 0.5,
          fade: float = DEFAULT_FADE) -> Clip:
    """A sine sweeping linearly from ``start`` to ``end`` hertz.

    The phase is the integral of the instantaneous frequency, not the frequency
    times the time; getting that wrong produces a sweep that ends at the wrong
    pitch and is the classic mistake here.
    """
    times = _time_base(duration, sample_rate)
    if not times.size:
        return Clip(np.zeros(0, dtype=np.float32), sample_rate, name='chirp')
    rate = (end - start) / max(times[-1], 1e-9)
    phase = 2.0 * np.pi * (start * times + 0.5 * rate * times * times)
    samples = (amplitude * np.sin(phase)).astype(np.float32)
    samples *= _fade_window(samples.size, sample_rate, fade)
    return Clip(samples, sample_rate, name='chirp %g-%gHz' % (start, end))


def noise(duration: float, sample_rate: int = DEFAULT_SAMPLE_RATE,
          amplitude: float = 0.5, seed: Optional[int] = None,
          fade: float = DEFAULT_FADE) -> Clip:
    """Uniform white noise.  Wind, static, the raw material of an impact."""
    generator = np.random.default_rng(seed)
    frames = max(0, int(duration * sample_rate))
    samples = generator.uniform(-amplitude, amplitude, frames).astype(np.float32)
    if samples.size:
        samples *= _fade_window(samples.size, sample_rate, fade)
    return Clip(samples, sample_rate, name='noise')


def impact(duration: float, sample_rate: int = DEFAULT_SAMPLE_RATE,
           amplitude: float = 0.9, seed: Optional[int] = None,
           decay: float = 12.0) -> Clip:
    """A percussive hit: noise under a sharp exponential decay.

    ``decay`` is the exponent's rate -- larger is shorter and drier.  The attack
    is instantaneous on purpose; a transient is what makes a hit read as a hit.
    """
    times = _time_base(duration, sample_rate)
    generator = np.random.default_rng(seed)
    samples = generator.uniform(-1.0, 1.0, times.size)
    samples *= amplitude * np.exp(-decay * times)
    return Clip(samples.astype(np.float32), sample_rate, name='impact')
