"""A standing rigged figure the ragdoll tests are run against, built in memory."""
import math

import numpy as np

from OpenGLContext.character.mixer import AnimationMixer
from OpenGLContext.character.rig import Rig
from OpenGLContext.loaders.gltf.animation import Skin
from OpenGLContext.scenegraph.basenodes import Transform
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

#: A standing figure, Y up, facing +Z: (node, name, parent node, translation from the parent).
JOINTS = [
    (0, 'Armature', None, (0.0, 0.0, 0.0)),
    (1, 'hips', 0, (0.0, 0.95, 0.0)),
    (2, 'spine', 1, (0.0, 0.15, 0.0)),
    (3, 'chest', 2, (0.0, 0.2, 0.0)),
    (4, 'neck', 3, (0.0, 0.2, 0.0)),
    (5, 'head', 4, (0.0, 0.05, 0.0)),
    (6, 'leftShoulder', 3, (0.08, 0.15, 0.0)),
    (7, 'leftUpperArm', 6, (0.1, 0.0, 0.0)),
    (8, 'leftLowerArm', 7, (0.0, -0.28, 0.0)),
    (9, 'leftHand', 8, (0.0, -0.26, 0.0)),
    (10, 'rightShoulder', 3, (-0.08, 0.15, 0.0)),
    (11, 'rightUpperArm', 10, (-0.1, 0.0, 0.0)),
    (12, 'rightLowerArm', 11, (0.0, -0.28, 0.0)),
    (13, 'rightHand', 12, (0.0, -0.26, 0.0)),
    (14, 'leftUpperLeg', 1, (0.1, -0.05, 0.0)),
    (15, 'leftLowerLeg', 14, (0.0, -0.42, 0.0)),
    (16, 'leftFoot', 15, (0.0, -0.42, 0.0)),
    (17, 'leftToes', 16, (0.0, -0.05, 0.14)),
    (18, 'rightUpperLeg', 1, (-0.1, -0.05, 0.0)),
    (19, 'rightLowerLeg', 18, (0.0, -0.42, 0.0)),
    (20, 'rightFoot', 19, (0.0, -0.42, 0.0)),
    (21, 'rightToes', 20, (0.0, -0.05, 0.14)),
]
BONES = {name: node for node, name, _parent, _move in JOINTS if name != 'Armature'}


def figure(scale: float = 1.0, skin_radius: float | None = None, held: bool = False):
    """A mixer over the standing figure, in a document of ``scale`` metres a unit.

    With ``skin_radius`` the forearms carry a skin: a ring of vertices that
    radius (metres) around each, weighted to the forearm joint. With ``held``
    a clip ``hold`` drives every joint's rotation, holding the rest pose.
    """
    transforms = {node: Transform(translation=tuple(v / scale for v in move))
                  for node, _name, _parent, move in JOINTS}
    children: dict[int, list[int]] = {}
    for node, _name, parent, _move in JOINTS:
        if parent is not None:
            children.setdefault(parent, []).append(node)
    rig = Rig([0], children, transforms)
    skins = []
    if skin_radius is not None:
        rest = rig.world_matrices(*rig.rest_pose())
        points, joints = [], []
        for node in (BONES['leftLowerArm'], BONES['rightLowerArm']):
            start = rest[rig.slot_of[node]][3, :3]
            for t in np.linspace(0.05, 0.2, 4) / scale:
                for a in np.linspace(0, 2 * math.pi, 12, endpoint=False):
                    points.append(start + (skin_radius / scale * math.cos(a), -t,
                                           skin_radius / scale * math.sin(a)))
                    joints.append(node)
        order = sorted(BONES.values())
        index = {node: k for k, node in enumerate(order)}
        mesh = PBRMesh(positions=np.array(points),
                       skin_joints=np.array([[index[j], 0, 0, 0] for j in joints]),
                       skin_weights=np.tile([1.0, 0, 0, 0], (len(points), 1)))
        inverse = np.array([np.linalg.inv(rest[rig.slot_of[node]]) for node in order])
        skins.append(Skin(order, inverse, 0, [mesh]))
    clips = {}
    if held:
        from OpenGLContext.loaders.gltf import animation as ga
        clips['hold'] = ga.Animation('hold', [
            ga.Channel(node, 'rotation', ga.Sampler(
                np.array([0.0, 1.0]), np.array([[0.0, 0.0, 0.0, 1.0]] * 2), 'LINEAR',
                is_rotation=True)) for node, _name, _parent, _move in JOINTS])
    return AnimationMixer(clips, transforms, skins=skins, rig=rig)
