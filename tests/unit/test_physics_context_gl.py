"""Physics in a real window: no tick code, the scene's floor is the ground, an idle scene is left alone."""
import time

import pytest

from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.testing.scenes import scene_context
from OpenGLContext.testing import physics as physics_testing

LOOK = PhysicalMaterial(baseColor=(0.6, 0.6, 0.6))


def _shape(geometry, at):
    return surfaces.shape(geometry, LOOK, translation=at)


def _frames(context, until, seconds=20.0):
    """Run the loop the way the main loop does, until ``until()`` or the time is up."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        context.runRenderQueue()
        context.runFrameHooks()
        context.OnDraw(force=1)
        if until():
            return True
        time.sleep(0.005)
    return False


def test_a_ball_comes_to_rest_on_the_scenes_floor_with_no_tick_code(gl_context):
    floor = _shape(surfaces.block((20, 1, 20)), (0, -0.5, 0))
    ball = _shape(surfaces.sphere(0.5), (0, 2.0, 0))
    with scene_context([floor, ball], size=(48, 48)) as context:
        body = context.physics.add_dynamic(ball, restitution=0.0)
        body.apply_impulse((0, 0, 200))
        assert _frames(context, lambda: physics_testing.idle(context.physics))
        assert ball.translation[1] == pytest.approx(0.5, abs=0.06)
        assert ball.translation[2] > 0.0                      # the push carried it


def test_an_idle_scene_asks_for_no_frames_and_the_worker_stops_ticking(gl_context):
    floor = _shape(surfaces.block((20, 1, 20)), (0, -0.5, 0))
    ball = _shape(surfaces.sphere(0.5), (0, 0.6, 0))
    with scene_context([floor, ball], size=(48, 48)) as context:
        context.physics.add_dynamic(ball, restitution=0.0)
        assert _frames(context, lambda: physics_testing.idle(context.physics))
        steps = physics_testing.ticks(context.physics)
        time.sleep(0.3)
        context.runFrameHooks()
        assert physics_testing.ticks(context.physics) == steps
        assert context.physics.frame(0.016) is False


def test_the_window_closes_the_worker(gl_context):
    ball = _shape(surfaces.sphere(0.5), (0, 5, 0))
    with scene_context([ball], size=(48, 48)) as context:
        physics = context.physics
        physics.add_dynamic(ball)
        physics.frame(0.0)
        assert physics_testing.stepping(physics)
    assert not physics_testing.stepping(physics)


def test_the_basenodes_scene_is_not_changed_by_physics_it_never_uses(gl_context):
    ball = _shape(surfaces.sphere(0.5), (0, 5, 0))
    with scene_context([basenodes.Group(children=[ball])], size=(48, 48)) as context:
        context.OnDraw(force=1)
        assert '_physics' not in context.__dict__


def test_a_move_set_in_on_idle_moves_the_character_in_the_same_frame(gl_context):
    from OpenGLContext.events import systemtime

    now = [100.0]
    previous = systemtime.setTimeSource(lambda: now[0])
    floor = _shape(surfaces.block((20, 1, 20)), (0, -0.5, 0))
    try:
        with scene_context([floor], size=(48, 48)) as context:
            me = context.physics.add_character(position=(0, 0.05, 0))
            moves = []

            def idle(*_arguments):
                now[0] += 1 / 60
                me.set_move(moves[-1] if moves else (0, 0, 0), mode='run')
                return 0

            context.OnIdle = idle
            for _ in range(30):
                context.loopIteration()
            here = me.position.copy()
            moves.append((1, 0, 0))
            context.loopIteration()
            assert me.position[0] > here[0] + 0.05      # two 1/120 s steps at run speed
    finally:
        systemtime.setTimeSource(previous)
