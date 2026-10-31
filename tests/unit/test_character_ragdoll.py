"""A rigged character as a ragdoll: bones chosen, sized from the skin, posed both ways."""
import math

import numpy as np
import pytest

from OpenGLContext.character.locomotion import ClipMap
from OpenGLContext.character.ragdoll import (
    MASS_SHARES, RagdollBudget, RagdollFigure, RagdollRig, limits_from_hanim, matrix_quaternions,
)
from OpenGLContext.character.rig import quat_to_matrices
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.ragdolls import forward_kinematics
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.types import CharacterState
from OpenGLContext.scenegraph.basenodes import Transform

from ._ragdoll_assets import BONES, figure


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


@pytest.fixture
def floor():
    physics = Physics(PhysicsDefinition(mode='inline', engine='jolt', tickHz=120.0))
    physics.add_static(None, proxy=Proxy.box((20.0, 1.0, 20.0)), translation=(0, -0.5, 0))
    yield physics
    physics.close()


def run(physics, figure_, seconds, dt=1 / 60):
    for _ in range(int(round(seconds / dt))):
        figure_.update(dt)
        physics.frame(dt)
        figure_.draw()


def _waved(mixer):
    """The rest pose with the left forearm raised: a pose the mixer answers as its own."""
    pose = mixer.rig.rest_pose()
    half = math.sqrt(0.5)
    pose[1][mixer.rig.slot_of[BONES['leftLowerArm']]] = (0.0, 0.0, half, half)
    mixer.blended_pose = lambda: tuple(part.copy() for part in pose)
    return pose


def test_a_figure_starts_in_its_animations_pose(floor):
    mixer = figure()
    pose = _waved(mixer)
    shared = RagdollRig.build(mixer, BONES)
    figure_ = RagdollFigure(floor, Model(mixer), rig=shared, mode='kinematic', placement=(
        (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (2.0, 0.0, 1.0, 1)))
    assert shared.placement == pytest.approx(np.eye(4))
    assert figure_.rig.spec is shared.spec and figure_.rig.placement[3, 0] == 2.0
    positions, _ = figure_.rig.bone_poses(pose)
    for body, place in zip(figure_.ragdoll.bones, positions, strict=True):
        assert body.position == pytest.approx(place, abs=1e-6)
    floor.frame(1 / 60)
    speeds = [float(np.linalg.norm(body.velocity)) for body in figure_.ragdoll.bones]
    assert max(speeds) < 1e-3


def test_a_knock_down_carries_the_blow_and_settles(floor):
    mixer = figure(skin_radius=0.04)
    figure_ = RagdollFigure(floor, Model(mixer), mode='kinematic', queryable=False)
    run(floor, figure_, 0.1)
    chest = figure_.ragdoll.bone('chest').position
    start = figure_.ragdoll.bone('hips').position.copy()
    figure_.knock_down(impulse=(0.0, 0.0, -120.0), point=chest, blend=0.2)
    assert figure_.ragdoll.mode.value == 'limp'
    run(floor, figure_, 1.0)
    assert not figure_.following
    moved = figure_.ragdoll.bone('hips').position - start
    assert moved[2] < -0.2
    assert floor.raycast((0.0, 3.0, -0.5), (0.0, -1.0, 0.0), 10.0).body not in \
        figure_.ragdoll.bones
    run(floor, figure_, 5.0)
    assert figure_.settled


def test_a_knock_down_keeps_the_figures_momentum(floor):
    figure_ = RagdollFigure(floor, Model(figure()), mode='kinematic')
    run(floor, figure_, 0.1)
    start = figure_.ragdoll.bone('hips').position.copy()
    figure_.knock_down(velocity=(3.0, 0.0, 0.0))
    run(floor, figure_, 0.5)
    assert figure_.ragdoll.bone('hips').position[0] - start[0] > 0.4


def test_a_settled_figure_skins_once_and_a_removed_one_keeps_its_pose(floor):
    mixer = figure(skin_radius=0.04)
    written = []
    mixer.reskin_from = lambda worlds: written.append(worlds)
    figure_ = RagdollFigure(floor, Model(mixer), mode='kinematic')
    figure_.knock_down()
    run(floor, figure_, 6.0)
    assert figure_.settled
    count = len(written)
    run(floor, figure_, 0.5)
    assert len(written) == count
    last = figure_.draw()
    figure_.remove()
    assert figure_.draw() is last
    assert len(written) == count


def _settled_figure(physics):
    figure_ = RagdollFigure(physics, Model(figure(skin_radius=0.04)), mode='kinematic')
    figure_.knock_down()
    run(physics, figure_, 6.0)
    assert figure_.settled
    return figure_


def test_a_settled_figure_reads_no_bones_to_draw(floor, monkeypatch):
    """Its draw costs nothing until a bone wakes: no sleep poll of the bones each frame."""
    figure_ = _settled_figure(floor)
    reads = []
    real = type(floor)._state

    def counted(self, body, *args, **named):
        reads.append(body)
        return real(self, body, *args, **named)

    monkeypatch.setattr(type(floor), '_state', counted)
    monkeypatch.setattr(type(floor), 'poses', lambda *a, **k: reads.append('poses'))
    run(floor, figure_, 0.5)
    assert reads == []


def test_a_settled_figure_struck_again_is_drawn_again(floor):
    mixer = figure(skin_radius=0.04)
    written = []
    mixer.reskin_from = lambda worlds: written.append(worlds)
    figure_ = RagdollFigure(floor, Model(mixer), mode='kinematic')
    figure_.knock_down()
    run(floor, figure_, 6.0)
    assert figure_.settled
    count = len(written)
    figure_.ragdoll.bone('hips').apply_impulse((0.0, 300.0, 0.0))
    run(floor, figure_, 0.5)
    assert len(written) > count + 10


def test_the_joints_follow_the_ragdoll_for_what_hangs_on_them(floor):
    mixer = figure(skin_radius=0.04, held=True)
    mixer.play('hold')
    figure_ = RagdollFigure(floor, Model(mixer), mode='kinematic')
    figure_.knock_down(impulse=(40.0, 0.0, 0.0), point=figure_.ragdoll.bone('head').position)
    run(floor, figure_, 1.0)
    worlds = figure_.draw()
    rig = mixer.rig
    composed = rig.world_matrices(*_transform_pose(rig))
    hand = rig.slot_of[BONES['leftHand']]
    assert composed[hand][3, :3] == pytest.approx(worlds[hand][3, :3], abs=1e-5)
    assert composed[hand][:3, :3] == pytest.approx(worlds[hand][:3, :3], abs=1e-5)


def _transform_pose(rig):
    """The pose the joints' Transforms hold now, as the rig's arrays."""
    translation = np.array([list(x.translation) for x in rig.transforms], dtype='d')
    rotation = np.array([_axis_angle_quaternion(x.rotation) for x in rig.transforms])
    scale = np.array([list(x.scale) for x in rig.transforms], dtype='d')
    return translation, rotation, scale


class Doll:
    """What RagdollBudget asks of a figure."""

    def __init__(self, name):
        self.name = name
        self.removed = False

    def remove(self):
        self.removed = True


def test_a_budget_freezes_the_oldest_figures_past_its_limit():
    budget = RagdollBudget(2)
    a, b, c = Doll('a'), Doll('b'), Doll('c')
    assert budget.admit(a) == [] and budget.admit(b) == []
    assert budget.admit(c) == [a]
    assert a.removed and not b.removed and budget.figures == (b, c)
    budget.release(b)
    assert budget.figures == (c,) and not b.removed
    budget.limit = 0
    assert c.removed and len(budget) == 0
    d = Doll('d')
    assert budget.admit(d) == [d] and d.removed
    with pytest.raises(ValueError):
        budget.limit = -1


def _axis_angle_quaternion(rotation):
    x, y, z, angle = (float(v) for v in rotation)
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    s = math.sin(angle / 2.0) / length
    return (x * s, y * s, z * s, math.cos(angle / 2.0))


# -- a character's fall: animation to ragdoll and back -------------------------

class Wearable(Model):
    """What a character wears: Model's skeleton, a group to hang it in, and an update."""

    def __init__(self, mixer):
        super().__init__(mixer)
        self.group = Transform()

    def update(self, dt):
        self.mixer.update(dt)

    def layer(self, *args, **named):
        return self.mixer.layer(*args, **named)


class Drawn:
    """The world matrices of the rig slots each frame drew, through either path."""

    def __init__(self, character):
        self.character = character
        self.frames: list[np.ndarray] = []
        mixer = character.model.mixer
        original = mixer.joint_matrices_from

        def record(worlds):
            self.frames.append(worlds @ character.ragdoll.placement())
            return original(worlds)
        mixer.joint_matrices_from = record

    def at(self, name: str, frame: int = -1) -> np.ndarray:
        rig = self.character.model.mixer.rig
        return self.frames[frame][rig.slot_of[BONES[name]]][3, :3].copy()


@pytest.fixture
def ground():
    physics = Physics(PhysicsDefinition(mode='inline', engine='jolt', tickHz=120.0))
    physics.add_static(None, proxy=Proxy.box((60.0, 1.0, 60.0)), translation=(0, -0.5, 0))
    yield physics
    physics.close()


def wearer(physics):
    """A character wearing the skinned figure, with a ragdoll ready, and what it draws."""
    character = physics.add_character(position=(0.0, 0.0, 0.0), model=Wearable(
        figure(skin_radius=0.04)), animations=ClipMap(), fit=False, ragdoll=True)
    return character, Drawn(character)


def frames(physics, count, dt=1 / 60):
    for _ in range(count):
        physics.frame(dt)


def run_ahead(character, physics, speed=5.0, count=20):
    for _ in range(count):
        character.set_move((0.0, 0.0, -1.0), 'run', speed=speed)
        physics.frame(1 / 60)


def test_a_character_holds_no_ragdoll_until_it_falls(ground):
    from OpenGLContext.character.ragdoll import CharacterRagdoll
    character, drawn = wearer(ground)
    assert isinstance(character.ragdoll, CharacterRagdoll)
    assert not character.ragdoll.active

    def untouched(*args, **named):
        raise AssertionError('a standing character does no ragdoll arithmetic')
    character.ragdoll.rig.worlds = untouched
    character.ragdoll.rig.bone_poses = untouched
    run_ahead(character, ground)
    assert ground.ragdolls == ()
    assert len(drawn.frames) >= 20


def test_a_fall_starts_the_ragdoll_where_the_figure_was_drawn(ground):
    character, drawn = wearer(ground)
    run_ahead(character, ground)
    head, hips = drawn.at('head'), drawn.at('hips')
    ragdoll = character.ragdoll.fall()
    assert ground.ragdolls == (ragdoll,)
    assert character.state == CharacterState.DOWN
    ground.frame(1 / 60)
    # A frame on at the 5 m/s it ran: 83 mm further along -z, within 3 cm.
    step = np.array([0.0, 0.0, -5.0 / 60])
    assert drawn.at('head') == pytest.approx(head + step, abs=0.03)
    assert drawn.at('hips') == pytest.approx(hips + step, abs=0.03)


def test_the_fallen_body_carries_the_runners_velocity(ground):
    character, drawn = wearer(ground)
    run_ahead(character, ground)
    start = drawn.at('hips')
    character.ragdoll.fall()
    frames(ground, 30)
    assert drawn.at('hips')[2] < start[2] - 0.8
    assert drawn.at('head')[1] < 0.8


def test_a_blow_knocks_the_body_down_the_way_it_is_struck(ground):
    character, drawn = wearer(ground)
    run_ahead(character, ground, count=5)
    hips, head = drawn.at('hips'), drawn.at('head')
    character.ragdoll.fall(impulse=(0.0, 0.0, 60.0), bone='chest', velocity=(0.0, 0.0, 0.0))
    frames(ground, 90)
    assert drawn.at('hips')[2] > hips[2] + 0.5
    assert drawn.at('head')[2] > head[2] + 0.5
    assert drawn.at('head')[1] < 0.3


def test_the_ragdoll_is_powered_then_limp(ground):
    from OpenGLContext.physics.ragdolls import RagdollMode
    character, _drawn = wearer(ground)
    driver = character.ragdoll
    ragdoll = driver.fall()
    assert ragdoll.mode is RagdollMode.POWERED
    frames(ground, int(driver.powered * 60) + 2)
    assert ragdoll.mode is RagdollMode.LIMP


def test_recovery_stands_the_capsule_where_the_body_lies_and_blends_back(ground):
    character, drawn = wearer(ground)
    driver = character.ragdoll
    run_ahead(character, ground)
    driver.fall()
    frames(ground, 60)
    rest = driver.rest()
    hips = drawn.at('hips')
    assert rest.feet[1] == pytest.approx(0.0, abs=0.02)
    assert rest.feet[[0, 2]] == pytest.approx(hips[[0, 2]], abs=0.05)
    bones = character.ragdoll.rig.slots
    lying = drawn.frames[-1][bones]
    feet = driver.recover(blend=0.25)
    assert feet == pytest.approx(rest.feet)
    assert character.position[[0, 2]] == pytest.approx(rest.feet[[0, 2]], abs=0.02)
    assert character.state == CharacterState.DOWN        # recovery does not end the fall
    ground.frame(1 / 60)
    assert ground.ragdolls == () and driver.blending
    # The first frame of the blend is within 3 cm of the body as it lay.
    assert np.abs(drawn.frames[-1][bones, 3, :3] - lying[:, 3, :3]).max() < 0.03
    frames(ground, 15)
    assert not driver.active
    blended = drawn.frames[-1]
    character.set_move((0.0, 0.0, 0.0))
    character.get_up()
    ground.frame(1 / 60)
    # The last frame of the blend is the animation's pose: the next frame, drawn by the
    # model alone, is the same within a millimetre.
    assert np.abs(drawn.frames[-1][:, 3, :3] - blended[:, 3, :3]).max() < 1e-3


def test_a_body_lying_on_what_characters_walk_through_gets_up_on_the_ground_below(ground):
    character, _drawn = wearer(ground)
    ground.add_static(None, proxy=Proxy.box((3.0, 0.4, 3.0)), translation=(0.0, 0.2, -1.0),
                      blocks_characters=False)
    assert len(ground.passable) == 1
    character.ragdoll.fall(velocity=(0.0, 0.0, -1.0))
    frames(ground, 60)
    rest = character.ragdoll.rest()
    assert rest.pelvis[1] > 0.4                    # on the box
    assert rest.feet[1] == pytest.approx(0.0, abs=0.02)

def test_removing_the_character_removes_its_ragdoll(ground):
    character, _drawn = wearer(ground)
    ragdoll = character.ragdoll.fall()
    ground.frame(1 / 60)
    character.remove()
    assert not ragdoll.alive and ground.ragdolls == ()


def test_falling_twice_keeps_one_ragdoll(ground):
    character, _drawn = wearer(ground)
    first = character.ragdoll.fall()
    second = character.ragdoll.fall()
    assert first is second and len(ground.ragdolls) == 1
