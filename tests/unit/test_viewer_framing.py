"""Where a viewer puts its camera (:mod:`OpenGLContext.viewer.framing`).

Pure arithmetic, so it is checked without a window: the fit distance really does
contain the model, the near and far planes really do scale with it, and the aim
really is the bearing and elevation of the line to what is being looked at.
"""
from math import asin, atan2, pi, sin

import numpy as np
import pytest

from OpenGLContext.viewer.framing import (
    DEFAULT_ELEVATION, DEFAULT_FOV, DEFAULT_MARGIN, DEFAULT_TILT,
    fit_sphere, look_from,
)


class TestFitSphere:
    def test_the_model_exactly_fills_the_field_of_view(self):
        """The whole point: the sphere subtends the field of view, edge to edge.

        A camera sees a sphere along its *tangents*, not across a plane through
        its centre, so the distance that fits it is ``r / sin(fov/2)``.
        """
        radius = 3.0
        pose = fit_sphere(radius, margin=1.0)
        assert asin(radius / pose.position[2]) == pytest.approx(pose.fov / 2.0)

    def test_the_margin_backs_the_camera_off(self):
        near = fit_sphere(1.0, margin=1.0)
        far = fit_sphere(1.0, margin=2.0)
        assert far.position[2] == pytest.approx(near.position[2] * 2.0)

    def test_a_margin_below_one_fills_more_of_the_frame(self):
        """A wide flat model's bounding sphere overstates what is visible."""
        assert fit_sphere(1.0, margin=0.8).position[2] < fit_sphere(1.0).position[2]

    def test_the_distance_scales_with_the_model(self):
        small, large = fit_sphere(1.0), fit_sphere(10.0)
        assert large.position[2] == pytest.approx(small.position[2] * 10.0)

    def test_the_camera_is_lifted_and_tilted(self):
        pose = fit_sphere(4.0, elevation=0.5, tilt=0.3)
        assert pose.position[1] == pytest.approx(2.0)
        assert pose.orientation == (1.0, 0.0, 0.0, 0.3)

    def test_the_defaults_are_the_named_ones(self):
        pose = fit_sphere(2.0)
        assert pose.position[1] == pytest.approx(2.0 * DEFAULT_ELEVATION)
        assert pose.orientation[3] == pytest.approx(DEFAULT_TILT)
        assert pose.fov == pytest.approx(DEFAULT_FOV)
        assert pose.position[2] == pytest.approx(
            2.0 / sin(DEFAULT_FOV / 2.0) * DEFAULT_MARGIN)

    def test_the_depth_range_scales_with_the_model(self):
        """One fixed near plane cannot serve both a bolt and a city."""
        small, large = fit_sphere(0.01), fit_sphere(1000.0)
        assert small.near < large.near
        assert small.far < large.far
        assert small.near < small.position[2] < small.far
        assert large.near < large.position[2] < large.far

    def test_a_degenerate_model_still_yields_a_usable_frustum(self):
        pose = fit_sphere(0.0)
        assert pose.near > 0.0
        assert pose.fov > 0.0

    def test_the_field_of_view_can_be_overridden(self):
        wide = fit_sphere(1.0, margin=1.0, fov=pi / 2)
        assert wide.fov == pytest.approx(pi / 2)
        assert wide.position[2] == pytest.approx(1.0 / sin(pi / 4))


class TestLookFrom:
    """Aiming from a point at a point.

    The camera convention itself -- which way a given quaternion faces -- is
    pinned by the blessed interior-shot baselines in
    ``tests/unit/test_gltf_conformance.py``, where Sponza is rendered this way.
    What these check is the arithmetic on top of it.
    """

    def _expected(self, eye, target):
        """The bearing and elevation of the line, in the platform's frame.

        A platform holds the world-into-camera rotation, so the pitch is
        negated and applied before the yaw; composed the other way round the
        camera aims as far above the target as it should be below it.
        """
        from OpenGLContext import quaternion
        direction = np.asarray(target, dtype='d') - np.asarray(eye, dtype='d')
        direction = direction / np.linalg.norm(direction)
        yaw = atan2(direction[0], -direction[2])
        pitch = asin(direction[1])
        return (quaternion.fromXYZR(1, 0, 0, -pitch)
                * quaternion.fromXYZR(0, 1, 0, yaw))

    def test_the_aim_is_the_bearing_then_the_elevation_of_the_line(self):
        for eye, target in (((0, 0, 0), (0, 0, -1)), ((0, 0, 0), (5, 0, 0)),
                            ((0, 0, 0), (0, 2, -2)), ((-3, 2, 4), (6, -1, -2)),
                            ((11.0, -3.5, 1.5), (-13.0, 1.0, -5.0))):
            pose = look_from(eye, target, radius=10.0)
            assert np.allclose(np.asarray(pose.quaternion.XYZR()),
                               np.asarray(self._expected(eye, target).XYZR()),
                               atol=1e-12), (eye, target)

    def test_looking_straight_ahead_needs_no_rotation_at_all(self):
        """A camera at rest already looks down -Z."""
        pose = look_from((0, 0, 0), (0, 0, -1), radius=1.0)
        assert np.allclose(np.asarray(pose.quaternion * [0.0, 0.0, -1.0, 0.0])[:3],
                           (0.0, 0.0, -1.0), atol=1e-12)

    def test_how_far_away_the_target_is_does_not_change_the_aim(self):
        near = look_from((0, 0, 0), (1, 1, -1), radius=1.0)
        far = look_from((0, 0, 0), (100, 100, -100), radius=1.0)
        assert np.allclose(np.asarray(near.quaternion.XYZR()),
                           np.asarray(far.quaternion.XYZR()), atol=1e-12)

    def test_the_camera_stands_where_it_was_told_to(self):
        pose = look_from((10, 2, -5), (10, 2, -9), radius=4.0)
        assert pose.position == (10.0, 2.0, -5.0)

    def test_looking_at_where_you_stand_names_no_direction(self):
        assert look_from((1, 1, 1), (1, 1, 1), radius=1.0) is None

    def test_the_aim_is_a_quaternion_not_an_axis_angle(self):
        """Yaw then pitch is two rotations, which one axis/angle cannot say."""
        pose = look_from((0, 0, 0), (1, 1, -1), radius=1.0)
        assert pose.orientation is None
        assert pose.quaternion is not None

    def test_the_depth_range_is_tighter_than_the_whole_model_fit(self):
        """An interior shot is inside the model, so its near plane comes in."""
        inside = look_from((0, 1, 0), (1, 1, 0), radius=100.0)
        outside = fit_sphere(100.0)
        assert inside.near < outside.near
        assert inside.far < outside.far


def test_a_pose_reads_like_a_tuple_and_by_name():
    pose = fit_sphere(1.0)
    position, orientation, fov, near, far, quaternion = pose
    assert position == pose.position and orientation == pose.orientation
    assert (fov, near, far) == (pose.fov, pose.near, pose.far)
    assert quaternion is None


def test_the_fit_and_the_aim_agree_about_a_centred_model():
    """Framing a model head-on and aiming at its centre come to the same pose."""
    pose = fit_sphere(5.0, elevation=0.0, tilt=0.0)
    aimed = look_from(pose.position, (0.0, 0.0, 0.0), radius=5.0)
    assert aimed.position == pose.position
    assert np.allclose(np.asarray(aimed.quaternion * [0.0, 0.0, -1.0, 0.0])[:3],
                       (0.0, 0.0, -1.0), atol=1e-12), 'straight down -Z'


class TestLookFromAimsWhereItSays:
    """The pose is checked through the view platform that renders it, not
    against the quaternion it happens to build: an aim that is right in the
    arithmetic and mirrored in the matrix is the bug this catches."""

    @staticmethod
    def rendered_direction(pose):
        import numpy as np
        from OpenGLContext.move.viewplatform import ViewPlatform
        platform = ViewPlatform()
        platform.setPosition(pose.position)
        if pose.quaternion is not None:
            platform.quaternion = pose.quaternion
        else:
            platform.setOrientation(pose.orientation)
        rotation = np.asarray(platform.modelMatrix())[:3, :3]
        return np.array([0.0, 0.0, -1.0]) @ np.linalg.inv(rotation)

    @pytest.mark.parametrize('target', [
        (0.0, 0.0, -10.0),          # straight ahead
        (10.0, 0.0, 0.0),           # a quarter turn right
        (0.0, -10.0, 0.0),          # straight down
        (0.0, -400.0, -900.0),      # down and ahead: standing over a dataset
        (300.0, -400.0, -900.0),    # and turned as well
    ])
    def test_the_camera_faces_the_target(self, target):
        import numpy as np
        from OpenGLContext.viewer import framing
        eye = (0.0, 400.0, 900.0)
        wanted = np.asarray(target, dtype='d') - np.asarray(eye, dtype='d')
        wanted = wanted / np.linalg.norm(wanted)
        pose = framing.look_from(eye, target, 1000.0)
        assert self.rendered_direction(pose) == pytest.approx(wanted, abs=1e-6)
