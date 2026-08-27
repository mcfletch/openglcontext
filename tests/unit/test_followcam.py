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
