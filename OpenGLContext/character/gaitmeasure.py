"""Measures how far a character's feet move during animations

A locomotion clip is authored for one ground speed. Played faster or slower
than that, the feet slide. :func:`measure_stride` finds the speed by sampling
the clip: a foot that is planted moves backwards under the hips at the speed
the body moves forward, so the speed of the lower foot relative to the hips
during its stance is the body's speed in that clip. A clip with root motion
carries the hips themselves, and its speed is the hips' travel over its length.

    >>> measure_stride(model, 'Jog_Fwd_Loop')            # doctest: +SKIP
    3.6

The result is in the model's own units a second at playback rate 1.0, with
height along +Y. Multiply by the scale of the node the model is drawn under
to get the speed in the world's units. :func:`measure` also reports the clip's
length and the times in the clip at which each foot lands, which a
:class:`~OpenGLContext.character.locomotion.ClipMap` takes as ``contacts``.

The measurement poses the model while it samples. The clip is played on a layer
of its own called ``measure``, which is emptied afterwards and leaves the
model posed by its other layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = ['Stride', 'measure', 'measure_stride', 'FEET', 'ROOT_MOTION']

#: The two feet as ``(side, humanoid bone)``.
FEET = (('left', 'leftFoot'), ('right', 'rightFoot'))
#: Metres a second of net hip travel over a clip above which it counts as
#: root motion.
ROOT_MOTION = 0.05
#: The share of a foot's height range, from its lowest, that counts as on the
#: ground.
_LOW = 0.25
#: The share of the planted steps, from the slowest, at and above which the
#: speed is read: a foot comes down and leaves the ground slower than the body
#: moves, and is at the body's speed between.
_PLANTED_QUANTILE = 0.75
#: The longest run of unplanted steps between two planted ones that is read as
#: one planting broken by sampling noise.
_GAP = 3
#: The layer a clip is sampled on.
_LAYER = 'measure'


@dataclass(frozen=True)
class Stride:
    """What sampling one clip found."""

    clip: str
    #: Model units a second at rate 1.0; 0.0 for a clip that plants no foot.
    speed: float
    #: Seconds the clip lasts.
    duration: float
    #: Whether the hips travel across the clip, so ``speed`` is their travel.
    root_motion: bool
    #: ``(side, seconds into the clip)`` of each foot landing, in time order.
    contacts: tuple[tuple[str, float], ...]


def measure_stride(model: Any, clip: str, samples: int = 64) -> float:
    """The ground speed ``clip`` carries ``model`` at, at playback rate 1.0."""
    return measure(model, clip, samples).speed


def measure(model: Any, clip: str, samples: int = 64) -> Stride:
    """Sample ``clip`` ``samples`` times and report its speed and foot landings.

    Raises :class:`KeyError` for a clip the model does not carry and
    :class:`ValueError` for a model with no humanoid skeleton or no feet.
    """
    duration = float(model.clips[clip].duration)
    humanoid = model.humanoid
    if humanoid is None:
        raise ValueError('measuring a stride needs a humanoid skeleton')
    if not all(bone in humanoid for _side, bone in FEET) or 'hips' not in humanoid:
        raise ValueError('measuring a stride needs the hips and both feet')
    times = np.linspace(0.0, duration, samples + 1)
    hips, feet = _sample(model, clip, times)
    travel = hips[-1] - hips[0]
    travel[1] = 0.0
    carried = float(np.hypot(travel[0], travel[2])) / duration if duration > 0 else 0.0
    root_motion = carried > ROOT_MOTION
    planted_speeds: list[np.ndarray] = []
    contacts: list[tuple[str, float]] = []
    for (side, _bone), path in zip(FEET, feet, strict=True):
        planted, on_ground = _stance(path - hips, path[:, 1], duration / samples)
        planted_speeds.append(on_ground)
        contacts.extend((side, float(times[i]))
                        for i in _landings(_fill_gaps(planted, _GAP)))
    stance = np.concatenate(planted_speeds)
    speed = carried if root_motion else (
        float(np.quantile(stance, _PLANTED_QUANTILE)) if len(stance) else 0.0)
    return Stride(clip, speed, duration, root_motion, tuple(sorted(
        contacts, key=lambda c: c[1])))


def _sample(model: Any, clip: str, times: np.ndarray
            ) -> tuple[np.ndarray, list[np.ndarray]]:
    """The hips' and each foot's model-space position at each of ``times``."""
    layer = model.layer(_LAYER)
    track = layer.play(clip, loop=False)
    humanoid = model.humanoid
    hips = np.zeros((len(times), 3))
    feet = [np.zeros((len(times), 3)) for _ in FEET]
    try:
        for row, moment in enumerate(times):
            track.time = float(moment)
            model.mixer.apply()
            hips[row] = humanoid.position('hips')
            for path, (_side, bone) in zip(feet, FEET, strict=True):
                path[row] = humanoid.position(bone)
    finally:
        layer.tracks = []
        model.mixer.apply()
    return hips, feet


def _stance(relative: np.ndarray, height: np.ndarray, step: float
            ) -> tuple[np.ndarray, np.ndarray]:
    """Which steps of the cycle a foot is planted for, and its speed in each.

    A step is planted when the foot is low at both ends and moving along the
    direction the low steps carry it in overall: the swing that skims the
    ground on its way down moves the other way and is left out. The last sample
    repeats the first, so the steps are the cycle.
    """
    low = height <= height.min() + _LOW * (height.max() - height.min()) + 1e-9
    velocity = np.diff(relative, axis=0) / step
    velocity[:, 1] = 0.0
    low_steps = low[:-1] & low[1:]
    heading = velocity[low_steps].sum(axis=0)
    norm = float(np.linalg.norm(heading))
    if norm < 1e-12:
        return np.zeros(len(velocity), dtype=bool), np.zeros(0)
    along = velocity @ (heading / norm)
    speed = np.linalg.norm(velocity, axis=1)
    planted = low_steps & (along > 0.5 * speed) & (speed > 0)
    return planted, speed[planted]


def _landings(planted: np.ndarray) -> list[int]:
    """The steps at which a foot comes down, the cycle taken as closed."""
    return [i for i in range(len(planted)) if planted[i] and not planted[i - 1]]


def _fill_gaps(planted: np.ndarray, longest: int) -> np.ndarray:
    """``planted`` with every run of at most ``longest`` unplanted steps filled in."""
    filled = planted.copy()
    if not planted.any():
        return filled
    start = int(np.flatnonzero(planted)[0])
    rolled = np.roll(planted, -start)
    # The cycle is closed, so a run left open at the end of ``rolled`` ends at
    # its first, planted, step.
    run_from = None
    for index, value in enumerate([*rolled, True]):
        if value:
            if run_from is not None and index - run_from <= longest:
                filled[(np.arange(run_from, index) + start) % len(planted)] = True
            run_from = None
        elif run_from is None:
            run_from = index
    return filled
