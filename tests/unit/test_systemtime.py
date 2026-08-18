"""The engine's wall clock, and replacing it with one that counts frames.

Every time-driven thing in the scenegraph -- TimeSensors, and so everything they
animate -- is advanced against ``systemtime.systemTime()``. Making that source
replaceable is what lets a recording advance the world by exactly one frame's
worth per frame drawn, however long the frame took to render.
"""
import pytest

from OpenGLContext.events import systemtime


@pytest.fixture(autouse=True)
def restore_the_wall_clock():
    """No test may leave a fake clock installed for the next one."""
    original = systemtime.timeSource()
    yield
    systemtime.setTimeSource(original)


def test_the_default_source_is_the_wall_clock():
    import time
    assert abs(systemtime.systemTime() - time.time()) < 1.0


def test_system_time_reads_the_installed_source():
    systemtime.setTimeSource(lambda: 1234.5)
    assert systemtime.systemTime() == 1234.5


def test_setting_a_source_gives_back_the_one_it_replaced():
    first = systemtime.setTimeSource(lambda: 1.0)
    second = systemtime.setTimeSource(lambda: 2.0)
    assert second() == 1.0
    systemtime.setTimeSource(first)
    assert systemtime.systemTime() != 1.0


def test_setting_none_restores_the_wall_clock():
    systemtime.setTimeSource(lambda: 99.0)
    systemtime.setTimeSource(None)
    assert systemtime.systemTime() > 1e9          # a real epoch time


def test_the_timer_subsystem_advances_against_the_installed_source():
    """A Timer polled with no time of its own reads the installed clock."""
    from OpenGLContext.events.timer import Timer

    clock = [1000.0]
    systemtime.setTimeSource(lambda: clock[0])
    timer = Timer(duration=10.0, repeating=0)
    timer.start()
    clock[0] += 4.0
    timer.poll()
    assert timer.internal.getCurrent() == pytest.approx(4.0)
