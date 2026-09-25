"""Where something is on a road, asked while a game runs.

The answers are checked against a scan of the whole line: a windowed search
that answers differently from the whole line is the defect it could have.
"""

import math

import numpy as np
import pytest

from OpenGLContext.scenegraph.roadcourse import WINDOW, RoadCourse


def _oval(points=600, rx=400.0, rz=250.0):
    angle = np.linspace(0.0, 2.0 * math.pi, points, endpoint=False)
    return np.stack([rx * np.cos(angle), np.zeros(points), rz * np.sin(angle)],
                    axis=-1)


def _straight(points=101, spacing=10.0):
    return np.stack([np.zeros(points), np.zeros(points),
                     -np.arange(points) * spacing], axis=-1)


class _Counting(RoadCourse):
    """A road that says how many segments each search looked at."""

    looked: list

    def _best(self, at, chosen):
        self.looked.append(len(chosen))
        return super()._best(at, chosen)


def _counting(line, **named):
    road = _Counting(line, **named)
    road.looked = []
    return road


class TestTheLine:
    def test_an_open_road_is_as_long_as_its_line(self) -> None:
        assert RoadCourse(_straight()).length == pytest.approx(1000.0)

    def test_a_closed_one_comes_back_round_to_its_start(self) -> None:
        line = _oval()
        closing = float(np.linalg.norm(line[0] - line[-1]))
        road = RoadCourse(line, closed=True)
        assert road.length == pytest.approx(road.stations[-1] + closing)

    def test_a_single_point_is_not_a_road(self) -> None:
        with pytest.raises(ValueError):
            RoadCourse(np.zeros((1, 3)))

    def test_a_point_wraps_round_a_closed_road(self) -> None:
        line = _oval()
        road = RoadCourse(line, closed=True)
        assert np.allclose(road.point(len(line) + 3), line[3])


class TestWhereSomethingIs:
    def test_off_the_line_is_measured_to_the_line(self) -> None:
        index, off = RoadCourse(_straight()).nearest((3.0, 0.0, -255.0))
        assert off == pytest.approx(3.0)
        assert index in (25, 26)

    def test_the_height_does_not_count(self) -> None:
        _index, off = RoadCourse(_straight()).nearest((0.0, 40.0, -250.0))
        assert off == pytest.approx(0.0)

    def test_how_far_along_is_between_the_samples(self) -> None:
        assert RoadCourse(_straight()).station_of((1.0, 0.0, -254.0)) \
            == pytest.approx(254.0)

    def test_across_the_seam_of_a_closed_road(self) -> None:
        line = _oval()
        road = RoadCourse(line, closed=True)
        between = (line[-1] + line[0]) / 2.0
        closing = road.length - road.stations[-1]
        assert road.station_of(between) == pytest.approx(
            road.stations[-1] + closing / 2.0, abs=0.01)

    def test_the_start_of_a_closed_road_is_nought(self) -> None:
        road = RoadCourse(_oval(), closed=True)
        assert road.station_of(road.point(0)) == pytest.approx(0.0)


class TestAskingNearWhereItWasLast:
    """A windowed answer is the whole line's answer, at a fraction of the work."""

    def test_a_lap_answers_as_the_whole_line_does(self) -> None:
        line = _oval()
        road = RoadCourse(line, closed=True)
        tracker = road.tracker()
        rng = np.random.default_rng(3)
        for t in np.linspace(0.0, 2.0 * math.pi, 900):
            wobble = rng.uniform(-6.0, 6.0)
            at = (np.array([(400.0 + wobble) * math.cos(t), 0.0,
                            (250.0 + wobble) * math.sin(t)]))
            # Outside a corner of the line two segments can be equally near,
            # and either is the answer: compared round the loop, to a step.
            (index, off), (wanted, wanted_off) = (tracker.nearest(at),
                                                  road.nearest(at))
            assert off == pytest.approx(wanted_off)
            assert min(abs(index - wanted), len(line) - abs(index - wanted)) <= 1
            apart = abs(tracker.station_of(at) - road.station_of(at))
            assert min(apart, road.length - apart) < 0.1

    def test_it_looks_at_a_window_rather_than_the_line(self) -> None:
        road = _counting(_oval(), closed=True)
        tracker = road.tracker()
        tracker.nearest(road.point(10))
        tracker.nearest(road.point(11))
        assert road.looked == [600, 2 * WINDOW + 1]

    def test_a_car_put_somewhere_else_is_found_there(self) -> None:
        road = RoadCourse(_oval(), closed=True)
        tracker = road.tracker()
        tracker.nearest(road.point(10))
        assert tracker.nearest(road.point(300)) == road.nearest(road.point(300))

    def test_a_car_far_off_the_road_is_looked_for_everywhere(self) -> None:
        """Past near_enough another part of the road can be the nearer."""
        road = _counting(_oval(), closed=True, near_enough=5.0)
        tracker = road.tracker()
        tracker.nearest(road.point(10))
        tracker.nearest(road.point(10) * 0.5)
        assert road.looked[-1] == 600

    def test_the_end_of_an_open_road_is_an_end(self) -> None:
        road = _counting(_straight(points=400), near_enough=50.0)
        tracker = road.tracker()
        tracker.nearest((0.0, 0.0, 10.0))
        tracker.nearest((0.0, 0.0, 5.0))
        assert road.looked[-1] <= WINDOW + 1
        assert tracker.nearest((0.0, 0.0, 5.0)) == (0, 5.0)

    def test_forgetting_scans_the_whole_line_again(self) -> None:
        road = _counting(_oval(), closed=True)
        tracker = road.tracker()
        tracker.nearest(road.point(10))
        tracker.forget()
        tracker.nearest(road.point(10))
        assert road.looked == [600, 600]


class TestWhichWayIsAcross:
    def test_to_the_right_of_the_way_the_road_runs(self) -> None:
        # Running down -Z, the right is +X.
        assert np.allclose(RoadCourse(_straight()).across(5), (1.0, 0.0, 0.0))

    def test_a_banked_road_rolls_it(self) -> None:
        bank = np.full(101, 0.1)
        across = RoadCourse(_straight(), bank=bank).across(5)
        assert np.linalg.norm(across) == pytest.approx(1.0)
        assert across[1] == pytest.approx(-math.sin(math.atan(0.1)))

    def test_a_repeated_point_takes_the_next_that_differs(self) -> None:
        line = _straight()
        line = np.vstack([line[:5], line[4:5], line[5:]])
        assert np.allclose(RoadCourse(line).across(4), (1.0, 0.0, 0.0))
