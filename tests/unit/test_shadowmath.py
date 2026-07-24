"""Unit tests for shadow-mapping matrix math (no OpenGL context required)."""
import numpy as np
import pytest

from OpenGLContext.passes import shadowmath


def _to_h(p):
    return np.array([p[0], p[1], p[2], 1.0], dtype='d')


class TestLookAt:
    def test_eye_maps_to_origin(self):
        """The light position must map to the eye-space origin."""
        eye = (3.0, 4.0, 5.0)
        view = shadowmath.look_at_matrix(eye, forward=(0, 0, -1)).astype('d')
        out = _to_h(eye) @ view
        assert np.allclose(out[:3], [0, 0, 0], atol=1e-5)

    def test_forward_point_is_negative_z(self):
        """A point one unit ahead along the view direction lands at eye -Z."""
        eye = (0.0, 0.0, 0.0)
        forward = (0.0, 0.0, -1.0)
        view = shadowmath.look_at_matrix(eye, forward).astype('d')
        ahead = _to_h((0.0, 0.0, -1.0)) @ view
        assert ahead[2] < 0
        assert np.allclose(ahead[2], -1.0, atol=1e-5)

    def test_forward_point_negative_z_arbitrary_direction(self):
        eye = (2.0, 1.0, -3.0)
        forward = (1.0, -1.0, 0.5)
        view = shadowmath.look_at_matrix(eye, forward).astype('d')
        fwd_unit = np.asarray(forward, 'd') / np.linalg.norm(forward)
        ahead = _to_h(np.asarray(eye) + fwd_unit) @ view
        assert np.allclose(ahead[2], -1.0, atol=1e-5)
        # and laterally centered
        assert np.allclose(ahead[:2], [0, 0], atol=1e-5)

    def test_orthonormal(self):
        view = shadowmath.look_at_matrix((1, 2, 3), (0.3, 0.4, -0.5)).astype('d')
        r = view[:3, :3]
        # rows of the rotation part should be orthonormal
        assert np.allclose(r @ r.T, np.eye(3), atol=1e-5)

    def test_handles_forward_parallel_to_up(self):
        """Looking straight down must not produce NaNs (up auto-selected)."""
        view = shadowmath.look_at_matrix((0, 10, 0), (0, -1, 0))
        assert np.all(np.isfinite(view))
        r = view[:3, :3].astype('d')
        assert np.allclose(r @ r.T, np.eye(3), atol=1e-5)


class TestPerspective:
    def test_point_in_front_maps_inside_ndc(self):
        proj = shadowmath.perspective_matrix(np.pi / 2, 1.0, 0.1, 100.0).astype('d')
        # eye-space point straight ahead, inside the frustum
        eye_pt = np.array([0.0, 0.0, -10.0, 1.0])
        clip = eye_pt @ proj
        ndc = clip[:3] / clip[3]
        assert np.all(ndc >= -1.0) and np.all(ndc <= 1.0)

    def test_w_is_positive_in_front(self):
        proj = shadowmath.perspective_matrix(np.pi / 3, 1.0, 0.1, 100.0).astype('d')
        clip = np.array([0.0, 0.0, -5.0, 1.0]) @ proj
        assert clip[3] > 0


class TestNearFar:
    def test_fits_points_in_front(self):
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        # points between z=0 and z=4 (i.e. 6..10 units in front of the light)
        pts = np.array([[0, 0, 0], [1, 1, 4], [-1, -1, 2]], dtype='d')
        near, far = shadowmath.near_far_from_points(view, pts)
        assert near > 0
        assert far > near
        # nearest point is at z=4 -> depth 6; farthest z=0 -> depth 10
        assert near <= 6.0 and far >= 10.0

    def test_empty_points_safe(self):
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        near, far = shadowmath.near_far_from_points(view, np.zeros((0, 3)))
        assert far > near > 0


class TestSpotMatrices:
    def test_round_trip_point_in_shadow_frustum(self):
        """A point in front of the spot light projects inside the shadow NDC."""
        pos = (0.0, 5.0, 0.0)
        direction = (0.0, -1.0, 0.0)        # pointing down
        view, proj = shadowmath.spot_light_view_projection(
            pos, direction, cutoff_angle=0.6, near=0.5, far=20.0
        )
        ground_pt = _to_h((0.0, 0.0, 0.0))   # directly below the light
        clip = ground_pt @ view.astype('d') @ proj.astype('d')
        ndc = clip[:3] / clip[3]
        assert np.all(np.abs(ndc) <= 1.0)
        # directly under the light -> near center of the map
        assert np.allclose(ndc[:2], [0, 0], atol=1e-4)


class TestShadowMatrixEye:
    def test_eye_space_lookup_matches_world_space(self):
        """shadow_matrix_eye applied to an eye-space point equals the direct
        world->light-clip transform of the same world point."""
        camera_view = shadowmath.look_at_matrix((0, 2, 12), (0, -0.1, -1))
        light_view, light_proj = shadowmath.spot_light_view_projection(
            (0, 8, 0), (0, -1, 0), cutoff_angle=0.7, near=0.5, far=40.0
        )
        world_pt = _to_h((1.0, 0.0, -2.0))
        # direct: world -> light clip
        direct = world_pt @ light_view.astype('d') @ light_proj.astype('d')
        # via eye space
        eye_pt = world_pt @ camera_view.astype('d')
        sme = shadowmath.shadow_matrix_eye(camera_view, light_view, light_proj).astype('d')
        via_eye = eye_pt @ sme
        assert np.allclose(direct, via_eye, atol=1e-4)


class TestOrtho:
    def test_maps_box_to_ndc(self):
        proj = shadowmath.ortho_matrix(-2, 2, -2, 2, 1, 10).astype('d')
        # eye-space point at center of the box, mid-depth
        pt = np.array([0.0, 0.0, -5.5, 1.0])
        clip = pt @ proj
        ndc = clip[:3] / clip[3]
        assert np.all(np.abs(ndc) <= 1.0 + 1e-6)

    def test_corners_map_to_ndc_extremes(self):
        proj = shadowmath.ortho_matrix(-2, 2, -2, 2, 1, 10).astype('d')
        right_top_near = np.array([2.0, 2.0, -1.0, 1.0]) @ proj
        ndc = right_top_near[:3] / right_top_near[3]
        assert np.allclose(ndc[0], 1.0, atol=1e-5)
        assert np.allclose(ndc[1], 1.0, atol=1e-5)


class TestFrustumCorners:
    def test_returns_eight_corners(self):
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        proj = shadowmath.perspective_matrix(np.pi / 3, 1.0, 1.0, 50.0)
        corners = shadowmath.frustum_corners_world(view, proj)
        assert corners.shape == (8, 3)
        assert np.all(np.isfinite(corners))

    def test_near_slice_closer_than_far_slice(self):
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        proj = shadowmath.perspective_matrix(np.pi / 3, 1.0, 1.0, 50.0)
        near_slice = shadowmath.frustum_corners_world(view, proj, 0.0, 0.2)
        far_slice = shadowmath.frustum_corners_world(view, proj, 0.8, 1.0)
        # near slice corners are closer to the camera at z=10 (larger z)
        assert near_slice[:, 2].mean() > far_slice[:, 2].mean()


class TestCascadeSplits:
    def test_monotonic_increasing_within_range(self):
        splits = shadowmath.cascade_splits(1.0, 100.0, 4)
        assert len(splits) == 4
        assert all(splits[i] < splits[i + 1] for i in range(3))
        assert splits[-1] == pytest.approx(100.0, rel=1e-6)
        assert splits[0] > 1.0


class TestDirectionalCascade:
    def test_covers_corners_in_ndc(self):
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        proj = shadowmath.perspective_matrix(np.pi / 3, 1.0, 1.0, 20.0)
        corners = shadowmath.frustum_corners_world(view, proj)
        lview, lproj = shadowmath.directional_cascade((0, -1, -0.3), corners)
        h = np.concatenate([corners, np.ones((8, 1))], axis=1)
        clip = h @ lview.astype('d') @ lproj.astype('d')
        ndc = clip[:, :3] / clip[:, 3:4]
        # every frustum corner must fall inside the cascade's ortho volume
        assert np.all(ndc[:, :2] >= -1.001) and np.all(ndc[:, :2] <= 1.001)
        assert np.all(ndc[:, 2] >= -1.001) and np.all(ndc[:, 2] <= 1.001)

    @staticmethod
    def _tight_cascade():
        """A tight near cascade whose near plane clips a nearby up-sun caster."""
        light = np.array([-0.62, -0.42, -0.28])
        light /= np.linalg.norm(light)
        cam_eye = np.array([-2.0, 1.6, 0.0])
        cam_fwd = np.array([1.0, -0.1, 0.0])
        cam_fwd /= np.linalg.norm(cam_fwd)
        view = shadowmath.look_at_matrix(cam_eye, cam_fwd)
        proj = shadowmath.perspective_matrix(np.pi / 3, 1.0, 0.2, 30.0)

        def depth01(dist):
            clip = np.array([0, 0, -dist, 1.0]) @ proj.astype('d')
            return float(np.clip(0.5 * clip[2] / clip[3] + 0.5, 0.0, 1.0))

        corners = shadowmath.frustum_corners_world(view, proj, depth01(0.2), depth01(1.5))
        receiver = cam_eye + cam_fwd * 1.0            # inside the cascade
        caster = receiver - light * 3.0               # 3m up-sun, same light ray
        return light, corners, receiver, caster

    @staticmethod
    def _ndc(lview, lproj, pt):
        clip = np.append(pt, 1.0) @ lview.astype('d') @ lproj.astype('d')
        return clip[:3] / clip[3]

    def test_up_sun_caster_clipped_without_bounds(self):
        """Precondition: fitting to the receiver frustum alone clips the caster."""
        light, corners, receiver, caster = self._tight_cascade()
        lview, lproj = shadowmath.directional_cascade(light, corners)
        assert -1.0 <= self._ndc(lview, lproj, receiver)[2] <= 1.0
        assert self._ndc(lview, lproj, caster)[2] < -1.0   # clipped by the near plane

    @staticmethod
    def _box(center, half=0.3):
        corners = np.array([[dx, dy, dz] for dx in (-half, half)
                            for dy in (-half, half) for dz in (-half, half)])
        return (center + corners)[None, :, :]        # (1, 8, 3)

    def test_up_sun_caster_kept_with_bounds(self):
        """caster_bounds extends the near plane so the up-sun caster is kept."""
        light, corners, receiver, caster = self._tight_cascade()
        lview, lproj = shadowmath.directional_cascade(
            light, corners, caster_bounds=self._box(caster))
        assert -1.0 <= self._ndc(lview, lproj, caster)[2] <= 1.0     # now inside
        assert -1.0 <= self._ndc(lview, lproj, receiver)[2] <= 1.0   # receiver still covered

    def test_bounds_do_not_change_xy(self):
        """Extending the near plane must not cost XY resolution (finding: precision)."""
        light, corners, receiver, caster = self._tight_cascade()
        lv0, lp0 = shadowmath.directional_cascade(light, corners)
        lv1, lp1 = shadowmath.directional_cascade(
            light, corners, caster_bounds=self._box(caster))
        assert np.allclose(self._ndc(lv0, lp0, receiver)[:2],
                           self._ndc(lv1, lp1, receiver)[:2], atol=1e-6)

    def test_off_footprint_caster_ignored(self):
        """A caster whose XY box is outside the cascade footprint must not move near."""
        light, corners, receiver, caster = self._tight_cascade()
        far_off = caster + np.array([1000.0, 0.0, 1000.0])   # nowhere near the footprint
        lv0, lp0 = shadowmath.directional_cascade(light, corners)
        lv1, lp1 = shadowmath.directional_cascade(
            light, corners, caster_bounds=self._box(far_off))
        assert np.allclose(lp0, lp1)


class TestNormalizeDegenerate:
    def test_zero_vector_returned_unchanged(self):
        """A (near-)zero vector has no direction, so it is returned as-is
        rather than dividing by ~0 and producing inf/nan."""
        z = np.zeros(3, dtype='d')
        out = shadowmath._normalize(z)
        assert np.array_equal(out, z)

    def test_tiny_vector_below_epsilon_returned_unchanged(self):
        tiny = np.array([1e-13, 0.0, 0.0])
        out = shadowmath._normalize(tiny)
        assert np.array_equal(out, tiny)


class TestNearFarDegenerate:
    def test_all_points_behind_light_falls_back(self):
        """Points entirely behind the light (far <= 0) yield the safe default
        instead of a negative/zero far plane."""
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        # points behind the light (z > 10 -> negative depth in front)
        pts = np.array([[0, 0, 20], [1, 1, 30]], dtype='d')
        near, far = shadowmath.near_far_from_points(view, pts, min_near=0.05)
        assert near == pytest.approx(0.05)
        assert far == pytest.approx(1.0)


class TestExtendNearDegenerateBounds:
    def test_empty_caster_bounds_leave_near_unchanged(self):
        """An empty (0,8,3) caster-bounds array must not move the near plane."""
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        proj = shadowmath.perspective_matrix(np.pi / 3, 1.0, 1.0, 20.0)
        corners = shadowmath.frustum_corners_world(view, proj)
        lv0, lp0 = shadowmath.directional_cascade((0, -1, -0.3), corners)
        lv1, lp1 = shadowmath.directional_cascade(
            (0, -1, -0.3), corners, caster_bounds=np.zeros((0, 8, 3)))
        assert np.allclose(lp0, lp1)

    def test_wrong_ndim_caster_bounds_leave_near_unchanged(self):
        """Caster bounds that are not (K,8,3) are ignored, not misinterpreted."""
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        mins = np.zeros(3)
        maxs = np.ones(3)
        near = shadowmath._extend_near_for_casters(
            np.zeros((8, 3)), view.astype('d'), mins, maxs, 5.0)
        assert near == 5.0


class TestCube:
    def test_six_faces_orthonormal(self):
        for face in range(6):
            v = shadowmath.cube_face_view((1, 2, 3), face).astype('d')
            r = v[:3, :3]
            assert np.allclose(r @ r.T, np.eye(3), atol=1e-5)

    def test_face_points_along_axis(self):
        # +X face: a point one unit in +X from the light maps to eye -Z
        v = shadowmath.cube_face_view((0, 0, 0), 0).astype('d')
        out = np.array([1.0, 0.0, 0.0, 1.0]) @ v
        assert out[2] < 0 and np.allclose(out[:2], 0, atol=1e-6)

    def test_projection_in_front(self):
        proj = shadowmath.cube_projection(0.1, 50.0).astype('d')
        clip = np.array([0.0, 0.0, -5.0, 1.0]) @ proj
        assert clip[3] > 0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
