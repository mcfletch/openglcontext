"""Ragdolls on the physics service: specs, bones as bodies, modes, poses, hits and removal."""
import math

import numpy as np
import pytest

from OpenGLContext.physics.engine import EngineUnavailable
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.ragdolls import (
    HUMANOID_LIMITS, Ragdoll, RagdollBone, RagdollMode, RagdollSpec, forward_kinematics,
    quat_conjugate, quat_multiply, quat_rotate,
)
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition

HZ = 120.0


def make(**named) -> Physics:
    named.setdefault('mode', 'inline')
    named.setdefault('tickHz', HZ)
    named.setdefault('engine', 'jolt')
    return Physics(PhysicsDefinition(**named))


def run_for(physics: Physics, seconds: float, frame: float = 1.0 / 60.0) -> None:
    for _ in range(int(round(seconds / frame))):
        physics.frame(frame)


@pytest.fixture
def world():
    physics = make()
    physics.add_static(None, proxy=Proxy.box((40.0, 1.0, 40.0)), translation=(0.0, -0.5, 0.0))
    yield physics
    physics.close()


def deviation(ragdoll: Ragdoll, spec: RagdollSpec) -> float:
    """The largest angle between a bone's turn and its rest turn in its parent's frame, radians."""
    turns = ragdoll.poses(interpolated=False).orientation
    worst = 0.0
    for i, bone in enumerate(spec.bones[1:], start=1):
        local = quat_multiply(quat_conjugate(turns[bone.parent]), turns[i])
        rest = np.asarray(bone.rotation)
        dot = abs(float(np.dot(local / np.linalg.norm(local), rest)))
        worst = max(worst, 2.0 * math.acos(min(1.0, dot)))
    return worst


# -- the spec -----------------------------------------------------------------

def test_the_humanoid_spec_is_eleven_bones_of_the_given_mass():
    spec = RagdollSpec.humanoid(height=1.8, mass=80.0)
    assert len(spec) == 11 and spec.names[0] == 'pelvis'
    assert spec.mass == pytest.approx(80.0)
    assert spec.bones[spec.index('shin_l')].bend == HUMANOID_LIMITS['shin'][2]
    # Strength scales with the figure's mass.
    assert spec.bones[spec.index('thigh_l')].strength == pytest.approx(600.0 * 80.0 / 70.0)


def test_from_skeleton_runs_each_capsule_to_the_first_child():
    spec = RagdollSpec.from_skeleton(['a', 'b', 'c'], [-1, 0, 1],
                                     [(0, 1, 0), (0, 0.5, 0), (0, 0.4, 0)], radius=0.05)
    assert spec.bones[0].length == pytest.approx(0.5)
    assert spec.bones[1].length == pytest.approx(0.4)
    # A leaf continues its own bone's direction for 0.9 of its length.
    assert spec.bones[2].length == pytest.approx(0.36)
    assert spec.bones[2].axis == pytest.approx((0.0, 1.0, 0.0))


@pytest.mark.parametrize('bones, message', [
    ([], 'at least one'),
    ([RagdollBone('a', 0, (0, 0, 0))], 'parent'),
    ([RagdollBone('a', -1, (0, 0, 0)), RagdollBone('a', 0, (0, 1, 0))], 'unique'),
    ([RagdollBone('a', -1, (0, 0, 0), mass=0.0)], 'mass'),
    ([RagdollBone('a', -1, (0, 0, 0), radius=math.nan)], 'radius'),
    ([RagdollBone('a', -1, (0, 0, 0), length=-1.0)], 'length'),
])
def test_a_spec_that_describes_no_skeleton_is_refused(bones, message):
    with pytest.raises(ValueError, match=message):
        RagdollSpec(bones=bones)


def test_a_spec_round_trips_through_plain_data():
    spec = RagdollSpec.humanoid(root_force=4000.0)
    again = RagdollSpec.from_dict(spec.as_dict())
    assert again == spec


def test_forward_kinematics_places_the_rest_pose():
    spec = RagdollSpec.humanoid()
    places, turns = forward_kinematics(spec, position=(1.0, 0.0, 2.0))
    assert places[0] == pytest.approx((1.0, 0.99, 2.0))
    assert places[spec.index('head')][1] == pytest.approx(0.99 + 0.30 + 0.32)
    # Turning the frame a half turn about y carries the left thigh to the other side.
    turned, _ = forward_kinematics(spec, rotation=(0.0, 1.0, 0.0, 0.0))
    assert turned[spec.index('thigh_l')][0] == pytest.approx(-0.10)


def test_quaternion_rows_compose_and_turn():
    quarter = np.array([0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4)])
    assert quat_rotate(quarter, (1.0, 0.0, 0.0)) == pytest.approx((0.0, 0.0, -1.0))
    half = quat_multiply(quarter, quarter)
    assert quat_rotate(half, (1.0, 0.0, 0.0)) == pytest.approx((-1.0, 0.0, 0.0))
    assert quat_multiply(quarter, quat_conjugate(quarter)) == pytest.approx((0, 0, 0, 1))


def test_the_mode_is_read_from_its_name():
    assert RagdollMode.coerce('Powered') is RagdollMode.POWERED
    assert RagdollMode.coerce(RagdollMode.LIMP) is RagdollMode.LIMP
    with pytest.raises(ValueError, match='kinematic, powered or limp'):
        RagdollMode.coerce('floppy')


# -- in the world ----------------------------------------------------------------

def test_the_bones_are_bodies_from_the_call_on(world):
    spec = RagdollSpec.humanoid()
    ragdoll = world.add_ragdoll(spec, position=(0.0, 0.0, 0.0))
    assert len(ragdoll.bones) == 11
    assert ragdoll.bone('head') is ragdoll.bones[2]
    assert ragdoll.bones[0].position == pytest.approx((0.0, 0.99, 0.0))
    assert world.ragdoll_of(ragdoll.bones[3]) is ragdoll
    assert world.ragdolls == (ragdoll,)
    assert sum(body.mass for body in ragdoll.bones) == pytest.approx(70.0)


def test_a_limp_ragdoll_struck_falls_to_the_floor(world):
    ragdoll = world.add_ragdoll(RagdollSpec.humanoid(), position=(0.0, 0.05, 0.0))
    run_for(world, 0.1)
    ragdoll.hit('chest', (60.0, 0.0, 0.0))
    run_for(world, 5.0)
    poses = ragdoll.poses()
    assert poses.position[:, 1].max() < 0.5
    assert poses.position[:, 1].min() > -0.05


def test_a_kinematic_ragdoll_holds_its_pose_and_follows_a_placement(world):
    spec = RagdollSpec.humanoid()
    ragdoll = world.add_ragdoll(spec, mode='kinematic')
    run_for(world, 0.5)
    assert deviation(ragdoll, spec) < 1e-3
    ragdoll.place((2.0, 0.0, 0.0))
    run_for(world, 0.25)
    assert ragdoll.poses().position[0] == pytest.approx((2.0, 0.99, 0.0), abs=1e-3)


def test_a_powered_ragdoll_recovers_from_a_blow_and_a_limp_one_does_not(world):
    spec = RagdollSpec.humanoid(root_force=4000.0, root_torque=1500.0)
    powered = world.add_ragdoll(spec, position=(0.0, 0.0, 0.0), mode='powered')
    limp = world.add_ragdoll(spec, position=(3.0, 0.0, 0.0), mode='kinematic')
    run_for(world, 0.2)
    limp.set_mode('limp')
    for doll in (powered, limp):
        doll.hit('lower_arm_l', (0.0, 0.0, 15.0))
        doll.hit('head', (8.0, 0.0, 0.0))
    run_for(world, 2.0)
    assert deviation(powered, spec) < 0.15
    assert deviation(limp, spec) > 0.3
    assert powered.bones[0].position[1] > 0.85


def test_a_clip_drives_a_kinematic_ragdoll(world):
    spec = RagdollSpec.humanoid()
    ragdoll = world.add_ragdoll(spec, mode='kinematic')
    rest = spec.rest_rotations()
    bent = rest.copy()
    elbow = spec.index('lower_arm_l')
    bent[elbow] = (math.sin(0.5), 0.0, 0.0, math.cos(0.5))
    ragdoll.play([0.0, 0.5], np.stack([rest, bent]))
    run_for(world, 1.0)
    turns = ragdoll.poses(interpolated=False).orientation
    local = quat_multiply(quat_conjugate(turns[spec.index('upper_arm_l')]), turns[elbow])
    assert abs(float(np.dot(local, bent[elbow]))) == pytest.approx(1.0, abs=1e-4)
    ragdoll.stop()
    ragdoll.set_pose(rest)
    run_for(world, 0.5)
    assert deviation(ragdoll, spec) < 1e-3


def test_strength_per_bone_lets_one_arm_swing_free(world):
    spec = RagdollSpec.humanoid(root_force=4000.0, root_torque=1500.0)
    ragdoll = world.add_ragdoll(spec, mode='powered')
    strength = np.array([bone.strength for bone in spec.bones])
    strength[spec.index('lower_arm_l')] = 0.0
    ragdoll.set_strength(strength)
    run_for(world, 0.2)
    ragdoll.hit('lower_arm_l', (0.0, 0.0, 6.0))
    run_for(world, 0.3)
    assert deviation(ragdoll, spec) > 0.2


def test_bad_commands_are_refused_on_the_render_thread(world):
    ragdoll = world.add_ragdoll(RagdollSpec.humanoid())
    with pytest.raises(ValueError, match='rotations'):
        ragdoll.set_pose(np.zeros((3, 4)))
    with pytest.raises(ValueError, match='blend'):
        ragdoll.set_mode('limp', blend=-1.0)
    with pytest.raises(ValueError, match='strength'):
        ragdoll.set_strength(-5.0)
    with pytest.raises(ValueError, match='ascend'):
        ragdoll.play([1.0, 0.0], np.zeros((2, 11, 4)))
    with pytest.raises(ValueError, match='position'):
        ragdoll.place((math.nan, 0.0, 0.0))
    with pytest.raises(KeyError):
        ragdoll.bone('tail')
    with pytest.raises(TypeError, match='RagdollSpec'):
        world.add_ragdoll('humanoid')
    with pytest.raises(ValueError, match='quaternion'):
        world.add_ragdoll(RagdollSpec.humanoid(), rotation=(0, 0, 0, 0))


def test_a_bone_is_removed_with_its_ragdoll(world):
    ragdoll = world.add_ragdoll(RagdollSpec.humanoid())
    run_for(world, 0.1)
    before = world.counts.bodies
    with pytest.raises(ValueError, match='remove the ragdoll'):
        world.remove(ragdoll.bones[1])
    ragdoll.remove()
    ragdoll.remove()
    run_for(world, 0.1)
    assert world.counts.bodies == before - 11
    assert not ragdoll.alive and not any(body.alive for body in ragdoll.bones)
    assert world.ragdolls == ()
    ragdoll.set_mode('powered')     # a removed ragdoll's commands go nowhere


def test_a_ray_names_the_bone_it_hits(world):
    ragdoll = world.add_ragdoll(RagdollSpec.humanoid(), mode='kinematic')
    run_for(world, 0.1)
    hit = world.raycast((0.0, 1.78, -3.0), (0.0, 0.0, 1.0), 10.0)
    assert hit is not None and hit.body is ragdoll.bone('head')


def test_the_costs_name_the_ragdolls(world):
    world.add_ragdoll(RagdollSpec.humanoid(), mode='powered')
    run_for(world, 0.5)
    world.note_render_cost('ragdolls', 0.002)
    costs = world.deformable_costs()
    assert costs['ragdolls'] == 1.0
    assert costs['ragdolls ms'] > 0.0
    assert costs['ragdolls draw ms'] > 0.0
    assert world.deformable_costs()['ragdolls draw ms'] == 0.0


@pytest.mark.engines('omi')
def test_an_engine_without_ragdolls_says_so():
    physics = Physics(PhysicsDefinition(mode='inline'))
    try:
        with pytest.raises(EngineUnavailable, match='ragdolls need the jolt engine'):
            physics.add_ragdoll(RagdollSpec.humanoid())
        assert physics.deformable_costs() == {}
    finally:
        physics.close()
