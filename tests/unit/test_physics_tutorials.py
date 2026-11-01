"""The physics tutorials: each script's context, run in a hidden window, does what its page says.

A script is loaded by path and its ``TestContext`` is made, as ``python script.py``
makes it. The world steps inline on a fixed clock, so a run is the same on every
machine and takes the time the frames take to draw, not the seconds they stand for.
"""
import contextlib
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from OpenGLContext import renderoptions
from OpenGLContext.testing.audio import RecordingAudio
from OpenGLContext.video.clock import FixedStepClock
from OpenGLContext.testing import physics as physics_testing

TUTORIALS = Path(__file__).resolve().parents[1] / 'tutorials'
FRAME = 1.0 / 60.0


def load(directory, name):
    """The tutorial ``name`` of ``directory`` as a module, its siblings importable."""
    folder = str(TUTORIALS / directory)
    path = TUTORIALS / directory / (name + '.py')
    if not path.exists():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, folder)
    try:
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(folder)
    return module


class Run:
    """A tutorial's context, and the frames it is given."""

    def __init__(self, context, clock, module):
        self.context = context
        self.clock = clock
        self.module = module

    @property
    def physics(self):
        return self.context.physics

    def frame(self):
        self.clock.advance()
        self.context.runRenderQueue()
        self.context.OnIdle()
        self.context.runFrameHooks()
        self.context.OnDraw(force=1)

    def seconds(self, seconds):
        for _ in range(int(round(seconds / FRAME))):
            self.frame()

    def until(self, condition, seconds=20.0):
        """Draw frames until ``condition()`` holds; whether it did within ``seconds`` of world time."""
        for _ in range(int(round(seconds / FRAME))):
            if condition():
                return True
            self.frame()
        return condition()


@contextlib.contextmanager
def running(directory, name, mode='inline', environment=None):
    """The ``TestContext`` of a tutorial, made and drawn in a hidden window."""
    settings = {'OPENGLCONTEXT_PHYSICS_MODE': mode, 'OPENGLCONTEXT_AUDIO': '0',
                'OPENGLCONTEXT_DISABLE_FPS_DISPLAY': '1', **(environment or {})}
    saved = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    renderoptions.reset_env_cache()
    module = load(directory, name)
    try:
        with FixedStepClock(60, start=0.0) as clock:
            context = module.TestContext()
            context.deferRedraw = True
            try:
                yield Run(context, clock, module)
            finally:
                context.releaseWindow()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        renderoptions.reset_env_cache()
        sys.modules.pop(name, None)


# -- 1. a ball rolls down the stairs ----------------------------------------------------

def test_the_ball_starts_on_the_landing_and_comes_to_the_floor_below_the_stairs(gl_context):
    with running('physics', 'physics_stairs') as run:
        run.frame()
        start = np.array(run.context.ball.translation)
        assert start[1] > 2.0                                  # on the top of the stairs
        assert run.until(lambda: run.context.ball.translation[1] < 0.3, seconds=20.0)
        assert run.context.ball.translation[2] > 4.8           # beyond the last step


def is_red(material):
    red, green, blue = (float(v) for v in tuple(material.baseColor)[:3])
    return red > 0.9 and green < 0.2 and blue < 0.2


# -- 2. the ball changes colour when it hits something -----------------------------------

def colour_of(material):
    return tuple(round(float(v), 3) for v in tuple(material.baseColor)[:3])


def test_the_ball_steps_through_the_colours_at_each_hard_hit_and_not_before(gl_context):
    with running('physics', 'physics_stairs_colour') as run:
        run.seconds(0.2)                                       # still on the landing
        start = colour_of(run.context.skin)
        COLOURS = sys.modules['physics_stairs_colour'].COLOURS
        assert start not in [tuple(round(v, 3) for v in c) for c in COLOURS]
        seen = []

        def collect():
            now = colour_of(run.context.skin)
            if now != start and (not seen or seen[-1] != now):
                seen.append(now)
            return len(seen) >= 4

        assert run.until(collect, seconds=10.0)
        palette = [tuple(round(v, 3) for v in c) for c in COLOURS]
        assert seen[0] == palette[0]
        assert seen == palette[: len(seen)]                    # each hit moves to the next colour
        assert run.context.impacts >= len(seen)


@pytest.mark.parametrize('mode', ['inline', 'thread'])
def test_the_physics_thread_handler_sets_the_colour_through_render_set(gl_context, mode):
    with running('physics', 'physics_stairs_thread', mode=mode) as run:
        run.frame()
        calls = []
        render = run.context.physics.render
        setter = render.set

        def recording(node, **fields):
            calls.append(threading.get_ident())
            return setter(node, **fields)

        render.set = recording
        pause = 0.004 if mode == 'thread' else 0.0

        def settled():
            time.sleep(pause)
            return is_red(run.context.skin)

        assert run.until(settled, seconds=8.0)
        assert calls
        if mode == 'thread':
            assert threading.get_ident() not in calls


# -- 3. choosing the collision shape ---------------------------------------------------

def test_each_body_is_given_the_shape_the_tutorial_names(gl_context):
    with running('physics', 'physics_stairs_shapes') as run:
        run.frame()
        context = run.context
        assert context.body.proxy.kind == 'sphere'
        assert context.barrel.proxy.kind == 'convex'
        assert len(context.barrel.proxy.params['points']) <= 40       # the 10 sided hull, not the 64 drawn
        assert context.bollard.proxy.kind == 'convex'
        assert context.crate_shape.kind == 'box'
        assert len(context.crates) >= 4
        assert all(crate.proxy is context.crate_shape for crate in context.crates)


def test_the_proxies_are_drawn_over_the_scene(gl_context):
    with running('physics', 'physics_stairs_shapes') as run:
        run.frame()
        children = run.context.sg.children
        assert len(children) == 4 + 6 + 2 + 1                    # scene, crates, barrel, bollard, overlay
        run.seconds(0.5)
        assert len(children) == 4 + 6 + 2 + 1


# -- 4. a new material ------------------------------------------------------------------

def run_both_lanes(seconds=6.0):
    """Each lane's crate where it ends, and how high each ball rose from its landing after the first strike.

    The heights are read after every step of the world, so a bounce between
    two frames is not missed.
    """
    with running('physics', 'physics_stairs_material') as run:
        context, module = run.context, run.module
        assert {name: body.material for name, body in context.lanes.items()} == {
            'wet-stone': 'wet-stone', 'rubber': 'rubber'}
        balls = {name: ball for name, (_, ball) in context.bodies.items()}
        landed, rebound = set(), dict.fromkeys(balls, 0.0)

        def record(view):
            for name, at in zip(balls, view.poses(list(balls.values())).position):
                above = float(at[1]) - module.RADIUS - module.TOP
                if above < 0.01:
                    landed.add(name)
                elif name in landed and at[2] < module.RUN:      # over the landing or the top step
                    rebound[name] = max(rebound[name], above)

        run.physics.on_step(record)
        run.seconds(seconds)
        crates = {name: np.array(crate.position) for name, (crate, _) in context.bodies.items()}
        return crates, rebound, landed


def test_the_crate_skids_off_the_wet_stone_and_holds_on_the_rubber(gl_context):
    crates, _, _ = run_both_lanes()
    wet, rubber = crates['wet-stone'], crates['rubber']
    assert wet[1] < 0.3 and wet[2] > 5.0                # on the floor below the stairs (z 5.34)
    assert rubber[1] > 2.2 and rubber[2] < 0.0          # on its landing, 1.4 m on (z -0.22)
    assert wet[2] - rubber[2] > 4.5                     # 5.56 m apart along the stairs


def test_the_ball_bounces_from_the_rubber_and_not_from_the_wet_stone(gl_context):
    _, rebound, landed = run_both_lanes()
    assert landed == {'wet-stone', 'rubber'}
    assert rebound['rubber'] > 0.45                     # 0.585 m
    assert rebound['wet-stone'] < 0.12                  # 0.059 m
    assert rebound['rubber'] > 4 * rebound['wet-stone']


# -- 5. a gravity zone ------------------------------------------------------------------

def test_the_ball_is_carried_up_inside_the_zone(gl_context):
    def highest(name):
        top = 0.0
        with running('physics', name) as run:
            run.frame()
            for _ in range(60 * 14):
                run.frame()
                top = max(top, float(run.context.ball.translation[1]))
        return top

    zone = highest('physics_stairs_gravity')
    assert zone > 3.5                                           # a metre above the landing it left


# -- 6. a sound on every hit -----------------------------------------------------------

def test_the_ball_thuds_where_it_lands_at_a_gain_that_follows_its_speed(gl_context):
    with running('physics', 'physics_stairs_sound') as run:
        audio = run.context.__dict__['_audio'] = RecordingAudio(run.context)
        assert run.until(lambda: len(audio.plays) >= 2, seconds=15.0)
        for play in audio.plays:
            assert play.source is run.module.THUD
            assert 0.0 < play.gain <= 1.0
            assert 0.0 <= play.at[1] <= 3.0
        palette = [tuple(round(v, 3) for v in c) for c in sys.modules['physics_stairs_colour'].COLOURS]
        assert colour_of(run.context.skin) in palette           # the colours of the tutorial before it


def test_a_sound_on_the_material_plays_without_a_handler(gl_context):
    with running('physics', 'physics_stairs_surface_sound') as run:
        audio = run.context.__dict__['_audio'] = RecordingAudio(run.context)
        assert run.until(lambda: len(audio.plays) >= 2, seconds=15.0)
        assert all(play.source is run.module.THUD for play in audio.plays)
        assert not hasattr(run.module.TestContext, 'OnBallHit')


# -- 7. turning it off and tuning it ---------------------------------------------------

def test_pausing_holds_the_ball_where_it_is_and_pausing_again_lets_it_go(gl_context):
    with running('physics', 'physics_stairs_tuning') as run:
        context = run.context
        run.seconds(0.5)
        context.OnPause(None)
        run.frame()
        held = np.array(context.ball.translation)
        run.seconds(0.5)
        assert np.allclose(context.ball.translation, held)
        context.OnPause(None)
        run.seconds(0.5)
        assert not np.allclose(context.ball.translation, held)


def test_the_reset_puts_the_ball_back_on_the_landing_and_rolls_it_again(gl_context):
    with running('physics', 'physics_stairs_tuning') as run:
        context = run.context
        assert run.until(lambda: context.ball.translation[1] < 1.0, seconds=15.0)
        context.OnReset(None)
        run.seconds(0.1)
        assert context.ball.translation[1] > 2.0
        assert run.until(lambda: context.ball.translation[1] < 1.0, seconds=15.0)


def test_with_physics_switched_off_the_ball_stays_where_it_was_put(gl_context):
    with running('physics', 'physics_stairs', environment={'OPENGLCONTEXT_PHYSICS': '0'}) as run:
        run.frame()
        placed = np.array(run.context.ball.translation)
        run.seconds(3.0)
        assert np.allclose(run.context.ball.translation, placed)
        assert physics_testing.ticks(run.physics) == 0


# -- characters ---------------------------------------------------------------------------

def run_forward(run):
    """Hold the forward key down: the follow mode steers from the keys, so a test asks it to."""
    run.context.__dict__['_follower'].mode.autoForward = 1.0


def test_the_fox_runs_across_the_hills_and_stays_on_them(gl_context):
    with running('character', 'character_run') as run:
        run.frame()
        hero = run.context.hero
        run_forward(run)
        for _ in range(60 * 4):
            run.frame()
            ground = float(run.module.LAND.sample(hero.position[0], hero.position[2]))
            assert hero.position[1] == pytest.approx(ground, abs=0.25)
        assert hero.position[2] < -6.0                          # forward is -Z
        assert hero.settled.role in ('walk', 'run')
        assert hero.grounded


def test_the_fox_stands_idle_until_it_is_told_to_move(gl_context):
    with running('character', 'character_run') as run:
        run.seconds(1.0)
        assert run.context.hero.settled.role == 'idle'


def test_the_camera_follows_the_fox_from_behind(gl_context):
    with running('character', 'character_run') as run:
        run.seconds(1.0)
        hero = run.context.hero
        eye = np.array(run.context.getViewPlatform().position)[:3]
        assert np.linalg.norm((eye - hero.position)[[0, 2]]) == pytest.approx(4.5, abs=0.6)
        assert eye[2] > hero.position[2]                        # the camera looks along -Z


def test_a_jump_lands_with_a_thud_and_the_slide_lasts_as_long_as_it_is_told(gl_context):
    with running('character', 'character_jump') as run:
        context = run.context
        audio = context.__dict__['_audio'] = RecordingAudio(context)
        run.seconds(1.0)                                        # settled after its first drop
        audio.clear()
        assert context.hero.jump()
        assert run.until(lambda: audio.plays, seconds=3.0)
        [play] = audio.plays
        assert play.source is run.module.THUD
        assert 0.5 < play.gain <= 1.0
        assert context.__dict__['_follower'].platform.slide_time == pytest.approx(1.2)
        context.__dict__['_follower'].platform.slide()
        run.frame()
        assert context.hero.state.value == 'sliding'
        run.seconds(1.5)
        assert context.hero.state.value == 'standing'


def test_each_foot_plays_the_clip_of_the_material_under_it(gl_context):
    with running('character', 'character_footsteps') as run:
        context = run.context
        audio = context.__dict__['_audio'] = RecordingAudio(context)
        run.seconds(0.5)
        run_forward(run)
        assert run.until(lambda: context.hero.position[2] < run.module.SLAB_AT[1] - 3.0,
                         seconds=12.0)
        played = [play.source for play in audio.plays]
        assert run.module.RUSTLE in played and run.module.CLICK in played
        # The materials the handler heard, in order, are grass, stone and grass again.
        runs = [name for index, name in enumerate(context.steps)
                if index == 0 or name != context.steps[index - 1]]
        assert runs == ['grass', 'stone', 'grass']


# -- the older tutorials, on the service ------------------------------------------------

def test_the_balls_rebound_higher_the_more_restitution_they_have(gl_context):
    with running('physics', 'physics_bounce') as run:
        run.frame()
        balls = run.context.balls
        rebound = [0.0] * len(balls)
        landed = [False] * len(balls)
        for _ in range(60 * 4):
            run.frame()
            for number, body in enumerate(balls):
                height = float(body.position[1])
                if height < run.module.RADIUS + 0.15:
                    landed[number] = True
                elif landed[number]:
                    rebound[number] = max(rebound[number], height)
        assert all(landed)
        assert rebound == sorted(rebound)
        assert rebound[-1] > 3 * rebound[1]


def test_a_box_slides_on_the_steep_ramp_and_holds_on_the_shallow_ones(gl_context):
    with running('physics', 'physics_friction') as run:
        run.frame()
        before = [np.array(body.position) for body in run.context.boxes]
        run.seconds(3.0)
        moved = [float(np.linalg.norm(np.array(body.position) - start))
                 for body, start in zip(run.context.boxes, before)]
        assert moved[0] < 0.1 and moved[1] < 0.1
        assert moved[2] > 1.0


def test_the_debris_falls_in_toward_the_planet(gl_context):
    with running('physics', 'physics_gravity_zones') as run:
        run.frame()
        bodies = [body for body in run.physics._bodies.values() if body.kind == 'dynamic']
        before = [float(np.linalg.norm(body.position)) for body in bodies]
        run.seconds(1.0)
        after = [float(np.linalg.norm(body.position)) for body in bodies]
        assert len(bodies) == 14
        assert all(now < then for now, then in zip(after, before))


def test_a_ball_is_green_while_it_is_in_the_trigger_and_orange_again_after(gl_context):
    with running('physics', 'physics_triggers') as run:
        run.frame()
        context = run.context
        skins = [body.node.children[0].appearance.material for body in context.balls]

        def colours():
            return [tuple(round(float(v), 1) for v in skin.baseColor) for skin in skins]

        assert len(skins) == 6
        assert run.until(lambda: any(colour[1] == 1.0 for colour in colours()), seconds=5.0)
        assert run.until(lambda: all(colour[1] < 1.0 for colour in colours())
                         and run.clock.elapsed > 2.0, seconds=10.0)


def test_the_bodies_dropped_into_the_room_come_to_rest_inside_it(gl_context):
    with running('physics', 'physics_room_drop') as run:
        run.frame()
        size, bodies = run.module.SIZE, run.context.bodies
        assert len(bodies) == 8
        assert run.until(lambda: all(body.asleep for body in bodies), seconds=30.0)
        for body in bodies:
            x, y, z = body.position
            assert abs(x) < size and abs(z) < size
            assert 0.2 < y < 3.0
        run.context.on_add(None)
        assert len(run.context.bodies) == 9
        run.context.on_reset(None)
        assert len(run.context.bodies) == 8


def test_the_joints_hold_the_pendulum_the_chain_the_spinner_and_the_drawer(gl_context):
    with running('physics', 'physics_joints') as run:
        run.frame()
        bodies = [body for body, _ in run.context.homes]
        arm, links, spinner, drawer = bodies[0], bodies[1:6], bodies[6], bodies[7]
        pivot = np.array([-5.0, 6.0, 0.0])
        lowest = 6.0
        for _ in range(60 * 3):
            run.frame()
            assert np.linalg.norm(np.array(arm.position) - pivot) == pytest.approx(1.0, abs=0.1)
            lowest = min(lowest, float(arm.position[1]))
            for upper, lower in zip(links, links[1:]):
                assert np.linalg.norm(np.array(upper.position) - lower.position) == pytest.approx(
                    1.0, abs=0.15)
        assert lowest < 5.2                                              # it has swung down
        assert float(spinner.angular_velocity[1]) == pytest.approx(4.0, abs=0.3)
        assert float(drawer.position[0]) == pytest.approx(5.5 + 1.5, abs=0.1)  # at its stop
        run.context.on_reverse(None)
        run.seconds(1.0)
        assert float(spinner.angular_velocity[1]) == pytest.approx(-4.0, abs=0.3)


def test_each_cooking_strategy_gives_the_proxy_it_names(gl_context):
    with running('physics', 'physics_cook_view') as run:
        run.frame()
        seen = [run.context.proxy.kind]
        for _ in range(2):
            run.context.on_cycle(None)
            run.frame()
            seen.append(run.context.proxy.kind)
        assert seen == run.module.STRATEGIES
        assert run.until(lambda: run.context.body.asleep, seconds=20.0)
        assert 0.3 < run.context.body.position[1] < 2.0


def test_the_pile_falls_into_the_bowl_and_a_wave_adds_forty(gl_context):
    with running('physics', 'physics_stress') as run:
        run.frame()
        context = run.context
        assert len(context.bodies) == run.module.WAVE
        assert run.until(lambda: all(body.position[1] < 4.0 for body in context.bodies),
                         seconds=15.0)
        assert all(abs(body.position[0]) < 12 and abs(body.position[2]) < 12
                   for body in context.bodies)
        context.on_add_wave(None)
        assert len(context.bodies) == 2 * run.module.WAVE


@pytest.mark.parametrize('mode', ['inline', 'thread'])
def test_the_cannon_game_plays_in_the_contexts_own_world(gl_context, mode):
    with running('physics', 'using_physics', mode=mode) as run:
        run.frame()
        game = run.context.game
        assert game.physics is run.physics
        game.aim.elevation, game.aim.power = 30.0, 6.0
        game.point()
        run.context.OnFire(None)
        assert game.state == 'flying'
        muzzle = np.array(game.muzzle)
        assert run.until(lambda: np.linalg.norm(np.array(game.position) - muzzle) > 1.0,
                         seconds=5.0)
        assert run.until(lambda: game.state != 'flying', seconds=30.0)
        assert len(run.context.trail.point) > 3


def test_a_ball_flashes_as_hard_as_it_landed_and_cools_again(gl_context):
    with running('physics', 'using_collisions') as run:
        run.frame()
        glows = list(run.context.glows.values())
        assert run.until(lambda: any(glow.strength > 0 for glow in glows), seconds=5.0)
        landed = next(glow for glow in glows if glow.strength > 0)
        assert 0.0 < landed.strength <= 1.0
        harder = max(glows, key=lambda glow: glow.strength)
        assert harder.strength >= landed.strength
        assert run.until(lambda: all(float(glow.material.emissiveColor[0]) < 0.05
                                     for glow in glows) and run.clock.elapsed > 4.0,
                         seconds=20.0)


def test_the_walker_climbs_the_stairs_and_stays_in_the_room(gl_context):
    with running('physics', 'physics_navigate') as run:
        run.frame()
        hero = run.context.hero
        run.context.walker.platform.yaw = np.pi                 # face +Z, up the stairs
        hero.teleport((6.0, 0.05, -8.5))
        run.context.getInputState().process(SimpleNamespace(name='w', state=1))
        top = 0.0
        for _ in range(60 * 4):
            run.frame()
            top = max(top, float(hero.position[1]))
            assert -0.1 < hero.position[1] < 2.5
            assert abs(hero.position[0]) < 12 and abs(hero.position[2]) < 12
        assert top > 1.0                                                  # up the steps
        assert np.allclose(run.context.getViewPlatform().position[:3], hero.drawn_eye, atol=1e-3)


# -- the keys a tutorial binds -----------------------------------------------------------

def press(run, key):
    """The keypress a GLFW window delivers for a character, through the context's own dispatch."""
    from OpenGLContext.windowsystem.glfw import GLFWKeypressEvent

    run.context.ProcessEvent(GLFWKeypressEvent(run.context, ord(key), (False, False, False)))
    run.frame()


@pytest.mark.parametrize('name', ['physics_cloth', 'physics_events'])
def test_every_key_a_tutorial_binds_reaches_its_action(gl_context, name):
    with running('physics', name) as run:
        context = run.context
        assert context.keys
        called = []
        for key in list(context.keys):
            context.keys[key] = lambda key=key: called.append(key)
        import gc
        gc.collect()                                    # a handler nothing holds is gone by now
        for key in list(context.keys):
            press(run, key)
        assert sorted(called) == sorted(context.keys)
