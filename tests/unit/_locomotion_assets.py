"""A walking rig built in memory, for the locomotion and stride tests.

The skeleton is :data:`~._character_assets.SKELETON`. :func:`walker_glb` puts
clips on it: :func:`striding` for a clip whose feet plant and slide back at a
speed known from the keys, :func:`waving` for any other clip of a given length.
"""

import numpy as np
from pygltflib import (
    GLTF2, Accessor, Animation, AnimationChannel, AnimationChannelTarget,
    AnimationSampler, Buffer, BufferView, Node, Scene,
)

from ._character_assets import SKELETON

LABELS = [name for name, _ in SKELETON]
HIPS = LABELS.index('Hips')
LEFT_FOOT = LABELS.index('LeftFoot')
RIGHT_FOOT = LABELS.index('RightFoot')
RIGHT_ARM = LABELS.index('RightArm')

#: Breakpoints of one foot's cycle as (fraction of the cycle, forward offset in
#: metres, height above the rest in metres): planted for the first 0.6 of the
#: cycle while the foot slides back 1 m, then lifted and swung forward.
FOOT_CYCLE = ((0.0, 0.5, 0.0), (0.6, -0.5, 0.0), (0.8, 0.0, 0.3), (1.0, 0.5, 0.0))
#: The fraction of the cycle a foot is planted for.
PLANTED = 0.6


def _cycle_value(fraction):
    fractions = [row[0] for row in FOOT_CYCLE]
    return (np.interp(fraction, fractions, [row[1] for row in FOOT_CYCLE]),
            np.interp(fraction, fractions, [row[2] for row in FOOT_CYCLE]))


def foot_channels(node, duration, shift):
    """Translation keys for a foot that follows :data:`FOOT_CYCLE`.

    ``shift`` is the fraction of the cycle the foot is ahead by. Every
    breakpoint of the cycle is a key, so linear interpolation reproduces the
    cycle exactly.
    """
    fractions = {0.0, 1.0}
    fractions.update((row[0] - shift) % 1.0 for row in FOOT_CYCLE)
    keys = sorted(fractions)
    values = []
    for fraction in keys:
        forward, lift = _cycle_value((fraction + shift) % 1.0)
        values.append([0.0, 0.1 + lift, forward])
    # The cycle is closed: the last key repeats the first.
    values[-1] = values[0]
    return (node, 'translation', [k * duration for k in keys], values)


def striding(duration=1.0, hips_travel=0.0):
    """A clip whose feet plant for :data:`PLANTED` of ``duration``.

    Each foot slides back 1 m over its planted time, so the body it carries
    goes ``1 / (PLANTED * duration)`` metres a second. ``hips_travel`` moves
    the hips that far forward over the clip as well, as root motion does.
    """
    channels = [foot_channels(LEFT_FOOT, duration, 0.0),
                foot_channels(RIGHT_FOOT, duration, 0.5)]
    if hips_travel:
        channels.append((HIPS, 'translation', [0.0, duration],
                         [[0.0, 0.1, 0.0], [0.0, 0.1, hips_travel]]))
    return channels


def marching(duration):
    """A clip whose feet lift and fall where they are, going nowhere."""
    keys = [0.0, 0.5 * duration, duration]
    return [(node, 'translation', keys,
             [[0.0, 0.1, 0.0], [0.0, 0.4, 0.0], [0.0, 0.1, 0.0]])
            for node in (LEFT_FOOT, RIGHT_FOOT)]


def waving(duration):
    """A clip of ``duration`` seconds that swings the right arm."""
    half = np.sin(np.pi / 4)
    return [(RIGHT_ARM, 'rotation', [0.0, duration],
             [[0, 0, 0, 1], [0, 0, half, half]])]


def walker_glb(clips):
    """The skeleton, with ``clips`` (name to channel list) as its animations."""
    blob = b''
    views = []
    accessors = []

    def add(array, kind):
        nonlocal blob
        raw = np.ascontiguousarray(array, dtype='<f4')
        views.append(BufferView(buffer=0, byteOffset=len(blob),
                                byteLength=raw.nbytes))
        blob += raw.tobytes()
        accessors.append(Accessor(
            bufferView=len(views) - 1, componentType=5126, count=len(raw),
            type=kind,
            min=raw.min(0).tolist() if raw.ndim > 1 else [float(raw.min())],
            max=raw.max(0).tolist() if raw.ndim > 1 else [float(raw.max())]))
        return len(accessors) - 1

    animations = []
    for name, channels in clips.items():
        samplers, targets = [], []
        for node, path, times, values in channels:
            samplers.append(AnimationSampler(
                input=add(np.asarray(times), 'SCALAR'),
                output=add(np.asarray(values),
                           'VEC4' if path == 'rotation' else 'VEC3'),
                interpolation='LINEAR'))
            targets.append(AnimationChannel(
                sampler=len(samplers) - 1,
                target=AnimationChannelTarget(node=node, path=path)))
        animations.append(Animation(name=name, samplers=samplers,
                                    channels=targets))
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(name=label, children=list(kids), translation=[0.0, 0.1, 0.0])
               for label, (_, kids) in zip(LABELS, SKELETON, strict=True)]
    g.accessors = accessors
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = animations
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())
