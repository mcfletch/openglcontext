"""A context that walks a height field, with the pieces of a window it does not need left out.

The host is a real :class:`~OpenGLContext.context.Context` under
:class:`~OpenGLContext.move.terrainwalk.TerrainWalkMixin`, so the declared
movement modes are selected, sampled and applied, the physics service is the
context's own and the render queue runs the frame, as they do in a window. The
clock is the test's: :func:`run` advances it a frame at a time.
"""
import threading
from types import SimpleNamespace

import numpy as np

from OpenGLContext import context as context_module
from OpenGLContext import quaternion
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.events import systemtime
from OpenGLContext.events.inputstate import InputState
from OpenGLContext.events.renderqueue import RenderQueue
from OpenGLContext.move.terrainwalk import TerrainWalkMixin
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph.terrain import HeightField

FRAME = 1.0 / 60.0
#: How far a place the physics world reports may be from the exact one, in metres: Jolt
#: hands positions back in single precision, two units in the last place at 20 m.
SINGLE = 1e-5


class Clock:
    """The engine's time source, advanced by the test, and the hosts the test made."""

    def __init__(self):
        self.now = 1000.0
        self.hosts = []
        self._previous = systemtime.setTimeSource(lambda: self.now)

    def advance(self, seconds):
        self.now += seconds

    def host(self, position=(0.0, 0.0, 0.0), **named):
        """A :class:`Host` that is closed when the clock is restored."""
        made = Host(position, **named)
        self.hosts.append(made)
        return made

    def restore(self):
        systemtime.setTimeSource(self._previous)
        for made in self.hosts:
            made.releaseWindow()


class Platform:
    """The view platform the avatar seats the camera on."""

    def __init__(self, position=(0.0, 0.0, 0.0)):
        self.position = np.array(tuple(position) + (1.0,), dtype='d')
        self.quaternion = quaternion.fromXYZR(0, 1, 0, 0)

    def setPosition(self, position):
        self.position = np.array(tuple(position) + (1.0,), dtype='d')

    def setOrientation(self, orientation):
        x, y, z, r = orientation
        self.quaternion = quaternion.fromXYZR(x, y, z, r)

    def setYaw(self, yaw):
        self.quaternion = quaternion.fromXYZR(0, 1, 0, yaw)

    forward = ViewPlatform.forward


class Manager:
    """Stands in for the free-fly movement manager, recording bind and unbind."""

    def __init__(self):
        self.bound = True

    def bind(self, _context):
        self.bound = True

    def unbind(self, _context):
        self.bound = False


class Host(TerrainWalkMixin, context_module.Context):
    """A context with a terrain to walk and nothing else."""

    telemetry = None

    def __init__(self, position=(0.0, 0.0, 0.0), *, platform=True, **physics):
        self.redrawRequest = threading.Event()
        self.renderQueue = RenderQueue(wake=self.redrawRequest.set)
        settings = dict(mode='inline', maxCatchUp=2.0, tickHz=120.0)
        settings.update(physics)
        self.contextDefinition = ContextDefinition(physics=PhysicsDefinition(**settings))
        self._captureClock = None
        self.windowsystem = SimpleNamespace(release=lambda: None)
        self.sceneLoader = None
        self.initializeEventManagers()
        self.platform = Platform(position) if platform else None
        self.movementManager = Manager()
        self.inputState = InputState()
        self.handlers = []
        self.redraws = []

    def getViewPort(self):
        return (64, 64)

    def getViewPlatform(self):
        return self.platform

    def addEventHandler(self, kind, name=None, function=None, **named):
        self.handlers.append((kind, name, named.get('state'), function))

    def triggerRedraw(self, force=0):
        self.redraws.append(force)

    def setPointerCapture(self, capture):
        self.captured = bool(capture)
        return True


def flat_field(height=5.0, extent=200.0):
    """Level ground at ``height`` over a ``extent`` x ``extent`` square."""
    return HeightField(np.ones((8, 8)), extent, height)


def ramp_field(extent=200.0, relief=20.0):
    """Ground rising along +x, so a step forward changes the eye height."""
    grid = np.linspace(0.0, 1.0, 16)[None, :] * np.ones((16, 1))
    return HeightField(grid, extent, relief)


def press(host, *names, state=1):
    """Hold (or release) keys, through the real event path."""
    class _Event:
        def __init__(self, name):
            self.name, self.state, self.type = name, state, 'keyboard'

        def getModifiers(self):
            return (0, 0, 0)
    for name in names:
        host.getInputState().process(_Event(name))


def walking(clock, field=None, colliders=None, radii=None, position=(0.0, 0.0, 0.0)):
    """A host standing on ``field``, walking, with the avatar in charge."""
    host = clock.host(position)
    host.init_walk(field if field is not None else flat_field(), colliders, radii)
    host.setupPhysics(enable=True)
    host.renderQueue.run()
    host.renderQueue.frame()
    return host


def run(host, clock, seconds=1.0, step=FRAME):
    """Run the frame for ``seconds`` of held input."""
    for _ in range(int(round(seconds / step))):
        clock.advance(step)
        host.renderQueue.run()
        host.renderQueue.frame()


def eye(host):
    return tuple(float(value) for value in host.platform.position[:3])
