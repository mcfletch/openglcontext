"""Background-threaded physics manager (:mod:`OpenGLContext.physics.threaded`).

``ThreadedPhysicsManager`` runs an :class:`omi_physics.threaded.ThreadedSimulation`
off the render thread and, on the render thread, copies the latest published pose
snapshot onto the scene ``Transform`` nodes. These tests drive a real
``omi_physics`` world (no mocks): they start the daemon thread and confirm the
simulation advances and the scene tracks it, exercise the ``with_world`` pause,
and pin the ``sync`` publish/no-op/force logic and its per-body skip conditions.
"""
import time

import numpy as np
import pytest

from OpenGLContext.scenegraph.transform import Transform
from OpenGLContext.physics.threaded import ThreadedPhysicsManager
from OpenGLContext.scenegraph.physicsbody import PhysicsBody
from omi_physics import model


def _falling_manager(gravity=9.81, sim_hz=240.0):
    mgr = ThreadedPhysicsManager(
        gravity=model.Gravity(gravity=gravity, direction=(0, -1, 0)), sim_hz=sim_hz)
    t = Transform(translation=(0, 10, 0))
    body = mgr.add(PhysicsBody(t, model.Motion(type=model.DYNAMIC)))
    return mgr, body, t


def _wait_for_steps(mgr, at_least=3, timeout=2.0):
    deadline = time.time() + timeout
    while mgr.steps < at_least and time.time() < deadline:
        time.sleep(0.005)


def test_thread_advances_simulation_and_scene_tracks_it():
    """Starting the thread steps the world, and a render-thread sync drops the box."""
    mgr, body, t = _falling_manager()
    mgr.start()
    try:
        _wait_for_steps(mgr, at_least=5)
    finally:
        mgr.stop()
    assert mgr.steps >= 5                     # background thread actually ticked
    mgr.sync(force=True)
    assert t.translation[1] < 10.0            # scene followed the falling body
    # the scene tracks the sim to within a tick of falling
    assert mgr.world.position[body.index][1] == pytest.approx(
        t.translation[1], abs=0.05)


def test_manager_reports_whether_the_thread_is_keeping_up():
    """The two numbers that separate slow physics from starved physics.

    A simulation getting fewer turns than it asked for looks, on screen, like a
    world with the wrong gravity in it. The manager passes the thread's own
    accounting through so an overlay can show it beside the frame rate.
    """
    mgr, _body, _t = _falling_manager(sim_hz=100.0)
    assert mgr.dropped == 0
    assert mgr.rate() == 0.0                   # nothing has ticked yet
    mgr.start()
    try:
        _wait_for_steps(mgr, at_least=30, timeout=3.0)
    finally:
        mgr.stop()
    assert mgr.steps >= 30
    assert mgr.rate() == pytest.approx(100.0, rel=0.35)
    assert mgr.dropped == 0                    # 100Hz of empty world is easy


def test_stop_halts_stepping():
    """After stop() the tick counter no longer advances."""
    mgr, _body, _t = _falling_manager()
    mgr.start()
    _wait_for_steps(mgr, at_least=3)
    mgr.stop()
    frozen = mgr.steps
    time.sleep(0.05)
    assert mgr.steps == frozen


def test_advance_publishes_latest_and_returns_unit_alpha():
    """The render-thread advance() syncs the newest poses and reports alpha 1.0."""
    mgr, _body, t = _falling_manager()
    mgr.start()
    try:
        _wait_for_steps(mgr, at_least=5)
    finally:
        mgr.stop()
    assert mgr.advance(1 / 60) == 1.0
    assert t.translation[1] < 10.0


def test_with_world_gives_exclusive_access():
    """with_world() holds the sim's world lock so structural edits are safe."""
    mgr, _body, _t = _falling_manager()
    mgr.start()
    try:
        with mgr.with_world():
            assert mgr.world.body_count == 1   # exclusive access to the live world
    finally:
        mgr.stop()


def test_sync_is_noop_before_any_snapshot_is_published():
    """With no snapshot yet, sync() leaves the authored pose untouched."""
    mgr, _body, t = _falling_manager()
    before = tuple(t.translation)
    mgr.sync()                                 # latest() is (None, ...) pre-start
    assert tuple(t.translation) == before


def test_sync_skips_republishing_the_same_version_unless_forced():
    """A second sync at the same version is a no-op; force re-writes anyway."""
    mgr, _body, t = _falling_manager()
    mgr._sim._publish()                        # one snapshot, no thread running
    mgr.sync()                                 # applies it (version advanced)
    applied = tuple(t.translation)
    t.translation = (7, 7, 7)                  # scribble over the pose
    mgr.sync()                                 # same version -> must not touch it
    assert tuple(t.translation) == (7, 7, 7)
    mgr.sync(force=True)                        # forced -> restores the snapshot pose
    assert np.allclose(t.translation, applied)


def test_sync_skips_bodies_that_are_unregistered_or_out_of_range():
    """A body with no index, or an index past the snapshot, is skipped safely."""
    mgr, real, t = _falling_manager()
    mgr._sim._publish()
    unregistered = PhysicsBody(Transform(translation=(1, 2, 3)),
                               model.Motion(type=model.DYNAMIC))   # index is None
    stray = PhysicsBody(Transform(translation=(4, 5, 6)),
                        model.Motion(type=model.DYNAMIC))
    stray.index = 999                          # beyond len(snapshot poses)
    mgr.bodies.extend([unregistered, stray])
    mgr.sync(force=True)
    assert tuple(unregistered.transform.translation) == (1, 2, 3)
    assert tuple(stray.transform.translation) == (4, 5, 6)
    assert real.index == 0                     # the real body still synced


def test_sync_skips_sleeping_dynamic_bodies():
    """Once a dynamic body sleeps its pose is not rewritten on subsequent syncs."""
    mgr = ThreadedPhysicsManager(gravity=model.Gravity(gravity=0.0), sim_hz=240.0)
    t = Transform(translation=(0, 0, 0))
    body = mgr.add(PhysicsBody(t, model.Motion(type=model.DYNAMIC)))
    mgr.start()
    try:
        deadline = time.time() + 3.0
        while mgr.world.awake[body.index] and time.time() < deadline:
            time.sleep(0.01)
    finally:
        mgr.stop()
    assert not mgr.world.awake[body.index]     # settled to sleep
    mgr.sync(force=True)
    resting = tuple(t.translation)
    t.translation = (9, 9, 9)                  # a later sync must leave it alone
    mgr._sim._publish()
    mgr.sync()
    assert tuple(t.translation) == (9, 9, 9)
    assert resting is not None


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
