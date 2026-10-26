"""A third-person character: keys relative to the camera, a camera that follows and keeps out of walls."""
import math
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from OpenGLContext import context as context_module
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.events import systemtime
from OpenGLContext.events.renderqueue import RenderQueue
from OpenGLContext.move.thirdperson import FollowMode, ThirdPersonPlatform
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


class Keys:
    """Held and pressed keys, as a movement mode reads them."""

    def __init__(self, *held):
        self._held = set(held)
        self._pressed = set(held)

    def held(self, *names):
        return any(name in self._held for name in names)

    def pressed(self, *names):
        hit = any(name in self._pressed for name in names)
        self._pressed.difference_update(names)
        return hit

    def axis(self, positive, negative):
        return float(self.held(*positive)) - float(self.held(*negative))

    def modifiers(self, name=''):
        return (0, 0, 0)

    def mouse_delta(self):
        return (0.0, 0.0)


class FakePlatform:
    """What FollowMode drives: it records the moves it is given."""

    def __init__(self):
        self.moves = []
        self.jumps = 0
        self.slides = 0
        self.turned = 0.0

    def set_move(self, forward=0.0, strafe=0.0, mode='walk', speed=None):
        self.moves.append((forward, strafe, mode, speed))

    def jump(self):
        self.jumps += 1

    def slide(self):
        self.slides += 1

    def turn(self, amount):
        self.turned += amount

    def look(self, amount):
        pass


# -- the mode -------------------------------------------------------------------

def test_the_mode_names_itself_and_binds_the_usual_keys():
    mode = FollowMode()
    assert mode.name == 'follow'
    for command in ('forward', 'back', 'left', 'right', 'turnleft', 'turnright',
                    'run', 'sprint', 'jump', 'slide'):
        assert mode.keys_for(command), command


def test_forward_walks_and_shift_runs_and_ctrl_sprints():
    mode = FollowMode()
    platform = FakePlatform()
    mode.update(0.016, Keys('w'), platform)
    mode.update(0.016, Keys('w', '<shift>'), platform)
    mode.update(0.016, Keys('w', *mode.keys_for('sprint')), platform)
    assert [move[:3] for move in platform.moves] == [
        (1.0, 0.0, 'walk'), (1.0, 0.0, 'run'), (1.0, 0.0, 'sprint')]
    assert platform.moves[0][3] == pytest.approx(mode.walkSpeed)
    assert platform.moves[2][3] == pytest.approx(mode.sprintSpeed)


def test_a_jump_is_one_launch_per_press():
    mode = FollowMode()
    platform = FakePlatform()
    keys = Keys(' ')
    mode.update(0.016, keys, platform)
    mode.update(0.016, keys, platform)
    assert platform.jumps == 1


def test_the_slide_key_slides():
    mode = FollowMode()
    platform = FakePlatform()
    mode.update(0.016, Keys(*mode.keys_for('slide')), platform)
    assert platform.slides == 1


def test_auto_forward_runs_without_a_key_and_steering_stays_with_the_keys():
    mode = FollowMode(autoForward=1.0)
    platform = FakePlatform()
    mode.update(0.016, Keys(), platform)
    mode.update(0.016, Keys('d'), platform)
    assert platform.moves[0][:2] == (1.0, 0.0)
    assert platform.moves[1][:2] == (1.0, 1.0)


def test_the_turn_keys_swing_the_camera():
    mode = FollowMode()
    platform = FakePlatform()
    mode.update(0.1, Keys(*mode.keys_for('turnright')), platform)
    assert platform.turned > 0.0


# -- the platform -------------------------------------------------------------------

def make_world():
    from OpenGLContext.physics.service import Physics
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0))
    service.add_static(surfaces.shape(surfaces.block((80, 1, 80)), LOOK, translation=(0, -0.5, 0)),
                       proxy='box')
    return service


class Camera:
    """A view platform that remembers where it was put."""

    def __init__(self):
        self.position = None
        self.orientation = None

    def setPosition(self, position):
        self.position = np.asarray(position, dtype='d')

    def setOrientation(self, orientation):
        self.orientation = orientation


def test_the_camera_stands_behind_the_character_along_the_yaw():
    physics = make_world()
    me = physics.add_character(position=(0, 0.05, 0))
    physics.frame(0.5)
    camera = Camera()
    platform = ThirdPersonPlatform.over(me, camera=camera, distance=4.0, height=1.5)
    platform.yaw = 0.0                      # looking along -z
    platform.update(0.016)
    platform.apply(SimpleNamespace(platform=camera))
    assert camera.position[0] == pytest.approx(0.0, abs=1e-6)
    assert camera.position[2] == pytest.approx(4.0, abs=0.01)
    assert camera.position[1] == pytest.approx(me.position[1] + 1.5, abs=0.01)
    platform.yaw = math.pi / 2             # looking along +x: the camera is on the -x side
    platform.apply(SimpleNamespace(platform=camera))
    assert camera.position[0] == pytest.approx(-4.0, abs=0.01)
    physics.close()


def test_keys_move_the_character_relative_to_the_camera_yaw():
    physics = make_world()
    me = physics.add_character(position=(0, 0.05, 0))
    physics.frame(0.5)
    platform = ThirdPersonPlatform.over(me, camera=Camera())
    platform.yaw = math.pi / 2             # the camera looks along +x
    mode = FollowMode()
    mode.update(0.016, Keys('w'), platform)
    for _ in range(60):
        physics.frame(1 / 60)
    assert me.position[0] > 1.0
    assert abs(me.position[2]) < 0.3
    physics.close()


def test_a_wall_behind_the_character_pulls_the_camera_in():
    physics = make_world()
    physics.add_static(surfaces.shape(surfaces.block((20, 6, 1)), LOOK, translation=(0, 3, 3)),
                       proxy='box')
    me = physics.add_character(position=(0, 0.05, 0))
    physics.frame(0.5)
    camera = Camera()
    platform = ThirdPersonPlatform.over(
        me, camera=camera, distance=6.0, height=1.5,
        sweep=lambda o, d, dist, r: physics.sweep_sphere(o, d, dist, r, skip=me.body))
    platform.yaw = 0.0
    for _ in range(30):
        platform.update(1 / 60)
        platform.apply(SimpleNamespace(platform=camera))
    assert camera.position[2] < 3.0 - 0.3
    physics.close()


# -- Context.follow ----------------------------------------------------------------------

class _Context(context_module.Context):
    telemetry = None

    def __init__(self):
        self.redrawRequest = threading.Event()
        self.renderQueue = RenderQueue(wake=self.redrawRequest.set)
        self.contextDefinition = ContextDefinition(physics=PhysicsDefinition(mode='inline', maxCatchUp=2.0))
        self._captureClock = None
        self.windowsystem = SimpleNamespace(release=lambda: None)
        self.sceneLoader = None
        self.initializeEventManagers()
        self.platform = None
        self.redraws = []

    def getViewPort(self):
        return (64, 64)

    def triggerRedraw(self, force=0):
        self.redraws.append(force)


@pytest.fixture
def clock():
    state = {'now': 1000.0}
    previous = systemtime.setTimeSource(lambda: state['now'])

    class Clock:
        def advance(self, seconds):
            state['now'] += seconds

    yield Clock()
    systemtime.setTimeSource(previous)


@pytest.fixture
def ctx():
    made = _Context()
    made.physics.add_static(surfaces.shape(surfaces.block((80, 1, 80)), LOOK, translation=(0, -0.5, 0)),
                            proxy='box')
    yield made
    made.releaseWindow()


def press(ctx, name, state=1):
    ctx.getInputState().process(SimpleNamespace(name=name, state=state))


def test_follow_has_the_character_obey_the_keys_and_the_camera_follow(ctx, clock):
    me = ctx.physics.add_character(position=(0, 0.05, 0))
    follower = ctx.follow(me, distance=5.0, height=1.5)
    press(ctx, 'w')
    for _ in range(90):
        clock.advance(1 / 60)
        ctx.renderQueue.frame()
    assert me.position[2] < -2.0                          # the default camera looks along -z
    eye = ctx.platform.position
    assert eye[2] == pytest.approx(me.position[2] + 5.0, abs=0.7)
    assert follower.character is me


def test_follow_asks_for_frames_while_the_character_moves(ctx, clock):
    me = ctx.physics.add_character(position=(0, 0.05, 0))
    ctx.follow(me)
    press(ctx, 'w')
    clock.advance(1 / 60)
    ctx.renderQueue.frame()
    assert ctx.redraws


def test_unfollow_stops_the_keys_and_the_camera(ctx, clock):
    me = ctx.physics.add_character(position=(0, 0.05, 0))
    follower = ctx.follow(me)
    press(ctx, 'w')
    for _ in range(30):
        clock.advance(1 / 60)
        ctx.renderQueue.frame()
    ctx.unfollow()
    here = me.position.copy()
    me.set_move((0, 0, 0))
    for _ in range(30):
        clock.advance(1 / 60)
        ctx.renderQueue.frame()
    assert follower.stopped
    assert me.position[2] == pytest.approx(here[2], abs=0.5)


def test_follow_is_a_registered_movement_mode():
    from OpenGLContext.move.navigationdefinition import Navigation, movementMode

    mode = movementMode('follow', scale=2.0)
    assert isinstance(mode, FollowMode) and mode.name == 'follow'
    assert mode.walkSpeed == pytest.approx(6.0)
    assert [declared.name for declared in Navigation(modes=['follow']).modes] == ['follow']


# -- Context.follow(view='eyes') -------------------------------------------------------------

def test_follow_from_the_eyes_puts_the_camera_at_them_and_the_keys_walk_the_character(ctx, clock):
    from OpenGLContext.move.firstperson import EyesController

    ctx.platform = Camera()
    me = ctx.physics.add_character(position=(0, 0.05, 0))
    follower = ctx.follow(me, view='eyes')
    assert isinstance(follower, EyesController)
    press(ctx, 'w')
    for _ in range(90):
        clock.advance(1 / 60)
        ctx.renderQueue.frame()
    assert me.position[2] < -2.0                          # yaw 0 looks along -z
    # The camera is at the eyes where the frame draws them, between the last two steps.
    assert np.allclose(ctx.platform.position, me.drawn_eye, atol=1e-6)


def test_follow_from_the_eyes_turns_with_the_turn_keys(ctx, clock):
    ctx.platform = Camera()
    me = ctx.physics.add_character(position=(0, 0.05, 0))
    follower = ctx.follow(me, view='eyes', yaw=0.5)
    assert follower.platform.yaw == pytest.approx(0.5)
    press(ctx, 'e')
    for _ in range(30):
        clock.advance(1 / 60)
        ctx.renderQueue.frame()
    assert follower.platform.yaw > 0.55


def test_follow_from_the_eyes_flies_in_the_fly_mode(ctx, clock):
    ctx.platform = Camera()
    me = ctx.physics.add_character(position=(0, 0.05, 0))
    follower = ctx.follow(me, view='eyes')
    assert follower.navigation.select('fly')
    assert me.controller.flying
    assert follower.navigation.select('walk')
    assert not me.controller.flying


def test_an_unknown_view_is_refused(ctx):
    me = ctx.physics.add_character(position=(0, 0.05, 0))
    with pytest.raises(ValueError, match='view'):
        ctx.follow(me, view='overhead')


class _Manager:
    """A free-fly navigator that remembers whether it holds the camera."""

    def __init__(self):
        self.bound = True

    def bind(self, context):
        self.bound = True

    def unbind(self, context):
        self.bound = False


@pytest.mark.parametrize('view', ['behind', 'eyes'])
def test_following_takes_the_camera_from_the_free_navigator_and_unfollowing_gives_it_back(
        ctx, view):
    ctx.platform = Camera()
    manager = ctx.movementManager = _Manager()
    me = ctx.physics.add_character(position=(0, 0.05, 0))
    ctx.follow(me, view=view)
    assert ctx.movementManager is None and not manager.bound
    ctx.unfollow()
    assert ctx.movementManager is manager and manager.bound
