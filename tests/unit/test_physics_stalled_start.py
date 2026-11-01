"""A long first frame does not change what the world does.

A window's first frame is slow: shaders compile and the window maps. The
ball of the stairs tutorial is added on the landing before that frame, and
the stairs are scenery, cooked from the scene once the service has seen it.
The world's first step waits for that scenery, so the ball strikes the
stairs with the same speeds however long the first frame took and whatever
the frame rate after it.
"""
import importlib.util
import time
from pathlib import Path

import pytest

from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing import physics as physics_testing

STAIRS = Path(__file__).resolve().parents[1] / 'tutorials' / 'physics' / 'physics_stairs.py'
#: Seconds of world time whose hits are compared: the ball is past the last step by then.
WATCHED = 3.0
#: Closing speed, in m/s, a hit must exceed to be counted; the tutorial's threshold.
ABOVE = 1.0
#: How far, in m/s, an impact speed may stray from the run with no stall.
TOLERANCE = 0.05


def stairs_module():
    spec = importlib.util.spec_from_file_location('stalled_start_stairs', STAIRS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Hits:
    """The impact speeds a body's ``'hit'`` handler hears, in order."""

    def __init__(self):
        self.speeds = []

    def heard(self, hit):
        if hit.time < WATCHED:
            self.speeds.append(round(float(hit.speed), 3))


def roll(mode, stall, fps):
    """The impact speeds of the tutorial's ball when the first frame takes ``stall`` seconds."""
    stairs = stairs_module()
    ball = stairs.make_ball()
    root = basenodes.sceneGraph(children=[stairs.make_stairs(), ball])
    physics = Physics(PhysicsDefinition(mode=mode), scene=lambda: root)
    hits = Hits()
    try:
        body = physics.add_dynamic(ball, translation=stairs.START, mass=2.0, restitution=0.4)
        body.apply_impulse((0, 0, 8))
        body.addEventHandler('hit', function=hits.heard, above=ABOVE)
        frame = 1.0 / fps
        if mode == 'thread':
            # The render thread is busy for ``stall`` seconds before its first frame.
            time.sleep(stall)
            physics.frame(0.0)
            ends = time.monotonic() + WATCHED + 1.0
            while time.monotonic() < ends:
                time.sleep(frame)
                physics.frame(frame)
        else:
            physics.frame(0.0)
            physics.frame(stall)
            for _ in range(int(round(WATCHED / frame))):
                physics.frame(frame)
        return hits.speeds
    finally:
        physics.close()


@pytest.fixture(scope='module')
def unstalled():
    """The impact speeds of a run whose frames are all 1/60 s, in each mode."""
    return {mode: roll(mode, 1.0 / 60.0, 60) for mode in ('inline', 'thread')}


@pytest.mark.parametrize('fps', [30, 60, 144])
@pytest.mark.parametrize('stall', [0.1, 1.0, 3.0])
@pytest.mark.parametrize('mode', ['inline', 'thread'])
def test_the_ball_strikes_the_stairs_the_same_way_after_a_long_first_frame(
        unstalled, mode, stall, fps):
    expected = unstalled[mode]
    assert len(expected) >= 4                       # the landing, then a stair at a time
    speeds = roll(mode, stall, fps)
    assert len(speeds) == len(expected), (speeds, expected)
    assert speeds == pytest.approx(expected, abs=TOLERANCE)


def test_the_world_does_not_step_before_its_scenery_has_joined():
    stairs = stairs_module()
    ball = stairs.make_ball()
    root = basenodes.sceneGraph(children=[stairs.make_stairs(), ball])
    physics = Physics(PhysicsDefinition(mode='thread'), scene=lambda: root)
    try:
        physics.add_dynamic(ball, translation=stairs.START, mass=2.0)
        time.sleep(0.5)
        assert physics_testing.ticks(physics) == 0  # not started by add_dynamic
        physics.frame(0.0)
        assert physics.scenery.derived              # the frame looked at the scene
        deadline = time.monotonic() + 20.0
        while physics.cooking and time.monotonic() < deadline:
            assert physics_testing.ticks(physics) == 0
            physics.frame(0.0)
            time.sleep(0.002)
        physics.frame(0.0)
        time.sleep(0.3)
        physics.frame(0.3)
        assert physics_testing.ticks(physics) > 0
        assert ball.translation[1] > stairs.START[1] - 0.1   # on the landing, not through it
    finally:
        physics.close()


def test_a_service_with_no_scene_starts_at_its_first_body():
    physics = Physics(PhysicsDefinition(mode='thread'))
    try:
        physics.add_dynamic(stairs_module().make_ball(), translation=(0, 5, 0))
        time.sleep(0.3)
        assert physics_testing.ticks(physics) > 0
    finally:
        physics.close()
