"""What a right-drag, a wheel notch and a middle-drag do to the camera.

The three rules an examine gesture has to keep, and which the trackball this
replaces broke:

* **The same movement turns the same amount, wherever it starts.** The drag was
  measured against the distance from its start point to the edge of the window,
  a different divisor on each side, so a drag beginning near an edge turned
  nineteen times as far one way as the other.
* **The horizon stays where it was.** Rotating about the camera's own two axes
  composes into roll; two hundred pixels of diagonal drag left the world upside
  down.
* **The view does not jump when the button goes down.** The pivot is the point
  under the cursor, not the centre of the screen, so a camera swung to face it
  would snap.

See `plans/EXAMINE-NAVIGATION.md`.
"""
import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.move import orbit

WIDTH, HEIGHT = 800, 600


def _facing(position=(0.0, 0.0, 10.0), centre=(0.0, 0.0, 0.0), start=(400, 300),
            **named):
    """An orbit of ``centre`` from ``position``, already aimed at it."""
    return orbit.TurntableOrbit(
        np.array(tuple(position) + (1.0,), dtype='d'),
        orbit.aimAt(position, centre),
        centre, start[0], start[1], WIDTH, HEIGHT, **named)


def _direction(quat, local=(0.0, 0.0, -1.0)):
    """Where a camera orientation points, in world coordinates."""
    return np.asarray(quat * np.array(tuple(local) + (0.0,), dtype='d'),
                      dtype='d')[:3]


def _angleBetween(first, second):
    first = np.asarray(first, 'd') / np.linalg.norm(first)
    second = np.asarray(second, 'd') / np.linalg.norm(second)
    return np.degrees(np.arccos(np.clip(float(np.dot(first, second)), -1.0, 1.0)))


class TestAimingAtAPoint:
    """`aimAt` is the levelled look-at every gesture is built on."""

    def test_it_looks_at_the_point(self):
        quat = orbit.aimAt((0.0, 0.0, 10.0), (0.0, 0.0, 0.0))
        assert np.allclose(_direction(quat), [0.0, 0.0, -1.0], atol=1e-6)

    def test_it_looks_at_a_point_off_to_one_side(self):
        quat = orbit.aimAt((10.0, 4.0, 0.0), (0.0, 0.0, 0.0))
        assert _angleBetween(_direction(quat), [-10.0, -4.0, 0.0]) < 1e-4

    def test_the_horizon_is_level(self):
        """No roll: the camera's right axis lies in the horizontal plane."""
        quat = orbit.aimAt((6.0, 7.0, -8.0), (1.0, 0.0, 2.0))
        right = _direction(quat, (1.0, 0.0, 0.0))
        assert abs(float(np.dot(right, orbit.WORLD_UP))) < 1e-6

    def test_the_up_axis_is_upward(self):
        quat = orbit.aimAt((6.0, 7.0, -8.0), (1.0, 0.0, 2.0))
        assert float(np.dot(_direction(quat, (0.0, 1.0, 0.0)),
                            orbit.WORLD_UP)) > 0.0

    def test_looking_straight_down_still_gives_a_frame(self):
        """Degenerate for a look-at, and a camera still has to point somewhere."""
        quat = orbit.aimAt((0.0, 10.0, 0.0), (0.0, 0.0, 0.0))
        assert _angleBetween(_direction(quat), [0.0, -1.0, 0.0]) < 1e-4


class TestTheDragStartsWhereTheViewIs:
    def test_a_drag_that_has_not_moved_changes_nothing(self):
        made = _facing()
        position, quat = made.rotate(400, 300)
        assert np.allclose(np.asarray(position, 'd')[:3], [0.0, 0.0, 10.0])
        assert _angleBetween(_direction(quat), [0.0, 0.0, -1.0]) < 1e-6

    def test_a_camera_not_aimed_at_the_pivot_does_not_snap_to_it(self):
        """The pivot is what the cursor touched, which is rarely dead centre."""
        aside = quaternion.fromXYZR(0, 1, 0, -0.4)      # looking 23 degrees off
        made = orbit.TurntableOrbit(
            np.array([0.0, 0.0, 10.0, 1.0], 'd'), aside, (0.0, 0.0, 0.0),
            400, 300, WIDTH, HEIGHT)
        _position, quat = made.rotate(400, 300)
        assert _angleBetween(_direction(quat), _direction(aside)) < 1e-6

    def test_a_rolled_camera_aimed_off_the_pivot_is_handed_back_untouched(self):
        """Every part of the orientation, not just where it points."""
        awkward = (quaternion.fromXYZR(0, 1, 0, -0.4)
                   * quaternion.fromXYZR(0, 0, 1, 0.25))
        made = orbit.TurntableOrbit(
            np.array([2.0, 1.0, 10.0, 1.0], 'd'), awkward, (1.0, 0.0, 0.0),
            123, 45, WIDTH, HEIGHT)
        _position, quat = made.rotate(123, 45)
        for local in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)):
            assert _angleBetween(_direction(quat, local),
                                 _direction(awkward, local)) < 1e-4, local

    def test_the_aim_offset_is_carried_through_the_drag(self):
        aside = quaternion.fromXYZR(0, 1, 0, -0.4)
        made = orbit.TurntableOrbit(
            np.array([0.0, 0.0, 10.0, 1.0], 'd'), aside, (0.0, 0.0, 0.0),
            400, 300, WIDTH, HEIGHT)
        position, quat = made.rotate(500, 300)
        toPivot = np.asarray([0.0, 0.0, 0.0], 'd') - np.asarray(position, 'd')[:3]
        # Still the same angle off the pivot as it began: 0.4 radians.
        assert _angleBetween(_direction(quat), toPivot) == pytest.approx(
            np.degrees(0.4), abs=0.5)


class TestSensitivityIsUniform:
    """The defect that made the gesture unusable: where you started decided
    how far the same movement turned."""

    def _swing(self, start, delta):
        made = _facing(start=start)
        made.rotate(start[0] + delta[0], start[1] + delta[1])
        return abs(np.degrees(made.azimuth - made.startAzimuth))

    def test_the_same_movement_turns_the_same_amount_either_way(self):
        assert self._swing((400, 300), (50, 0)) == pytest.approx(
            self._swing((400, 300), (-50, 0)))

    def test_a_drag_beginning_near_an_edge_is_not_hypersensitive(self):
        near = self._swing((40, 300), (-30, 0))
        middle = self._swing((400, 300), (-30, 0))
        assert near == pytest.approx(middle), (
            'where the drag started decided how far it turned')

    def test_a_drag_the_height_of_the_window_is_half_a_turn(self):
        assert self._swing((400, 0), (0, 0)) == 0.0
        assert self._swing((400, 300), (HEIGHT, 0)) == pytest.approx(180.0)

    def test_the_two_axes_turn_at_the_same_rate(self):
        """A circular hand movement should trace a circular orbit."""
        made = _facing()
        made.rotate(400 + 100, 300)
        yaw = abs(made.azimuth - made.startAzimuth)
        made.rotate(400, 300 + 100)
        pitch = abs(made.elevation - made.startElevation)
        assert yaw == pytest.approx(pitch)


class TestWhichWayItTurns:
    """The sense the engine has always had, kept."""

    def test_dragging_right_swings_the_camera_left(self):
        made = _facing()
        position, _quat = made.rotate(450, 300)
        assert float(np.asarray(position, 'd')[0]) < 0.0

    def test_dragging_up_moves_the_camera_below_the_pivot(self):
        """Pick points count y upward, so a larger y is a drag upward."""
        made = _facing()
        position, _quat = made.rotate(400, 350)
        assert float(np.asarray(position, 'd')[1]) < 0.0


class TestTheHorizonStaysLevel:
    def test_a_diagonal_drag_does_not_roll_the_world(self):
        made = _facing()
        _position, quat = made.rotate(600, 500)
        right = _direction(quat, (1.0, 0.0, 0.0))
        assert abs(float(np.dot(right, orbit.WORLD_UP))) < 1e-6

    def test_a_pivot_off_to_one_side_does_not_tilt_it_either(self):
        """The case a level horizon is easiest to lose: the camera is aimed at
        the middle of the screen and the pivot is what the cursor touched, off
        to one side. Carrying the whole leftover rotation onto each new frame
        tilts the world a little every step, and a few drags of that is
        visible."""
        made = orbit.TurntableOrbit(
            np.array([0.0, 0.0, 10.0, 1.0], 'd'),
            orbit.aimAt((0.0, 0.0, 10.0), (0.0, 0.0, 0.0)),
            (1.4, 1.4, 1.0), 460, 340, WIDTH, HEIGHT)
        _position, quat = made.rotate(560, 400)
        right = _direction(quat, (1.0, 0.0, 0.0))
        assert abs(float(np.dot(right, orbit.WORLD_UP))) < 1e-6

    def test_a_camera_that_was_rolled_keeps_its_roll(self):
        """Levelling is not the gesture's to impose: a viewer who tilted the
        horizon on purpose keeps the tilt."""
        rolled = orbit.aimAt((0.0, 0.0, 10.0), (0.0, 0.0, 0.0)) \
            * quaternion.fromXYZR(0, 0, 1, 0.3)
        made = orbit.TurntableOrbit(
            np.array([0.0, 0.0, 10.0, 1.0], 'd'), rolled, (0.0, 0.0, 0.0),
            400, 300, WIDTH, HEIGHT)
        before = _direction(rolled, (1.0, 0.0, 0.0))
        _position, quat = made.rotate(500, 300)
        after = _direction(quat, (1.0, 0.0, 0.0))
        assert float(np.dot(after, orbit.WORLD_UP)) == pytest.approx(
            float(np.dot(before, orbit.WORLD_UP)), abs=1e-6)

    def test_the_camera_is_never_upside_down(self):
        made = _facing()
        for point in ((500, 400), (600, 500), (750, 590), (100, 20)):
            _position, quat = made.rotate(*point)
            assert float(np.dot(_direction(quat, (0.0, 1.0, 0.0)),
                                orbit.WORLD_UP)) > 0.0, point


class TestThePoles:
    def test_dragging_past_the_top_stops_at_the_top(self):
        made = _facing()
        position, _quat = made.rotate(400, 300 - 10 * HEIGHT)
        offset = np.asarray(position, 'd')[:3]
        elevation = np.degrees(np.arcsin(offset[1] / np.linalg.norm(offset)))
        assert elevation == pytest.approx(np.degrees(orbit.ELEVATION_LIMIT),
                                          abs=0.01)

    def test_dragging_past_the_bottom_stops_at_the_bottom(self):
        made = _facing()
        position, _quat = made.rotate(400, 300 + 10 * HEIGHT)
        offset = np.asarray(position, 'd')[:3]
        elevation = np.degrees(np.arcsin(offset[1] / np.linalg.norm(offset)))
        assert elevation == pytest.approx(-np.degrees(orbit.ELEVATION_LIMIT),
                                          abs=0.01)

    def test_the_limit_is_short_of_the_pole(self):
        assert orbit.ELEVATION_LIMIT < np.pi / 2.0


class TestItIsAnOrbit:
    def test_the_distance_to_the_pivot_never_changes(self):
        made = _facing(position=(3.0, 4.0, 12.0), centre=(1.0, 0.0, 2.0))
        before = np.linalg.norm(np.array([3.0, 4.0, 12.0]) - np.array([1.0, 0.0, 2.0]))
        for point in ((500, 400), (200, 100), (799, 599)):
            position, _quat = made.rotate(*point)
            after = np.linalg.norm(np.asarray(position, 'd')[:3]
                                   - np.array([1.0, 0.0, 2.0]))
            assert after == pytest.approx(before, abs=1e-9), point

    def test_a_drag_and_a_drag_back_returns_to_the_start(self):
        """Every update is measured from the drag's origin, not the last frame,
        so nothing accumulates."""
        made = _facing()
        made.rotate(700, 500)
        position, quat = made.rotate(400, 300)
        assert np.allclose(np.asarray(position, 'd')[:3], [0.0, 0.0, 10.0],
                           atol=1e-9)
        assert _angleBetween(_direction(quat), [0.0, 0.0, -1.0]) < 1e-6

    def test_the_pivot_stays_where_it_is(self):
        made = _facing()
        made.rotate(600, 200)
        assert np.allclose(made.centre[:3], [0.0, 0.0, 0.0])


class TestDolly:
    def test_a_notch_toward_the_pivot_halves_nothing_and_moves_closer(self):
        made = _facing()
        position, _quat = made.dolly(0.8)
        assert np.linalg.norm(np.asarray(position, 'd')[:3]) == pytest.approx(8.0)

    def test_a_notch_away_moves_back(self):
        made = _facing()
        position, _quat = made.dolly(1.25)
        assert np.linalg.norm(np.asarray(position, 'd')[:3]) == pytest.approx(12.5)

    def test_it_stays_on_the_line_to_the_pivot(self):
        made = _facing(position=(3.0, 4.0, 12.0), centre=(1.0, 0.0, 2.0))
        position, _quat = made.dolly(0.5)
        before = np.array([3.0, 4.0, 12.0]) - np.array([1.0, 0.0, 2.0])
        after = np.asarray(position, 'd')[:3] - np.array([1.0, 0.0, 2.0])
        assert _angleBetween(before, after) < 1e-9

    def test_it_never_arrives_at_the_pivot(self):
        """Dollying through the pivot leaves the camera inside the thing it was
        looking at, with nothing left to orbit."""
        made = _facing(minimumRadius=0.5)
        for _ in range(50):
            made.dolly(0.5)
        assert made.radius >= 0.5

    def test_a_dolly_and_then_a_drag_orbits_at_the_new_distance(self):
        made = _facing()
        made.dolly(0.5)
        position, _quat = made.rotate(500, 300)
        assert np.linalg.norm(np.asarray(position, 'd')[:3]) == pytest.approx(5.0)


class TestPan:
    def test_dragging_right_carries_the_scene_right(self):
        """So the camera goes left."""
        made = _facing()
        position, _quat = made.pan(450, 300)
        assert float(np.asarray(position, 'd')[0]) < 0.0

    def test_dragging_up_carries_the_scene_up(self):
        made = _facing()
        position, _quat = made.pan(400, 350)
        assert float(np.asarray(position, 'd')[1]) < 0.0

    def test_the_pivot_travels_with_the_camera(self):
        made = _facing()
        position, _quat = made.pan(450, 380)
        moved = np.asarray(position, 'd')[:3] - np.array([0.0, 0.0, 10.0])
        assert np.allclose(made.centre[:3], moved, atol=1e-9)

    def test_the_view_does_not_turn(self):
        made = _facing()
        _position, quat = made.pan(450, 380)
        assert _angleBetween(_direction(quat), [0.0, 0.0, -1.0]) < 1e-6

    def test_the_point_under_the_cursor_keeps_up_with_it(self):
        """A pan that lags the pointer feels broken; the scale comes from the
        distance to the pivot and the field of view."""
        made = _facing(fieldOfView=np.pi / 3.0)
        position, _quat = made.pan(400 + HEIGHT // 2, 300)
        # Half the window's height of movement, at the pivot's depth, is
        # radius * tan(fov/2) of world.
        expected = 10.0 * np.tan(np.pi / 6.0)
        assert float(np.asarray(position, 'd')[0]) == pytest.approx(-expected,
                                                                   rel=1e-6)

    def test_further_away_pans_further(self):
        near = _facing(position=(0.0, 0.0, 4.0))
        far = _facing(position=(0.0, 0.0, 40.0))
        assert (abs(float(np.asarray(far.pan(450, 300)[0], 'd')[0]))
                > abs(float(np.asarray(near.pan(450, 300)[0], 'd')[0])))


class TestDegenerateInput:
    def test_a_camera_standing_on_the_pivot_does_not_divide_by_zero(self):
        made = orbit.TurntableOrbit(
            np.array([1.0, 2.0, 3.0, 1.0], 'd'),
            quaternion.fromXYZR(0, 1, 0, 0.0), (1.0, 2.0, 3.0),
            400, 300, WIDTH, HEIGHT)
        position, quat = made.rotate(500, 400)
        assert np.all(np.isfinite(np.asarray(position, 'd')))
        assert np.all(np.isfinite(np.asarray(list(quat), 'd')))

    def test_a_window_with_no_height_does_not_divide_by_zero(self):
        made = orbit.TurntableOrbit(
            np.array([0.0, 0.0, 10.0, 1.0], 'd'),
            quaternion.fromXYZR(0, 1, 0, 0.0), (0.0, 0.0, 0.0),
            0, 0, 0, 0)
        position, _quat = made.rotate(5, 5)
        assert np.all(np.isfinite(np.asarray(position, 'd')))

    def test_a_camera_directly_above_the_pivot_can_still_be_orbited(self):
        made = _facing(position=(0.0, 10.0, 0.0))
        position, _quat = made.rotate(500, 300)
        assert np.all(np.isfinite(np.asarray(position, 'd')))
        assert np.linalg.norm(np.asarray(position, 'd')[:3]) == pytest.approx(10.0)


class TestCancelling:
    def test_it_gives_back_exactly_what_it_was_handed(self):
        start = np.array([3.0, 4.0, 12.0, 1.0], 'd')
        facing = quaternion.fromXYZR(0, 1, 0, 0.3)
        made = orbit.TurntableOrbit(start, facing, (1.0, 0.0, 2.0),
                                    400, 300, WIDTH, HEIGHT)
        made.rotate(700, 100)
        made.dolly(0.25)
        position, quat = made.cancel()
        assert np.allclose(np.asarray(position, 'd'), start)
        assert quat is facing


class TestTheDragMeasureItself:
    """`DragWatcher.uniformFractions` is the symmetric measure the orbit and the
    trackball share."""

    def test_the_same_movement_measures_the_same_either_way(self):
        from OpenGLContext.move.dragwatcher import DragWatcher
        watcher = DragWatcher(40, 300, WIDTH, HEIGHT)
        left = watcher.uniformFractions(10, 300)
        right = watcher.uniformFractions(70, 300)
        assert left[0] == pytest.approx(-right[0])

    def test_it_measures_against_the_whole_window(self):
        from OpenGLContext.move.dragwatcher import DragWatcher
        watcher = DragWatcher(0, 0, WIDTH, HEIGHT)
        assert watcher.uniformFractions(WIDTH, HEIGHT) == pytest.approx(
            (1.0, 1.0))

    def test_no_movement_is_no_fraction(self):
        from OpenGLContext.move.dragwatcher import DragWatcher
        watcher = DragWatcher(123, 45, WIDTH, HEIGHT)
        assert watcher.uniformFractions(123, 45) == (0.0, 0.0)

    def test_a_window_with_no_size_does_not_divide_by_zero(self):
        from OpenGLContext.move.dragwatcher import DragWatcher
        watcher = DragWatcher(0, 0, 0, 0)
        assert watcher.uniformFractions(10, 10) == (0.0, 0.0)


class TestTheTrackballIsSymmetricToo:
    """The arcball stays as a customisation point, and its drag measure was as
    lopsided as the orbit's was."""

    def _swing(self, start, delta):
        from OpenGLContext.move.trackball import Trackball
        facing = quaternion.fromXYZR(0, 1, 0, 0.0)
        made = Trackball(np.array([0.0, 0.0, 10.0, 1.0], 'd'), facing,
                         (0.0, 0.0, 0.0), start[0], start[1], WIDTH, HEIGHT,
                         dragAngle=np.pi)
        _position, turned = made.rotate(start[0] + delta[0], start[1] + delta[1])
        return 2.0 * np.degrees(np.arccos(min(1.0, abs(float(np.dot(
            np.asarray(list(facing), 'd'), np.asarray(list(turned), 'd')))))))

    def test_a_drag_beginning_near_an_edge_is_not_hypersensitive(self):
        assert self._swing((40, 300), (-30, 0)) == pytest.approx(
            self._swing((400, 300), (-30, 0)))

    def test_it_still_answers_to_update(self):
        """The name the manager called it by before."""
        from OpenGLContext.move.trackball import Trackball
        assert Trackball.update is Trackball.rotate
