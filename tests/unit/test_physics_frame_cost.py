"""Tests for what a physics frame costs once bodies come to rest.

A snapshot lists the rows that changed since the one before it; the nodes, the
replica and the published poses are written for those rows and no others. The
counts here are of work done (rows converted, nodes written, boxes refitted), so
they hold on any machine.
"""
import time

import numpy as np
import pytest
from omi_physics import mathutil, model
from omi_physics.world import PhysicsWorld

from OpenGLContext.physics import runtime as runtime_module
from OpenGLContext.physics import service as service_module
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.records import BodySpec, Command
from OpenGLContext.physics.replica import Replica, build
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.worker import InlineWorker, ThreadWorker
from OpenGLContext.scenegraph.basenodes import Transform
from OpenGLContext.testing import physics as physics_testing

#: A frame that is not a whole number of steps, so published poses are interpolated.
FRAME = 0.015


def definition(**named) -> PhysicsDefinition:
    named.setdefault('tickHz', 100.0)
    named.setdefault('maxCatchUp', 2.0)
    return PhysicsDefinition(**named)


def floor(uid: int = 1000) -> Command:
    return Command('add', uid, (BodySpec(uid, 'static', Proxy.box((60, 1, 60)), model.Motion(),
                                         position=(0, -0.5, 0)),))


def box(uid: int, position) -> Command:
    return Command('add', uid, (BodySpec(uid, 'dynamic', Proxy.box((0.5, 0.5, 0.5)),
                                         model.Motion(mass=1.0), position=position),))


def boxes_at_rest(count: int = 20) -> InlineWorker:
    """An inline worker whose ``count`` boxes, ids 1 to ``count``, have come to rest."""
    worker = InlineWorker(definition())
    worker.submit(floor())
    for uid in range(1, count + 1):
        worker.submit(box(uid, ((uid % 5) * 2.0, 0.3 + 0.1 * (uid % 3), (uid // 5) * 2.0)))
    for _ in range(5000):
        worker.collect(FRAME)
        if not worker.runtime.busy():
            return worker
    raise AssertionError('the boxes did not come to rest')


def service_at_rest(count: int = 20, **named) -> tuple[Physics, list]:
    named.setdefault('mode', 'inline')
    physics = Physics(definition(**named))
    physics.add_static(None, Proxy.box((60, 1, 60)), translation=(0, -0.5, 0))
    bodies = [physics.add_dynamic(Transform(translation=((i % 5) * 2.0, 0.3 + 0.1 * (i % 3),
                                                         (i // 5) * 2.0)),
                                  Proxy.box((0.5, 0.5, 0.5)), mass=1.0)
              for i in range(count)]
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        physics.frame(FRAME)
        if named['mode'] == 'thread':
            time.sleep(0.005)
        if all(body.asleep for body in bodies):
            return physics, bodies
    raise AssertionError('the boxes did not come to rest')


# -- the pose a body falls asleep at ------------------------------------------

def drifter_world(world) -> None:
    """Let a body sleep while it still drifts at half a metre a second, so its last steps show."""
    world.sleep_linear_speed = 1.0
    world.sleep_time = 0.05


def test_a_body_that_falls_asleep_is_drawn_where_the_world_left_it():
    physics = Physics(definition(mode='inline', gravity=(0, 0, 0)))
    drifter_world(physics_testing.inspect(physics))
    body = physics.add_dynamic(Transform(), Proxy.box((0.5, 0.5, 0.5)), mass=1.0,
                               linear_damping=0.0)
    body.set_velocity((0.5, 0.0, 0.0))
    for _ in range(500):
        physics.frame(FRAME)
        if body.asleep:
            break
    assert body.asleep
    live = physics_testing.inspect(physics).position[physics_testing.slot_of(physics, body)]
    assert live[0] > 0.01
    assert np.allclose(np.asarray(body.node.translation), live, atol=1e-6, rtol=0.0)
    physics.close()


def test_a_replica_holds_the_pose_a_body_fell_asleep_at():
    worker = InlineWorker(definition(gravity=(0, 0, 0)))
    drifter_world(worker.runtime.world)
    worker.submit(box(1, (0, 0, 0)))
    worker.submit(Command('damping', 1, (0.0, None)))
    worker.submit(Command('velocity', 1, ((0.5, 0.0, 0.0),)))
    replica = Replica()
    replica.add(box(1, (0, 0, 0)).args[0])
    for _ in range(500):
        out = worker.collect(FRAME)
        if out.snapshot is not None:
            replica.sync(out.snapshot)
        if not worker.runtime.busy():
            break
    world = worker.runtime.world
    index = worker.runtime.entry(1).index
    assert not world.awake[index]
    assert np.array_equal(replica.world.position[replica.index_of(1)], world.position[index])
    assert np.array_equal(replica.world.orientation[replica.index_of(1)],
                          world.orientation[index])


# -- which rows a snapshot lists ------------------------------------------------

def test_a_snapshot_of_a_world_at_rest_lists_no_rows():
    worker = boxes_at_rest()
    worker.submit(Command('damping', 1, (0.1, None), seq=10))
    snapshot = worker.collect(FRAME).snapshot
    assert snapshot is not None
    assert snapshot.changed is not None and len(snapshot.changed) == 0


def test_a_snapshot_lists_the_row_of_the_body_that_moved():
    worker = boxes_at_rest()
    worker.submit(Command('impulse', 7, ((0.0, 3.0, 0.0), None), seq=10))
    snapshot = worker.collect(FRAME).snapshot
    assert snapshot.changed.tolist() == [snapshot.rows[7]]


def test_a_snapshot_converts_only_the_rows_it_lists(monkeypatch):
    worker = boxes_at_rest()
    converted = []
    original = mathutil.quat_to_axis_angle

    def counting(quaternions):
        converted.append(len(quaternions))
        return original(quaternions)

    monkeypatch.setattr(runtime_module.mathutil, 'quat_to_axis_angle', counting)
    worker.submit(Command('impulse', 7, ((0.0, 3.0, 0.0), None), seq=10))
    worker.collect(FRAME)
    assert sum(converted) <= 1


def test_a_snapshot_lists_a_sleeping_body_moved_by_hand():
    worker = boxes_at_rest()
    world = worker.runtime.world
    world.pose_arrays()[0][worker.runtime.entry(3).index] += (0.0, 0.0, 1.0)   # asleep, not woken
    worker.submit(Command('damping', 1, (0.1, None), seq=10))
    snapshot = worker.collect(FRAME).snapshot
    assert snapshot.changed.tolist() == [snapshot.rows[3]]
    assert np.array_equal(snapshot.position[snapshot.rows[3]],
                          world.position[worker.runtime.entry(3).index])


def test_a_snapshot_after_a_body_is_added_lists_every_row():
    worker = boxes_at_rest()
    worker.submit(box(99, (20, 0.3, 20)))
    assert worker.collect(FRAME).snapshot.changed is None


def test_rows_a_snapshot_does_not_list_hold_the_pose_before():
    worker = boxes_at_rest()
    before = worker.runtime.snapshot()
    worker.submit(Command('impulse', 7, ((0.0, 3.0, 0.0), None), seq=10))
    after = worker.collect(FRAME).snapshot
    still = [row for uid, row in after.rows.items() if uid != 7]
    assert np.array_equal(after.position[still], before.position[still])
    assert np.array_equal(after.axis_angle[still], before.axis_angle[still])


def test_a_snapshot_changes_counted_since_a_version_the_reader_saw():
    worker = boxes_at_rest()
    seen = worker.runtime.snapshot()
    assert seen.changed_since(seen.version - 1) is not None
    assert seen.changed_since(seen.version - 2) is None


def test_a_thread_worker_lists_rows_changed_in_snapshots_nobody_collected():
    worker = ThreadWorker(definition())
    worker.submit(floor())
    for uid in (1, 2):
        worker.submit(box(uid, (uid * 3.0, 0.3, 0)))
    for _ in range(3000):
        worker.step(0.01)
        if not worker.runtime.busy():
            break
    seen = worker.collect(0.0).snapshot
    runtime = worker.runtime
    runtime.world.pose_arrays()[0][runtime.entry(2).index] += (0.0, 0.0, 0.5)
    worker.step(0.01)                 # published with row 2 changed
    worker.step(0.01)                 # published with nothing changed
    latest = worker.collect(0.0).snapshot
    assert latest.changed_since(seen.version).tolist() == [latest.rows[2]]


# -- what the render thread writes ------------------------------------------------

def test_a_frame_writes_the_nodes_of_the_bodies_that_moved_and_no_others(monkeypatch):
    physics, bodies = service_at_rest(20)
    written = []
    original = service_module.write_pose

    def counting(node, position, axis_angle):
        written.append(node)
        original(node, position, axis_angle)

    monkeypatch.setattr(service_module, 'write_pose', counting)
    bodies[7].apply_impulse((0.0, 3.0, 0.0))
    physics.frame(FRAME)
    assert written == [bodies[7].node]
    physics.close()


def test_a_replica_refits_the_boxes_of_the_bodies_that_moved_and_no_others(monkeypatch):
    worker = boxes_at_rest()
    replica = build({uid: spec for uid, spec in _specs(worker).items()}, worker.runtime.snapshot())
    refitted = []
    original = PhysicsWorld.refit_aabbs

    def counting(world, margin=0.05, rows=None):
        if world is replica.world:
            refitted.append(len(world.bodies) if rows is None else len(rows))
        return original(world, margin, rows=rows) if rows is not None else original(world, margin)

    monkeypatch.setattr(PhysicsWorld, 'refit_aabbs', counting)
    worker.submit(Command('impulse', 7, ((0.0, 3.0, 0.0), None), seq=10))
    replica.sync(worker.collect(FRAME).snapshot)
    assert sum(refitted) <= 1


def _specs(worker: InlineWorker) -> dict:
    """The spec of each body the worker's runtime holds, as the service keeps them."""
    specs = {1000: floor().args[0]}
    runtime = worker.runtime
    for uid in range(1, 21):
        index = runtime.entry(uid).index
        specs[uid] = BodySpec(uid, 'dynamic', Proxy.box((0.5, 0.5, 0.5)), model.Motion(mass=1.0),
                              position=tuple(runtime.world.position[index]),
                              orientation=tuple(runtime.world.orientation[index]))
    return specs


@pytest.mark.parametrize('mode', ['inline', 'thread'])
def test_nodes_and_replica_agree_with_the_world_once_it_rests(mode):
    physics, bodies = service_at_rest(10, mode=mode)
    physics._character_replica()
    bodies[4].apply_impulse((0.0, 2.0, 0.0))
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        physics.frame(FRAME)
        if mode == 'thread':
            time.sleep(0.005)
        if all(body.asleep for body in bodies):
            break
    physics.frame(FRAME)
    future = physics_testing.run(physics, lambda world: world.position.copy())
    live = future.result(timeout=5.0)
    slots = physics_testing.run(physics, lambda world: [physics.worker.runtime.entry(b.uid).index for b in bodies])
    slots = slots.result(timeout=5.0)
    replica = physics._replica
    for body, slot in zip(bodies, slots, strict=True):
        assert np.allclose(np.asarray(body.node.translation), live[slot], atol=1e-6, rtol=0.0)
        assert np.array_equal(replica.world.position[replica.index_of(body.uid)], live[slot])
    physics.close()


# -- characters ----------------------------------------------------------------------

def test_a_running_character_in_a_trigger_sends_its_stand_in_a_place_and_a_velocity_a_frame(
        monkeypatch):
    physics = Physics(definition(mode='inline'))
    physics.add_static(None, Proxy.box((60, 1, 60)), translation=(0, -0.5, 0))
    physics.add_trigger(None, Proxy.box((20, 4, 20)), translation=(0, 2.0, 0))
    character = physics.add_character(position=(0, 0.1, 0))
    for _ in range(30):
        physics.frame(FRAME)
    sent = []
    original = physics._send

    def counting(command):
        if command.uid == character.body.uid:
            sent.append(command.op)
        original(command)

    monkeypatch.setattr(physics, '_send', counting)
    character.set_move((1.0, 0.0, 0.0), 'run')
    for _ in range(10):
        physics.frame(FRAME)
    assert sent and set(sent) <= {'place', 'velocity'}
    physics.close()


def test_a_character_standing_still_sends_its_stand_in_nothing(monkeypatch):
    physics = Physics(definition(mode='inline'))
    physics.add_static(None, Proxy.box((60, 1, 60)), translation=(0, -0.5, 0))
    character = physics.add_character(position=(0, 0.1, 0))
    for _ in range(120):
        physics.frame(FRAME)
    sent = []
    monkeypatch.setattr(physics.worker, 'submit', sent.append)
    for _ in range(10):
        physics.frame(FRAME)
    assert [command.op for command in sent if command.uid == character.body.uid] == []
    physics.close()
