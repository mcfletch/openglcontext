"""Counting wheel notches out of a toolkit's rotation reports.

Shared by the backends whose toolkit states how much rotation one detent is;
see `OpenGLContext/events/wheel.py`. A wheel and a touchpad arrive the same way
and have to be counted differently: one sends a whole detent at a time, the
other a stream of fractions of one.
"""
import pytest

from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP
from OpenGLContext.events.wheel import WheelNotches

DETENT = 120.0


@pytest.fixture
def wheel():
    return WheelNotches(DETENT)


class TestAConventionalWheel:
    def test_one_detent_is_one_notch(self, wheel):
        assert wheel.notches(DETENT) == [WHEEL_UP]

    def test_turning_the_other_way(self, wheel):
        assert wheel.notches(-DETENT) == [WHEEL_DOWN]

    def test_a_flick_of_three_is_three(self, wheel):
        assert wheel.notches(3 * DETENT) == [WHEEL_UP] * 3

    def test_it_leaves_nothing_over(self, wheel):
        wheel.notches(DETENT)
        assert wheel.remainder == 0.0

    def test_no_rotation_is_no_notch(self, wheel):
        assert wheel.notches(0) == []


class TestATouchpad:
    """Fractions of a detent, summed until they make one."""

    def test_a_part_of_a_notch_scrolls_nothing_yet(self, wheel):
        assert wheel.notches(DETENT / 4.0) == []

    def test_the_parts_add_up_to_one(self, wheel):
        for _ in range(3):
            assert wheel.notches(DETENT / 4.0) == []
        assert wheel.notches(DETENT / 4.0) == [WHEEL_UP]

    def test_what_is_left_over_is_carried(self, wheel):
        wheel.notches(DETENT * 1.5)
        assert wheel.remainder == pytest.approx(DETENT * 0.5)

    def test_the_carried_part_completes_the_next_notch(self, wheel):
        wheel.notches(DETENT * 1.5)
        assert wheel.notches(DETENT * 0.5) == [WHEEL_UP]

    def test_turning_back_drops_what_was_carried(self, wheel):
        """Jitter over a pad must not accumulate into a notch the way it is
        not moving."""
        wheel.notches(DETENT * 0.9)
        assert wheel.notches(-DETENT * 0.2) == []
        assert wheel.remainder == pytest.approx(-DETENT * 0.2)


class TestDegenerateInput:
    def test_a_detent_of_nothing_reports_nothing(self):
        """Rather than dividing by it: a toolkit that names no detent size is
        a toolkit this cannot count for."""
        assert WheelNotches(0).notches(500) == []
