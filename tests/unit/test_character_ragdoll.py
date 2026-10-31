"""A rigged character as a ragdoll: bones chosen, sized from the skin, posed both ways."""
import math

import numpy as np
import pytest

from OpenGLContext.character.mixer import AnimationMixer
from OpenGLContext.character.ragdoll import (
    MASS_SHARES, RagdollFigure, RagdollRig, limits_from_hanim, matrix_quaternions,
)
from OpenGLContext.character.rig import Rig, quat_to_matrices
from OpenGLContext.loaders.gltf.animation import Skin
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.ragdolls import forward_kinematics
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
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


def figure(scale: float = 1.0, skin_radius: float | None = None):
    """A mixer over the standing figure, in a document of ``scale`` metres a unit.

    With ``skin_radius`` the forearms carry a skin: a ring of vertices that
    radius (metres) around each, weighted to the forearm joint.
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
    return AnimationMixer({}, transforms, skins=skins, rig=rig)


class Model:
    """What RagdollRig.from_model reads of a CharacterModel."""

    def __init__(self, mixer):
        self.mixer = mixer
        self.humanoid = type('H', (), {'bones': BONES})()


def test_the_default_bones_are_chosen_and_the_rest_ride():
    rig = RagdollRig.build(figure(), BONES)
    assert rig.names[0] == 'hips' and len(rig.names) == 16
    assert 'neck' not in rig.names and 'leftShoulder' not in rig.names
    head = rig.names.index('head')
    # The head's parent bone is the chest; the neck rides the chest.
    assert rig.names[rig.parents[head]] == 'chest'
    neck_slot = rig.rig.slot_of[BONES['neck']]
    assert rig.names[rig.bone_of_slot[neck_slot]] == 'chest'
    assert rig.bone_of_slot[rig.rig.slot_of[0]] == -1      # above the root
    assert rig.spec.mass == pytest.approx(70.0)


def test_a_capsule_runs_to_the_first_child_and_a_foot_to_its_toes():
    spec = RagdollRig.build(figure(), BONES).spec
    thigh = spec.bones[spec.index('leftUpperLeg')]
    assert thigh.length == pytest.approx(0.42)
    assert thigh.axis == pytest.approx((0.0, -1.0, 0.0))
    foot = spec.bones[spec.index('leftFoot')]
    assert foot.length == pytest.approx(math.hypot(0.05, 0.14))
    hand = spec.bones[spec.index('leftHand')]
    assert hand.length == pytest.approx(0.9 * 0.26)
    assert hand.axis == pytest.approx((0.0, -1.0, 0.0))


def test_the_skin_gives_the_radius():
    thin = RagdollRig.build(figure(skin_radius=0.03), BONES).spec
    thick = RagdollRig.build(figure(skin_radius=0.06), BONES).spec
    forearm = thin.index('leftLowerArm')
    assert thin.bones[forearm].radius == pytest.approx(0.03, abs=2e-3)
    assert thick.bones[forearm].radius == pytest.approx(0.06, abs=2e-3)


def test_a_document_in_centimetres_is_a_ragdoll_in_metres():
    metres = RagdollRig.build(figure(), BONES).spec
    centimetres = RagdollRig.build(figure(scale=0.01, skin_radius=0.04), BONES,
                                   placement=np.diag([0.01, 0.01, 0.01, 1.0])).spec
    for a, b in zip(metres.bones, centimetres.bones, strict=True):
        assert b.translation == pytest.approx(a.translation, abs=1e-6)
        assert b.length == pytest.approx(a.length, abs=1e-6)


def test_masses_follow_the_segment_shares():
    spec = RagdollRig.build(figure(), BONES, mass=80.0).spec
    thigh = spec.bones[spec.index('leftUpperLeg')].mass
    shin = spec.bones[spec.index('leftLowerLeg')].mass
    assert thigh / shin == pytest.approx(MASS_SHARES['thigh'] / MASS_SHARES['shin'])
    assert spec.mass == pytest.approx(80.0)


def test_limb_chains_named_out_of_order_are_put_in_order():
    swapped = dict(BONES, leftLowerArm=BONES['leftHand'], leftHand=BONES['leftLowerArm'])
    rig = RagdollRig.build(figure(), swapped)
    assert rig.rig.indices[rig.slots[rig.names.index('leftLowerArm')]] == BONES['leftLowerArm']


def test_a_long_unnamed_joint_between_two_bones_is_bridged():
    missing = {name: node for name, node in BONES.items() if name != 'leftUpperArm'}
    rig = RagdollRig.build(figure(), missing)
    bridged = rig.rig.indices[rig.slots[rig.names.index('leftUpperArm')]]
    assert bridged == BONES['leftUpperArm']
    assert 'rightUpperArm' in rig.names


def test_a_skeleton_without_hips_is_refused():
    with pytest.raises(ValueError, match='hips'):
        RagdollRig.build(figure(), {'head': BONES['head']})
    with pytest.raises(ValueError, match='humanoid'):
        RagdollRig.from_model(type('M', (), {'humanoid': None})())


def test_the_rest_pose_is_its_own_target_and_comes_back_whole():
    rig = RagdollRig.build(figure(), BONES)
    pose = rig.rig.rest_pose()
    turns, moves = rig.targets(pose)
    assert turns == pytest.approx(rig.spec.rest_rotations())
    assert moves == pytest.approx(rig.spec.rest_translations())
    places, orientations = forward_kinematics(rig.spec, turns, moves)
    worlds = rig.worlds(places, orientations, pose)
    assert worlds == pytest.approx(rig.rig.world_matrices(*pose), abs=1e-9)


def test_a_bone_turned_by_the_ragdoll_carries_the_joints_that_ride_it():
    rig = RagdollRig.build(figure(), BONES)
    pose = rig.rig.rest_pose()
    places, orientations = rig.bone_poses(pose)
    chest = rig.names.index('chest')
    quarter = (0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4))
    orientations[chest] = quarter
    worlds = rig.worlds(places, orientations, pose)
    neck = worlds[rig.rig.slot_of[BONES['neck']]]
    # The neck sits 0.2 above the chest whichever way the chest faces.
    assert neck[3, :3] == pytest.approx(places[chest] + (0.0, 0.2, 0.0))
    assert matrix_quaternions(neck[None, :3, :3])[0] == pytest.approx(quarter)


def test_matrix_quaternions_invert_the_rigs_matrices():
    rng = np.random.default_rng(3)
    quaternions = rng.normal(size=(40, 4))
    quaternions /= np.linalg.norm(quaternions, axis=1, keepdims=True)
    back = matrix_quaternions(quat_to_matrices(quaternions) * 2.5)
    assert np.abs(np.abs(np.einsum('ij,ij->i', back, quaternions)) - 1.0).max() < 1e-9


def test_hanim_limits_become_twist_and_swing():
    twist, swing = limits_from_hanim((-0.5, -0.2, -1.0), (0.5, 0.3, 0.1), (0.0, 1.0, 0.0))
    assert twist == (-0.2, 0.3)
    assert swing == (0.5, 1.0)
    free, _ = limits_from_hanim((0, 0, 0), (0, 0, 0), (1.0, 0.0, 0.0))
    assert free == (-math.pi, math.pi)
    rig = RagdollRig.build(figure(), BONES, limits={'head': ((-0.1, -0.2, -0.3), (0.1, 0.2, 0.3))})
    assert rig.spec.bones[rig.names.index('head')].twist == (-0.2, 0.2)


def test_a_figure_follows_its_animation_then_falls_limp():
    physics = Physics(PhysicsDefinition(mode='inline', engine='jolt', tickHz=120.0))
    try:
        physics.add_static(None, proxy=Proxy.box((20.0, 1.0, 20.0)), translation=(0, -0.5, 0))
        mixer = figure(skin_radius=0.04)
        written = []
        mixer.reskin_from = lambda worlds: written.append(worlds)  # the skins see these
        figure_ = RagdollFigure(physics, Model(mixer), mode='kinematic')
        for _ in range(20):
            figure_.update(1 / 60)
            physics.frame(1 / 60)
            figure_.draw()
        rest = mixer.rig.world_matrices(*mixer.rig.rest_pose())
        assert written[-1] == pytest.approx(rest, abs=1e-5)
        figure_.following = False
        figure_.set_mode('limp')
        for _ in range(240):
            figure_.update(1 / 60)
            physics.frame(1 / 60)
        head = figure_.draw()[mixer.rig.slot_of[BONES['head']]][3, 1]
        assert head < 0.6
        assert physics.deformable_costs()['ragdolls draw ms'] > 0.0
        figure_.remove()
        assert not figure_.ragdoll.alive
    finally:
        physics.close()
