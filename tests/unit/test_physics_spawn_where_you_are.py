"""Switching to walking drops in where the camera is
(:mod:`OpenGLContext.move.physicswalk`).

The spawn search places the avatar somewhere it can walk out of, which is right
for a model you have just opened and no answer at all once the world is a city:
the camera is wherever you flew to, and the middle of a twelve-kilometre dataset
is several kilometres away -- often over water. So enabling walking seats the
avatar at the camera and lets gravity bring it down to whatever is underneath.
"""
import numpy as np
import pytest

from omi_physics import model
from omi_physics.world import PhysicsWorld
from OpenGLContext import quaternion
from OpenGLContext.move.physicswalk import PhysicsWalkMixin


def _floor(size=6000.0):
    """A flat floor spanning `size` metres, the way a city's ground reads."""
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    half = size / 2
    points = np.array([[-half, 0.0, -half], [half, 0.0, -half],
                       [half, 0.0, half], [-half, 0.0, half]], dtype='d')
    shape = world.add_shape(model.Shape.trimesh(points, np.array([[0, 2, 1],
                                                                 [0, 3, 2]])))
    world.add_body(model.Motion(type=model.STATIC),
                   collider=model.Collider(shape=shape))
    return world, (np.array([-half, 0.0, -half]), np.array([half, 0.0, half]))


class _Platform:
    """The free-fly camera, as much of it as walking reads."""

    def __init__(self, position):
        self.position = np.array(tuple(position) + (1.0,), dtype='d')
        self.quaternion = quaternion.fromXYZR(0, 1, 0, 0)

    def setPosition(self, position):
        self.position = np.array(tuple(position) + (1.0,), dtype='d')

    def setOrientation(self, orientation):
        x, y, z, r = orientation
        self.quaternion = quaternion.fromXYZR(x, y, z, r)


class _Host(PhysicsWalkMixin):
    """A context with a floor and a camera, and nothing else.

    A world rather than a model, which is what asks for the drop-in.
    """

    physicsDropIn = True

    def __init__(self, camera):
        self.platform = _Platform(camera)
        self.movementManager = None
        self.contextDefinition = type('_Definition', (), {'movementModes': []})()
        self.world, self.bounds = _floor()

    def buildPhysicsWorld(self):
        return self.world, self.bounds

    def getViewPlatform(self):
        return self.platform

    def addEventHandler(self, kind, **named):
        pass

    def triggerRedraw(self, count=1):
        pass

    def getNavigation(self):
        return None

    def applyMovementModes(self, scale):
        pass


def _settle(host, seconds=6.0):
    for _ in range(int(seconds * 60)):
        host.physicsPlatform.update(1.0 / 60.0)
        if host.physicsPlatform.character.grounded:
            break


def test_walking_starts_under_the_camera_not_in_the_middle():
    host = _Host(camera=(2200.0, 40.0, -1750.0))
    assert host.enablePhysics(True)
    landed = host.physicsPlatform.character.position
    assert landed[0] == pytest.approx(2200.0, abs=1.0)
    assert landed[2] == pytest.approx(-1750.0, abs=1.0)


def test_a_camera_in_the_air_falls_rather_than_hovering():
    """`g` means walk, so the avatar drops to what is under it.

    Sixty metres rather than the several hundred a city is flown at, because
    what is under test is that it falls at all: the descent itself is the
    physics engine's and is timed by terminal velocity.
    """
    host = _Host(camera=(0.0, 60.0, 0.0))
    host.enablePhysics(True)
    started = host.physicsPlatform.character.position[1]
    assert not host.physicsPlatform.character.flying
    _settle(host, seconds=12.0)
    character = host.physicsPlatform.character
    assert character.position[1] < started - 10.0, character.position


def test_going_back_to_free_fly_and_returning_keeps_the_place():
    host = _Host(camera=(1000.0, 30.0, 500.0))
    host.enablePhysics(True)
    _settle(host)
    host.enablePhysics(False)
    assert not host.physicsWalking
    host.platform.setPosition((-800.0, 60.0, -400.0))     # flew somewhere else
    host.enablePhysics(True)
    landed = host.physicsPlatform.character.position
    assert landed[0] == pytest.approx(-800.0, abs=1.0)
    assert landed[2] == pytest.approx(-400.0, abs=1.0)
