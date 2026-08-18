"""Small rigged glTF documents the character tests are run against.

Built in memory rather than fetched, so the character tests need no network and
no sample-asset checkout. :func:`skeleton_glb` is a named bone hierarchy with an
attachment point on the right hand; :func:`character_glb` adds a skinned mesh
and two clips, which is the shape of the thing a game actually loads.
"""

import numpy as np
from pygltflib import (
    GLTF2, Accessor, Animation, AnimationChannel, AnimationChannelTarget,
    AnimationSampler, Attributes, Buffer, BufferView, Mesh, Node, Primitive,
    Scene, Skin,
)

#: (name, children) for each node, in declaration order. The names follow the
#: Mixamo convention, which is the one most stand-in content arrives in.
SKELETON = [
    ('Hips', [1, 6, 9]),            # 0
    ('Spine', [2]),                 # 1
    ('Spine1', [3, 12, 15]),        # 2
    ('Neck', [4]),                  # 3
    ('Head', [5]),                  # 4
    ('weapon_sight', []),           # 5
    ('LeftUpLeg', [7]),             # 6
    ('LeftLeg', [8]),               # 7
    ('LeftFoot', []),               # 8
    ('RightUpLeg', [10]),           # 9
    ('RightLeg', [11]),             # 10
    ('RightFoot', []),              # 11
    ('LeftArm', [13]),              # 12
    ('LeftForeArm', [14]),          # 13
    ('LeftHand', []),               # 14
    ('RightArm', [16]),             # 15
    ('RightForeArm', [17]),         # 16
    ('RightHand', [18]),            # 17
    ('socket_grip', []),            # 18
]

#: Where the attachment point sits under the right hand.
GRIP = 18


def skeleton_glb(extensions=None, names=None):
    """A named bone hierarchy with no geometry, as a .glb."""
    labels = names if names is not None else [name for name, _ in SKELETON]
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(name=label, children=list(kids), translation=[0.0, 0.1, 0.0])
               for label, (_, kids) in zip(labels, SKELETON, strict=True)]
    g.buffers = [Buffer(byteLength=4)]
    g.set_binary_blob(b'\0\0\0\0')
    if extensions:
        g.extensions = extensions
        g.extensionsUsed = list(extensions)
    return b"".join(g.save_to_bytes())


def _pack(arrays):
    blob, spans = b"", []
    for array in arrays:
        raw = np.ascontiguousarray(array).tobytes()
        spans.append((len(blob), len(raw)))
        blob += raw
    return blob, spans


def character_glb():
    """The skeleton, a two-vertex mesh skinned to it, and two clips.

    ``raise`` swings the right arm; ``kick`` swings the right leg. One clip per
    half of the body, so a masked layer has something to prove itself on.
    """
    labels = [name for name, _ in SKELETON]
    joints_of = {'RightArm': labels.index('RightArm'),
                 'RightUpLeg': labels.index('RightUpLeg')}
    position = np.array([[0, 1, 0], [0, -1, 0]], dtype='<f4')
    joints = np.array([[0, 0, 0, 0], [1, 0, 0, 0]], dtype='<u2')
    weights = np.array([[1, 0, 0, 0], [1, 0, 0, 0]], dtype='<f4')
    inverse_bind = np.stack([np.eye(4), np.eye(4)]).astype('<f4')
    times = np.array([0.0, 1.0], dtype='<f4')
    quarter = np.sin(np.pi / 4), np.cos(np.pi / 4)
    swing = np.array([[0, 0, 0, 1], [0, 0, quarter[0], quarter[1]]], dtype='<f4')

    blob, spans = _pack([position, joints, weights, inverse_bind, times, swing])
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0, 19])]
    g.nodes = [Node(name=label, children=list(kids), translation=[0.0, 0.1, 0.0])
               for label, (_, kids) in zip(labels, SKELETON, strict=True)]
    g.nodes.append(Node(name='Body', mesh=0, skin=0))
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, JOINTS_0=1, WEIGHTS_0=2))])]
    g.skins = [Skin(joints=[joints_of['RightArm'], joints_of['RightUpLeg']],
                    inverseBindMatrices=3, skeleton=0)]
    g.accessors = [
        Accessor(bufferView=0, componentType=5126, count=2, type='VEC3',
                 min=position.min(0).tolist(), max=position.max(0).tolist()),
        Accessor(bufferView=1, componentType=5123, count=2, type='VEC4'),
        Accessor(bufferView=2, componentType=5126, count=2, type='VEC4'),
        Accessor(bufferView=3, componentType=5126, count=2, type='MAT4'),
        Accessor(bufferView=4, componentType=5126, count=2, type='SCALAR',
                 min=[0.0], max=[1.0]),
        Accessor(bufferView=5, componentType=5126, count=2, type='VEC4'),
    ]
    g.bufferViews = [BufferView(buffer=0, byteOffset=o, byteLength=n)
                     for o, n in spans]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = [
        Animation(name=name,
                  samplers=[AnimationSampler(input=4, output=5,
                                             interpolation='LINEAR')],
                  channels=[AnimationChannel(
                      sampler=0,
                      target=AnimationChannelTarget(node=node, path='rotation'))])
        for name, node in (('raise', joints_of['RightArm']),
                           ('kick', joints_of['RightUpLeg']))
    ]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def held_glb(socket='socket_grip', translation=(0.0, 0.1, 0.3), rotation=None,
             under=False):
    """A thing a figure holds, declaring where it is held.

    A root node with a mesh on it and one empty node saying where a hand takes
    hold of it -- the shape every weapon in this workspace ships in. ``under``
    puts the point one node deeper, so the composed transform is what has to be
    read rather than one node's own.
    """
    position = np.array([[0, 0, 0], [0, 0, 1]], dtype='<f4')
    blob, spans = _pack([position])
    point = Node(name=socket, translation=list(translation),
                 rotation=list(rotation) if rotation else None)
    g = GLTF2()
    g.scene = 0
    g.nodes = [Node(name='Weapon', mesh=0, children=[1])]
    if under:
        g.nodes[0].children = [1]
        g.nodes.append(Node(name='Mid', children=[2], translation=[0.0, 0.05, 0.0]))
        g.nodes.append(point)
        point.translation = [translation[0], translation[1] - 0.05, translation[2]]
    else:
        g.nodes.append(point)
    g.scenes = [Scene(nodes=[0])]
    g.meshes = [Mesh(primitives=[Primitive(attributes=Attributes(POSITION=0))])]
    g.accessors = [Accessor(bufferView=0, componentType=5126, count=2, type='VEC3',
                            min=position.min(0).tolist(),
                            max=position.max(0).tolist())]
    g.bufferViews = [BufferView(buffer=0, byteOffset=o, byteLength=n)
                     for o, n in spans]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())
