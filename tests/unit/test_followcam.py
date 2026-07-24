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
