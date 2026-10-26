"""The time step a simulation takes each frame, read from a clock.

No window: the clock readings are handed in, so a stall, a cap and the first
frame can each be put in front of it directly.
"""
import pytest

from OpenGLContext.events.framestep import FrameStep


def test_a_step_is_the_time_since_the_last():
    frames = FrameStep(start=10.0)
    assert frames.step(10.016) == pytest.approx(0.016)
    assert frames.step(10.05) == pytest.approx(0.034)


def test_the_first_step_without_a_start_is_nought():
    frames = FrameStep()
    assert frames.step(5.0) == 0.0
    assert frames.step(5.02) == pytest.approx(0.02)


def test_a_stall_is_one_longest_step_rather_than_a_leap():
    frames = FrameStep(start=0.0, longest=0.1)
    assert frames.step(3.0) == pytest.approx(0.1)
    assert frames.step(3.016) == pytest.approx(0.016)


def test_a_clock_that_goes_back_is_no_time():
    frames = FrameStep(start=1.0)
    assert frames.step(0.5) == 0.0


def test_without_a_cap_there_is_no_waiting():
    frames = FrameStep(start=0.0)
    assert frames.wait(0.001) == 0.0


def test_a_cap_waits_out_the_rest_of_the_frame():
    frames = FrameStep(start=0.0, cap=0.05)
    assert frames.wait(0.02) == pytest.approx(0.03)
    assert frames.wait(0.07) == 0.0
    frames.step(0.05)
    assert frames.wait(0.06) == pytest.approx(0.04)


def test_the_cap_can_be_toggled():
    frames = FrameStep()
    assert frames.toggle_cap(0.05) == 0.05
    assert frames.cap == 0.05
    assert frames.toggle_cap(0.05) is None


def test_the_longest_step_must_be_positive():
    with pytest.raises(ValueError, match='longest'):
        FrameStep(longest=0.0)


# -- whole fixed steps ---------------------------------------------------------

def test_fixed_steps_owes_the_whole_steps_a_frame_holds_and_carries_the_rest():
    from OpenGLContext.events.framestep import FixedSteps
    steps = FixedSteps(step=0.01, longest=1.0)
    assert steps.owed(0.025) == 2
    assert steps.remainder == pytest.approx(0.005)
    assert steps.alpha == pytest.approx(0.5)
    assert steps.owed(0.005) == 1
    assert steps.remainder == pytest.approx(0.0)


def test_frames_of_any_length_owe_one_step_per_step_of_time():
    from OpenGLContext.events.framestep import FixedSteps
    for rate in (30, 60, 144, 1000):
        steps = FixedSteps(step=1 / 120, longest=0.1)
        assert sum(steps.owed(1.0 / rate) for _ in range(rate * 3)) == 360, rate


def test_fixed_steps_owes_at_most_the_longest_time():
    from OpenGLContext.events.framestep import FixedSteps
    steps = FixedSteps(step=0.01, longest=0.05)
    assert steps.owed(3.0) == 5
    assert steps.remainder == 0.0


def test_drop_forgets_the_part_step():
    from OpenGLContext.events.framestep import FixedSteps
    steps = FixedSteps(step=0.01, longest=1.0)
    steps.owed(0.008)
    steps.drop()
    assert steps.owed(0.004) == 0
    assert steps.remainder == pytest.approx(0.004)


def test_fixed_steps_refuses_a_step_or_longest_that_is_not_above_nought():
    from OpenGLContext.events.framestep import FixedSteps
    with pytest.raises(ValueError, match='step'):
        FixedSteps(step=0.0, longest=1.0)
    with pytest.raises(ValueError, match='longest'):
        FixedSteps(step=0.01, longest=-1.0)
    steps = FixedSteps(step=0.01, longest=1.0)
    assert steps.owed(-0.5) == 0
    assert steps.remainder == 0.0
