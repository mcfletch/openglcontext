"""Tests for the workers that step a physics runtime: inline in the frame hook, or on a thread."""
import threading
import time

import numpy as np
import pytest
from omi_physics import model

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.records import BodySpec, Command
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.worker import InlineWorker, ThreadWorker


def definition(**named) -> PhysicsDefinition:
    named.setdefault('tickHz', 100.0)
    named.setdefault('maxCatchUp', 2.0)
    return PhysicsDefinition(**named)


def ball(uid=1, position=(0, 5, 0), report=False) -> Command:
    return Command('add', uid, (BodySpec(uid, 'dynamic', Proxy.sphere(0.5), model.Motion(mass=1.0),
                                         position=position, report=report),))


def floor(uid=9) -> Command:
    return Command('add', uid, (BodySpec(uid, 'static', Proxy.box((20, 1, 20)), model.Motion(),
                                         position=(0, -0.5, 0)),))


@pytest.fixture
def threaded():
    worker = ThreadWorker(definition())
    yield worker
    worker.stop()


def y_of(snapshot, uid=1) -> float:
    return float(snapshot.position[snapshot.rows[uid]][1])


# -- inline ---------------------------------------------------------------

def test_inline_applies_what_was_submitted_then_steps_and_publishes():
    worker = InlineWorker(definition())
    worker.submit(ball())
    out = worker.collect(0.1)
    assert out.snapshot is not None and 1 in out.snapshot.rows
    assert y_of(out.snapshot) < 5.0


def test_inline_steps_by_the_fixed_step_not_the_frame():
    worker = InlineWorker(definition())
    worker.collect(0.05)
    assert worker.runtime.world.step_count == 5


def test_inline_publishes_the_pose_part_way_through_the_next_step():
    worker = InlineWorker(definition(tickHz=64.0))
    worker.submit(ball())
    out = worker.collect(0.0390625)            # 2.5 steps: the pose is between steps 2 and 3
    world = worker.runtime.world
    row = out.snapshot.rows[1]
    previous, current = world.prev_position[0][1], world.position[0][1]
    assert min(previous, current) <= out.snapshot.position[row][1] <= max(previous, current)
    assert out.snapshot.position[row][1] == pytest.approx((previous + current) / 2, abs=1e-9)


def test_inline_applies_a_command_made_inside_a_step_hook_at_once():
    worker = InlineWorker(definition(gravity=(0, 0, 0)))
    worker.submit(ball())
    worker.collect(0.0)
    sent = []

    def before(step):
        if not sent:
            sent.append(step.index)
            worker.submit(Command('velocity', 1, ((0.0, 0.0, 4.0),)))

    worker.runtime.before_step.append(before)
    out = worker.collect(0.01)
    assert sent == [0]
    assert out.snapshot.linear_velocity[out.snapshot.rows[1]][2] == pytest.approx(4.0, rel=0.01)
    assert worker.runtime.world.position[worker.runtime.entry(1).index][2] > 0.0   # it moved in that step


def test_inline_events_come_back_once():
    worker = InlineWorker(definition())
    worker.runtime.set_logging(True)
    worker.submit(floor())
    worker.submit(ball(position=(0, 1.0, 0), report=True))
    first = worker.collect(0.5)
    assert any(event.phase == 'begin' for event in first.events)
    assert worker.collect(0.0).events == []


def test_inline_step_without_a_frame_hook_advances_the_world():
    worker = InlineWorker(definition())
    worker.submit(ball())
    worker.step(0.1)
    assert worker.runtime.world.step_count == 10


# -- thread ---------------------------------------------------------------

def test_a_thread_worker_steps_the_world_on_its_own_thread(threaded):
    threaded.submit(ball())
    threaded.start()
    assert threaded.wait_ticks(5)
    out = threaded.collect(0.016)
    assert out.snapshot is not None and y_of(out.snapshot) < 5.0
    assert threaded.thread_id not in (None, threading.get_ident())


def test_a_thread_worker_applies_commands_before_the_next_tick(threaded):
    threaded.start()
    threaded.submit(ball(position=(0, 5, 0)))
    threaded.submit(Command('velocity', 1, ((0.0, 0.0, 2.0),)))
    threaded.settle()
    out = threaded.collect(0.016)
    assert out.snapshot.applied_seq >= 0
    assert out.snapshot.linear_velocity[out.snapshot.rows[1]][2] == pytest.approx(2.0, abs=0.01)


def test_commands_from_many_threads_all_arrive(threaded):
    threaded.start()
    threaded.submit(ball())

    def post(first):
        for number in range(50):
            threaded.submit(Command('force', 1, ((float(first), float(number), 0.0),)))

    workers = [threading.Thread(target=post, args=(n,)) for n in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    threaded.settle()
    assert threaded.runtime.applied_seq >= 0
    assert 1 in threaded.runtime


def test_collect_returns_a_snapshot_only_when_a_new_one_was_published(threaded):
    threaded.submit(ball())
    threaded.start()
    threaded.wait_ticks(3)
    assert threaded.collect(0.016).snapshot is not None
    threaded.stop()
    threaded.collect(0.016)                  # the last tick published before the thread ended
    assert threaded.collect(0.016).snapshot is None


def test_a_thread_worker_stops_ticking_when_nothing_is_awake(threaded):
    threaded.submit(floor())
    threaded.submit(ball(position=(0, 0.6, 0)))
    threaded.start()
    deadline = time.monotonic() + 15.0
    while not threaded.idle and time.monotonic() < deadline:
        time.sleep(0.02)
    assert threaded.idle
    steps = threaded.steps
    time.sleep(0.3)
    assert threaded.steps == steps


def test_a_command_wakes_an_idle_thread_worker(threaded):
    threaded.submit(floor())
    threaded.submit(ball(position=(0, 0.5, 0)))
    threaded.start()
    deadline = time.monotonic() + 15.0
    while not threaded.idle and time.monotonic() < deadline:
        time.sleep(0.02)
    assert threaded.idle
    steps = threaded.steps
    threaded.submit(Command('impulse', 1, ((0.0, 8.0, 0.0), None)))
    assert threaded.wait_ticks(5)
    assert threaded.steps > steps


def test_events_made_on_the_thread_are_handed_over_once(threaded):
    threaded.runtime.set_logging(True)
    threaded.submit(floor())
    threaded.submit(ball(position=(0, 1.0, 0), report=True))
    threaded.start()
    threaded.settle()
    deadline = time.monotonic() + 15.0
    events = []
    while not events and time.monotonic() < deadline:
        events = [e for e in threaded.collect(0.016).events if e.phase == 'begin']
        time.sleep(0.02)
    assert events
    assert not [e for e in threaded.collect(0.016).events if e.phase == 'begin']


def test_starting_twice_runs_one_thread(threaded):
    threaded.start()
    first = threaded.thread_id
    threaded.start()
    assert threaded.thread_id == first


def test_stop_ends_the_thread_and_can_be_repeated(threaded):
    threaded.start()
    threaded.stop()
    threaded.stop()
    assert threaded.thread_id is None


def test_a_command_that_raises_does_not_end_the_thread(threaded, caplog):
    threaded.submit(ball())
    threaded.submit(Command('place', 1, ('not a position', None)))
    threaded.start()
    assert threaded.wait_ticks(3)
    assert 'failed' in caplog.text


def test_a_thread_worker_reports_whether_it_keeps_up(threaded):
    threaded.submit(ball())
    threaded.start()
    threaded.wait_ticks(10)
    assert threaded.rate() > 0.0
    assert threaded.dropped >= 0
    assert threaded.sim_hz == pytest.approx(100.0)


def test_thread_hooks_run_on_the_worker_thread(threaded):
    seen = []
    threaded.runtime.after_step.append(lambda step: seen.append(threading.get_ident()))
    threaded.submit(ball())
    threaded.start()
    threaded.wait_ticks(3)
    assert seen and set(seen) == {threaded.thread_id}


def test_both_workers_give_the_same_poses_for_the_same_commands():
    thread = ThreadWorker(definition())
    try:
        thread.submit(floor())
        thread.submit(ball(position=(0, 2, 0)))
        thread.start()
        thread.wait_ticks(50)
        thread.stop()
        steps = thread.runtime.world.step_count
        reference = InlineWorker(definition(maxCatchUp=steps * 0.01 + 1.0))
        reference.submit(floor())
        reference.submit(ball(position=(0, 2, 0)))
        reference.step(steps * 0.01)
        assert reference.runtime.world.step_count == steps
        assert np.allclose(thread.runtime.snapshot().position,
                           reference.runtime.snapshot().position, atol=1e-9)
    finally:
        thread.stop()


# -- a world where nothing moves ------------------------------------------------

def settled_inline(**named) -> InlineWorker:
    """An inline worker whose ball has come to rest on the floor."""
    worker = InlineWorker(definition(**named))
    worker.submit(floor())
    worker.submit(ball(position=(0, 0.6, 0)))
    for _ in range(3000):
        worker.collect(0.01)
        if not worker.runtime.busy():
            return worker
    raise AssertionError('the ball did not come to rest')


def test_inline_does_not_step_a_world_where_nothing_moves():
    worker = settled_inline()
    steps = worker.runtime.world.step_count
    outs = [worker.collect(0.01) for _ in range(60)]
    assert worker.runtime.world.step_count == steps
    assert all(out.snapshot is None for out in outs)


def test_inline_steps_again_once_a_command_arrives():
    worker = settled_inline()
    steps = worker.runtime.world.step_count
    worker.submit(Command('impulse', 1, ((0.0, 2.0, 0.0), None), seq=99))
    out = worker.collect(0.01)
    assert worker.runtime.world.step_count == steps + 1
    assert out.snapshot is not None and out.snapshot.applied_seq == 99


def test_inline_publishes_a_command_applied_by_a_flush_between_frames():
    worker = settled_inline()
    worker.submit(Command('damping', 1, (0.5, None), seq=77))
    worker.flush()
    out = worker.collect(0.01)
    assert out.snapshot is not None and out.snapshot.applied_seq == 77


def test_inline_publishes_its_first_frame_with_nothing_to_step():
    worker = InlineWorker(definition())
    assert worker.collect(0.01).snapshot is not None
    assert worker.collect(0.01).snapshot is None


def test_inline_keeps_stepping_a_still_world_that_a_step_hook_wants():
    worker = settled_inline()
    seen = []
    worker.runtime.after_step.append(lambda step: seen.append(step.index))
    worker.runtime.wants_steps.append(lambda: True)
    for _ in range(5):
        worker.collect(0.01)
    assert len(seen) == 5


def test_inline_keeps_stepping_a_still_world_with_a_driven_body():
    worker = settled_inline()
    worker.submit(Command('add', 5, (BodySpec(5, 'kinematic', Proxy.box((1, 1, 1)),
                                              model.Motion(type=model.KINEMATIC),
                                              position=(5, 0.5, 0)),)))
    worker.submit(Command('drive', 5, (lambda t: ((5.0, 0.5, 0.0), None),)))
    worker.collect(0.01)
    steps = worker.runtime.world.step_count
    for _ in range(5):
        worker.collect(0.01)
    assert worker.runtime.world.step_count == steps + 5


def test_a_thread_worker_keeps_ticking_while_a_step_hook_wants(threaded):
    threaded.submit(floor())
    threaded.submit(ball(position=(0, 0.6, 0)))
    wanted = [True]
    threaded.runtime.wants_steps.append(lambda: wanted[0])
    threaded.start()
    assert threaded.wait_ticks(5)
    assert not threaded.idle
    wanted[0] = False
    deadline = time.monotonic() + 15.0
    while not threaded.idle and time.monotonic() < deadline:
        time.sleep(0.02)
    assert threaded.idle


# -- a failing step ---------------------------------------------------------

class StepFault(Exception):
    """The fault a broken world raises from its step."""


def broken_step(dt):
    raise StepFault('the world could not step')


def test_a_step_that_raises_is_kept_as_the_worker_error(threaded, caplog):
    threaded.submit(ball())
    threaded.runtime.world.step = broken_step
    threaded.start()
    deadline = time.monotonic() + 5.0
    while threaded.error is None and time.monotonic() < deadline:
        time.sleep(0.005)
    assert isinstance(threaded.error, StepFault)
    assert 'the world could not step' in caplog.text


def test_settle_and_run_end_when_the_thread_has_failed():
    from OpenGLContext.physics.service import Physics  # noqa: PLC0415 the service owns run()
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 imports the scenegraph

    service = Physics(definition(mode='thread'))
    try:
        service.worker.runtime.world.step = broken_step
        service.add_dynamic(surfaces.shape(surfaces.sphere(0.5), None, translation=(0, 5, 0)))
        deadline = time.monotonic() + 5.0
        while service.error is None and time.monotonic() < deadline:
            time.sleep(0.005)
        assert isinstance(service.error, StepFault)
        started = time.monotonic()
        assert service.worker.settle(timeout=2.0) is False
        assert time.monotonic() - started < 1.0
        future = service.run(lambda world: 1)
        with pytest.raises(StepFault):
            future.result(timeout=1.0)
        with pytest.raises(RuntimeError, match='physics') as raised:
            service.frame(0.02)
        assert isinstance(raised.value.__cause__, StepFault)
    finally:
        service.close()
