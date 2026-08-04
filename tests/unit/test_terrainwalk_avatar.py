"""Walking a height field with the declared movement modes.

:class:`~OpenGLContext.move.terrainwalk.TerrainWalkMixin` is the terrain form of
:class:`~OpenGLContext.move.physicswalk.PhysicsWalkMixin`: the same avatar, the
same modes and the same keys, with the ground and the obstacles resolved
analytically against a :class:`HeightField` and a field of cylinders instead of
against a cooked collision mesh.

These drive the whole path with no GL and no window -- a real
:class:`~OpenGLContext.events.inputstate.InputState`, a real
:class:`~OpenGLContext.move.navigation.NavigationManager`, real modes and a real
character controller -- so what is checked is where the walker actually ends up.
"""
import math

import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.events.inputstate import InputState
from OpenGLContext.move import modes as movemodes
from OpenGLContext.move.terrainwalk import TerrainWalkMixin
from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin
from OpenGLContext.scenegraph.terrain import HeightField


# -- the ground ---------------------------------------------------------------

def flat_field(height=5.0, extent=200.0):
    """Level ground at ``height`` over a ``extent`` x ``extent`` square."""
    return HeightField(np.ones((8, 8)), extent, height)


def ramp_field(extent=200.0, relief=20.0):
    """Ground rising along +x, so a step forward changes the eye height."""
    grid = np.linspace(0.0, 1.0, 16)[None, :] * np.ones((16, 1))
    return HeightField(grid, extent, relief)


# -- the smallest host the mix-in can be added to -----------------------------

class _Platform:
    """The view platform the avatar seats the camera on."""

    def __init__(self, position=(0.0, 0.0, 0.0)):
        self.position = np.array(tuple(position) + (1.0,), dtype='d')
        self.quaternion = quaternion.fromXYZR(0, 1, 0, 0)

    def setPosition(self, position):
        self.position = np.array(tuple(position) + (1.0,), dtype='d')

    def setOrientation(self, orientation):
        x, y, z, r = orientation
        self.quaternion = quaternion.fromXYZR(x, y, z, r)


class _Manager:
    """Stands in for the free-fly movement manager, recording bind/unbind."""

    def __init__(self):
        self.bound = True

    def bind(self, context):
        self.bound = True

    def unbind(self, context):
        self.bound = False


class _Definition:
    movementModes = None
    movementMode = None


class _Host(TerrainWalkMixin, ViewPlatformMixin):
    """A context with a terrain to walk and nothing else.

    Built on the real navigation mix-in, so the modes are selected, sampled and
    applied exactly as they are in a window.
    """

    def __init__(self, position=(0.0, 0.0, 0.0)):
        self.platform = _Platform(position)
        self.movementManager = _Manager()
        self.contextDefinition = _Definition()
        self.inputState = InputState()
        self.handlers = []
        self.redraws = 0
        self.clock = 0.0

    def getViewPlatform(self):
        return self.platform

    def addEventHandler(self, kind, name=None, function=None, **named):
        self.handlers.append((kind, name, named.get('state'), function))

    def triggerRedraw(self, count=0):
        self.redraws += count or 1

    def setPointerCapture(self, capture):
        self.captured = bool(capture)
        return True

    def physicsNow(self):
        """A clock the test drives, so a step is exactly the dt asked for."""
        return self.clock


def press(host, *names, state=1):
    """Hold (or release) keys, through the real event path."""
    class _Event:
        def __init__(self, name):
            self.name, self.state, self.type = name, state, 'keyboard'

        def getModifiers(self):
            return (0, 0, 0)
    for name in names:
        host.getInputState().process(_Event(name))


def walking(field=None, colliders=None, radii=None, position=(0.0, 0.0, 0.0)):
    """A host standing on ``field``, walking, with the avatar in charge."""
    host = _Host(position)
    host.init_walk(field if field is not None else flat_field(),
                   colliders, radii)
    host.setupPhysics(enable=True)
    return host


def run(host, seconds=1.0, step=1.0 / 60.0):
    """Step the avatar for ``seconds`` of held input."""
    for _ in range(int(round(seconds / step))):
        host.clock += step
        host.stepPhysics()


def eye(host):
    return tuple(float(value) for value in host.platform.position[:3])


# -- the modes the terrain declares -------------------------------------------

class TestDeclaredModes:
    def test_walking_terrain_is_first_person(self):
        """Mouse-look is the mode a landscape starts in, as it is in twig-bb."""
        host = walking()
        declared = list(host.contextDefinition.movementModes)
        assert isinstance(declared[0], movemodes.FPSMode)
        assert declared[0].capturePointer

    def test_walking_and_flying_are_offered_as_well(self):
        host = walking()
        names = [str(mode.name) for mode in host.contextDefinition.movementModes]
        assert names == ['fps', 'walk', 'fly']

    def test_a_host_that_declared_its_own_modes_keeps_them(self):
        """The speeds a game chose are not overwritten by the defaults."""
        host = _Host()
        host.contextDefinition.movementModes = [
            movemodes.WalkMode(name='walk', walkSpeed=11.0)]
        host.init_walk(flat_field())
        host.setupPhysics(enable=True)
        declared = list(host.contextDefinition.movementModes)
        assert len(declared) == 1
        assert declared[0].walkSpeed == pytest.approx(11.0)

    def test_the_avatar_is_person_sized_whatever_the_terrain_spans(self):
        """A height field is in world units, so nothing is scaled to its extent."""
        host = walking(field=flat_field(extent=4096.0))
        assert host.physicsAvatarScale((-2048, 0, -2048), (2048, 450, 2048)) \
            == pytest.approx(1.0)
        assert host.physicsPlatform.character.caps.eyeHeight \
            == pytest.approx(host.eye_height)


# -- where the walker ends up -------------------------------------------------

class TestWalking:
    def test_the_walker_stands_at_eye_height_on_the_ground(self):
        host = walking(field=flat_field(height=5.0))
        run(host, 0.2)
        assert eye(host)[1] == pytest.approx(5.0 + host.eye_height, abs=1e-6)

    def test_holding_forward_walks(self):
        host = walking()
        press(host, 'w')
        before = eye(host)
        run(host, 1.0)
        after = eye(host)
        assert math.dist(before[::2], after[::2]) > 1.0

    def test_letting_go_stops(self):
        host = walking()
        press(host, 'w')
        run(host, 0.5)
        press(host, 'w', state=0)
        stopped = eye(host)
        run(host, 0.5)
        assert eye(host)[::2] == pytest.approx(stopped[::2], abs=1e-3)

    def test_the_eye_follows_the_slope(self):
        """Walking uphill raises the camera by exactly the ground it gained."""
        host = walking(field=ramp_field())
        press(host, 'w')
        run(host, 1.0)
        x, y, z = eye(host)
        assert y == pytest.approx(host._tw_hf.height_at(x, z) + host.eye_height,
                                  abs=1e-6)

    def test_retuning_the_mode_retunes_the_walk(self):
        """What the settings screen edits is what the avatar moves at.

        The screen writes the field on the live mode node, so the only thing
        that makes the number real is the mode carrying it down to the body
        every frame.
        """
        def walked(speed):
            host = walking()
            host.contextDefinition.movementModes[0].walkSpeed = speed
            press(host, 'w')
            run(host, 1.0)
            return math.dist((0.0, 0.0), eye(host)[::2])
        assert walked(6.0) == pytest.approx(2 * walked(3.0), rel=0.05)

    def test_the_mouse_turns_the_view(self):
        host = walking()
        host.getInputState().mouse_moved(120.0, 0.0)
        run(host, 1.0 / 60.0)
        assert host.physicsPlatform.yaw != pytest.approx(0.0)


class TestObstacles:
    def test_a_trunk_stops_the_walker(self):
        """The walker is pushed out of a cylinder rather than through it."""
        trunk = np.array([[0.0, 0.0, -6.0]], 'f')
        radius = np.array([0.5], 'f')
        host = walking(colliders=trunk, radii=radius)
        # Face the trunk: the camera's forward at yaw 0 is -z.
        press(host, 'w')
        run(host, 4.0)
        x, _y, z = eye(host)
        assert math.hypot(x - 0.0, z + 6.0) >= 0.5 + host.player_radius - 1e-3

    def test_open_ground_is_not_obstructed(self):
        host = walking(colliders=np.zeros((0, 3), 'f'), radii=np.zeros(0, 'f'))
        press(host, 'w')
        run(host, 1.0)
        assert eye(host)[2] < -1.0


class TestFlying:
    def test_flying_leaves_the_ground(self):
        host = walking()
        host.togglePhysicsFly()
        press(host, ' ')                      # rise
        run(host, 1.0)
        x, y, z = eye(host)
        assert y > host._tw_hf.height_at(x, z) + host.eye_height + 1.0

    def test_the_ground_is_still_a_floor_while_flying(self):
        host = walking()
        host.togglePhysicsFly()
        press(host, 'c')                      # sink
        run(host, 2.0)
        x, y, z = eye(host)
        assert y >= host._tw_hf.height_at(x, z) + host.eye_height - 1e-6


class TestJumping:
    def test_a_jump_leaves_the_ground_and_lands_again(self):
        host = walking()
        press(host, ' ')
        run(host, 2.0 / 60.0)
        press(host, ' ', state=0)
        x, y, z = eye(host)
        assert y > host._tw_hf.height_at(x, z) + host.eye_height
        run(host, 2.0)
        x, y, z = eye(host)
        assert y == pytest.approx(host._tw_hf.height_at(x, z) + host.eye_height,
                                  abs=1e-6)


# -- living beside the free-fly camera ----------------------------------------

class TestFreeFly:
    def test_the_cascade_clamp_leaves_the_avatar_alone(self):
        """While the avatar owns the camera, the free-fly clamp must not fight it."""
        host = walking()
        press(host, ' ')                      # mid-jump: above the ground
        run(host, 2.0 / 60.0)
        airborne = eye(host)
        host.collide_and_clamp()
        assert eye(host) == pytest.approx(airborne)

    def test_the_cascade_clamp_still_holds_the_free_fly_camera_down(self):
        host = _Host((3.0, 999.0, -2.0))
        host.init_walk(flat_field(height=5.0))
        host.collide_and_clamp()
        assert eye(host)[1] == pytest.approx(5.0 + host.eye_height)

    def test_handing_the_camera_back_and_taking_it_again(self):
        host = walking()
        manager = host._freeManager
        host.togglePhysics()
        assert host.physicsWalking is False and manager.bound is True
        host.platform.setPosition((10.0, 400.0, 10.0))
        host.togglePhysics()
        assert host.physicsWalking is True
        run(host, 0.2)
        x, y, z = eye(host)
        assert (x, z) == pytest.approx((10.0, 10.0), abs=1e-3)
        assert y == pytest.approx(host._tw_hf.height_at(x, z) + host.eye_height,
                                  abs=1e-6)


class TestBeforeAnyTerrain:
    """Nothing is bound until :meth:`init_walk`, and until then nothing happens.

    A context can mix this in and decide later whether it has a landscape --
    a scene still loading, a viewer that opened a model instead -- so every
    entry point has to be harmless with no height field behind it.
    """

    def test_walking_is_refused_with_no_terrain_to_walk(self):
        host = _Host()
        assert host.setupPhysics(enable=True) is False
        assert host.physicsWalking is False
        assert host.movementManager is not None

    def test_placing_and_resolving_are_harmless(self):
        host = _Host()
        host.spawnAvatar(None, None, None)
        host.syncAvatarToCamera()
        host.standAvatarOnTerrain()
        host.resolveTerrain()
        assert host.physicsPlatform is None

    def test_a_bound_avatar_with_the_terrain_taken_away_resolves_to_nothing(self):
        host = walking()
        host._tw_hf = None
        host.standAvatarOnTerrain()
        host.resolveTerrain()          # must not raise


class TestIdle:
    def test_idle_steps_the_avatar(self):
        host = walking()
        press(host, 'w')
        host.clock += 0.25
        host.OnIdle()
        assert eye(host)[2] < -0.01           # the idle frame walked it forward

    def test_idle_still_streams_as_the_walker_moves(self):
        host = walking()
        seen = []
        host.add_stream(1.0, lambda x, z: seen.append((x, z)))
        host.OnIdle()
        assert len(seen) == 1                 # fires once on the first frame
        press(host, 'w')
        run(host, 1.0)
        host.OnIdle()
        assert len(seen) == 2


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
