"""A recording taken during a capture leaves the capture's clock alone.

Both a capture and a recording want to own the world's time source, and they
want the same thing of it: a frame's worth per frame, so the run is repeatable.
A capture's is the stricter -- a fixed step from a fixed start -- so a recording
that finds one installed reads it rather than replacing it with one that
advances by however long each frame actually took.
"""

import pytest

from OpenGLContext.events import systemtime
from OpenGLContext.telemetry.record import RecordingClock
from OpenGLContext.video.clock import FixedStepClock


@pytest.fixture(autouse=True)
def restore_the_wall_clock():
    original = systemtime.timeSource()
    yield
    systemtime.setTimeSource(original)


def test_a_recording_on_its_own_drives_the_world():
    """With nothing else installed the recording's clock is the world's."""
    clock = RecordingClock(start=100.0).install()

    assert systemtime.timeSource() is clock
    clock.advance(0.5)
    assert systemtime.systemTime() == pytest.approx(100.5)


def test_a_recording_defers_to_a_capture_clock():
    """The capture is left driving, and the recording does not displace it."""
    capture = FixedStepClock(fps=60, start=0.0).install()

    recording = RecordingClock().install()

    assert systemtime.timeSource() is capture
    capture.advance()
    assert systemtime.systemTime() == pytest.approx(1 / 60)
    recording.advance(3.7)                       # a frame that took 3.7 seconds
    assert systemtime.systemTime() == pytest.approx(1 / 60)


def test_restoring_a_deferred_recording_leaves_the_capture_in_place():
    """Closing the recording must not hand the wall clock back mid-capture."""
    capture = FixedStepClock(fps=60, start=0.0).install()
    recording = RecordingClock().install()

    recording.restore()

    assert systemtime.timeSource() is capture
