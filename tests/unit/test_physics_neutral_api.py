"""The service's calls that read and drive the world without naming the engine underneath."""
import math
import time

import numpy as np
import pytest

from OpenGLContext.physics import (
    CharacterCapabilities, CharacterState, Physics, PhysicsDefinition, Proxy, WorldCounts,
)
from OpenGLContext.scenegraph.basenodes import Transform
from OpenGLContext.testing import physics as physics_testing

pytestmark = pytest.mark.engines('omi', 'jolt')

MODES = ['inline', 'thread']


def make(mode):
    return Physics(PhysicsDefinition(mode=mode, tickHz=100.0, maxCatchUp=1.0, linearDamping=0.0))


@pytest.fixture(params=MODES)
def physics(request):
    service = make(request.param)
    yield service
    service.close()


@pytest.fixture(autouse=True)
def warn_again(monkeypatch):
    """Let each deprecated name warn in each test: each warns once a process."""
    from OpenGLContext.physics import character, proxy, service

    monkeypatch.setattr(service, '_WARNED', set())
    monkeypatch.setattr(character, '_WARNED', [])
    monkeypatch.setattr(proxy, '_WARNED', [])


@pytest.mark.engines('omi', reason='physics.world is the omi world; on Jolt it raises')
def test_a_deprecated_name_warns_once(monkeypatch):
    physics = make('inline')
    try:
        with pytest.warns(DeprecationWarning):
            physics.world  # noqa: B018 the read is what warns
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter('error')
            physics.world  # noqa: B018 a second read is silent
    finally:
        physics.close()


def test_materials_equal_engine_materials_with_the_same_values():
    from omi_physics import model

    from OpenGLContext.physics import CollisionFilter, Material

    assert Material(restitution=0.5) == model.Material(restitution=0.5)
    assert model.Material(restitution=0.5) == Material(restitution=0.5)
    assert Material(restitution=0.5) != model.Material(restitution=0.4)
    assert CollisionFilter(('a',)) == model.CollisionFilter(('a',))
    assert Material() != 'average'
    assert len({Material(), Material()}) == 1


def run(physics, seconds, frame=0.02):
    for _ in range(int(round(seconds / frame))):
        physics.frame(frame)
        if physics.definition.mode == 'thread':
            time.sleep(frame)


def settle(physics):
    """Wait for a threaded world to publish what has been sent to it."""
    physics.frame(0.0)
    for _ in range(50):
        time.sleep(0.01)
        physics.frame(0.0)


# -- poses -------------------------------------------------------------------

def test_poses_read_bodies_as_arrays(physics):
    resting = physics.add_static(None, proxy=Proxy.box((1, 1, 1)), translation=(4, 0, 0))
    falling = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 10, 0), mass=3.0)
    run(physics, 0.3)
    settle(physics)
    poses = physics.poses([falling, resting])
    assert poses.position.shape == (2, 3) and poses.orientation.shape == (2, 4)
    assert poses.velocity.shape == (2, 3) and poses.angular_velocity.shape == (2, 3)
    assert list(poses.uids) == [falling.uid, resting.uid]
    assert poses.position[0][1] < 10.0 and poses.velocity[0][1] < 0.0
    assert np.allclose(poses.position[1], (4, 0, 0))
    assert np.allclose(poses.orientation[1], (0, 0, 0, 1))
    assert list(poses.mass) == [3.0, 0.0]
    assert np.allclose(poses.position[0], falling.position)


def test_poses_take_uids_as_well_as_bodies(physics):
    body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(1, 2, 3))
    assert np.allclose(physics.poses([body.uid]).position[0], (1, 2, 3))
    assert physics.poses([]).position.shape == (0, 3)


def test_poses_raise_for_a_body_the_service_does_not_hold(physics):
    with pytest.raises(KeyError):
        physics.poses([987654])


def test_poses_at_the_end_of_the_step_are_not_interpolated():
    physics = make('inline')
    try:
        body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 10, 0))
        physics.frame(0.015)          # one step and half of the next
        drawn = physics.poses([body]).position[0]
        stepped = physics.poses([body], interpolated=False).position[0]
        assert drawn[1] > stepped[1]          # drawn between the last two steps
        assert np.allclose(body.step_position, stepped)
    finally:
        physics.close()


def test_frames_faster_than_the_tick_draw_a_body_between_its_ticks():
    """At four frames a tick, each frame draws a moving body a quarter tick further on."""
    physics = make('inline')
    try:
        node = Transform(translation=(0, 10, 0))
        body = physics.add_dynamic(node, proxy=Proxy.sphere(0.5), gravity_factor=0.0)
        body.set_velocity((4.0, 0.0, 0.0))
        for _ in range(8):
            physics.frame(0.01)
        drawn = []
        for _ in range(8):
            physics.frame(0.0025)
            drawn.append(float(node.translation[0]))
        assert np.allclose(np.diff(drawn), 0.01, atol=1e-4)
    finally:
        physics.close()


# -- gravity factor --------------------------------------------------------

def test_a_body_with_no_gravity_factor_floats(physics):
    floating = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 10, 0))
    falling = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(5, 10, 0))
    assert floating.gravity_factor == 1.0
    floating.set_gravity_factor(0.0)
    floating.set_velocity((0.0, 0.0, 0.0))
    assert floating.gravity_factor == 0.0
    settle(physics)
    held = float(floating.position[1])
    run(physics, 0.3)
    settle(physics)
    assert floating.position[1] == pytest.approx(held, abs=1e-6)
    assert falling.position[1] < 9.8


def test_the_gravity_factor_is_an_add_option(physics):
    rising = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 0, 0),
                                 gravity_factor=-1.0)
    assert rising.gravity_factor == -1.0
    run(physics, 0.3)
    settle(physics)
    assert rising.position[1] > 0.1


def test_a_gravity_factor_must_be_finite(physics):
    body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5))
    with pytest.raises(ValueError):
        body.set_gravity_factor(math.nan)


# -- the engine ------------------------------------------------------------

def test_the_engine_is_described_and_read_only(physics, physics_engine):
    engine = physics.engine
    name = {'omi': 'omi_physics', 'jolt': 'jolt'}[physics_engine]
    assert engine.name == name
    assert engine.tick_hz == 100.0
    assert engine.precision == 'double'
    assert engine.version
    assert str(engine).startswith(name + ' ')
    with pytest.raises(AttributeError):
        physics.engine = None


def test_the_counts_are_the_bodies_and_contacts_of_the_last_step(physics):
    assert physics.counts == WorldCounts(bodies=0, contacts=0)
    physics.add_static(None, proxy=Proxy.box((20, 1, 20)), translation=(0, -0.5, 0))
    physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 0.45, 0))
    run(physics, 0.1)
    settle(physics)
    assert physics.counts == WorldCounts(bodies=2, contacts=1)


def test_a_removed_body_is_not_counted(physics):
    floor = physics.add_static(None, proxy=Proxy.box((20, 1, 20)), translation=(0, -0.5, 0))
    physics.add_static(None, proxy=Proxy.box((1, 1, 1)), translation=(5, 0, 0))
    run(physics, 0.1)
    physics.remove(floor)
    run(physics, 0.1)
    settle(physics)
    assert physics.counts.bodies == 1


# -- on_step ---------------------------------------------------------------

def test_on_step_is_called_after_each_step_with_a_step_view(physics):
    body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 10, 0))
    seen = []

    def watch(view):
        seen.append((view.step.index, float(view.poses([body]).position[0][1])))
        assert not hasattr(view, 'world')

    hook = physics.on_step(watch)
    run(physics, 0.1)
    settle(physics)
    assert len(seen) >= 5
    indices = [index for index, _ in seen]
    assert indices == sorted(indices)
    assert seen[-1][1] < 10.0
    hook.cancel()
    count = len(seen)
    run(physics, 0.1)
    settle(physics)
    assert len(seen) == count


def test_a_step_view_writes_through_body_handles_at_once(physics):
    body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 10, 0))

    def hold(view):
        body.set_velocity((0.0, 0.0, 0.0))
        body.set_transform((0.0, 10.0, 0.0))

    physics.on_step(hold)
    run(physics, 0.2)
    settle(physics)
    assert body.position[1] == pytest.approx(10.0, abs=0.05)


def test_a_step_view_answers_queries(physics):
    floor = physics.add_static(None, proxy=Proxy.box((10, 1, 10)), translation=(0, -0.5, 0))
    found = []
    physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(4, 5, 0))

    def look(view):
        hit = view.raycast((0, 3, 0), (0, -1, 0), 10.0)
        found.append(None if hit is None else hit.body)

    physics.on_step(look)
    run(physics, 0.05)
    settle(physics)
    assert found and found[-1] is floor


def test_post_calls_a_function_on_the_stepping_thread(physics):
    called = []
    physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 10, 0))
    physics.post(called.append, 7)
    run(physics, 0.05)
    settle(physics)
    assert called == [7]


# -- characters ------------------------------------------------------------

def test_a_character_reads_its_capsule_without_the_controller(physics):
    caps = CharacterCapabilities(radius=0.4, standHeight=1.7)
    floor = physics.add_static(None, proxy=Proxy.box((20, 1, 20)), translation=(0, -0.5, 0))
    assert floor.alive
    walker = physics.add_character(position=(0, 0, 0), capabilities=caps)
    run(physics, 0.3)
    assert walker.radius == pytest.approx(0.4)
    assert walker.height == pytest.approx(1.7)
    assert walker.grounded
    assert walker.vertical_speed == pytest.approx(0.0, abs=1e-6)
    assert walker.motion_state is CharacterState.STANDING
    assert walker.state == CharacterState.STANDING
    assert isinstance(walker.capabilities, CharacterCapabilities)
    assert walker.capabilities.radius == pytest.approx(0.4)
    assert walker.jump()
    run(physics, 0.04)
    assert walker.vertical_speed > 0.0
    assert walker.motion_state is CharacterState.AIRBORNE
    assert walker.state == CharacterState.AIRBORNE
    assert walker.stuck is False


def test_a_character_takes_engine_capabilities_at_the_boundary(physics):
    from omi_physics.character import CharacterCapabilities as OmiCapabilities

    walker = physics.add_character(capabilities=OmiCapabilities(radius=0.2))
    assert isinstance(walker.capabilities, CharacterCapabilities)
    assert walker.radius == pytest.approx(0.2)


def test_the_controller_is_a_deprecated_alias(physics):
    walker = physics.add_character()
    with pytest.warns(DeprecationWarning):
        controller = walker.controller
    assert controller is walker._controller


# -- joints ----------------------------------------------------------------

def test_a_hinge_reads_its_angle(physics):
    door = physics.add_dynamic(None, proxy=Proxy.box((1, 2, 0.1)), translation=(0.5, 1, 0))
    hinge = physics.add_hinge(door, anchor=(0, 1, 0), axis=(0, 1, 0), motor=(2.0, 5000.0))
    assert hinge.angle == pytest.approx(0.0, abs=1e-6)
    run(physics, 0.5)
    settle(physics)
    assert abs(hinge.angle) > 0.3


def test_a_slider_reads_its_position(physics):
    physics.gravity = (0.0, 0.0, 0.0)
    block = physics.add_dynamic(None, proxy=Proxy.box((1, 1, 1)), translation=(0, 1, 0))
    slider = physics.add_slider(block, axis=(1, 0, 0), motor=(1.0, 50000.0))
    assert slider.position == pytest.approx(0.0, abs=1e-6)
    run(physics, 0.5)
    settle(physics)
    assert slider.position > 0.2


def test_a_universal_joint_holds_its_anchor(physics):
    shaft = physics.add_dynamic(None, proxy=Proxy.box((0.2, 2, 0.2)), translation=(0, 1, 0))
    joint = physics.add_universal(shaft, anchor=(0, 2, 0), axis=(1, 0, 0), to_axis=(0, 0, 1))
    assert joint.kind == 'universal'
    run(physics, 0.5)
    settle(physics)
    top = np.asarray(shaft.position) + 0.0
    assert np.linalg.norm(top - (0, 1, 0)) < 0.2


def test_a_wheel_turns_on_its_axle_and_reads_its_angles(physics):
    car = physics.add_kinematic(None, proxy=Proxy.box((2, 0.5, 4)), translation=(0, 2, 0))
    wheel = physics.add_dynamic(None, proxy=Proxy.cylinder(0.3, 0.4), translation=(1.2, 2, 1.5))
    joint = physics.add_wheel(wheel, car, anchor=(1.2, 2, 1.5), steering_axis=(0, 1, 0),
                              axle=(1, 0, 0), steering_limits=(0.0, 0.0), motor=(5.0, 20.0),
                              suspension=(20000.0, 500.0))
    assert joint.kind == 'wheel'
    run(physics, 0.5)
    settle(physics)
    steer, spin = joint.angles
    assert abs(steer) < 0.05
    assert abs(spin) > 0.1
    assert joint.angle == pytest.approx(steer)


def test_a_motor_joint_turns_a_body(physics):
    physics.gravity = (0.0, 0.0, 0.0)
    rotor = physics.add_dynamic(None, proxy=Proxy.box((1, 0.1, 0.1)), translation=(0, 1, 0),
                                angular_damping=0.0)
    joint = physics.add_motor(rotor, axes=[(0, 1, 0)], torques=[5.0])
    assert joint.kind == 'motor'
    run(physics, 0.3)
    settle(physics)
    assert rotor.angular_velocity[1] > 0.1
    assert abs(joint.angle) > 0.0
    joint.drive(torques=[0.0])
    assert joint.torques == (0.0,)


def test_joint_kinds_reject_what_they_cannot_take(physics):
    body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5))
    with pytest.raises(ValueError):
        physics.add_motor(body, axes=[(0, 1, 0)], torques=[1.0, 2.0])
    with pytest.raises(ValueError):
        physics.add_universal(body, anchor=(0, 0, 0), axis=(1, 0, 0), to_axis=(1, 0, 0))
    ball = physics.add_ball(body, anchor=(0, 1, 0))
    with pytest.raises(AttributeError):
        ball.position  # noqa: B018 a ball has no slide to read


# -- deprecated aliases and the test helper ----------------------------------

@pytest.mark.engines('omi', reason='physics.world is the omi world; on Jolt it raises')
@pytest.mark.parametrize('name', ['world', 'backend'])
def test_the_world_reads_are_deprecated(name):
    physics = make('inline')
    try:
        with pytest.warns(DeprecationWarning):
            getattr(physics, name)
    finally:
        physics.close()


@pytest.mark.engines('omi', reason='reads the omi world and its slots')
def test_slot_reads_and_run_are_deprecated():
    physics = make('inline')
    try:
        body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5))
        with pytest.warns(DeprecationWarning):
            slot = physics.slot_of(body)
        with pytest.warns(DeprecationWarning):
            assert physics.body_at(slot) is body
        with pytest.warns(DeprecationWarning):
            assert physics.index_of(body) == slot
        with pytest.warns(DeprecationWarning):
            assert physics.run(lambda world: world.body_count).result() >= 1
    finally:
        physics.close()


@pytest.mark.engines('omi', reason='reads the omi world and its slots')
def test_the_test_helper_reaches_the_omi_world_and_slots():
    physics = make('inline')
    try:
        body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(1, 2, 3))
        world = physics_testing.inspect(physics)
        slot = physics_testing.slot_of(physics, body)
        assert np.allclose(world.position[slot], (1, 2, 3))
        assert physics_testing.body_at(physics, slot) is body
    finally:
        physics.close()


def test_the_test_helper_refuses_a_threaded_world():
    physics = make('thread')
    try:
        with pytest.raises(RuntimeError):
            physics_testing.inspect(physics)
    finally:
        physics.close()


def test_the_proxy_shape_is_a_deprecated_alias():
    proxy = Proxy.sphere(0.5)
    with pytest.warns(DeprecationWarning):
        assert proxy.shape.radius == 0.5


# -- state ------------------------------------------------------------------

def test_a_saved_state_puts_the_bodies_back(physics_engine):
    physics = make('inline')
    try:
        physics.add_static(None, proxy=Proxy.box((20, 1, 20)), translation=(0, -0.5, 0))
        body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 5, 0))
        run(physics, 0.2)
        if physics_engine == 'omi':
            # omi_physics keeps no state to save.
            with pytest.raises(NotImplementedError):
                physics.save_state()
            return
        saved = physics.save_state()
        settle(physics)
        at_save = float(physics.poses([body], interpolated=False).position[0][1])
        run(physics, 0.5)
        assert float(body.position[1]) < at_save - 0.1
        physics.restore_state(saved)
        run(physics, 0.02)
        assert float(physics.poses([body], interpolated=False).position[0][1]) > at_save - 0.05
    finally:
        physics.close()
