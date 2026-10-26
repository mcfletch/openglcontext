"""Sounds made in code, and how far a sound carries.

A game plays files: ``context.audio.play('thud.ogg')``. A tutorial, a test or
a prototype makes its sounds from arithmetic instead, and this module holds
the makers, from :mod:`omi_audio.synth`, under the engine's name::

    from OpenGLContext.audio import sounds

    THUD = sounds.impact(0.25, decay=18.0, seed=7)
    context.audio.play(THUD, at=hit.point, emitter=sounds.positional(near=3.0))

Each maker returns a :class:`~omi_audio.clip.Clip`, which
:meth:`~OpenGLContext.audio.manager.Audio.play` takes where it takes a path.
Durations are in seconds, frequencies in hertz and amplitudes from 0 to 1.

``tone``
    A sine with optional harmonics: a beep, a drone, a note.
``chirp``
    A sweep from one frequency to another.
``noise``
    White noise: wind, static.
``impact``
    Noise under a sharp decay: a crack, a tap.
``rumble``
    Low-passed noise over a falling tone: a detonation, a motor, a thud.
``silence``
    A clip of nothing, for padding a :func:`sequence`.
``surf``, ``birdsong``
    Ambient beds that loop.
``reverberated``, ``echoed``
    A clip with a room's tail or an echo added.
"""
from __future__ import annotations

import numpy as np
from omi_audio import model
from omi_audio.clip import Clip
from omi_audio.spatial import DistanceModel
from omi_audio.synth import (
    birdsong, chirp, echoed, impact, noise, reverberated, rumble, silence, surf, tone,
)

__all__ = [
    'Clip', 'birdsong', 'chirp', 'echoed', 'impact', 'noise', 'positional', 'reverberated',
    'rumble', 'sequence', 'silence', 'surf', 'tone',
]

#: The names ``positional`` takes for how gain falls off past ``near``.
CURVES = tuple(member.value for member in DistanceModel)


def sequence(*clips: Clip, name: str = '') -> Clip:
    """One clip that plays ``clips`` one after another: a run of notes, a two-part chime.

    The clips share one sample rate; ValueError otherwise, or for none.
    """
    if not clips:
        raise ValueError('a sequence takes at least one clip')
    rate = clips[0].sample_rate
    if any(clip.sample_rate != rate for clip in clips):
        raise ValueError('every clip of a sequence has one sample rate, not %s' % (
            sorted({clip.sample_rate for clip in clips}),))
    return Clip(np.concatenate([clip.samples for clip in clips]), rate, name=name)


def positional(near: float = 1.0, rolloff: float = 1.0, far: float = 0.0,
               curve: str = 'inverse') -> model.AudioEmitter:
    """An emitter for :meth:`~OpenGLContext.audio.manager.Audio.play` that fades with distance.

    The sound is at full gain within ``near`` metres of the listener and falls
    off beyond it, faster the larger ``rolloff`` is: under 1 carries, over 1
    dies quickly. ``far`` is where a ``'linear'`` curve reaches silence (0
    for none). ``curve`` is ``'inverse'``, ``'linear'`` or ``'exponential'``,
    the distance models of ``KHR_audio_emitter``.
    """
    if not near > 0.0:
        raise ValueError('near is a distance above zero, not %r' % (near,))
    if not rolloff >= 0.0 or not far >= 0.0:
        raise ValueError('rolloff and far are zero or more, not %r and %r' % (rolloff, far))
    if curve not in CURVES:
        raise ValueError('curve is one of %s, not %r' % (', '.join(CURVES), curve))
    return model.AudioEmitter(positional=model.PositionalProperties(
        distanceModel=curve, refDistance=float(near), rolloffFactor=float(rolloff),
        maxDistance=float(far)))
