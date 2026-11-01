"""Unit tests for the fixed-offset follow camera (:mod:`OpenGLContext.move.followcam`).

The follow camera has one job: sit at a fixed offset from a moving target and look
at it, with no user control.  It also supports *holding* — freezing on the last
target — which the marble demo uses to keep the view on the square a marble fell
from while it respawns.

The look-at orientation is validated **end-to-end through the real view path**:
feed it to a ``ViewPlatform`` and check where the target lands in view space via
``ViewPlatform.modelMatrix`` (the core-profile world→view transform, row-vector
convention).  A correctly-aimed camera puts the target on the view -Z axis,
centered (x≈0, y≈0, z<0).  Testing the actual consumer, not an assumed quaternion
convention, is what catches aim bugs the renderer would show.
"""
import numpy as np
import pytest

from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.move.followcam import (
    look_at_orientation, FollowCamera, _matrix_to_axis_angle)


def _axis_angle_matrix(axis, angle):
    """Rodrigues rotation matrix for ``angle`` radians about a unit ``axis``."""
    axis = np.asarray(axis, dtype='d')
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c, s = np.cos(angle), np.sin(angle)
    k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + s * k + (1 - c) * (k @ k)


def test_identity_rotation_returns_zero_angle():
    """A near-identity matrix maps to the canonical zero-angle axis-angle."""
    x, y, z, angle = _matrix_to_axis_angle(np.eye(3))
    assert (x, y, z) == (0.0, 1.0, 0.0)
    assert angle == 0.0


def test_180_degree_rotation_recovers_axis_from_diagonal():
    """At exactly pi the axis comes from the diagonal (the off-diagonal form is degenerate)."""
    for axis in [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 1, 1)]:
        x, y, z, angle = _matrix_to_axis_angle(_axis_angle_matrix(axis, np.pi))
        assert angle == pytest.approx(np.pi, abs=1e-6)
        recovered = np.array([x, y, z])
        want = np.asarray(axis, dtype='d')
        want = want / np.linalg.norm(want)
        # axis sign is free at 180 degrees, so compare up to a flip
        assert np.allclose(recovered, want, atol=1e-6) or \
            np.allclose(recovered, -want, atol=1e-6)


def test_general_rotation_axis_and_angle_roundtrip():
    """A mid-range rotation recovers both its axis and angle."""
    axis, angle = (0.3, -0.7, 0.4), 0.9
    x, y, z, got = _matrix_to_axis_angle(_axis_angle_matrix(axis, angle))
    assert got == pytest.approx(angle, abs=1e-9)
    want = np.asarray(axis, dtype='d')
    want = want / np.linalg.norm(want)
    assert np.allclose((x, y, z), want, atol=1e-9)


def _target_in_view_space(eye, target, up=(0.0, 1.0, 0.0)):
    """Where ``target`` lands in the camera's view space for a look-at at ``eye``."""
    platform = ViewPlatform()
    platform.setPosition(tuple(eye))
    platform.setOrientation(look_at_orientation(eye, target, up))
    homogeneous = np.array([target[0], target[1], target[2], 1.0])
    return (homogeneous @ platform.modelMatrix(inverse=False))[:3]


def test_look_at_puts_target_centered_and_in_front():
    view = _target_in_view_space((0.0, 10.0, 10.0), (0.0, 0.0, 0.0))
    assert abs(view[0]) < 1e-6 and abs(view[1]) < 1e-6   # centered
    assert view[2] < 0                                   # in front of the camera


def test_look_at_from_the_side_stays_centered():
    view = _target_in_view_space((14.0, 8.0, 0.0), (2.0, 1.0, -3.0))
    assert abs(view[0]) < 1e-6 and abs(view[1]) < 1e-6
    assert view[2] < 0


def test_look_straight_down_puts_target_in_front():
    view = _target_in_view_space((0, 20, 0), (0, 0, 0), up=(0, 0, -1))
    assert abs(view[0]) < 1e-6 and abs(view[1]) < 1e-6
    assert view[2] < 0


class _FakePlatform:
    def __init__(self):
        self.position = None
        self.orientation = None

    def setPosition(self, position):
        self.position = np.asarray(position, dtype='d')[:3]

    def setOrientation(self, orientation):
        self.orientation = orientation


def test_apply_places_eye_at_target_plus_offset():
    plat = _FakePlatform()
    cam = FollowCamera(plat, offset=(0.0, 12.0, 12.0))
    cam.target((5.0, 0.0, -3.0))
    cam.apply()
    assert np.allclose(plat.position, (5.0, 12.0, 9.0))


def test_apply_looks_at_the_target():
    plat = ViewPlatform()
    cam = FollowCamera(plat, offset=(0.0, 12.0, 12.0))
    target = (5.0, 0.0, -3.0)
    cam.target(target)
    cam.apply()
    homogeneous = np.array([target[0], target[1], target[2], 1.0])
    view = (homogeneous @ plat.modelMatrix(inverse=False))[:3]
    assert abs(view[0]) < 1e-6 and abs(view[1]) < 1e-6   # target centered
    assert view[2] < 0                                   # in front


def test_hold_freezes_the_target_until_release():
    plat = _FakePlatform()
    cam = FollowCamera(plat, offset=(0.0, 10.0, 0.0))
    cam.target((0.0, 0.0, 0.0))
    cam.apply()
    held_eye = plat.position.copy()

    cam.hold()
    cam.target((100.0, -50.0, 0.0))     # marble has fallen far away
    cam.apply()
    assert np.allclose(plat.position, held_eye)   # camera stayed put

    cam.release()
    cam.apply()
    assert np.allclose(plat.position, (100.0, -40.0, 0.0))  # follows again


def test_is_holding_reports_state():
    cam = FollowCamera(_FakePlatform(), offset=(0, 5, 5))
    assert not cam.is_holding
    cam.hold()
    assert cam.is_holding
    cam.release()
    assert not cam.is_holding


# -- speed-scaled follow distance ----------------------------------------------
#
# A chase camera that sits at one distance shows the same amount of world at
# every speed, which is least useful exactly when the player is moving fastest.
# `pull_back` eases the camera outward as the target speeds up.

def _pull_back_camera(**named):
    named.setdefault('offset', (0.0, 12.0, 12.0))
    named.setdefault('pull_back', 0.5)
    named.setdefault('pull_back_speed', 10.0)
    return FollowCamera(_FakePlatform(), **named)


def test_a_camera_with_no_pull_back_never_moves_its_offset():
    """The default is the fixed-offset camera, unchanged by advancing it."""
    cam = FollowCamera(_FakePlatform(), offset=(0.0, 12.0, 12.0))
    cam.target((0.0, 0.0, 0.0))
    for _ in range(200):
        cam.advance(1 / 60.0, speed=1000.0)
    cam.apply()
    assert cam.distance_scale == 1.0
    assert np.allclose(cam.platform.position, (0.0, 12.0, 12.0))


def test_a_standing_target_is_watched_from_the_base_offset():
    cam = _pull_back_camera()
    cam.target((0.0, 0.0, 0.0))
    for _ in range(200):
        cam.advance(1 / 60.0, speed=0.0)
    assert cam.distance_scale == pytest.approx(1.0, abs=1e-3)


def test_a_target_at_full_speed_is_watched_from_the_pulled_back_offset():
    cam = _pull_back_camera()
    cam.target((0.0, 0.0, 0.0))
    for _ in range(400):
        cam.advance(1 / 60.0, speed=10.0)
    assert cam.distance_scale == pytest.approx(1.5, abs=1e-3)
    cam.apply()
    assert np.allclose(cam.platform.position, (0.0, 18.0, 18.0))


def test_beyond_full_speed_the_camera_stops_pulling_back():
    """The scale is a ramp to a limit, not an unbounded function of speed."""
    cam = _pull_back_camera()
    for _ in range(400):
        cam.advance(1 / 60.0, speed=1000.0)
    assert cam.distance_scale == pytest.approx(1.5, abs=1e-3)


def test_half_speed_asks_for_half_the_pull_back():
    cam = _pull_back_camera()
    for _ in range(400):
        cam.advance(1 / 60.0, speed=5.0)
    assert cam.distance_scale == pytest.approx(1.25, abs=1e-3)


def test_the_camera_eases_rather_than_jumping_to_the_new_distance():
    """One frame moves part of the way, so a speed spike does not snap the view."""
    cam = _pull_back_camera(pull_back_rate=3.0)
    cam.advance(1 / 60.0, speed=10.0)
    assert 1.0 < cam.distance_scale < 1.1


def test_the_eased_distance_does_not_depend_on_the_frame_rate():
    """Same elapsed time, different step sizes, same distance -- within a hair.

    A camera whose framing depended on how fast the machine ran would frame the
    same run differently on two machines.
    """
    slow = _pull_back_camera()
    fast = _pull_back_camera()
    for _ in range(30):
        slow.advance(1 / 30.0, speed=10.0)
    for _ in range(120):
        fast.advance(1 / 120.0, speed=10.0)
    assert slow.distance_scale == pytest.approx(fast.distance_scale, abs=1e-3)


def test_pulling_back_keeps_looking_at_the_target():
    cam = FollowCamera(ViewPlatform(), offset=(0.0, 12.0, 12.0),
                       pull_back=0.5, pull_back_speed=10.0)
    target = (5.0, 0.0, -3.0)
    cam.target(target)
    for _ in range(400):
        cam.advance(1 / 60.0, speed=10.0)
    cam.apply()
    homogeneous = np.array([target[0], target[1], target[2], 1.0])
    view = (homogeneous @ cam.platform.modelMatrix(inverse=False))[:3]
    assert abs(view[0]) < 1e-6 and abs(view[1]) < 1e-6
    assert view[2] < 0


def test_a_zero_length_step_leaves_the_distance_alone():
    """Called with dt=0 (a paused frame) the camera holds where it is."""
    cam = _pull_back_camera()
    cam.advance(1 / 60.0, speed=10.0)
    settled = cam.distance_scale
    cam.advance(0.0, speed=10.0)
    assert cam.distance_scale == settled


# -- look-ahead, damped following and not standing inside the scenery -----------
#
# A third-person camera looks a little ahead of the target, follows it with a
# damped glide, and keeps its arm out of the walls: the three things a chase
# camera adds to a fixed offset. Each is off by default.

def _frame(cam, dt=1 / 60.0, speed=0.0):
    cam.advance(dt, speed)
    cam.apply()
    return np.array(cam.platform.position)


def _wall_behind(z, radius_free=True):
    """A sweep that meets a wall across the plane ``z`` and reports the hit."""
    calls = []

    def sweep(origin, direction, distance, radius):
        calls.append((np.array(origin), np.array(direction), distance, radius))
        if direction[2] <= 1e-9:
            return None
        hit = (z - radius - origin[2]) / direction[2]
        return hit if 0.0 <= hit < distance else None

    sweep.calls = calls
    return sweep


class TestLookAhead:
    def test_the_view_is_centred_ahead_of_a_moving_target(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 4.0, 8.0), look_ahead=0.5)
        cam.target((0.0, 0.0, 0.0), velocity=(0.0, 0.0, -10.0))
        _frame(cam)
        assert np.allclose(cam.look, (0.0, 0.0, -5.0))
        assert np.allclose(cam.platform.position, (0.0, 4.0, 3.0))

    def test_the_velocity_is_worked_out_from_where_the_target_has_been(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 4.0, 8.0), look_ahead=0.5)
        cam.target((0.0, 0.0, 0.0))
        _frame(cam, dt=0.1)
        cam.target((0.0, 0.0, -1.0))
        _frame(cam, dt=0.1)
        assert np.allclose(cam.look, (0.0, 0.0, -1.0 - 5.0))

    def test_a_held_camera_does_not_look_ahead(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 4.0, 8.0), look_ahead=0.5)
        cam.target((0.0, 0.0, 0.0), velocity=(0.0, 0.0, -10.0))
        cam.hold()
        _frame(cam)
        assert np.allclose(cam.look, (0.0, 0.0, 0.0))

    def test_no_look_ahead_looks_at_the_target(self):
        cam = FollowCamera(_FakePlatform())
        cam.target((1.0, 2.0, 3.0), velocity=(0.0, 0.0, -10.0))
        _frame(cam)
        assert np.allclose(cam.look, (1.0, 2.0, 3.0))


class TestSmoothFollowing:
    def _step_response(self, dt, seconds, smooth_time=0.5):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0),
                           smooth_time=smooth_time)
        cam.target((0.0, 0.0, 0.0))
        _frame(cam, dt)
        cam.target((10.0, 0.0, 0.0))
        trace = [_frame(cam, dt)[0] for _ in range(int(seconds / dt))]
        return np.array(trace)

    def test_the_camera_glides_to_a_target_that_jumps(self):
        trace = self._step_response(1 / 60, 0.5)
        assert 0.0 < trace[0] < 1.0
        assert 5.0 < trace[-1] < 9.9

    def test_it_settles_on_the_target(self):
        assert self._step_response(1 / 60, 4.0)[-1] == pytest.approx(10.0, abs=0.01)

    def test_it_never_overshoots(self):
        trace = self._step_response(1 / 60, 4.0)
        assert trace.max() <= 10.0 + 1e-9
        assert np.all(np.diff(trace) >= -1e-9)

    def test_the_glide_does_not_depend_on_the_frame_rate(self):
        slow = self._step_response(1 / 30, 1.0)[-1]
        fast = self._step_response(1 / 240, 1.0)[-1]
        assert slow == pytest.approx(fast, abs=0.1)

    def test_the_first_frame_is_where_the_target_is(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0), smooth_time=0.5)
        cam.target((7.0, 0.0, 0.0))
        assert _frame(cam)[0] == pytest.approx(7.0)

    def test_snapping_puts_it_on_the_target_at_once(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0), smooth_time=0.5)
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        cam.target((100.0, 0.0, 0.0))
        cam.snap()
        assert _frame(cam)[0] == pytest.approx(100.0)

    def test_snapped_onto_a_moving_target_it_holds_its_place_from_the_first_frame(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0), look_ahead=0.15,
                           smooth_time=0.15)
        place = 0.0
        cam.target((place, 0.0, 0.0), velocity=(24.0, 0.0, 0.0))
        cam.snap()
        for _ in range(30):
            assert cam.look[0] == pytest.approx(place, abs=1e-6)
            place += 24.0 / 60.0
            cam.target((place, 0.0, 0.0), velocity=(24.0, 0.0, 0.0))
            _frame(cam)

    @pytest.mark.parametrize('fps', [30.0, 60.0, 144.0])
    def test_looking_ahead_by_the_glide_time_looks_at_a_steadily_moving_target(self, fps):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0), look_ahead=0.25,
                           smooth_time=0.25)
        place = 0.0
        cam.target((place, 0.0, 0.0), velocity=(10.0, 0.0, 0.0))
        _frame(cam, dt=0.0)
        for _ in range(int(fps * 2)):
            place += 10.0 / fps
            cam.target((place, 0.0, 0.0), velocity=(10.0, 0.0, 0.0))
            _frame(cam, dt=1.0 / fps)
        assert cam.look[0] == pytest.approx(place, abs=0.01)

    def test_a_stopped_clock_leaves_the_camera_where_it_is(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0), smooth_time=0.5)
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        cam.target((10.0, 0.0, 0.0))
        assert _frame(cam, dt=0.0)[0] == pytest.approx(0.0)


class TestAvoidingTheWorld:
    """The arm shortens to the first hit and eases back out."""

    OFFSET = (0.0, 0.0, 8.0)

    def _camera(self, wall_z, **named):
        named.setdefault('avoid_radius', 0.5)
        named.setdefault('min_arm', 0.0)
        return FollowCamera(_FakePlatform(), offset=self.OFFSET,
                            sweep=_wall_behind(wall_z), **named)

    def _walk_at_the_wall(self, cam, start, stop, speed=4.0, dt=1 / 60.0):
        """The target backs toward +z, then away again, as the camera trails."""
        z, arms, steps, previous = start, [], [], None
        sign = 1.0
        while True:
            cam.target((0.0, 0.0, z))
            eye = _frame(cam, dt)
            arms.append(float(np.linalg.norm(eye - cam.look)))
            if previous is not None:
                steps.append(float(np.linalg.norm(eye - previous)))
            previous = eye
            z += sign * speed * dt
            if sign > 0 and z >= stop:
                sign = -1.0
            if sign < 0 and z <= start:
                return arms, steps

    def test_what_lies_between_the_subject_and_the_look_point_does_not_pull_the_camera_in(self):
        # A log across the path 2 m ahead of the runner, between it and the point looked at 3 m
        # ahead: the camera stays where it stands, behind the runner.
        cam = self._camera(wall_z=-2.0, min_arm=2.0)
        cam.target((0.0, 0.0, -3.0), subject=(0.0, 0.0, 0.0))
        eye = _frame(cam)
        assert eye[2] == pytest.approx(5.0)

    def test_the_camera_stays_behind_the_subject_by_the_shortest_arm(self):
        # A wall right behind the runner: the camera comes in to it, and no nearer the runner than
        # the shortest arm.
        cam = self._camera(wall_z=0.5, min_arm=1.5)
        cam.target((0.0, 0.0, -3.0), subject=(0.0, 0.0, 0.0))
        eye = _frame(cam)
        assert eye[2] == pytest.approx(1.5)

    def test_by_default_the_subject_is_the_target_and_not_the_point_looked_ahead_to(self):
        cam = self._camera(wall_z=-2.0, min_arm=1.0, look_ahead=0.3)
        cam.target((0.0, 0.0, 0.0), velocity=(0.0, 0.0, -10.0))
        eye = _frame(cam)
        assert eye[2] == pytest.approx(5.0)

    def test_the_arm_comes_in_to_the_hit_and_out_again(self):
        cam = self._camera(wall_z=6.0)
        arms, _ = self._walk_at_the_wall(cam, start=-4.0, stop=3.0)
        assert arms[0] == pytest.approx(8.0)
        assert min(arms) == pytest.approx(2.5, abs=0.1)
        assert arms[-1] == pytest.approx(8.0, abs=0.3)

    def test_the_camera_is_never_inside_the_wall(self):
        cam = self._camera(wall_z=6.0)
        z = 0.0
        for _ in range(240):
            cam.target((0.0, 0.0, z))
            eye = _frame(cam, 1 / 60.0)
            assert eye[2] <= 6.0 - 0.5 + 1e-6
            z += 0.02

    def test_the_arm_stops_at_the_hit(self):
        cam = self._camera(wall_z=6.0)
        cam.target((0.0, 0.0, 0.0))
        eye = _frame(cam)
        assert eye[2] == pytest.approx(5.5)

    def test_the_sweep_is_asked_from_the_look_point_toward_the_camera(self):
        cam = self._camera(wall_z=6.0)
        cam.target((1.0, 2.0, 3.0))
        _frame(cam)
        origin, direction, distance, radius = cam.sweep.calls[-1]
        assert np.allclose(origin, (1.0, 2.0, 3.0))
        assert np.allclose(direction, (0.0, 0.0, 1.0))
        assert (distance, radius) == (8.0, 0.5)

    def test_it_eases_back_out_rather_than_snapping(self):
        cam = self._camera(wall_z=6.0, arm_ease=4.0)
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        cam.target((0.0, 0.0, -20.0))
        first = _frame(cam, 1 / 60.0)
        assert float(np.linalg.norm(first - cam.look)) < 8.0
        for _ in range(240):
            last = _frame(cam, 1 / 60.0)
        assert float(np.linalg.norm(last - cam.look)) == pytest.approx(8.0, abs=0.01)

    def test_it_comes_no_nearer_than_the_minimum_arm(self):
        cam = self._camera(wall_z=1.0, min_arm=1.5)
        cam.target((0.0, 0.0, 0.0))
        assert float(np.linalg.norm(_frame(cam) - cam.look)) == pytest.approx(1.5)

    def test_a_clear_view_keeps_the_whole_arm(self):
        cam = self._camera(wall_z=100.0)
        cam.target((0.0, 0.0, 0.0))
        assert _frame(cam)[2] == pytest.approx(8.0)

    def test_pulling_back_is_not_slowed_by_the_easing(self):
        cam = FollowCamera(_FakePlatform(), offset=self.OFFSET,
                           sweep=_wall_behind(100.0), pull_back=0.5,
                           pull_back_speed=10.0, pull_back_rate=1000.0)
        cam.target((0.0, 0.0, 0.0))
        for _ in range(5):
            _frame(cam, 1 / 60.0, speed=10.0)
        assert _frame(cam, 1 / 60.0, speed=10.0)[2] == pytest.approx(12.0, abs=0.01)

    def test_no_frame_steps_further_than_max_step(self):
        cam = self._camera(wall_z=6.0, max_step=0.1)
        _, steps = self._walk_at_the_wall(cam, start=-4.0, stop=3.0)
        assert max(steps) <= 0.1 + 1e-9

    def test_the_camera_still_looks_at_the_look_point(self):
        cam = FollowCamera(ViewPlatform(), offset=self.OFFSET,
                           sweep=_wall_behind(6.0), min_arm=0.0)
        cam.target((0.0, 1.0, 0.0))
        cam.advance(1 / 60.0)
        cam.apply()
        homogeneous = np.array([0.0, 1.0, 0.0, 1.0])
        view = (homogeneous @ cam.platform.modelMatrix(inverse=False))[:3]
        assert abs(view[0]) < 1e-6 and abs(view[1]) < 1e-6
        assert view[2] < 0


class TestMaxStep:
    def test_a_camera_that_is_told_to_jump_is_held_to_the_step(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0), max_step=0.25)
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        cam.target((10.0, 0.0, 0.0))
        assert _frame(cam)[0] == pytest.approx(0.25)

    def test_snapping_is_not_a_step(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0), max_step=0.25)
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        cam.target((10.0, 0.0, 0.0))
        cam.snap()
        assert _frame(cam)[0] == pytest.approx(10.0)


class TestConstraints:
    def test_a_constraint_may_move_the_camera(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 4.0, 8.0))
        cam.constrain(lambda eye, look: (eye + np.array([2.0, 0.0, 0.0]), look))
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        assert np.allclose(cam.platform.position, (2.0, 4.0, 8.0))

    def test_a_constraint_may_move_what_it_looks_at(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 4.0, 8.0))
        cam.constrain(lambda eye, look: (eye, look + np.array([0.0, 1.0, 0.0])))
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        assert np.allclose(cam.look, (0.0, 1.0, 0.0))

    def test_constraints_apply_in_the_order_given(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0))
        cam.constrain(lambda eye, look: (eye + 1.0, look))
        cam.constrain(lambda eye, look: (eye * 2.0, look))
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        assert np.allclose(cam.platform.position, (2.0, 2.0, 2.0))

    def test_the_sweep_is_made_after_the_constraints(self):
        sweep = _wall_behind(100.0)
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 8.0), sweep=sweep)
        cam.constrain(lambda eye, look: (eye + np.array([0.0, 0.0, 4.0]), look))
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        assert sweep.calls[-1][2] == pytest.approx(12.0)

    def test_a_constraint_can_be_taken_away(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 0.0, 0.0))
        rule = cam.constrain(lambda eye, look: (eye + 1.0, look))
        cam.unconstrain(rule)
        cam.target((0.0, 0.0, 0.0))
        _frame(cam)
        assert np.allclose(cam.platform.position, (0.0, 0.0, 0.0))


class TestThePoseBeforeAnyFrame:
    def test_applying_without_advancing_solves_the_current_target(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 4.0, 8.0), look_ahead=0.5)
        cam.target((0.0, 0.0, 0.0), velocity=(0.0, 0.0, -10.0))
        cam.apply()
        assert np.allclose(cam.platform.position, (0.0, 4.0, 3.0))

    def test_with_no_features_the_newest_target_is_always_used(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 4.0, 8.0))
        cam.target((0.0, 0.0, 0.0))
        cam.advance(1 / 60.0)
        cam.target((5.0, 0.0, 0.0))
        cam.apply()
        assert np.allclose(cam.platform.position, (5.0, 4.0, 8.0))

    def test_the_eye_and_look_point_are_readable(self):
        cam = FollowCamera(_FakePlatform(), offset=(0.0, 4.0, 8.0))
        cam.target((1.0, 0.0, 0.0))
        assert np.allclose(cam.eye, (1.0, 4.0, 8.0))
        assert np.allclose(cam.look, (1.0, 0.0, 0.0))
        cam.look_ahead = 1.0
        cam.target((1.0, 0.0, 0.0), velocity=(2.0, 0.0, 0.0))
        assert np.allclose(cam.eye, (3.0, 4.0, 8.0))
