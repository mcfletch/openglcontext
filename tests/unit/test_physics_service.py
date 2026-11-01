"""Tests for Physics, the service a context hosts, and the Body handles it returns.

These build scenegraph nodes from the engine's own surfaces and step a real
world with no window. Most run the service inline, where the test sets the clock;
the thread cases at the end run it on the world thread.
"""
import threading
import time

import numpy as np
import pytest

from OpenGLContext.physics.materials import PRESETS
from OpenGLContext.physics.callbacks import physics_callback
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.testing import physics as physics_testing


LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def ball(radius=0.5, at=(0, 5, 0)):
    return surfaces.shape(surfaces.sphere(radius), LOOK, translation=at)


def block(size, at=(0, 0, 0)):
    return surfaces.shape(surfaces.block(size), LOOK, translation=at)


def make(**named) -> Physics:
    named.setdefault('mode', 'inline')
    named.setdefault('maxCatchUp', 2.0)
    named.setdefault('tickHz', 100.0)
    return Physics(PhysicsDefinition(**named))



def run_for(physics: Physics, seconds: float, frame: float = 0.02) -> None:
    for _ in range(int(round(seconds / frame))):
        physics.frame(frame)


@pytest.fixture
def physics():
    service = make()
    yield service
    service.close()


# -- adding ----------------------------------------------------------------

def test_a_dynamic_body_falls_and_its_node_follows(physics):
    node = ball()
    body = physics.add_dynamic(node)
    run_for(physics, 0.5)
    assert node.translation[1] < 5.0
    assert body.position[1] == pytest.approx(node.translation[1], abs=0.02)


def test_translation_and_rotation_place_the_node_before_the_body_is_made(physics):
    node = ball(at=(0, 0, 0))
    body = physics.add_dynamic(node, translation=(1, 2, 3), rotation=(0, 1, 0, 0.5))
    assert tuple(node.translation) == (1, 2, 3)
    assert body.position == pytest.approx((1, 2, 3))
    assert tuple(node.rotation) == pytest.approx((0, 1, 0, 0.5))


def test_a_static_body_never_moves_and_stops_a_dynamic_one(physics):
    floor = block((20, 1, 20), at=(0, -0.5, 0))
    node = ball(0.5, at=(0, 2, 0))
    physics.add_static(floor)
    physics.add_dynamic(node, restitution=0.0)
    run_for(physics, 3.0)
    assert node.translation[1] == pytest.approx(0.5, abs=0.06)
    assert tuple(floor.translation) == (0, -0.5, 0)


def test_a_kinematic_body_is_pushed_by_nothing_and_has_the_kind(physics):
    body = physics.add_kinematic(block((1, 1, 1), at=(0, 3, 0)))
    run_for(physics, 0.5)
    assert body.kind == 'kinematic'
    assert body.position[1] == pytest.approx(3.0)


def test_add_returns_a_body_with_a_kind_and_the_node(physics):
    node = ball()
    body = physics.add_dynamic(node)
    assert body.kind == 'dynamic' and body.node is node and body.uid > 0


def test_body_ids_are_never_reused(physics):
    first = physics.add_dynamic(ball())
    physics.remove(first)
    second = physics.add_dynamic(ball())
    assert second.uid != first.uid


def test_mass_comes_from_the_shape_when_none_is_given(physics):
    body = physics.add_dynamic(block((1, 1, 1), at=(0, 5, 0)), proxy='box')
    assert physics_testing.mass(physics, body) == pytest.approx(500.0)


def test_mass_given_is_the_mass(physics):
    body = physics.add_dynamic(ball(), mass=3.0)
    assert physics_testing.mass(physics, body) == pytest.approx(3.0)
    # Read from the world, not from what the service asked for.
    engine = physics._engine
    engine.given[body.uid] = (1.0, engine.given[body.uid][1])
    assert physics_testing.mass(physics, body) == pytest.approx(3.0)
    body.set_mass(5.0)
    assert physics_testing.mass(physics, body) == pytest.approx(5.0)
    assert body.velocity == pytest.approx((0.0, 0.0, 0.0))
    assert physics_testing.mass(physics, physics.add_static(block((1, 1, 1)))) == 0.0


@pytest.mark.parametrize('proxy, kind', [
    ('sphere', 'sphere'), ('box', 'box'), ('convex', 'convex'),
    (Proxy.capsule(1.0, 0.25), 'capsule'), (Proxy.cylinder(1.0, 0.25), 'cylinder'),
])
def test_proxy_may_be_a_strategy_or_a_proxy(physics, proxy, kind):
    body = physics.add_dynamic(ball(), proxy=proxy)
    assert physics_testing.shape_kind(physics, body) == kind


def test_proxy_may_be_another_node_drawing_a_simpler_mesh(physics):
    body = physics.add_dynamic(block((2, 2, 2)), proxy=ball(1.0))
    assert physics_testing.shape_kind(physics, body) == 'sphere'


def test_a_proxy_is_shared_by_the_bodies_made_with_it(physics):
    crate = physics.cook(block((1, 1, 1)), 'box')
    for number in range(4):
        physics.add_dynamic(block((1, 1, 1), at=(number * 2, 5, 0)), proxy=crate)
    physics.frame(0.0)
    assert physics_testing.shape_count(physics) == 1


def test_a_node_that_draws_nothing_is_refused_with_its_name(physics):
    from OpenGLContext.scenegraph.transform import Transform
    with pytest.raises(ValueError, match='no triangles'):
        physics.add_dynamic(Transform())


def test_friction_and_restitution_keywords_make_a_material(physics):
    bouncy = physics.add_dynamic(ball(), restitution=0.9, friction=0.2)
    plain = physics.add_dynamic(ball())
    material = physics_testing.material(physics, bouncy)
    assert material.restitution == pytest.approx(0.9)
    assert material.staticFriction == pytest.approx(0.2)
    assert physics_testing.material(physics, plain) is None


def test_a_material_name_is_a_preset(physics):
    body = physics.add_dynamic(ball(), material='rubber')
    assert physics_testing.material(physics, body).restitution == pytest.approx(
        PRESETS['rubber'].restitution)


def test_a_bouncier_ball_rises_higher(physics):
    floor = block((20, 1, 20), at=(0, -0.5, 0))
    physics.add_static(floor, restitution=0.0)
    high = ball(0.25, at=(-3, 3, 0))
    low = ball(0.25, at=(3, 3, 0))
    physics.add_dynamic(high, restitution=0.95)
    physics.add_dynamic(low, restitution=0.05)
    peaks = {id_: 0.0 for id_ in ('high', 'low')}
    landed = {'high': False, 'low': False}
    for _ in range(150):
        physics.frame(0.02)
        for name, node in (('high', high), ('low', low)):
            if node.translation[1] < 0.3:
                landed[name] = True
            elif landed[name]:
                peaks[name] = max(peaks[name], node.translation[1])
    assert peaks['high'] > peaks['low'] + 0.5


# -- writing ---------------------------------------------------------------

def test_an_impulse_moves_a_body_by_impulse_over_mass(physics):
    physics.gravity = (0, 0, 0)
    body = physics.add_dynamic(ball(at=(0, 0, 0)), mass=2.0, linear_damping=0.0)
    body.apply_impulse((0, 0, 3))
    physics.frame(0.02)
    assert body.velocity == pytest.approx((0, 0, 1.5), abs=0.01)
    run_for(physics, 1.0)
    assert body.position[2] == pytest.approx(1.5, rel=0.1)


def test_a_body_nobody_has_written_to_keeps_its_velocity_reading_at_zero(physics):
    physics.gravity = (0, 0, 0)
    body = physics.add_dynamic(ball(at=(0, 0, 0)))
    physics.frame(0.1)
    assert body.speed == pytest.approx(0.0)


def test_set_velocity_and_speed(physics):
    physics.gravity = (0, 0, 0)
    body = physics.add_dynamic(ball(at=(0, 0, 0)), linear_damping=0.0)
    body.set_velocity((3, 4, 0))
    physics.frame(0.02)
    assert body.speed == pytest.approx(5.0, abs=0.01)


def test_a_torque_impulse_spins_the_body(physics):
    physics.gravity = (0, 0, 0)
    body = physics.add_dynamic(block((1, 1, 1), at=(0, 0, 0)), angular_damping=0.0)
    body.apply_torque_impulse((0, 3, 0))
    physics.frame(0.02)
    assert body.angular_velocity[1] > 0.0


def test_set_force_pushes_until_cleared(physics):
    physics.gravity = (0, 0, 0)
    body = physics.add_dynamic(ball(at=(0, 0, 0)), mass=1.0, linear_damping=0.0)
    body.set_force((10, 0, 0))
    run_for(physics, 0.5)
    pushed = body.velocity[0]
    body.set_force((0, 0, 0))
    run_for(physics, 0.5)
    assert pushed == pytest.approx(5.0, rel=0.1)
    assert body.velocity[0] == pytest.approx(pushed, rel=0.05)


def test_set_transform_teleports_and_reads_back_at_once(physics):
    node = ball(at=(0, 5, 0))
    body = physics.add_dynamic(node)
    body.set_transform(translation=(7, 8, 9))
    assert body.position == pytest.approx((7, 8, 9))
    physics.frame(0.02)
    assert node.translation[0] == pytest.approx(7, abs=0.01)


def test_set_transform_turns_a_body(physics):
    physics.gravity = (0, 0, 0)
    node = block((1, 2, 3), at=(0, 0, 0))
    body = physics.add_dynamic(node)
    body.set_transform(rotation=(0, 1, 0, np.pi / 2))
    physics.frame(0.02)
    assert body.rotation[3] == pytest.approx(np.pi / 2, abs=0.02)
    assert node.rotation[3] == pytest.approx(np.pi / 2, abs=0.02)


def test_orientation_is_the_rotation_as_a_quaternion(physics):
    physics.gravity = (0, 0, 0)
    body = physics.add_dynamic(block((1, 2, 3)))
    body.set_transform(rotation=(0, 1, 0, np.pi / 2))
    physics.frame(0.02)
    half = np.sqrt(0.5)
    assert body.orientation == pytest.approx((0.0, half, 0.0, half), abs=1e-6)


def test_matrix_places_a_point_of_the_body_in_the_world(physics):
    """Row-vector: the body's local +x, turned a quarter about +y, points along -z."""
    physics.gravity = (0, 0, 0)
    body = physics.add_dynamic(block((1, 2, 3)))
    body.set_transform(translation=(4, 5, 6), rotation=(0, 1, 0, np.pi / 2))
    physics.frame(0.02)
    matrix = body.matrix
    assert matrix.shape == (4, 4)
    assert np.array([1.0, 0.0, 0.0, 1.0]) @ matrix == pytest.approx((4, 5, 5, 1), abs=1e-6)
    assert matrix[3, :3] == pytest.approx(body.position)


def test_an_unturned_body_has_the_identity_orientation(physics):
    body = physics.add_static(block((1, 1, 1)))
    assert body.orientation == pytest.approx((0, 0, 0, 1))
    assert body.matrix[:3, :3] == pytest.approx(np.eye(3))


def test_a_write_to_the_node_does_not_move_a_dynamic_body(physics):
    node = ball(at=(0, 5, 0))
    physics.add_dynamic(node)
    node.translation = (50, 50, 50)
    run_for(physics, 0.1)
    assert node.translation[0] != pytest.approx(50)


def test_gravity_can_change_while_the_world_runs(physics):
    body = physics.add_dynamic(ball(at=(0, 5, 0)), linear_damping=0.0)
    physics.gravity = (0, 0, -9.81)
    run_for(physics, 0.5)
    assert body.velocity[2] < -3.0
    assert abs(body.velocity[1]) < 0.5


def test_time_is_the_seconds_of_steps_the_world_has_taken(physics):
    assert physics.time == 0.0
    physics.add_dynamic(ball())
    run_for(physics, 0.5, frame=0.05)
    assert physics.time == pytest.approx(0.5)


def test_time_inside_a_step_is_the_time_that_step_began(physics):
    seen = []

    @physics_callback
    def before(step):
        seen.append((step.time, physics.time))

    handler = physics.addEventHandler('before-step', before)
    physics.add_dynamic(ball())
    run_for(physics, 0.05, frame=0.05)
    handler.cancel()
    assert len(seen) == 5
    assert [clock for clock, _ in seen] == pytest.approx([read for _, read in seen])


def test_damping_setters_slow_a_body(physics):
    physics.gravity = (0, 0, 0)
    body = physics.add_dynamic(ball(at=(0, 0, 0)), linear_damping=0.0)
    body.set_velocity((10, 0, 0))
    body.linear_damping = 6.0
    run_for(physics, 0.5)
    assert 0.0 < body.velocity[0] < 3.0


def test_remove_ends_the_nodes_pose_and_forgets_the_body(physics):
    node = ball()
    body = physics.add_dynamic(node)
    run_for(physics, 0.1)
    physics.remove(body)
    run_for(physics, 0.1)
    held = node.translation[1]
    run_for(physics, 0.3)
    assert node.translation[1] == pytest.approx(held)
    assert physics.body_for(node) is None
    assert not body.alive


def test_a_writer_on_a_removed_body_does_nothing(physics):
    body = physics.add_dynamic(ball())
    body.remove()
    body.apply_impulse((1, 0, 0))
    body.set_transform(translation=(1, 1, 1))
    run_for(physics, 0.1)
    assert not body.alive


def test_body_remove_and_physics_remove_are_the_same(physics):
    body = physics.add_dynamic(ball())
    body.remove()
    body.remove()
    assert not body.alive


# -- the frame ---------------------------------------------------------------

def test_the_frame_asks_for_a_redraw_while_a_body_is_awake_and_stops_once_it_sleeps(physics):
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    physics.add_dynamic(ball(0.5, at=(0, 1.5, 0)), restitution=0.0)
    asked = [physics.frame(0.02) for _ in range(400)]
    assert asked[0] is True
    assert asked[-1] is False
    assert True in asked and asked.index(False) > 5


def test_a_scene_with_nothing_dynamic_never_asks_for_a_frame(physics):
    physics.add_static(block((20, 1, 20)))
    assert [physics.frame(0.02) for _ in range(5)] == [False] * 5


def test_poses_are_written_only_for_awake_bodies(physics):
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    node = ball(0.5, at=(0, 0.6, 0))
    physics.add_dynamic(node, restitution=0.0)
    run_for(physics, 8.0)
    settled = tuple(node.translation)
    node.translation = (9, 9, 9)           # a sleeping body's node is left alone
    physics.frame(0.02)
    assert tuple(node.translation) == (9, 9, 9)
    assert settled[1] == pytest.approx(0.5, abs=0.06)


def test_a_disabled_service_keeps_everything_where_it_was_put():
    service = Physics(PhysicsDefinition(enabled=False, mode='inline'))
    node = ball()
    body = service.add_dynamic(node)
    assert service.frame(0.1) is False
    assert node.translation[1] == pytest.approx(5.0)
    body.apply_impulse((1, 0, 0))
    assert body.kind == 'dynamic'
    service.close()


def test_enable_false_pauses_and_true_resumes(physics):
    node = ball()
    physics.add_dynamic(node)
    run_for(physics, 0.2)
    physics.enable(False)
    held = node.translation[1]
    run_for(physics, 0.2)
    assert node.translation[1] == pytest.approx(held)
    physics.enable(True)
    run_for(physics, 0.2)
    assert node.translation[1] < held


def test_a_body_removed_while_paused_leaves_the_world_on_resume(physics):
    crate = physics.add_dynamic(ball())
    run_for(physics, 0.1)
    physics.enable(False)
    physics.remove(crate)
    physics.enable(True)
    run_for(physics, 0.1)
    assert not physics_testing.holds(physics, crate)


def test_a_body_added_while_paused_falls_on_resume(physics):
    physics.enable(False)
    node = ball()
    physics.add_dynamic(node)
    run_for(physics, 0.1)
    assert node.translation[1] == pytest.approx(5.0)
    physics.enable(True)
    run_for(physics, 0.3)
    assert node.translation[1] < 5.0


def test_a_transform_set_while_paused_is_applied_and_read_back(physics):
    body = physics.add_dynamic(ball())
    physics.enable(False)
    body.set_transform((3.0, 7.0, 0.0))
    assert body.position == pytest.approx((3.0, 7.0, 0.0))
    physics.enable(True)
    physics.frame(0.0)
    assert physics_testing.world_position(physics, body) == pytest.approx((3.0, 7.0, 0.0), abs=0.01)


def test_a_joint_made_while_paused_holds_on_resume(physics):
    body = physics.add_dynamic(ball(at=(1, 5, 0)))
    physics.enable(False)
    physics.add_ball(body, anchor=(0, 5, 0))
    physics.enable(True)
    run_for(physics, 0.5)
    assert physics_testing.joint_count(physics) == 1
    assert np.linalg.norm(body.position - np.array((0.0, 5.0, 0.0))) == pytest.approx(1.0, abs=0.05)


def test_a_service_disabled_at_start_runs_its_bodies_once_enabled():
    service = make(enabled=False)
    try:
        node = ball()
        body = service.add_dynamic(node)
        body.apply_impulse((2, 0, 0))
        service.enable(True)
        run_for(service, 0.3)
        assert node.translation[1] < 5.0
        assert node.translation[0] > 0.0
    finally:
        service.close()


def test_a_body_removed_while_paused_on_a_thread_leaves_the_world_on_resume():
    service = make(mode='thread')
    try:
        crate = service.add_dynamic(ball())
        service.add_dynamic(ball(at=(3, 5, 0)))
        service.enable(False)
        service.remove(crate)
        service.enable(True)
        assert not physics_testing.holds(service, crate)
    finally:
        service.close()


def test_a_tick_frequency_other_than_the_worlds_is_refused_changing_nothing(physics):
    # A Jolt world steps at the rate it was made with: its tick is part of the world thread.
    with pytest.raises(ValueError, match='100 steps a second'):
        physics.enable(False, tick_frequency=200.0)
    assert physics.definition.tickHz == 100.0
    assert physics._enabled
    physics.enable(True, tick_frequency=100.0)
    physics.frame(0.0)
    assert physics_testing.step_dt(physics) == pytest.approx(0.01)


def test_set_config_refuses_another_step_changing_nothing(physics):
    with pytest.raises(ValueError, match='tickHz'):
        physics.set_config(physics.definition.replaced(tickHz=240.0, gravity=(0.0, -1.0, 0.0)))
    assert physics.definition.tickHz == 100.0
    assert physics.gravity == pytest.approx((0.0, -9.81, 0.0))


def test_step_advances_a_standalone_service_by_hand(physics):
    node = ball()
    physics.add_dynamic(node)
    physics.step(0.3)
    physics.frame(0.0)
    assert node.translation[1] < 5.0


def test_set_config_changes_gravity_and_keeps_the_step(physics):
    body = physics.add_dynamic(ball(), linear_damping=0.0)
    physics.set_config(PhysicsDefinition(mode='inline', gravity=(0, -2.0, 0), tickHz=100.0,
                                         maxCatchUp=2.0))
    run_for(physics, 0.5)
    assert body.velocity[1] == pytest.approx(-1.0, abs=0.15)
    assert physics_testing.step_dt(physics) == pytest.approx(0.01)


def test_set_config_refuses_a_definition_that_cannot_run(physics):
    with pytest.raises(ValueError, match='tickHz'):
        physics.set_config(PhysicsDefinition(tickHz=-1.0))


def test_post_calls_a_function_on_the_stepping_thread(physics):
    seen = []
    physics.post(seen.append, 'x')
    physics.frame(0.0)
    assert seen == ['x']


# -- finding a body ------------------------------------------------------------

def test_body_for_finds_the_body_of_a_node(physics):
    node = ball()
    body = physics.add_dynamic(node)
    assert physics.body_for(node) is body


def test_body_for_finds_the_nearest_ancestor_with_a_body(physics):
    from OpenGLContext.scenegraph.transform import Transform
    inner = ball(at=(0, 0, 0))
    outer = Transform(children=[inner], translation=(0, 5, 0))
    body = physics.add_dynamic(outer)
    assert physics.body_for(inner, within=outer) is body


def test_body_for_a_node_without_one_is_none(physics):
    assert physics.body_for(ball()) is None


def test_bodies_in_lists_the_bodies_under_a_node(physics):
    from OpenGLContext.scenegraph.transform import Transform
    one, two = ball(at=(0, 5, 0)), ball(at=(3, 5, 0))
    group = Transform(children=[one, two])
    first, second = physics.add_dynamic(one), physics.add_dynamic(two)
    assert set(physics.bodies_in(group)) == {first, second}


# -- the thread ----------------------------------------------------------------

def test_the_service_runs_on_a_thread_without_the_caller_stepping_it():
    service = Physics(PhysicsDefinition(mode='thread', tickHz=200.0))
    try:
        node = ball()
        body = service.add_dynamic(node)
        physics_testing.wait_ticks(service, 10)
        service.frame(0.016)
        assert node.translation[1] < 5.0
        body.apply_impulse((0, 0, 4))
        physics_testing.settle(service)
        service.frame(0.016)
        assert body.velocity[2] > 0.0
    finally:
        service.close()


def test_a_thread_service_asks_for_frames_only_while_something_moves():
    service = Physics(PhysicsDefinition(mode='thread', tickHz=200.0))
    try:
        service.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
        service.add_dynamic(ball(0.5, at=(0, 0.6, 0)), restitution=0.0)
        deadline = time.monotonic() + 20.0
        asked = True
        while asked and time.monotonic() < deadline:
            time.sleep(0.05)
            asked = service.frame(0.016)
        assert not asked
        # The world thread goes idle once it has published the step that left
        # everything asleep; the frame reads that step a moment before.
        while not physics_testing.idle(service) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert physics_testing.idle(service)
    finally:
        service.close()


def test_close_stops_the_thread_and_is_safe_twice():
    service = Physics(PhysicsDefinition(mode='thread'))
    service.add_dynamic(ball())
    service.close()
    service.close()
    assert not physics_testing.stepping(service)


def test_switching_mode_keeps_the_bodies():
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0))
    try:
        node = ball()
        body = service.add_dynamic(node)
        run_for(service, 0.2)
        before = body.position[1]
        service.set_config(PhysicsDefinition(mode='thread', maxCatchUp=2.0))
        physics_testing.wait_ticks(service, 10)
        service.frame(0.016)
        assert body.alive and body.position[1] < before
    finally:
        service.close()


def test_a_physics_callback_leaves_the_render_threads_tables_to_the_render_thread():
    service = make(mode='thread')
    removed = threading.Event()
    try:
        service.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
        crate = service.add_dynamic(ball(at=(0, 3, 0)))
        other = service.add_dynamic(ball(at=(4, 3, 0)))

        @physics_callback
        def remove_it(step):
            if crate.alive:
                other.set_velocity((1.0, 0.0, 0.0))
                service.remove(crate)
                removed.set()

        service.addEventHandler('before-step', remove_it)
        assert removed.wait(5.0)
        physics_testing.settle(service)
        assert not physics_testing.holds(service, crate)
        assert crate.uid in service._bodies and crate.uid in service._specs
        service.frame(0.02)
        assert crate.uid not in service._bodies and crate.uid not in service._specs
        assert crate not in service._movers
    finally:
        service.close()


# -- physical inputs are checked ---------------------------------------------------

NAN, INF = float('nan'), float('inf')


@pytest.mark.parametrize(('options', 'named'), [
    ({'mass': 0.0}, 'mass'),
    ({'mass': -2.0}, 'mass'),
    ({'mass': NAN}, 'mass'),
    ({'mass': INF}, 'mass'),
    ({'density': 0.0}, 'density'),
    ({'translation': (NAN, 0.0, 0.0)}, 'translation'),
    ({'translation': (0.0, INF, 0.0)}, 'translation'),
    ({'rotation': (0.0, 1.0, 0.0, NAN)}, 'rotation'),
    ({'linear_damping': -1.0}, 'linear_damping'),
    ({'angular_damping': NAN}, 'angular_damping'),
    ({'friction': NAN}, 'friction'),
    ({'restitution': -0.5}, 'restitution'),
])
def test_a_dynamic_body_with_an_impossible_input_is_refused(physics, options, named):
    with pytest.raises(ValueError, match=named):
        physics.add_dynamic(ball(), **options)
    assert not physics._bodies


@pytest.mark.parametrize(('write', 'named'), [
    (lambda body: body.apply_impulse((NAN, 0, 0)), 'impulse'),
    (lambda body: body.apply_impulse((1, 0, 0), at=(0, INF, 0)), 'at'),
    (lambda body: body.apply_torque_impulse((0, NAN, 0)), 'impulse'),
    (lambda body: body.set_force((INF, 0, 0)), 'force'),
    (lambda body: body.set_velocity((0, 0, NAN)), 'velocity'),
    (lambda body: body.set_angular_velocity((0, INF, 0)), 'velocity'),
    (lambda body: body.set_transform((NAN, 0, 0)), 'translation'),
    (lambda body: body.set_transform(None, (0, 1, 0, INF)), 'rotation'),
    (lambda body: setattr(body, 'linear_damping', -1.0), 'linear_damping'),
    (lambda body: setattr(body, 'angular_damping', NAN), 'angular_damping'),
])
def test_a_write_of_an_impossible_value_is_refused(physics, write, named):
    body = physics.add_dynamic(ball())
    with pytest.raises(ValueError, match=named):
        write(body)
    physics.frame(0.02)
    assert np.all(np.isfinite(body.position))


@pytest.mark.parametrize(('fields', 'named'), [
    ({'tickHz': INF}, 'tickHz'),
    ({'tickHz': NAN}, 'tickHz'),
    ({'maxCatchUp': INF}, 'maxCatchUp'),
    ({'gravity': (0.0, NAN, 0.0)}, 'gravity'),
    ({'linearDamping': -1.0}, 'linearDamping'),
    ({'angularDamping': INF}, 'angularDamping'),
])
def test_a_definition_with_an_impossible_value_is_refused(fields, named):
    with pytest.raises(ValueError, match=named):
        PhysicsDefinition(**fields).validate()


def test_an_infinite_tick_frequency_and_gravity_are_refused(physics):
    with pytest.raises(ValueError, match='tick_frequency'):
        physics.enable(True, tick_frequency=INF)
    with pytest.raises(ValueError, match='gravity'):
        physics.gravity = (0.0, INF, 0.0)


def test_a_static_body_placed_by_hand_reads_back_where_it_was_put(physics):
    wall = physics.add_static(block((1, 1, 1), at=(0, 0, 0)))
    wall.set_transform((4.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.5))
    run_for(physics, 0.1)
    assert wall.position == pytest.approx((4.0, 0.0, 0.0))
    assert wall.rotation == pytest.approx((0.0, 1.0, 0.0, 0.5))


def test_a_node_that_has_a_body_is_refused_a_second(physics):
    node = ball()
    first = physics.add_dynamic(node)
    with pytest.raises(ValueError, match='already'):
        physics.add_static(node)
    assert physics.body_for(node) is first
    first.remove()
    second = physics.add_kinematic(node)
    assert physics.body_for(node) is second


def test_a_frame_time_that_is_not_a_number_is_refused_and_the_clock_runs_on(physics):
    body = physics.add_dynamic(ball())
    physics.frame(0.02)
    with pytest.raises(ValueError, match='dt'):
        physics.frame(float('nan'))
    with pytest.raises(ValueError, match='dt'):
        physics.step(float('nan'))
    before = physics.time
    run_for(physics, 0.2)
    assert physics.time == pytest.approx(before + 0.2, abs=0.011)
    physics.frame(float('inf'))         # clamped to maxCatchUp
    physics.frame(-1.0)                 # a clock that went back adds no time
    assert body.alive


def test_settle_fails_where_the_world_does_not_take_the_commands(monkeypatch):
    service = make(mode='thread')
    try:
        body = service.add_dynamic(ball())
        physics_testing.settle(service)
        service.enable(False)           # a paused world takes no commands
        body.set_velocity((1.0, 0.0, 0.0))
        monkeypatch.setattr(physics_testing, 'WAIT', 0.2)
        with pytest.raises(AssertionError, match='commands'):
            physics_testing.settle(service)
    finally:
        service.close()
