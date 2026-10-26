"""Tests for Physics, the service a context hosts, and the Body handles it returns.

These build scenegraph nodes from the engine's own surfaces and step a real
world with no window. Most run the service inline, where the test sets the clock;
the thread cases at the end run it on its worker.
"""
import threading

import numpy as np
import pytest
from omi_physics import model

from OpenGLContext.physics.callbacks import physics_callback
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

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


def settled(physics: Physics):
    """The runtime, after the commands made so far have been applied."""
    physics.worker.flush()
    return physics.worker.runtime


def shape_type(physics: Physics, body) -> str:
    runtime = settled(physics)
    return runtime.world.shapes[int(runtime.world.collider_shape[runtime.entry(body.uid).index])].type


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
    index = settled(physics).entry(body.uid).index
    assert settled(physics).world.mass[index] == pytest.approx(500.0)


def test_mass_given_is_the_mass(physics):
    body = physics.add_dynamic(ball(), mass=3.0)
    index = settled(physics).entry(body.uid).index
    assert settled(physics).world.mass[index] == pytest.approx(3.0)


@pytest.mark.parametrize('proxy, kind', [
    ('sphere', 'sphere'), ('box', 'box'), ('convex', 'convex'),
    (Proxy.capsule(1.0, 0.25), 'capsule'), (model.Shape.cylinder(1.0, 0.25), 'cylinder'),
])
def test_proxy_may_be_a_strategy_a_proxy_or_a_shape(physics, proxy, kind):
    body = physics.add_dynamic(ball(), proxy=proxy)
    assert shape_type(physics, body) == kind


def test_proxy_may_be_another_node_drawing_a_simpler_mesh(physics):
    body = physics.add_dynamic(block((2, 2, 2)), proxy=ball(1.0))
    assert shape_type(physics, body) == 'sphere'


def test_a_proxy_is_shared_by_the_bodies_made_with_it(physics):
    crate = physics.cook(block((1, 1, 1)), 'box')
    for number in range(4):
        physics.add_dynamic(block((1, 1, 1), at=(number * 2, 5, 0)), proxy=crate)
    physics.frame(0.0)
    assert len(settled(physics).world.shapes) == 1


def test_a_node_that_draws_nothing_is_refused_with_its_name(physics):
    from OpenGLContext.scenegraph.transform import Transform
    with pytest.raises(ValueError, match='no triangles'):
        physics.add_dynamic(Transform())


def test_friction_and_restitution_keywords_make_a_material(physics):
    bouncy = physics.add_dynamic(ball(), restitution=0.9, friction=0.2)
    plain = physics.add_dynamic(ball())
    world = settled(physics).world
    material = world.material_for(int(world.collider_material[settled(physics).entry(bouncy.uid).index]))
    assert material.restitution == pytest.approx(0.9)
    assert material.staticFriction == pytest.approx(0.2)
    assert int(world.collider_material[settled(physics).entry(plain.uid).index]) == -1


def test_a_material_name_is_a_preset(physics):
    body = physics.add_dynamic(ball(), material='rubber')
    world = settled(physics).world
    index = settled(physics).entry(body.uid).index
    assert world.material_for(int(world.collider_material[index])).restitution == pytest.approx(
        model.MATERIAL_PRESETS['rubber'].restitution)


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
    assert crate.uid not in settled(physics)


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
    runtime = settled(physics)
    assert runtime.world.position[runtime.entry(body.uid).index] == pytest.approx((3.0, 7.0, 0.0))


def test_a_joint_made_while_paused_holds_on_resume(physics):
    body = physics.add_dynamic(ball(at=(1, 5, 0)))
    physics.enable(False)
    physics.add_ball(body, anchor=(0, 5, 0))
    physics.enable(True)
    run_for(physics, 0.5)
    assert len(settled(physics).joints) == 1
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
        assert service.worker.settle()
        assert crate.uid not in service.worker.runtime
    finally:
        service.close()


def test_enable_with_a_tick_frequency_changes_the_step(physics):
    physics.enable(True, tick_frequency=200.0)
    physics.frame(0.0)
    assert settled(physics).step_dt == pytest.approx(0.005)


def test_step_advances_a_standalone_service_by_hand(physics):
    node = ball()
    physics.add_dynamic(node)
    physics.step(0.3)
    physics.frame(0.0)
    assert node.translation[1] < 5.0


def test_world_is_the_live_world_in_inline_mode(physics):
    assert physics.world is settled(physics).world


def test_world_is_refused_when_a_thread_owns_it():
    service = Physics(PhysicsDefinition(mode='thread'))
    try:
        with pytest.raises(RuntimeError, match='run'):
            _ = service.world
    finally:
        service.close()


def test_set_config_changes_gravity_and_the_step(physics):
    body = physics.add_dynamic(ball(), linear_damping=0.0)
    physics.set_config(PhysicsDefinition(mode='inline', gravity=(0, -2.0, 0), tickHz=200.0,
                                         maxCatchUp=2.0))
    run_for(physics, 0.5)
    assert body.velocity[1] == pytest.approx(-1.0, abs=0.15)
    assert settled(physics).step_dt == pytest.approx(0.005)


def test_set_config_refuses_a_definition_that_cannot_run(physics):
    with pytest.raises(ValueError, match='tickHz'):
        physics.set_config(PhysicsDefinition(tickHz=-1.0))


def test_run_calls_a_function_with_the_world_and_returns_its_answer(physics):
    physics.add_dynamic(ball())
    future = physics.run(lambda world: world.live_body_count)
    assert future.result(timeout=2) == 1


def test_post_calls_a_function_on_the_worker(physics):
    seen = []
    physics.post(seen.append, 'x')
    physics.frame(0.0)
    assert seen == ['x']


def test_run_reports_what_the_function_raised(physics):
    def fails(world):
        raise ValueError('refused')

    with pytest.raises(ValueError, match='refused'):
        physics.run(fails).result(timeout=2)


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
        service.worker.wait_ticks(10)
        service.frame(0.016)
        assert node.translation[1] < 5.0
        body.apply_impulse((0, 0, 4))
        service.worker.settle()
        service.frame(0.016)
        assert body.velocity[2] > 0.0
    finally:
        service.close()


def test_a_thread_service_asks_for_frames_only_while_something_moves():
    service = Physics(PhysicsDefinition(mode='thread', tickHz=200.0))
    try:
        service.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
        service.add_dynamic(ball(0.5, at=(0, 0.6, 0)), restitution=0.0)
        worker = service.worker
        import time
        deadline = time.monotonic() + 20.0
        asked = True
        while asked and time.monotonic() < deadline:
            time.sleep(0.05)
            asked = service.frame(0.016)
        assert not asked
        assert worker.idle
    finally:
        service.close()


def test_close_stops_the_thread_and_is_safe_twice():
    service = Physics(PhysicsDefinition(mode='thread'))
    service.add_dynamic(ball())
    service.close()
    service.close()
    assert service.worker.thread_id is None


def test_switching_mode_keeps_the_bodies():
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0))
    try:
        node = ball()
        body = service.add_dynamic(node)
        run_for(service, 0.2)
        before = body.position[1]
        service.set_config(PhysicsDefinition(mode='thread', maxCatchUp=2.0))
        service.worker.wait_ticks(10)
        service.frame(0.016)
        assert body.alive and body.position[1] < before
    finally:
        service.close()


def test_a_place_waiting_behind_a_callback_write_is_not_read_as_applied():
    """A physics callback's write is applied in the step; a render-thread write
    still in the inbox is not, though the callback's write is numbered after it."""
    service = make(mode='thread', gravity=(0.0, 0.0, 0.0))
    in_step, posted = threading.Event(), threading.Event()
    try:
        node = ball(at=(0, 5, 0))
        body = service.add_dynamic(node)
        body.set_velocity((1.0, 0.0, 0.0))

        @physics_callback
        def push(step):
            if not in_step.is_set():
                in_step.set()
                posted.wait(5.0)
            body.set_force((0.0, 0.0, 0.0))

        service.addEventHandler('before-step', push)
        assert in_step.wait(5.0)
        body.set_transform((9.0, 9.0, 9.0))
        thread = service.worker._thread
        service.worker._stop.set()      # the thread ends after this step, the place still queued
        posted.set()
        thread.join(5.0)
        service.frame(0.02)
        assert body.position == pytest.approx((9.0, 9.0, 9.0))
        assert tuple(node.translation) == pytest.approx((0.0, 5.0, 0.0))   # no stale pose written
    finally:
        posted.set()
        service.close()
