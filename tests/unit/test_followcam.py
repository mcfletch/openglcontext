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

from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.move.followcam import look_at_orientation, FollowCamera


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
