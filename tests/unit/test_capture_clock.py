"""A capture run advances the world a frame at a time.

A scene animated from the clock -- a Timer, a TimeSensor -- is at whatever pose
the wall clock had reached when the capture was taken, and how long five frames
take is not the same twice. Pinning the engine's time source to a fixed step per
frame puts every run's capture at the same instant, which is what makes a stored
reference frame worth comparing against.
"""

import pytest

from OpenGLContext import context as context_module
from OpenGLContext.events import systemtime
from OpenGLContext.events.timer import Timer


@pytest.fixture(autouse=True)
def restore_the_wall_clock():
    original = systemtime.timeSource()
    yield
    systemtime.setTimeSource(original)


class _Context(context_module.Context):
    """A context with the window and the GL taken out."""

    def __init__(self, frames=None):
        from OpenGLContext.events import timeeventgeneratormanager
        self.timeManager = timeeventgeneratormanager.TimeEventGeneratorManager()
        if frames is not None:
            self._autoExitFrames = frames
            self._autoExitFrameCount = 0
        self.setupAutoExitClock()

    def getTimeManager(self):
        return self.timeManager


@pytest.fixture
def env(monkeypatch):
    def configure(frames=None):
        monkeypatch.delenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', raising=False)
        if frames is not None:
            monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', str(frames))
    return configure


def test_the_wall_clock_drives_an_ordinary_run(env):
    """Nothing is pinned when no capture was asked for."""
    env(None)
    before = systemtime.timeSource()

    context = _Context()

    assert context._autoExitClock is None
    assert systemtime.timeSource() is before


def test_a_capture_run_pins_the_clock(env):
    """Asking for a capture installs the frame-stepped clock."""
    env(5)

    context = _Context(frames=5)

    assert context._autoExitClock is not None
    assert systemtime.timeSource() is context._autoExitClock


def test_the_same_frame_reaches_the_same_instant(env):
    """Two runs of the same length put the world at the same time."""
    env(5)

    times = []
    for _ in range(2):
        context = _Context(frames=5)
        for _ in range(5):
            context.advanceCaptureClock()
        times.append(systemtime.systemTime())

    assert times[0] == times[1]


def test_a_timer_reaches_the_same_fraction(env):
    """The pose an animated scene is captured in repeats exactly."""
    env(5)

    fractions = []
    for _ in range(2):
        context = _Context(frames=5)
        timer = Timer(duration=8.0, repeating=1)
        timer.register(context)
        timer.start()
        for _ in range(5):
            context.advanceCaptureClock()
            context.timeManager(context)
        fractions.append(timer.internal.getFraction())

    assert fractions[0] == fractions[1]
    assert fractions[0] > 0, "the timer has to have moved for this to mean anything"
