"""A clock that counts frames rather than seconds (no GL context needed)."""
import pytest

from OpenGLContext.events import systemtime
from OpenGLContext.video.clock import FixedStepClock


@pytest.fixture(autouse=True)
def restore_the_wall_clock():
    original = systemtime.timeSource()
    yield
    systemtime.setTimeSource(original)


def test_time_stands_still_until_a_frame_is_finished():
    clock = FixedStepClock(fps=60, start=100.0)
    assert clock() == 100.0
    assert clock() == 100.0                       # reading it does not advance it
    clock.advance()
    assert clock() == pytest.approx(100.0 + 1 / 60)


def test_a_frame_is_always_worth_the_same_amount_of_time():
    clock = FixedStepClock(fps=30, start=0.0)
    for _ in range(90):
        clock.advance()
    assert clock() == pytest.approx(3.0)
    assert clock.frames == 90


def test_a_ratio_frame_rate_keeps_its_exactness():
    """29.97 is 30000/1001, and a long recording must not drift off it."""
    clock = FixedStepClock(fps=(30000, 1001), start=0.0)
    for _ in range(30000):
        clock.advance()
    assert clock() == pytest.approx(1001.0)


def test_installing_it_takes_over_the_engine_clock_and_gives_it_back():
    before = systemtime.systemTime()
    with FixedStepClock(fps=60, start=5.0) as clock:
        assert systemtime.systemTime() == 5.0
        clock.advance()
        assert systemtime.systemTime() == pytest.approx(5.0 + 1 / 60)
    assert systemtime.systemTime() >= before      # the wall clock is back


def test_it_starts_from_the_clock_it_replaced_when_given_no_start():
    systemtime.setTimeSource(lambda: 4242.0)
    with FixedStepClock(fps=60) as clock:
        assert clock() == 4242.0


def test_leaving_restores_whatever_was_there_rather_than_the_wall_clock():
    """Nested recordings, or a replay driving a recording, must not lose a clock."""
    systemtime.setTimeSource(lambda: 7.0)
    with FixedStepClock(fps=60, start=0.0):
        pass
    assert systemtime.systemTime() == 7.0
