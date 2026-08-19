"""A rigged figure of realistic size, built in memory for the crowd benchmark.

The scaling work is only meaningful against content of the shape a game
actually ships: a skeleton of tens of joints, a few thousand skinned vertices,
and a couple of dozen clips of which most channels hold one value for their
whole length -- which is what an exporter writes, because it writes every joint
whether or not that joint moves in that clip.

Built here rather than fetched so the benchmark needs no asset checkout, and
sized by argument so the same harness can ask what a heavier rig costs.
"""

import numpy as np
from pygltflib import (
    GLTF2, Accessor, Animation, AnimationChannel, AnimationChannelTarget,
    AnimationSampler, Attributes, Buffer, BufferView, Mesh, Node, Primitive,
    Scene, Skin,
)

#: How a fifty-seven bone humanoid is shaped: a spine with limbs off it, five
#: or six deep. The benchmark rig follows the same proportions at any size.
BRANCHING = 3


def _skeleton(joints):
    """(children, translations) for a tree of ``joints`` nodes, spine-shaped."""
    children = {i: [] for i in range(joints)}
    parents = [-1] * joints
    frontier = [0]
    following = []
    index = 1
    while index < joints:
        parent = frontier.pop(0) if frontier else following.pop(0)
        for _ in range(BRANCHING):
            if index >= joints:
                break
            children[parent].append(index)
            parents[index] = parent
            following.append(index)
            index += 1
        if not frontier:
            frontier, following = following, []
    return children, parents


def crowd_character_glb(joints=57, vertices=4096, clips=23, keys=21,
                        moving=8, seed=11):
    """A rig of ``joints`` bones, ``vertices`` skinned vertices and ``clips`` clips.

    Each clip carries a channel per joint per path, as an exported one does,
    of which ``moving`` joints' rotations actually vary; the rest hold a single
    value, which is the shape the sampler's grouping is built for.
    """
    rng = np.random.default_rng(seed)
    children, parents = _skeleton(joints)

    strip = int(np.ceil(vertices / 2.0))
    heights = np.linspace(0.0, 2.0, strip)
    position = np.empty((strip * 2, 3), dtype='<f4')
    normal = np.zeros((strip * 2, 3), dtype='<f4')
    position[0::2] = np.stack([np.full(strip, -0.25), heights,
                               np.zeros(strip)], axis=1)
    position[1::2] = np.stack([np.full(strip, 0.25), heights,
                               np.zeros(strip)], axis=1)
    normal[:, 2] = 1.0
    index = []
    for row in range(strip - 1):
        base = row * 2
        index += [base, base + 1, base + 3, base, base + 3, base + 2]
    index = np.asarray(index, dtype='<u4')

    # Every vertex is held by four joints picked around its height, which is
    # what makes the palette fetch in the shader a real four-matrix blend.
    reach = np.clip((heights / 2.0 * joints).astype(int), 0, joints - 1)
    bound = np.repeat(reach, 2)
    skin_joints = np.stack([(bound + offset) % joints for offset in range(4)],
                           axis=1).astype('<u2')
    skin_weights = rng.random((len(position), 4)).astype('f8') + 0.1
    skin_weights /= skin_weights.sum(axis=1, keepdims=True)
    skin_weights = skin_weights.astype('<f4')

    inverse_bind = np.tile(np.eye(4), (joints, 1, 1)).astype('<f4')
    still_times = np.array([0.0, 1.0], dtype='<f4')
    moving_times = np.linspace(0.0, 1.0, keys).astype('<f4')

    arrays = [position, normal, skin_joints, skin_weights, index, inverse_bind,
              still_times, moving_times]
    accessors = [
        Accessor(bufferView=0, componentType=5126, count=len(position),
                 type='VEC3', min=position.min(0).tolist(),
                 max=position.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(normal), type='VEC3'),
        Accessor(bufferView=2, componentType=5123, count=len(skin_joints),
                 type='VEC4'),
        Accessor(bufferView=3, componentType=5126, count=len(skin_weights),
                 type='VEC4'),
        Accessor(bufferView=4, componentType=5125, count=len(index), type='SCALAR'),
        Accessor(bufferView=5, componentType=5126, count=joints, type='MAT4'),
        Accessor(bufferView=6, componentType=5126, count=2, type='SCALAR',
                 min=[0.0], max=[1.0]),
        Accessor(bufferView=7, componentType=5126, count=keys, type='SCALAR',
                 min=[0.0], max=[1.0]),
    ]
    animations = []
    for clip in range(clips):
        samplers, channels = [], []
        still_translation = _accessor(arrays, accessors, 6,
                                      np.zeros((2, 3), dtype='<f4'), 'VEC3')
        still_scale = _accessor(arrays, accessors, 6,
                                np.ones((2, 3), dtype='<f4'), 'VEC3')
        still_rotation = _accessor(
            arrays, accessors, 6,
            np.tile(np.array([0, 0, 0, 1], dtype='<f4'), (2, 1)), 'VEC4')
        for path, output in (('translation', still_translation),
                             ('scale', still_scale), ('rotation', still_rotation)):
            for joint in range(joints):
                samplers.append(AnimationSampler(input=6, output=output,
                                                 interpolation='STEP'))
                channels.append(AnimationChannel(
                    sampler=len(samplers) - 1,
                    target=AnimationChannelTarget(node=joint, path=path)))
        turn = np.zeros((keys, 4), dtype='<f4')
        angle = np.linspace(0.0, np.pi / 3 * (1 + clip % 3), keys)
        turn[:, 2] = np.sin(angle / 2)
        turn[:, 3] = np.cos(angle / 2)
        curve = _accessor(arrays, accessors, 7, turn, 'VEC4')
        for step in range(moving):
            joint = (step * max(1, joints // max(1, moving))) % joints
            samplers.append(AnimationSampler(input=7, output=curve,
                                             interpolation='LINEAR'))
            channels.append(AnimationChannel(
                sampler=len(samplers) - 1,
                target=AnimationChannelTarget(node=joint, path='rotation')))
        animations.append(Animation(name='clip%02d' % clip, samplers=samplers,
                                    channels=channels))

    blob, spans = _pack(arrays)
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0, joints])]
    g.nodes = [Node(name='joint%03d' % i, children=list(children[i]) or None,
                    translation=[0.0, 2.0 / max(1, joints), 0.0])
               for i in range(joints)]
    g.nodes.append(Node(name='Body', mesh=0, skin=0))
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, NORMAL=1, JOINTS_0=2, WEIGHTS_0=3),
        indices=4)])]
    g.skins = [Skin(joints=list(range(joints)), inverseBindMatrices=5, skeleton=0)]
    g.accessors = accessors
    g.bufferViews = [BufferView(buffer=0, byteOffset=o, byteLength=n)
                     for o, n in spans]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = animations
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _accessor(arrays, accessors, times_view, values, kind):
    """Append one sampler-output array and return its accessor index."""
    arrays.append(np.ascontiguousarray(values))
    accessors.append(Accessor(bufferView=len(arrays) - 1, componentType=5126,
                              count=len(values), type=kind))
    return len(accessors) - 1


def _pack(arrays):
    blob, spans = b"", []
    for array in arrays:
        raw = np.ascontiguousarray(array).tobytes()
        spans.append((len(blob), len(raw)))
        blob += raw
    return blob, spans
