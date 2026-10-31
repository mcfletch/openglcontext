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

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext import quaternion
from OpenGLContext.move.physicswalk import PhysicsWalkMixin
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph.transform import Transform


#: The half width of the floor, metres: a city's ground.
HALF = 3000.0


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

    forward = ViewPlatform.forward


class _Host(PhysicsWalkMixin):
    """A context with a floor and a camera, and nothing else.

    A world rather than a model, which is what asks for the drop-in.
    """

    physicsDropIn = True

    @staticmethod
    def physicsAvatarScale(low, high):
        """A person in a city is a person, as the viewer sizes one in a world."""
        return 1.0

    def __init__(self, camera):
        self.platform = _Platform(camera)
        self.movementManager = None
        self.contextDefinition = ContextDefinition()
        self.physics = Physics(PhysicsDefinition(mode='inline'))

    def buildPhysicsWorld(self):
        self.physics.add_static(Transform(translation=(0.0, -0.5, 0.0)),
                                Proxy.box((2 * HALF, 1.0, 2 * HALF)))
        return np.array([-HALF, 0.0, -HALF]), np.array([HALF, 0.0, HALF])

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


@pytest.fixture
def hosts():
    made = []
    yield lambda camera: made.append(_Host(camera)) or made[-1]
    for host in made:
        host.physics.close()


def _settle(host, seconds=6.0):
    for _ in range(int(seconds * 60)):
        host.physicsPlatform.update(1.0 / 60.0)
        if host.physicsPlatform.character.grounded:
            break


def test_walking_starts_under_the_camera_not_in_the_middle(hosts):
    host = hosts(camera=(2200.0, 40.0, -1750.0))
    assert host.enablePhysics(True)
    landed = host.physicsPlatform.character.position
    assert landed[0] == pytest.approx(2200.0, abs=1.0)
    assert landed[2] == pytest.approx(-1750.0, abs=1.0)


def test_a_camera_in_the_air_falls_rather_than_hovering(hosts):
    """`g` means walk, so the avatar drops to what is under it.

    Sixty metres rather than the several hundred a city is flown at, because
    what is under test is that it falls at all: the descent itself is the
    physics engine's and is timed by terminal velocity.
    """
    host = hosts(camera=(0.0, 60.0, 0.0))
    host.enablePhysics(True)
    started = host.physicsPlatform.character.position[1]
    assert not host.physicsPlatform.character.flying
    _settle(host, seconds=12.0)
    character = host.physicsPlatform.character
    assert character.position[1] < started - 10.0, character.position


def test_going_back_to_free_fly_and_returning_keeps_the_place(hosts):
    host = hosts(camera=(1000.0, 30.0, 500.0))
    host.enablePhysics(True)
    _settle(host)
    host.enablePhysics(False)
    assert not host.physicsWalking
    host.platform.setPosition((-800.0, 60.0, -400.0))     # flew somewhere else
    host.enablePhysics(True)
    landed = host.physicsPlatform.character.position
    assert landed[0] == pytest.approx(-800.0, abs=1.0)
    assert landed[2] == pytest.approx(-400.0, abs=1.0)
