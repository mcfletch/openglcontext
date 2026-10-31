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


#: A standing figure in metres, Y up, facing +Z, named as the humanoid bones:
#: (name, parent index, translation from the parent).
FIGURE = [
    ('Armature', None, (0.0, 0.0, 0.0)),
    ('hips', 0, (0.0, 0.95, 0.0)),
    ('spine', 1, (0.0, 0.15, 0.0)),
    ('chest', 2, (0.0, 0.2, 0.0)),
    ('neck', 3, (0.0, 0.2, 0.0)),
    ('head', 4, (0.0, 0.05, 0.0)),
    ('leftShoulder', 3, (0.08, 0.15, 0.0)),
    ('leftUpperArm', 6, (0.1, 0.0, 0.0)),
    ('leftLowerArm', 7, (0.0, -0.28, 0.0)),
    ('leftHand', 8, (0.0, -0.26, 0.0)),
    ('rightShoulder', 3, (-0.08, 0.15, 0.0)),
    ('rightUpperArm', 10, (-0.1, 0.0, 0.0)),
    ('rightLowerArm', 11, (0.0, -0.28, 0.0)),
    ('rightHand', 12, (0.0, -0.26, 0.0)),
    ('leftUpperLeg', 1, (0.1, -0.05, 0.0)),
    ('leftLowerLeg', 14, (0.0, -0.42, 0.0)),
    ('leftFoot', 15, (0.0, -0.42, 0.0)),
    ('leftToes', 16, (0.0, -0.05, 0.14)),
    ('rightUpperLeg', 1, (-0.1, -0.05, 0.0)),
    ('rightLowerLeg', 18, (0.0, -0.42, 0.0)),
    ('rightFoot', 19, (0.0, -0.42, 0.0)),
    ('rightToes', 20, (0.0, -0.05, 0.14)),
]


def _box(start, end, half):
    """A box ``half`` metres either side of the segment start-end: 24 corners, normals, 36 indices."""
    start, end = np.asarray(start, 'd'), np.asarray(end, 'd')
    centre, reach = (start + end) / 2.0, np.abs(end - start) / 2.0 + half
    positions, normals, index = [], [], []
    for axis in range(3):
        for sign in (-1.0, 1.0):
            normal = np.zeros(3)
            normal[axis] = sign
            u, v = [k for k in range(3) if k != axis]
            base = len(positions)
            for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                corner = centre + normal * reach
                corner[u] += a * reach[u]
                corner[v] += b * reach[v]
                positions.append(corner)
                normals.append(normal)
            index += [base, base + 1, base + 2, base, base + 2, base + 3]
    return positions, normals, index


def ragdoll_figure_glb(half=0.045):
    """The :data:`FIGURE` skeleton with a box skinned to each joint, and a ``stand`` clip.

    Each joint but the root wears a box ``half`` metres either side of the
    segment to its first child (a leaf's runs on 0.08 m past it), every
    vertex weighted wholly to that joint, so where each vertex is drawn
    follows from one joint's matrix. The clip holds the rest pose, so the
    figure has an animation for a ragdoll to follow.
    """
    rest = []
    for _name, parent, move in FIGURE:
        rest.append(np.asarray(move, 'd') + (rest[parent] if parent is not None else 0.0))
    children = {i: [k for k, (_n, p, _m) in enumerate(FIGURE) if p == i]
                for i in range(len(FIGURE))}
    position, normal, joints, weights, index = [], [], [], [], []
    for i in range(1, len(FIGURE)):
        if children[i]:
            end = rest[children[i][0]]
        else:
            run = rest[i] - rest[FIGURE[i][1]]
            end = rest[i] + run / np.linalg.norm(run) * 0.08
        corners, faces, triangles = _box(rest[i], end, half)
        base = len(position)
        position += corners
        normal += faces
        index += [base + k for k in triangles]
        joints += [[i, 0, 0, 0]] * len(corners)
        weights += [[1.0, 0.0, 0.0, 0.0]] * len(corners)
    position = np.array(position, dtype='<f4')
    normal = np.array(normal, dtype='<f4')
    joints = np.array(joints, dtype='<u2')
    weights = np.array(weights, dtype='<f4')
    index = np.array(index, dtype='<u4')
    inverse_bind = np.tile(np.eye(4), (len(FIGURE), 1, 1))
    inverse_bind[:, 3, :3] = -np.array(rest)
    inverse_bind = inverse_bind.astype('<f4')
    times = np.array([0.0, 1.0], dtype='<f4')
    still = np.array([[0, 0, 0, 1], [0, 0, 0, 1]], dtype='<f4')

    blob, spans = _pack([position, normal, joints, weights, index, inverse_bind, times, still])
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0, len(FIGURE)])]
    g.nodes = [Node(name=name, children=children[i], translation=list(move))
               for i, (name, _parent, move) in enumerate(FIGURE)]
    g.nodes.append(Node(name='Body', mesh=0, skin=0))
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, NORMAL=1, JOINTS_0=2, WEIGHTS_0=3),
        indices=4)])]
    g.skins = [Skin(joints=list(range(len(FIGURE))), inverseBindMatrices=5, skeleton=0)]
    g.accessors = [
        Accessor(bufferView=0, componentType=5126, count=len(position), type='VEC3',
                 min=position.min(0).tolist(), max=position.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(normal), type='VEC3'),
        Accessor(bufferView=2, componentType=5123, count=len(joints), type='VEC4'),
        Accessor(bufferView=3, componentType=5126, count=len(weights), type='VEC4'),
        Accessor(bufferView=4, componentType=5125, count=len(index), type='SCALAR'),
        Accessor(bufferView=5, componentType=5126, count=len(FIGURE), type='MAT4'),
        Accessor(bufferView=6, componentType=5126, count=2, type='SCALAR',
                 min=[0.0], max=[1.0]),
        Accessor(bufferView=7, componentType=5126, count=2, type='VEC4'),
    ]
    g.bufferViews = [BufferView(buffer=0, byteOffset=o, byteLength=n) for o, n in spans]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = [Animation(
        name='stand',
        samplers=[AnimationSampler(input=6, output=7, interpolation='LINEAR')],
        channels=[AnimationChannel(sampler=0, target=AnimationChannelTarget(node=1, path='rotation'))])]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def skinned_bar_glb(rings=6, degrees=60.0, axis=2, tilt=True):
    """A bar of triangles that bends about its middle when its clip plays.

    Geometry with area, unlike :func:`character_glb`'s two vertices, so a
    render of it can be compared against a render of it -- which is how the
    vertex shader's skinning is held to the CPU deform it replaces. The bar
    runs up the Y axis from the origin; the lower half is bound to a joint that
    does not move and the upper half to one that rotates about the midpoint, so
    a frame of the clip is unmistakably a different shape from the rest pose.
    """
    heights = np.linspace(0.0, 2.0, rings)
    position, normal, joints, weights, index = [], [], [], [], []
    for row, y in enumerate(heights):
        for x in (-0.4, 0.4):
            position.append([x, float(y), 0.0])
            # Tilted rather than square-on, so a joint rotation moves the
            # normal as well as the vertex: a bar facing the camera with the
            # bend about the same axis would skin its normals to themselves and
            # prove nothing about them.
            normal.append([0.35 * x / 0.4, 0.25 if tilt else 0.0,
                           0.9] if tilt else [0.0, 0.0, 1.0])
            upper = min(1.0, max(0.0, (y - 0.6) / 0.8))
            joints.append([0, 1, 0, 0])
            weights.append([1.0 - upper, upper, 0.0, 0.0])
        if row:
            base = (row - 1) * 2
            index += [base, base + 1, base + 3, base, base + 3, base + 2]
    position = np.array(position, dtype='<f4')
    normal = np.array(normal, dtype='<f4')
    joints = np.array(joints, dtype='<u2')
    weights = np.array(weights, dtype='<f4')
    index = np.array(index, dtype='<u4')
    inverse_bind = np.stack([
        np.eye(4), np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0],
                             [0, -1, 0, 1]], dtype='f8'),
    ]).astype('<f4')
    times = np.array([0.0, 1.0], dtype='<f4')
    half = np.radians(degrees) / 2.0
    spin = [0.0, 0.0, 0.0, np.cos(half)]
    spin[axis] = np.sin(half)
    turn = np.array([[0, 0, 0, 1], spin], dtype='<f4')

    blob, spans = _pack([position, normal, joints, weights, index,
                         inverse_bind, times, turn])
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0, 2])]
    g.nodes = [
        Node(name='Base', children=[1]),
        Node(name='Bend', translation=[0.0, 1.0, 0.0]),
        Node(name='Bar', mesh=0, skin=0),
    ]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, NORMAL=1, JOINTS_0=2, WEIGHTS_0=3),
        indices=4)])]
    g.skins = [Skin(joints=[0, 1], inverseBindMatrices=5, skeleton=0)]
    g.accessors = [
        Accessor(bufferView=0, componentType=5126, count=len(position),
                 type='VEC3', min=position.min(0).tolist(),
                 max=position.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(normal), type='VEC3'),
        Accessor(bufferView=2, componentType=5123, count=len(joints), type='VEC4'),
        Accessor(bufferView=3, componentType=5126, count=len(weights), type='VEC4'),
        Accessor(bufferView=4, componentType=5125, count=len(index), type='SCALAR'),
        Accessor(bufferView=5, componentType=5126, count=2, type='MAT4'),
        Accessor(bufferView=6, componentType=5126, count=2, type='SCALAR',
                 min=[0.0], max=[1.0]),
        Accessor(bufferView=7, componentType=5126, count=2, type='VEC4'),
    ]
    g.bufferViews = [BufferView(buffer=0, byteOffset=o, byteLength=n)
                     for o, n in spans]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.animations = [Animation(
        name='bend',
        samplers=[AnimationSampler(input=6, output=7, interpolation='LINEAR')],
        channels=[AnimationChannel(
            sampler=0, target=AnimationChannelTarget(node=1, path='rotation'))])]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())
