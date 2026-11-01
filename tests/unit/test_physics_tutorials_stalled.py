"""The physics tutorials after a long first frame.

A window's first frame is slow while shaders compile and the window maps. The
world runs on its own thread in real time, so these give the first draw a
stall and then draw frames at the pace their clock says.
"""
import time

import pytest

from tests.unit.test_physics_tutorials import TUTORIALS, running


def stall_first_draw(context, seconds):
    """Make the next ``context.OnDraw`` sleep ``seconds`` before it draws."""
    draw = context.OnDraw

    def slow(*arguments, **named):
        del context.OnDraw
        time.sleep(seconds)
        return draw(*arguments, **named)

    context.OnDraw = slow


def paced(run, seconds, fps=60.0, condition=None):
    """Draw frames ``1/fps`` seconds apart in real time for ``seconds``, or until ``condition()``."""
    frame = 1.0 / fps
    ends = time.monotonic() + seconds
    while time.monotonic() < ends:
        if condition is not None and condition():
            return True
        started = time.monotonic()
        run.frame()
        time.sleep(max(0.0, frame - (time.monotonic() - started)))
    return condition is None or condition()


#: Seconds of world time the ball's hits are compared over: it is on the floor by then.
HITS_OVER = 3.0


def ball_hits(stall, fps):
    """The impact speeds the colour tutorial's ball strikes at in its first :data:`HITS_OVER`
    seconds, how many hits it heard in all, and how many its own handler counted."""
    with running('physics', 'physics_stairs_colour', mode='thread') as run:
        speeds = []
        heard_times = []

        class Heard:
            def hit(self, hit):
                heard_times.append(hit.time)
                if hit.time < HITS_OVER:
                    speeds.append(float(hit.speed))

        heard = Heard()
        run.context.body.addEventHandler('hit', function=heard.hit, above=1.0)
        stall_first_draw(run.context, stall)
        paced(run, HITS_OVER + 1.0 + stall, fps, condition=lambda: run.physics.time > HITS_OVER)
        return speeds, len(heard_times), run.context.impacts


@pytest.mark.parametrize('stall, fps', [(0.1, 60), (1.0, 30), (1.0, 60), (1.0, 144), (3.0, 60)])
def test_the_ball_changes_colour_at_each_hit_whatever_the_first_frame_took(gl_context, stall, fps):
    expected, _, _ = ball_hits(0.0, 60)
    speeds, heard, impacts = ball_hits(stall, fps)
    assert impacts == heard                                  # a colour for every hit
    assert len(speeds) == len(expected) >= 4
    assert speeds == pytest.approx(expected, abs=0.05)       # m/s


def lowest_scenery(context):
    """The lowest point, in metres, of what the scene draws before anything moves."""
    from OpenGLContext.physics.gltf_world import iter_meshes, site_mesh

    lows = [float(found[0][:, 1].min()) for found in
            (site_mesh(site) for site in iter_meshes(context.getSceneGraph()))
            if found is not None and len(found[0])]
    return min(lows)


PHYSICS_TUTORIALS = sorted(path.stem for path in (TUTORIALS / 'physics').glob('*.py'))


def fallen(name, stall):
    """The ids of the bodies of tutorial ``name`` below its scenery after 3 s of world time."""
    with running('physics', name, mode='thread') as run:
        floor = lowest_scenery(run.context) - 0.5
        if stall:
            stall_first_draw(run.context, stall)
        paced(run, 3.0 + stall)
        return {body.uid for body in list(run.physics._bodies.values())
                if body.kind == 'dynamic' and body.alive and float(body.position[1]) < floor}


@pytest.mark.parametrize('name', PHYSICS_TUTORIALS)
def test_nothing_falls_through_the_scenery_after_a_long_first_frame(gl_context, name):
    # A body that leaves the scenery by design (a box sliding off the end of a ramp)
    # leaves it in the run with no stall too.
    assert fallen(name, 1.0) <= fallen(name, 0.0)


@pytest.mark.parametrize('stall', [0.2, 0.5, 1.0, 1.5])
def test_the_ball_rolls_down_to_the_floor_whatever_the_first_frame_took(gl_context, stall):
    with running('physics', 'physics_stairs', mode='thread') as run:
        ball = run.context.ball
        stall_first_draw(run.context, stall)
        lowest = float('inf')
        ends = time.monotonic() + stall + 6.0
        while time.monotonic() < ends:
            paced(run, 0.1)
            lowest = min(lowest, float(ball.translation[1]))
            if ball.translation[1] < 0.3 and ball.translation[2] > 4.8:
                break
        assert lowest > -0.5                                   # never through the floor
        assert ball.translation[1] < 0.3                       # on the floor
        assert ball.translation[2] > 4.8                       # beyond the last step


@pytest.mark.parametrize('stall', [0.2, 0.5, 1.0, 1.5])
def test_the_lanes_balls_and_crates_stay_on_their_stairs_whatever_the_first_frame_took(
        gl_context, stall):
    with running('physics', 'physics_stairs_material', mode='thread') as run:
        nodes = [*run.context.balls.values(), *run.context.crates.values()]
        stall_first_draw(run.context, stall)
        lowest = float('inf')
        ends = time.monotonic() + stall + 3.0
        while time.monotonic() < ends:
            paced(run, 0.1)
            lowest = min(lowest, *(float(node.translation[1]) for node in nodes))
        assert lowest > -0.5                                   # never through the floor
