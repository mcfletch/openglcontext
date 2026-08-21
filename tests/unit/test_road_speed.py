"""How fast a bend may be driven, and what a sign says about it."""
import math
from typing import Any

import numpy as np
import pytest

from OpenGLContext.scenegraph.road import (
    CAUTION,
    advisory_speed,
    corner_speed,
    cornering_radius,
    sight_distances,
)


class TestWhatABendAllows:
    def test_it_is_the_speed_the_grip_holds(self) -> None:
        assert corner_speed(100.0) == pytest.approx(math.sqrt(1.0 * 9.81 * 100.0))

    def test_a_wider_bend_allows_more(self) -> None:
        assert corner_speed(400.0) > corner_speed(100.0)

    def test_less_grip_allows_less(self) -> None:
        assert corner_speed(100.0, grip=0.5) < corner_speed(100.0)

    def test_a_straight_has_no_limit(self) -> None:
        assert corner_speed(float('inf')) == float('inf')

    def test_and_neither_has_a_road_with_no_bend_in_it(self) -> None:
        assert corner_speed(0.0) == 0.0

    def test_it_is_the_other_side_of_the_radius_a_road_may_have(self) -> None:
        """The two are one rule read each way, so a road built to a design speed
        signs its corners at that speed and not at some other number."""
        assert corner_speed(cornering_radius(40.0)) == pytest.approx(40.0)


class TestWhatTheSignSays:
    def test_it_is_well_inside_what_the_bend_allows(self) -> None:
        assert advisory_speed(100.0) < corner_speed(100.0) * 3.6

    def test_by_the_caution_fraction(self) -> None:
        assert advisory_speed(100.0, step=1) == pytest.approx(
            round(corner_speed(100.0) * 3.6 * CAUTION), abs=1.0)

    def test_it_is_a_number_a_sign_can_carry(self) -> None:
        assert advisory_speed(100.0) % 10 == 0

    def test_it_is_never_faster_than_the_bend_allows(self) -> None:
        for radius in (10.0, 25.0, 60.0, 140.0, 400.0, 1200.0):
            assert advisory_speed(radius) <= corner_speed(radius) * 3.6

    def test_a_bend_too_tight_to_sign_still_says_something(self) -> None:
        assert advisory_speed(1.0) > 0

    def test_and_a_straight_is_not_a_bend_to_sign(self) -> None:
        assert advisory_speed(float('inf')) == 0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestHowFarDownTheRoadCanBeSeen:
    """A straight can be seen along; a bend cannot be seen round."""

    @staticmethod
    def straight(length: float = 400.0, spacing: float = 4.0) -> Any:
        steps = np.arange(0.0, length + spacing, spacing)
        return np.stack([steps, np.zeros_like(steps), np.zeros_like(steps)], axis=1)

    @staticmethod
    def bend(radius: float, spacing: float = 4.0) -> Any:
        angle = np.arange(0.0, 2.0 * math.pi, spacing / radius)
        return np.stack([radius * np.sin(angle),
                         np.zeros_like(angle),
                         radius - radius * np.cos(angle)], axis=1)

    def test_a_straight_road_can_be_seen_to_the_end_of_the_reach(self) -> None:
        found = sight_distances(self.straight(), clear=3.6, reach=200.0,
                                closed=False)
        assert found[0] == pytest.approx(200.0)

    def test_a_bend_can_be_seen_round_as_far_as_the_line_of_sight_stays_clear(
            self) -> None:
        """A line of sight is the *chord* between the driver and what they are
        looking at, not the tangent they are pointing down: what blocks it is
        whatever stands inside the bend, and how far inside the view is clear
        is what decides how far round they can see.

        On a circle of radius *r*, the arc whose chord bows out by *clear* has
        run about `sqrt(8 * r * clear)` -- twice what the tangent allows, which
        is the difference between a road that can be passed on and one that
        cannot."""
        clear = 3.6
        radius = 200.0
        found = sight_distances(self.bend(radius), clear=clear, reach=600.0)
        assert found[0] == pytest.approx(math.sqrt(8.0 * radius * clear),
                                         rel=0.15)

    def test_a_tighter_bend_can_be_seen_round_less(self) -> None:
        tight = sight_distances(self.bend(80.0), clear=3.6, reach=600.0)
        wide = sight_distances(self.bend(400.0), clear=3.6, reach=600.0)
        assert tight[0] < wide[0]

    def test_more_room_beside_the_road_can_be_seen_further_round(self) -> None:
        """What is cleared back from the inside of a bend is what a driver
        sees across, so a road through open ground is passable where the same
        road with trees at the verge is not."""
        close = sight_distances(self.bend(200.0), clear=2.0, reach=600.0)
        open_ = sight_distances(self.bend(200.0), clear=12.0, reach=600.0)
        assert open_[0] > close[0]

    def test_there_is_an_answer_for_every_point_of_the_road(self) -> None:
        line = self.bend(200.0)
        assert sight_distances(line, clear=3.6).shape == (len(line),)

    def test_nothing_is_ever_seen_further_than_the_reach(self) -> None:
        found = sight_distances(self.straight(2000.0), clear=3.6,
                                reach=150.0, closed=False)
        assert found.max() <= 150.0

    def test_the_end_of_an_open_road_is_the_end_of_what_can_be_seen(self) -> None:
        """Not a wrap onto the far end of the world, which is where a closed
        course continues and an open one does not."""
        found = sight_distances(self.straight(400.0), clear=3.6,
                                reach=600.0, closed=False)
        assert found[-1] == pytest.approx(0.0, abs=8.0)


class TestWhatIsClearBesideTheRoadCanVaryAlongIt:
    """A road does not run through one thing for its whole length. The wood
    that stops a driver seeing round a bend is not there on a viaduct -- the
    railing is see-through and the drop beyond it holds nothing at all -- and
    inside a bore the wall is at the road's edge. One figure for the lot makes
    a viaduct as blind as the forest it flies over.
    """

    @staticmethod
    def ring(radius: float = 200.0, spacing: float = 4.0) -> Any:
        angle = np.arange(0.0, 2.0 * math.pi, spacing / radius)
        return np.stack([radius * np.cos(angle), np.zeros_like(angle),
                         radius * np.sin(angle)], axis=1)

    def test_one_figure_still_serves_the_whole_road(self) -> None:
        line = self.ring()
        assert np.allclose(sight_distances(line, clear=5.0),
                           sight_distances(line, clear=np.full(len(line), 5.0)))

    def test_and_a_figure_for_each_point_is_used_at_that_point(self) -> None:
        line = self.ring()
        clear = np.full(len(line), 4.0)
        clear[:len(line) // 4] = 40.0            # a viaduct over a quarter of it
        found = sight_distances(line, clear=clear, reach=600.0)
        assert found[0] > 3.0 * found[len(line) // 2]

    def test_a_road_seen_across_is_seen_further_than_one_seen_along(self):
        line = self.ring()
        close = sight_distances(line, clear=4.0)
        open_ = sight_distances(line, clear=40.0)
        assert open_.min() > close.max()
