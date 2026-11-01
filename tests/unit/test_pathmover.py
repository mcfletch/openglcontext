"""Running along a course: the move that keeps a character on its lane."""
import math

import numpy as np
import pytest

from OpenGLContext.move.pathmover import PathMover, PathStep
from OpenGLContext.scenegraph.roadcourse import RoadCourse

DT = 1 / 120


def straight(length=300.0, spacing=1.0):
    """A course running toward -z, so its right-hand side is +x."""
    z = -np.arange(0.0, length + spacing, spacing)
    return RoadCourse(np.stack([np.zeros_like(z), np.zeros_like(z), z], axis=-1))


def winding(length=400.0, spacing=1.0):
    """A course that swings left and right by up to 29 degrees every 150 m."""
    points, at, heading = [np.zeros(3)], np.zeros(3), 0.0
    for step in range(int(length / spacing)):
        heading = 0.5 * math.sin(2.0 * math.pi * step * spacing / 150.0)
        at = at + spacing * np.array([math.sin(heading), 0.0, -math.cos(heading)])
        points.append(at)
    return RoadCourse(np.array(points))


def oval():
    angle = np.linspace(0.0, 2.0 * math.pi, 400, endpoint=False)
    return RoadCourse(np.stack([100.0 * np.cos(angle), np.zeros(400),
                                60.0 * np.sin(angle)], axis=-1), closed=True)


def drive(mover, position, seconds, dt=DT, watch=None):
    """Move a body at the velocity the mover asks for; ``watch`` sees each step."""
    position = np.array(position, dtype='d')
    for _ in range(int(round(seconds / dt))):
        step = mover.update(position, dt)
        position = position + np.array(step.velocity) * dt
        if watch is not None:
            watch(position, step)
    return position


class TestFollowingTheLine:
    def test_it_runs_along_the_course_at_the_speed(self):
        mover = PathMover(straight(), speed=10.0)
        step = mover.update((0.0, 0.0, -5.0), DT)
        assert step.velocity == pytest.approx((0.0, 0.0, -10.0))
        assert step.direction == pytest.approx((0.0, 0.0, -1.0))
        assert step.speed == pytest.approx(10.0)

    def test_a_bent_course_keeps_the_character_within_five_centimetres(self):
        course = winding()
        mover = PathMover(course, speed=10.0)
        worst = []
        drive(mover, course.point(0), 20.0,
              watch=lambda position, step: worst.append(abs(step.lateral_error)))
        assert max(worst) < 0.05

    def test_two_hundred_metres_are_covered_in_twenty_seconds(self):
        course = winding()
        mover = PathMover(course, speed=10.0)
        end = drive(mover, course.point(0), 20.0)
        assert course.station_of(end) == pytest.approx(200.0, abs=1.0)

    def test_it_steers_back_from_beside_the_line(self):
        mover = PathMover(straight(), speed=10.0)
        position = drive(mover, (0.8, 0.0, -2.0), 1.0)
        assert position[0] == pytest.approx(0.0, abs=0.05)

    def test_a_character_to_the_left_is_steered_right(self):
        mover = PathMover(straight(), speed=10.0)
        step = mover.update((-1.0, 0.0, -5.0), DT)
        assert step.velocity[0] > 0
        assert step.lateral_error == pytest.approx(-1.0)

    def test_the_height_is_left_to_the_controller(self):
        step = PathMover(straight(), speed=10.0).update((0.0, 3.0, -5.0), DT)
        assert step.velocity[1] == 0.0
        assert step.direction[1] == 0.0

    def test_the_speed_can_change_while_running(self):
        mover = PathMover(straight(), speed=10.0)
        mover.update((0.0, 0.0, -5.0), DT)
        mover.speed = 4.0
        assert mover.update((0.0, 0.0, -5.0), DT).velocity[2] == pytest.approx(-4.0)

    def test_a_closed_course_goes_round_for_ever(self):
        course = oval()
        mover = PathMover(course, speed=12.0)
        worst = []
        end = drive(mover, course.point(0), 40.0,
                    watch=lambda p, step: worst.append(abs(step.lateral_error)))
        assert max(worst) < 0.1
        assert not mover.finished
        assert np.isfinite(end).all()

    def test_standing_still_asks_for_no_move(self):
        step = PathMover(straight(), speed=0.0).update((0.0, 0.0, -5.0), DT)
        assert step.velocity == (0.0, 0.0, 0.0)
        assert step.direction == (0.0, 0.0, 0.0)


class TestDegenerateCourses:
    def test_a_course_of_one_repeated_point_is_already_at_its_end(self):
        mover = PathMover(RoadCourse(np.zeros((2, 3))), speed=5.0)
        step = mover.update((0.0, 0.0, 0.0), DT)
        assert mover.finished
        assert step.direction == (0.0, 0.0, 0.0)

    def test_a_repeated_point_takes_the_direction_of_its_neighbour(self):
        line = np.array([[0, 0, 0], [0, 0, 0], [0, 0, -10.0], [0, 0, -20.0]])
        mover = PathMover(RoadCourse(line), speed=5.0)
        assert mover.update((0.0, 0.0, -2.0), DT).velocity == pytest.approx(
            (0.0, 0.0, -5.0))


class TestTheEndOfTheCourse:
    def test_an_open_course_ends(self):
        course = straight(length=50.0)
        mover = PathMover(course, speed=10.0)
        end = drive(mover, course.point(0), 8.0)
        assert mover.finished
        assert end[2] == pytest.approx(-50.0, abs=0.2)

    def test_a_finished_mover_asks_for_no_move(self):
        mover = PathMover(straight(length=50.0), speed=10.0)
        step = mover.update((0.0, 0.0, -50.0), DT)
        assert step.velocity == (0.0, 0.0, 0.0)
        assert mover.finished

    def test_restarting_is_possible(self):
        mover = PathMover(straight(length=50.0), speed=10.0)
        mover.update((0.0, 0.0, -50.0), DT)
        mover.reset()
        assert not mover.finished
        assert mover.update((0.0, 0.0, -5.0), DT).velocity[2] < 0


class TestLanes:
    def test_a_lane_is_a_lateral_offset_to_the_right_of_the_line(self):
        mover = PathMover(straight(), speed=10.0, lane=2.0)
        position = drive(mover, (2.0, 0.0, -5.0), 2.0)
        assert position[0] == pytest.approx(2.0, abs=0.05)

    def test_a_hop_of_one_lane_takes_sixteen_hundredths_of_a_second(self):
        mover = PathMover(straight(), speed=10.0)
        mover.hop_to(2.0, over=0.16)
        position = np.array([0.0, 0.0, -5.0])
        across = []
        for _ in range(int(0.5 / DT)):
            position = position + np.array(mover.update(position, DT).velocity) * DT
            across.append(position[0])

        def at(seconds):
            return across[round(seconds / DT) - 1]

        assert at(0.08) == pytest.approx(1.0, abs=0.1)
        assert at(0.16) == pytest.approx(2.0, abs=0.05)
        assert at(0.5) == pytest.approx(2.0, abs=0.05)
        assert at(0.04) < 0.4

    def test_it_is_hopping_until_the_hop_is_over(self):
        mover = PathMover(straight(), speed=10.0)
        mover.hop_to(2.0, over=0.16)
        assert mover.hopping
        position = np.array([0.0, 0.0, -5.0])
        for _ in range(int(0.1 / DT)):
            position = position + np.array(mover.update(position, DT).velocity) * DT
        assert mover.hopping
        for _ in range(int(0.1 / DT)):
            position = position + np.array(mover.update(position, DT).velocity) * DT
        assert not mover.hopping
        assert mover.lane == pytest.approx(2.0)

    def test_a_hop_on_a_bent_course_stays_on_its_lane(self):
        course = winding()
        mover = PathMover(course, speed=10.0)
        position = np.array(course.point(0))
        worst = []
        for frame in range(int(10.0 / DT)):
            if frame == int(3.0 / DT):
                mover.hop_to(2.0, over=0.16)
            step = mover.update(position, DT)
            position = position + np.array(step.velocity) * DT
            if frame > int(3.5 / DT):
                worst.append(abs(step.lateral_error - 2.0))
        assert max(worst) < 0.05

    def test_a_hop_back_starts_from_where_the_first_had_got_to(self):
        mover = PathMover(straight(), speed=10.0)
        mover.hop_to(2.0, over=0.2)
        position = np.array([0.0, 0.0, -5.0])
        for _ in range(int(0.1 / DT)):
            position = position + np.array(mover.update(position, DT).velocity) * DT
        halfway = mover.lane
        mover.hop_to(0.0, over=0.2)
        mover.update(position, DT)
        assert mover.lane == pytest.approx(halfway, abs=0.1)

    def test_a_hop_over_no_time_changes_lane_at_once(self):
        mover = PathMover(straight(), speed=10.0)
        mover.hop_to(2.0, over=0.0)
        mover.update((0.0, 0.0, -5.0), DT)
        assert mover.lane == pytest.approx(2.0)

    def test_no_time_passing_changes_nothing(self):
        mover = PathMover(straight(), speed=10.0)
        mover.hop_to(2.0, over=0.16)
        mover.update((0.0, 0.0, -5.0), 0.0)
        assert mover.lane == 0.0


def test_a_step_reads_as_a_record():
    step = PathMover(straight(), speed=10.0).update((0.0, 0.0, -5.0), DT)
    assert isinstance(step, PathStep)
    assert step.station == pytest.approx(5.0)
