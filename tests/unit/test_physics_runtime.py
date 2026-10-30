"""Tests for WorldRuntime, the worker-side state of a physics service.

The runtime owns one omi_physics world, applies plain-data commands to it, steps
it by a fixed step and publishes snapshots and events as data. These tests drive
a real world with no window and no scenegraph.
"""
import numpy as np
import pytest
from omi_physics import model

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.records import Motion, BodySpec, Command
from OpenGLContext.physics.runtime import WorldRuntime
from OpenGLContext.physics.settings import PhysicsDefinition


def runtime(gravity=(0.0, -9.81, 0.0), tick_hz=100.0, **named) -> WorldRuntime:
    return WorldRuntime(PhysicsDefinition(gravity=gravity, tickHz=tick_hz, **named))


def add(rt: WorldRuntime, uid: int, kind: str, proxy: Proxy, position=(0, 0, 0),
        mass: float = 1.0, **named) -> BodySpec:
    spec = BodySpec(uid, kind, proxy, Motion(mass=mass), position=tuple(position), **named)
    rt.apply(Command('add', uid, (spec,)))
    return spec


def test_a_dropped_ball_falls_by_the_fixed_steps_that_fit_the_frame():
    rt = runtime()
    add(rt, 1, 'dynamic', Proxy.sphere(0.5), position=(0, 10, 0))
    rt.step_frame(0.1)                       # ten steps of 0.01
    snapshot = rt.snapshot()
    row = snapshot.rows[1]
    assert snapshot.step == 10
    assert snapshot.time == pytest.approx(0.1)
    expected = 10.0 - 0.5 * 9.81 * 0.1 ** 2
    assert snapshot.position[row][1] == pytest.approx(expected, abs=0.06)


def test_the_remainder_of_a_frame_carries_to_the_next():
    rt = runtime(tick_hz=64.0)               # a step of 1/64 s, exact in binary
    assert rt.step_frame(0.0390625) == 2     # 2.5 steps: half a step is left
    assert rt.step_frame(0.0390625) == 3     # 3 whole steps: nothing is left
    assert rt.world.step_count == 5


def test_a_frame_longer_than_the_catch_up_steps_only_that_much():
    rt = runtime(tick_hz=64.0, maxCatchUp=0.078125)    # five steps
    assert rt.step_frame(5.0) == 5


def test_a_step_that_floating_point_leaves_a_hair_short_is_still_taken():
    rt = runtime(tick_hz=100.0)
    assert sum(rt.step_frame(0.01) for _ in range(100)) == 100


def test_static_bodies_are_not_in_the_snapshot():
    rt = runtime()
    add(rt, 1, 'static', Proxy.box((10, 1, 10)))
    add(rt, 2, 'dynamic', Proxy.sphere(0.5), position=(0, 3, 0))
    snapshot = rt.snapshot()
    assert 1 not in snapshot.rows and 2 in snapshot.rows


def test_an_impulse_changes_velocity_by_impulse_over_mass():
    rt = runtime(gravity=(0, 0, 0))
    add(rt, 1, 'dynamic', Proxy.sphere(0.5), mass=2.0)
    rt.apply(Command('impulse', 1, ((0.0, 0.0, 3.0), None)))
    snapshot = rt.snapshot()
    assert np.allclose(snapshot.linear_velocity[snapshot.rows[1]], (0, 0, 1.5))


def test_an_impulse_at_a_point_off_the_centre_also_spins_the_body():
    rt = runtime(gravity=(0, 0, 0))
    add(rt, 1, 'dynamic', Proxy.box((1, 1, 1)))
    rt.apply(Command('impulse', 1, ((1.0, 0.0, 0.0), (0.0, 0.5, 0.0))))
    snapshot = rt.snapshot()
    assert abs(snapshot.angular_velocity[snapshot.rows[1]][2]) > 0.0


def test_a_torque_impulse_spins_the_body():
    rt = runtime(gravity=(0, 0, 0))
    add(rt, 1, 'dynamic', Proxy.box((1, 1, 1)))
    rt.apply(Command('torque_impulse', 1, ((0.0, 2.0, 0.0),)))
    snapshot = rt.snapshot()
    assert snapshot.angular_velocity[snapshot.rows[1]][1] > 0.0


def test_a_held_force_accelerates_until_cleared():
    rt = runtime(gravity=(0, 0, 0))
    add(rt, 1, 'dynamic', Proxy.sphere(0.5), mass=1.0)
    rt.apply(Command('force', 1, ((10.0, 0.0, 0.0),)))
    rt.step_frame(0.1)
    fast = rt.snapshot().linear_velocity[rt.snapshot().rows[1]][0]
    rt.apply(Command('force', 1, ((0.0, 0.0, 0.0),)))
    rt.step_frame(0.1)
    after = rt.snapshot().linear_velocity[rt.snapshot().rows[1]][0]
    assert fast == pytest.approx(1.0, rel=0.05)
    assert after == pytest.approx(fast, rel=0.05)


def test_set_velocity_replaces_the_velocity():
    rt = runtime(gravity=(0, 0, 0))
    add(rt, 1, 'dynamic', Proxy.sphere(0.5))
    rt.apply(Command('velocity', 1, ((1.0, 2.0, 3.0),)))
    snapshot = rt.snapshot()
    assert np.allclose(snapshot.linear_velocity[snapshot.rows[1]], (1, 2, 3))


def test_place_moves_a_body_and_keeps_its_velocity():
    rt = runtime(gravity=(0, 0, 0))
    add(rt, 1, 'dynamic', Proxy.sphere(0.5))
    rt.apply(Command('velocity', 1, ((0.0, 0.0, 2.0),)))
    rt.apply(Command('place', 1, ((5.0, 6.0, 7.0), None)))
    snapshot = rt.snapshot()
    row = snapshot.rows[1]
    assert np.allclose(snapshot.position[row], (5, 6, 7))
    assert np.allclose(snapshot.linear_velocity[row], (0, 0, 2))


def test_place_can_turn_a_body_by_an_axis_angle():
    rt = runtime(gravity=(0, 0, 0))
    add(rt, 1, 'dynamic', Proxy.box((1, 1, 1)))
    rt.apply(Command('place', 1, (None, (0.0, 1.0, 0.0, np.pi / 2))))
    snapshot = rt.snapshot()
    axis_angle = snapshot.axis_angle[snapshot.rows[1]]
    assert axis_angle[3] == pytest.approx(np.pi / 2)
    assert np.allclose(axis_angle[:3], (0, 1, 0))


def test_gravity_can_change_while_the_world_runs():
    rt = runtime(gravity=(0, 0, 0))
    add(rt, 1, 'dynamic', Proxy.sphere(0.5))
    rt.apply(Command('gravity', 0, ((0.0, 0.0, -10.0),)))
    rt.step_frame(0.1)
    snapshot = rt.snapshot()
    assert snapshot.linear_velocity[snapshot.rows[1]][2] == pytest.approx(-1.0, rel=0.05)


def test_damping_slows_a_body():
    rt = runtime(gravity=(0, 0, 0), maxCatchUp=1.0)
    add(rt, 1, 'dynamic', Proxy.sphere(0.5))
    rt.apply(Command('velocity', 1, ((10.0, 0.0, 0.0),)))
    rt.apply(Command('damping', 1, (5.0, None)))
    rt.step_frame(0.5)
    snapshot = rt.snapshot()
    assert 0.0 < snapshot.linear_velocity[snapshot.rows[1]][0] < 5.0


def test_removing_a_body_takes_it_out_of_the_snapshot():
    rt = runtime()
    add(rt, 1, 'dynamic', Proxy.sphere(0.5), position=(0, 5, 0))
    rt.apply(Command('remove', 1))
    assert 1 not in rt.snapshot().rows
    assert rt.world.live_body_count == 0


def test_commands_for_a_body_that_was_removed_are_dropped():
    rt = runtime()
    add(rt, 1, 'dynamic', Proxy.sphere(0.5))
    rt.apply(Command('remove', 1))
    add(rt, 2, 'dynamic', Proxy.sphere(0.5), position=(0, 5, 0))   # takes the freed slot
    rt.apply(Command('impulse', 1, ((100.0, 0.0, 0.0), None)))
    snapshot = rt.snapshot()
    assert np.allclose(snapshot.linear_velocity[snapshot.rows[2]], (0, 0, 0))


def test_commands_carry_the_sequence_the_snapshot_reports_as_applied():
    rt = runtime()
    add(rt, 1, 'dynamic', Proxy.sphere(0.5))
    rt.apply(Command('velocity', 1, ((1.0, 0.0, 0.0),), seq=1))
    assert rt.snapshot().applied_seq == 1


def test_the_applied_sequence_waits_for_an_earlier_command_still_on_its_way():
    rt = runtime()
    add(rt, 1, 'dynamic', Proxy.sphere(0.5))
    rt.apply(Command('force', 1, ((1.0, 0.0, 0.0),), seq=2))
    rt.apply(Command('force', 1, ((1.0, 0.0, 0.0),), seq=4))
    assert rt.snapshot().applied_seq == 0
    rt.apply(Command('place', 1, ((0.0, 3.0, 0.0), None), seq=1))
    assert rt.snapshot().applied_seq == 2
    rt.apply(Command('place', 1, ((0.0, 3.0, 0.0), None), seq=3))
    assert rt.snapshot().applied_seq == 4


def test_one_proxy_shared_by_many_bodies_is_added_to_the_world_once():
    rt = runtime()
    proxy = Proxy.sphere(0.5)
    for uid in range(1, 6):
        add(rt, uid, 'dynamic', proxy, position=(uid * 2, 5, 0))
    assert len(rt.world.shapes) == 1


def test_a_material_name_resolves_to_a_preset():
    rt = runtime()
    add(rt, 1, 'dynamic', Proxy.sphere(0.5), material='rubber')
    index = rt.entry(1).index
    assert rt.world.material_for(int(rt.world.collider_material[index])).restitution == pytest.approx(
        model.MATERIAL_PRESETS['rubber'].restitution)


def test_before_and_after_step_hooks_are_called_for_every_step_in_order():
    rt = runtime()
    calls = []
    rt.before_step.append(lambda step: calls.append(('before', step.index)))
    rt.after_step.append(lambda step: calls.append(('after', step.index)))
    rt.step_frame(0.03)
    assert calls == [('before', 0), ('after', 0), ('before', 1), ('after', 1),
                     ('before', 2), ('after', 2)]


def test_a_step_record_carries_its_length_and_time():
    rt = runtime()
    seen = []
    rt.after_step.append(seen.append)
    rt.step_frame(0.02)
    assert [round(step.time, 9) for step in seen] == [0.0, 0.01]
    assert all(step.dt == pytest.approx(0.01) for step in seen)


def test_a_hook_that_raises_does_not_stop_the_step(caplog):
    rt = runtime()

    def fails(step):
        raise RuntimeError('refused')

    rt.before_step.append(fails)
    assert rt.step_frame(0.02) == 2
    assert 'refused' in caplog.text


def _ball_on_floor(rt: WorldRuntime) -> None:
    add(rt, 1, 'static', Proxy.box((20, 1, 20)), position=(0, -0.5, 0))
    add(rt, 2, 'dynamic', Proxy.sphere(0.5), position=(0, 2.0, 0), report=True)


def test_a_ball_landing_on_a_floor_makes_a_begin_event_naming_both_bodies():
    rt = runtime(maxCatchUp=2.0)
    rt.set_logging(True)
    _ball_on_floor(rt)
    rt.step_frame(1.0)
    events = rt.take_events()
    begins = [event for event in events if event.kind == 'contact' and event.phase == 'begin']
    assert begins
    assert {begins[0].a, begins[0].b} == {1, 2}
    assert begins[0].approach > 1.0
    assert begins[0].step >= 0 and begins[0].time > 0.0


def test_events_are_taken_once():
    rt = runtime(maxCatchUp=2.0)
    rt.set_logging(True)
    _ball_on_floor(rt)
    rt.step_frame(1.0)
    assert rt.take_events()
    assert rt.take_events() == []


def test_nothing_is_logged_until_asked_for():
    rt = runtime(maxCatchUp=2.0)
    _ball_on_floor(rt)
    rt.step_frame(1.0)
    assert rt.take_events() == []


def test_a_body_removed_while_touching_ends_its_contact_with_reason_removed():
    rt = runtime(maxCatchUp=2.0)
    rt.set_logging(True)
    _ball_on_floor(rt)
    rt.step_frame(1.0)
    rt.take_events()
    rt.apply(Command('remove', 2))
    ended = [event for event in rt.take_events() if event.phase == 'end']
    assert ended and ended[0].reason == 'removed'
    assert {ended[0].a, ended[0].b} == {1, 2}


def test_a_trigger_reports_what_enters_it():
    rt = runtime(maxCatchUp=2.0)
    rt.set_logging(True)
    add(rt, 1, 'trigger', Proxy.box((4, 4, 4)), position=(0, 0, 0))
    add(rt, 2, 'dynamic', Proxy.sphere(0.25), position=(0, 3.5, 0))
    rt.step_frame(1.0)
    entered = [event for event in rt.take_events() if event.kind == 'trigger' and event.phase == 'enter']
    assert entered and entered[0].a == 1 and entered[0].b == 2


def test_the_snapshot_marks_which_bodies_are_asleep():
    rt = runtime()
    _ball_on_floor(rt)
    for _ in range(80):
        rt.step_frame(0.1)
    snapshot = rt.snapshot()
    assert not snapshot.awake[snapshot.rows[2]]


def test_kinematic_bodies_are_in_the_snapshot_and_not_dynamic():
    rt = runtime()
    add(rt, 1, 'kinematic', Proxy.box((1, 1, 1)))
    snapshot = rt.snapshot()
    assert not snapshot.dynamic[snapshot.rows[1]]


def test_snapshots_have_increasing_versions():
    rt = runtime()
    add(rt, 1, 'dynamic', Proxy.sphere(0.5))
    first = rt.snapshot().version
    assert rt.snapshot().version > first
