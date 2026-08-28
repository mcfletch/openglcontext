"""The clock a capture run advances on.

A capture renders a fixed number of frames and reads the last one back.  With
the wall clock driving the scene, the frame it reads depends on how long the
machine took to get there, so a TimeSensor lands at a different point in its
cycle every run and the image differs.  Counting frames instead makes the
captured frame a function of the scene.
"""
import pytest

from OpenGLContext import context as context_module
from OpenGLContext.events import systemtime
from OpenGLContext.video.clock import CAPTURE_FPS, FixedStepClock, capture_clock


@pytest.fixture(autouse=True)
def restore_time_source():
    """Nothing may leave the engine's clock replaced."""
    original = systemtime.timeSource()
    yield
    systemtime.setTimeSource(original)


class TestWhetherACaptureGetsOne:
    def test_an_ordinary_run_keeps_the_wall_clock(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_CAPTURE_FPS', raising=False)
        assert capture_clock() is None

    def test_a_bounded_run_gets_one(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '8')
        monkeypatch.delenv('OPENGLCONTEXT_CAPTURE_FPS', raising=False)
        clock = capture_clock()
        assert isinstance(clock, FixedStepClock)
        assert clock.frame_rate == (CAPTURE_FPS, 1)

    def test_a_rate_can_be_named(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '8')
        monkeypatch.setenv('OPENGLCONTEXT_CAPTURE_FPS', '30')
        assert capture_clock().frame_rate == (30, 1)

    def test_a_rate_of_zero_asks_for_real_time(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '8')
        monkeypatch.setenv('OPENGLCONTEXT_CAPTURE_FPS', '0')
        assert capture_clock() is None

    def test_a_rate_alone_is_enough(self, monkeypatch):
        """Asking for a frame-counting clock does not require a bounded run."""
        monkeypatch.delenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', raising=False)
        monkeypatch.setenv('OPENGLCONTEXT_CAPTURE_FPS', '25')
        assert capture_clock().frame_rate == (25, 1)


class TestWhereItStarts:
    def test_two_runs_start_at_the_same_time(self, monkeypatch):
        """A start taken from the wall clock would differ between runs."""
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '8')
        assert capture_clock()() == capture_clock()()

    def test_the_frames_it_counts_decide_the_time(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '8')
        monkeypatch.setenv('OPENGLCONTEXT_CAPTURE_FPS', '50')
        clock = capture_clock()
        start = clock()
        clock.advance(25)
        assert clock() - start == pytest.approx(0.5)


class _Context(context_module.Context):
    """A context with the window and the GL taken out."""

    def __init__(self):
        import threading
        self.currentDepth = 0
        self.redrawRequest = threading.Event()
        self.setupThreading()
        self.setupCaptureClock()

    def setCurrent(self):
        pass

    def unsetCurrent(self):
        pass

    def DoEventCascade(self):
        return 0


class TestTheContextDrivesIt:
    def test_a_capture_run_installs_it(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '8')
        held = _Context()
        assert systemtime.timeSource() is held._captureClock

    def test_an_ordinary_run_leaves_the_clock_alone(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_CAPTURE_FPS', raising=False)
        before = systemtime.timeSource()
        held = _Context()
        assert held._captureClock is None
        assert systemtime.timeSource() is before

    def test_finishing_gives_the_wall_clock_back(self, monkeypatch):
        """OnQuit calls stopCaptureClock; the time source is process-wide, so
        a context that has finished must not leave the world advancing on
        frames nobody is drawing."""
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '8')
        before = systemtime.timeSource()
        held = _Context()
        assert systemtime.timeSource() is not before
        held.stopCaptureClock()
        assert systemtime.timeSource() is before
        held.stopCaptureClock()  # OnQuit can run more than once

    def test_each_frame_moves_the_world_on_by_one(self, monkeypatch):
        """Including a frame with nothing to draw: a scene whose only motion
        comes from a timer would otherwise stop the clock that drives it."""
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '0')
        monkeypatch.setenv('OPENGLCONTEXT_CAPTURE_FPS', '10')
        monkeypatch.setattr(context_module, 'inContextThread', lambda: True)
        held = _Context()
        start = systemtime.systemTime()
        for _ in range(5):
            held.OnDraw(force=0)
        assert systemtime.systemTime() - start == pytest.approx(0.5)
