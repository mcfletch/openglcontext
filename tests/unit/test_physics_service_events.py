"""Tests for the events a Physics service delivers to handlers.

Handlers are held weakly and called on the render thread, in the frame, unless
the function is marked as a physics callback.
"""
import gc
import threading
import time

import pytest

from OpenGLContext.physics.callbacks import physics_callback
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.testing import physics as physics_testing


LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def ball(radius=0.5, at=(0, 2, 0)):
    return surfaces.shape(surfaces.sphere(radius), LOOK, translation=at)


def block(size, at=(0, 0, 0)):
    return surfaces.shape(surfaces.block(size), LOOK, translation=at)


class Listener:
    """Something that owns handler methods, as a context does."""

    def __init__(self):
        self.heard = []
        self.threads = []

    def OnHit(self, hit):
        self.heard.append(hit)

    @physics_callback
    def OnHitOnTheWorker(self, hit):
        self.heard.append(hit)
        self.threads.append(threading.get_ident())


def make(**named) -> Physics:
    named.setdefault('mode', 'inline')
    named.setdefault('maxCatchUp', 2.0)
    named.setdefault('tickHz', 100.0)
    return Physics(PhysicsDefinition(**named))


def run_for(physics, seconds, frame=0.02):
    for _ in range(int(round(seconds / frame))):
        physics.frame(frame)


@pytest.fixture
def world():
    physics = make()
    floor = physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)), restitution=0.0)
    yield physics, floor
    physics.close()


def test_a_bodys_handler_hears_it_land_with_the_bodies_and_the_speed(world):
    physics, floor = world
    listener = Listener()
    body = physics.add_dynamic(ball(), restitution=0.0)
    body.addEventHandler('hit', function=listener.OnHit)
    run_for(physics, 1.0)
    assert len(listener.heard) == 1
    hit = listener.heard[0]
    assert hit.body is body and hit.other is floor
    assert hit.node is body.node and hit.other_node is floor.node
    assert hit.speed == pytest.approx(hit.approach) and hit.speed > 3.0
    assert hit.kind == 'contact' and hit.phase == 'begin' and hit.step > 0


def test_the_normal_points_into_the_body_that_was_struck(world):
    physics, floor = world
    listener = Listener()
    body = physics.add_dynamic(ball(), restitution=0.0)
    body.addEventHandler('hit', function=listener.OnHit)
    floor.addEventHandler('hit', function=listener.OnHit)
    run_for(physics, 1.0)
    from_ball = next(h for h in listener.heard if h.body is body)
    from_floor = next(h for h in listener.heard if h.body is floor)
    assert from_ball.normal[1] > 0.9           # the ball is pushed up
    assert from_floor.normal[1] < -0.9         # the floor is pushed down


def test_a_handler_on_physics_hears_every_body(world):
    physics, _floor = world
    listener = Listener()
    physics.addEventHandler('hit', function=listener.OnHit)
    physics.add_dynamic(ball(at=(-3, 2, 0)), restitution=0.0)
    physics.add_dynamic(ball(at=(3, 2, 0)), restitution=0.0)
    run_for(physics, 1.0)
    assert len(listener.heard) == 2


def test_above_leaves_out_a_gentle_touch(world):
    physics, _floor = world
    gentle, hard = Listener(), Listener()
    body = physics.add_dynamic(ball(at=(0, 0.52, 0)), restitution=0.0)
    body.addEventHandler('hit', function=gentle.OnHit, above=1.0)
    other = physics.add_dynamic(ball(at=(4, 3, 0)), restitution=0.0)
    other.addEventHandler('hit', function=hard.OnHit, above=1.0)
    run_for(physics, 1.5)
    assert gentle.heard == []
    assert len(hard.heard) == 1


def test_other_limits_a_handler_to_hits_against_that_body(world):
    physics, floor = world
    crate = physics.add_static(block((1, 1, 1), at=(5, 0.5, 0)))
    against_floor, against_crate = Listener(), Listener()
    body = physics.add_dynamic(ball(at=(0, 2, 0)), restitution=0.0)
    body.addEventHandler('hit', function=against_floor.OnHit, other=floor)
    body.addEventHandler('hit', function=against_crate.OnHit, other=[crate])
    run_for(physics, 1.0)
    assert len(against_floor.heard) == 1 and against_crate.heard == []


def test_separate_and_touching_are_heard_when_asked_for(world):
    physics, _floor = world
    listener = Listener()
    body = physics.add_dynamic(ball(at=(0, 1.0, 0)), restitution=0.9)
    body.addEventHandler('touching', function=listener.OnHit)
    body.addEventHandler('separate', function=listener.OnHit)
    run_for(physics, 1.5)
    phases = {hit.phase for hit in listener.heard}
    assert {'persist', 'end'} <= phases


def test_a_trigger_reports_enter_and_exit_to_both_sides(world):
    physics, _floor = world
    zone = physics.add_trigger(block((4, 4, 4), at=(0, 2, 0)), proxy='box')
    enter, leave = Listener(), Listener()
    zone.addEventHandler('enter', function=enter.OnHit)
    zone.addEventHandler('exit', function=leave.OnHit)
    body = physics.add_dynamic(ball(0.25, at=(0, 5.5, 0)), restitution=0.0)
    run_for(physics, 1.0)
    assert [h.other for h in enter.heard] == [body]
    body.set_transform(translation=(0, 12, 0))
    run_for(physics, 0.1)
    assert [h.other for h in leave.heard] == [body]


def test_sleep_and_wake_are_events_of_a_body(world):
    physics, _floor = world
    listener = Listener()
    body = physics.add_dynamic(ball(0.5, at=(0, 0.6, 0)), restitution=0.0)
    body.addEventHandler('sleep', function=listener.OnHit)
    body.addEventHandler('wake', function=listener.OnHit)
    run_for(physics, 6.0)
    assert [h.phase for h in listener.heard][:1] == ['sleep']
    body.apply_impulse((0, 10, 0))
    run_for(physics, 0.2)
    assert 'wake' in [h.phase for h in listener.heard]


def test_the_engine_holds_no_events_once_a_frame_has_delivered_them(world):
    physics, _floor = world
    listener = Listener()
    body = physics.add_dynamic(ball())
    for event in ('hit', 'touching'):
        body.addEventHandler(event, function=listener.OnHit, above=-1.0)
    run_for(physics, 2.0)
    assert len(listener.heard) > 10
    assert physics_testing.event_backlog(physics) == (0, 0)


def test_a_handler_is_held_weakly(world):
    physics, _floor = world
    listener = Listener()
    body = physics.add_dynamic(ball(), restitution=0.0)
    body.addEventHandler('hit', function=listener.OnHit)
    heard = listener.heard
    del listener
    gc.collect()
    run_for(physics, 1.0)
    assert heard == []


def test_a_lambda_nobody_else_holds_is_not_called(world):
    physics, _floor = world
    seen = []
    body = physics.add_dynamic(ball(), restitution=0.0)
    body.addEventHandler('hit', function=lambda hit: seen.append(hit))
    gc.collect()
    run_for(physics, 1.0)
    assert seen == []


def test_a_lambda_somebody_holds_is_called(world):
    physics, _floor = world
    seen = []
    keep = seen.append
    body = physics.add_dynamic(ball(), restitution=0.0)
    body.addEventHandler('hit', function=keep)
    run_for(physics, 1.0)
    assert len(seen) == 1


def test_cancel_stops_a_handler_and_function_none_removes_the_bodys_handlers(world):
    physics, _floor = world
    first, second = Listener(), Listener()
    body = physics.add_dynamic(ball(), restitution=0.0)
    handler = body.addEventHandler('hit', function=first.OnHit)
    body.addEventHandler('hit', function=second.OnHit)
    handler.cancel()
    handler.cancel()
    body.addEventHandler('hit', function=None)
    run_for(physics, 1.0)
    assert first.heard == [] and second.heard == []


def test_removing_a_body_ends_its_handlers_after_the_last_end_event(world):
    physics, _floor = world
    listener = Listener()
    body = physics.add_dynamic(ball(at=(0, 0.6, 0)), restitution=0.0)
    body.addEventHandler('separate', function=listener.OnHit)
    run_for(physics, 0.5)
    body.remove()
    run_for(physics, 0.1)
    assert [h.reason for h in listener.heard] == ['removed']
    assert len(physics.handlers) == 0


def test_a_handler_that_raises_is_logged_once_and_the_others_still_hear(caplog):
    physics = make(handlerErrors='log')
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)), restitution=0.0)
    good = Listener()

    class Bad:
        def OnHit(self, hit):
            raise ValueError('refused')

    bad = Bad()
    body = physics.add_dynamic(ball(), restitution=0.9)
    body.addEventHandler('hit', function=bad.OnHit)
    body.addEventHandler('hit', function=good.OnHit)
    run_for(physics, 2.0)
    physics.close()
    assert len([r for r in caplog.records if r.levelname == 'ERROR']) == 1
    assert 'refused' in caplog.text
    assert len(good.heard) >= 2


class Refusal(Exception):
    """What the failing code of these tests raises."""


def refuse(*arguments):
    raise Refusal('refused')


def test_the_testing_plugin_has_handler_errors_raised():
    assert PhysicsDefinition().handlerErrors == 'raise'
    with pytest.raises(ValueError, match='handlerErrors'):
        PhysicsDefinition(handlerErrors='shout').validate()


@pytest.mark.parametrize('mode', ['inline', 'thread'])
def test_a_handler_that_raises_is_raised_from_the_frame_once(mode):
    physics = make(mode=mode, handlerErrors='raise')
    try:
        physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)), restitution=0.0)
        body = physics.add_dynamic(ball(), restitution=0.0)
        body.addEventHandler('hit', function=refuse)
        with pytest.raises(Refusal):
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                physics.frame(0.02)
                time.sleep(0.005 if mode == 'thread' else 0.0)
        physics.frame(0.02)
    finally:
        physics.close()


def test_step_code_and_posted_functions_that_raise_are_raised_from_the_frame():
    physics = make(handlerErrors='raise')
    try:
        physics.add_dynamic(ball())
        hook = physics.on_step(refuse)
        with pytest.raises(Refusal):
            physics.frame(0.02)
        hook.cancel()
        physics.frame(0.02)
        physics.post(refuse)
        with pytest.raises(Refusal):
            physics.frame(0.02)
        physics.frame(0.02)
        physics.addEventHandler('after-step', physics_callback(refuse))
        with pytest.raises(Refusal):
            physics.step(0.02)
    finally:
        physics.close()


def test_with_handler_errors_logged_the_frame_goes_on(caplog):
    physics = make(handlerErrors='log')
    try:
        physics.add_dynamic(ball())
        physics.on_step(refuse)
        physics.post(refuse)
        physics.frame(0.02)
        physics.frame(0.02)
        # The step code is logged once however often it fails, and the posted function ran once.
        assert len([record for record in caplog.records if record.levelname == 'ERROR']) == 2
    finally:
        physics.close()


def test_an_unknown_event_or_filter_is_refused(world):
    physics, _floor = world
    body = physics.add_dynamic(ball())
    with pytest.raises(ValueError, match='hit'):
        body.addEventHandler('bump', function=print)
    with pytest.raises(TypeError, match='loudness'):
        body.addEventHandler('hit', function=print, loudness=3)


# -- the physics thread --------------------------------------------------------

def test_a_marked_function_runs_on_the_world_thread_and_may_change_the_world():
    physics = Physics(PhysicsDefinition(mode='thread', tickHz=200.0))
    try:
        physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)), restitution=0.0)
        listener = Listener()
        body = physics.add_dynamic(ball(at=(0, 1.0, 0)), restitution=0.0)

        @physics_callback
        def bounce(hit):
            listener.heard.append(hit)
            listener.threads.append(threading.get_ident())
            hit.body.apply_impulse((0, 20000, 0))

        body.addEventHandler('hit', function=bounce)
        deadline = time.monotonic() + 10.0
        while len(listener.heard) < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert listener.heard
        assert listener.threads[0] == physics._engine.thread_id  # noqa: SLF001 the world thread's id
        assert listener.threads[0] != threading.get_ident()
        physics_testing.wait_ticks(physics, 5)
        physics.frame(0.016)
        assert body.velocity[1] > 5.0 or body.position[1] > 0.8
    finally:
        physics.close()


def test_a_render_handler_is_not_called_on_the_world_thread():
    physics = Physics(PhysicsDefinition(mode='thread', tickHz=200.0))
    try:
        physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)), restitution=0.0)
        listener = Listener()
        body = physics.add_dynamic(ball(at=(0, 1.0, 0)), restitution=0.0)
        body.addEventHandler('hit', function=listener.OnHit)

        deadline = time.monotonic() + 10.0
        while not listener.heard and time.monotonic() < deadline:
            time.sleep(0.02)
            physics.frame(0.016)
        assert listener.heard
    finally:
        physics.close()


def test_inline_physics_callbacks_run_after_each_step_and_render_handlers_once_per_frame():
    physics = make(maxCatchUp=1.0)
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    steps_seen, frames_seen = [], []
    body = physics.add_dynamic(ball(0.5, at=(0, 0.52, 0)), restitution=0.9)

    @physics_callback
    def on_step(hit):
        steps_seen.append(hit.step)

    def on_frame(hit):
        frames_seen.append(hit.step)

    body.addEventHandler('touching', function=on_step)
    keep = on_frame
    body.addEventHandler('touching', function=keep)
    physics.frame(0.1)                       # ten steps in one frame
    assert len(steps_seen) == len(frames_seen)
    assert steps_seen == sorted(steps_seen)
    physics.close()


# -- before and after the step --------------------------------------------------

def test_step_handlers_are_called_around_every_step_with_the_step():
    physics = make()
    seen = []

    @physics_callback
    def before(step):
        seen.append(('before', step.index))

    @physics_callback
    def after(step):
        seen.append(('after', step.index))

    physics.addEventHandler('before-step', function=before)
    physics.addEventHandler('after-step', function=after)
    physics.frame(0.03)
    assert seen == [('before', 0), ('after', 0), ('before', 1), ('after', 1),
                    ('before', 2), ('after', 2)]
    physics.close()


def test_a_step_handler_must_be_marked():
    physics = make()
    with pytest.raises(ValueError, match='physics_callback'):
        physics.addEventHandler('before-step', function=print)
    physics.close()


def test_a_step_handler_may_change_a_body_between_steps():
    physics = make(gravity=(0, 0, 0))
    body = physics.add_dynamic(ball(at=(0, 0, 0)), linear_damping=0.0)

    @physics_callback
    def push(step):
        body.set_velocity((1.0, 0.0, 0.0))

    physics.addEventHandler('before-step', function=push)
    run_for(physics, 0.5)
    assert body.velocity[0] == pytest.approx(1.0)
    physics.close()


# -- scene changes from the world thread --------------------------------------------

def test_render_set_from_a_marked_handler_reaches_the_scene_before_the_frame_ends():
    physics = make()
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    paint = PhysicalMaterial(baseColor=(1, 1, 1))
    body = physics.add_dynamic(ball(at=(0, 1.0, 0)), restitution=0.0)

    @physics_callback
    def flash(hit):
        physics.render.set(paint, baseColor=(1, 0, 0))

    body.addEventHandler('hit', function=flash)
    run_for(physics, 1.0)
    assert tuple(paint.baseColor)[:3] == pytest.approx((1, 0, 0))
    physics.close()


# -- the telemetry journal -----------------------------------------------------------

def journalled(**named):
    """A service that writes every event a handler hears to a list, as a recording would."""
    marks = []
    physics = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0),
                      mark=lambda name, /, **fields: marks.append((name, fields)),
                      recording=lambda: True, **named)
    return physics, marks


def landing(physics, node=None):
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)), restitution=0.0)
    node = node if node is not None else ball()
    body = physics.add_dynamic(node, restitution=0.0)
    listener = Listener()
    body.addEventHandler('hit', function=listener.OnHit)
    run_for(physics, 1.0)
    return body, listener


def test_an_event_a_handler_heard_is_written_to_the_journal_with_when_it_happened():
    physics, marks = journalled()
    body, listener = landing(physics)
    assert len(marks) == 1
    name, fields = marks[0]
    assert name == 'physics-hit'
    assert fields['step'] > 0 and fields['time'] > 0.0
    assert (fields['a'], fields['b']) == ('#1', '#2')      # the lower-numbered body of the pair first
    assert fields['approach'] > 3.0
    physics.close()


def test_a_bodys_def_name_is_how_the_journal_names_it():
    physics, marks = journalled()
    node = ball()
    node.DEF = 'Ball'
    landing(physics, node)
    assert marks[0][1]['b'] == 'Ball'
    physics.close()


def test_events_nobody_listens_for_are_not_written():
    physics, marks = journalled()
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    physics.add_dynamic(ball())
    run_for(physics, 1.0)
    assert marks == []
    physics.close()


def test_nothing_is_written_when_nothing_is_recording():
    marks = []
    physics = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0),
                      mark=lambda name, /, **fields: marks.append(name), recording=lambda: False)
    landing(physics)
    assert marks == []
    physics.close()


def test_two_runs_of_the_same_scene_write_the_same_journal():
    first, first_marks = journalled()
    landing(first)
    second, second_marks = journalled()
    landing(second)
    assert first_marks == second_marks and first_marks
    first.close()
    second.close()


def test_the_journal_can_be_compared_on_replay():
    from OpenGLContext.telemetry.replay import MarkComparison

    physics, marks = journalled()
    landing(physics)
    recorded = [{'name': name, 'frame': index, 'fields': fields}
                for index, (name, fields) in enumerate(marks)]
    comparison = MarkComparison(recorded)
    for index, (name, fields) in enumerate(marks):
        assert comparison.mark(index, name, fields)
    physics.close()


def test_a_step_handler_is_called_every_step_of_a_world_at_rest():
    physics = make()
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    body = physics.add_dynamic(ball(at=(0, 0.5, 0)))
    for _ in range(2000):
        physics.frame(0.02)
        if body.asleep:
            break
    assert body.asleep
    seen = []

    @physics_callback
    def count(step):
        seen.append(step.index)

    physics.addEventHandler('before-step', function=count)
    run_for(physics, 0.1, frame=0.01)
    assert len(seen) == 10
    physics.close()


def test_no_bounce_is_lost_at_a_low_frame_rate():
    def bounces(frame):
        physics = make(tickHz=120.0)
        try:
            physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)), restitution=0.6)
            listener = Listener()
            body = physics.add_dynamic(ball(0.2), restitution=0.6)
            body.addEventHandler('hit', function=listener.OnHit)
            run_for(physics, 3.0, frame)
            return [round(hit.time, 6) for hit in listener.heard]
        finally:
            physics.close()

    at_120 = bounces(1.0 / 120.0)
    assert len(at_120) >= 3
    assert bounces(1.0 / 20.0) == at_120


@pytest.mark.parametrize('table', ['before_step', 'after_step', 'on_events'])
def test_an_engine_hook_that_raises_is_logged_and_raised_from_the_frame(table, caplog):
    physics = make(handlerErrors='raise')
    try:
        physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)), restitution=0.0)
        body = physics.add_dynamic(ball(), restitution=0.0)
        body.addEventHandler('hit', function=Listener().OnHit)
        getattr(physics._engine, table).append(refuse)
        physics.on_step(lambda view: None)      # the world calls its step hooks while code wants steps
        with pytest.raises(Refusal):
            for _ in range(200):
                physics.frame(0.02)
        assert 'refused' in caplog.text
    finally:
        physics.close()


def test_step_code_that_raises_is_logged_once_and_cancelled_code_is_dropped(caplog):
    physics = make(handlerErrors='log')
    try:
        physics.add_dynamic(ball())
        failing = physics.on_step(refuse)
        calls = []
        cancelled = physics.on_step(calls.append)
        for _ in range(3):
            physics.frame(0.02)
        assert len([record for record in caplog.records if 'step hook' in record.message]) == 1
        assert failing.failed and len(calls) == 6
        cancelled.cancel()
        physics.frame(0.02)
        assert cancelled not in physics._step_hooks and len(calls) == 6
    finally:
        physics.close()


def test_the_error_that_stopped_the_world_is_raised_from_one_frame():
    physics = make()
    try:
        physics.add_dynamic(ball())
        physics.frame(0.02)
        stopped = RuntimeError('the world thread died')
        physics._engine._error = stopped
        assert physics.error is stopped
        with pytest.raises(RuntimeError, match='the world thread died') as raised:
            physics.frame(0.02)
        assert raised.value.__cause__ is stopped
        physics._engine._error = None
        physics.frame(0.02)
    finally:
        physics.close()
