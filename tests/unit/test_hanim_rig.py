"""HAnim's arithmetic, `OpenGLContext.character.hanim`: no GL, no scenegraph."""
import math

import numpy as np
import pytest

from OpenGLContext.character import hanim
from vrml.vrml97 import transformmatrix


def rotation_about(axis, angle):
    return transformmatrix.transformMatrix(rotation=tuple(axis) + (angle,))


class TestNames:
    def test_an_alias_is_read_as_the_standard_name(self):
        assert hanim.canonical_joint('l_ankle') == 'l_talocrural'

    def test_the_bvh_root_is_the_humanoid_root(self):
        assert hanim.canonical_joint('HumanoidRoot') == 'humanoid_root'

    def test_surrounding_space_is_not_part_of_a_name(self):
        assert hanim.canonical_joint(' l_hip ') == 'l_hip'

    def test_a_name_the_standard_lacks_is_kept(self):
        assert hanim.canonical_joint('tail_1') == 'tail_1'

    def test_a_joint_has_the_level_its_name_gives(self):
        assert hanim.joint_level('l_knee') == 1
        assert hanim.joint_level('l_ankle') == 1
        assert hanim.joint_level('tail_1') is None

    @pytest.mark.parametrize('name, loa, expected', [
        ('l_knee', 1, True), ('vc1', 1, False), ('vc1', 3, True),
        ('vc1', -1, True), ('tail_1', 0, True),
    ])
    def test_a_level_of_articulation_admits_its_joints(self, name, loa, expected):
        assert hanim.within_level(name, loa) is expected


class TestSkinInfluences:
    def test_a_vertex_one_joint_moves_wholly_is_that_joints(self):
        joints, weights = hanim.skin_influences(2, [([0], [1.0])])
        assert joints[0].tolist() == [1, 0, 0, 0]
        assert weights[0].tolist() == [1.0, 0.0, 0.0, 0.0]

    def test_a_vertex_no_joint_reaches_stays_where_it_is(self):
        joints, weights = hanim.skin_influences(2, [([0], [1.0])])
        assert joints[1][0] == hanim.REST_JOINT
        assert weights[1].tolist() == [1.0, 0.0, 0.0, 0.0]

    def test_what_the_weights_leave_out_stays_at_rest(self):
        joints, weights = hanim.skin_influences(1, [([0], [1.0]), ([0], [0.5])])
        found = {joint: weight for joint, weight in zip(joints[0].tolist(), weights[0].tolist())
                 if weight}
        assert found[1] == pytest.approx(1.0)
        assert found[2] == pytest.approx(0.5)
        assert found[hanim.REST_JOINT] == pytest.approx(-0.5)

    def test_weights_within_a_tolerance_of_one_are_renormalised(self):
        joints, weights = hanim.skin_influences(1, [([0], [0.6]), ([0], [0.398])])
        assert hanim.REST_JOINT not in joints[0][weights[0] != 0].tolist()
        assert weights[0].sum() == pytest.approx(1.0)

    def test_the_heaviest_four_are_kept_and_renormalised(self):
        influences = [([0], [w]) for w in (0.3, 0.25, 0.2, 0.15, 0.1)]
        joints, weights = hanim.skin_influences(1, influences)
        assert sorted(joints[0].tolist()) == [1, 2, 3, 4]
        assert weights[0].sum() == pytest.approx(1.0)
        assert weights[0][0] == pytest.approx(0.3 / 0.9)

    def test_one_joint_listing_a_vertex_twice_adds_the_weights(self):
        joints, weights = hanim.skin_influences(1, [([0, 0], [0.5, 0.5])])
        assert joints[0][0] == 1
        assert weights[0][0] == pytest.approx(1.0)

    def test_an_index_without_a_weight_moves_wholly(self):
        joints, weights = hanim.skin_influences(2, [([0, 1], [])])
        assert weights[:, 0].tolist() == [1.0, 1.0]
        assert joints[:, 0].tolist() == [1, 1]

    def test_an_index_past_the_points_is_left_out(self):
        joints, weights = hanim.skin_influences(1, [([0, 5, -1], [1, 1, 1])])
        assert joints[0][0] == 1

    def test_no_points_gives_empty_tables(self):
        joints, weights = hanim.skin_influences(0, [([0], [1.0])])
        assert joints.shape == (0, 4) and weights.shape == (0, 4)

    def test_blending_matches_the_rest_offset_sum(self):
        """v + sum(w (M v - v)): the weights need not sum to one."""
        points = np.array([[0.1, 0.5, 0.0], [0.2, 0.9, 0.1]])
        hip = rotation_about((1, 0, 0), 0.4)
        knee = hip @ rotation_about((0, 0, 1), -0.3)
        influences = [([0, 1], [1.0, 0.2]), ([0], [0.5])]
        joints, weights = hanim.skin_influences(2, influences)
        palette = np.stack([np.eye(4), hip, knee])
        posed = hanim.skin_points(points, joints, weights, palette)
        homogeneous = np.c_[points, np.ones(2)]
        expected = points.copy()
        expected[0] += (homogeneous[0] @ hip)[:3] - points[0]
        expected[0] += 0.5 * ((homogeneous[0] @ knee)[:3] - points[0])
        expected[1] += 0.2 * ((homogeneous[1] @ hip)[:3] - points[1])
        np.testing.assert_allclose(posed, expected, atol=1e-6)


class TestBounds:
    def test_the_joint_reach_bounds_the_posed_points(self):
        rng = np.random.default_rng(3)
        points = rng.uniform(-1, 1, (200, 3))
        influences = [(np.arange(0, 120), rng.uniform(0.2, 0.8, 120)),
                      (np.arange(80, 200), np.ones(120))]
        joints, weights = hanim.skin_influences(200, influences)
        weights = np.abs(weights)
        weights /= weights.sum(axis=1, keepdims=True)
        palette = np.stack([np.eye(4), rotation_about((0, 1, 0), 1.0),
                            transformmatrix.transformMatrix(translation=(3, 0, 0))])
        reach = hanim.joint_reach(points, joints, weights, len(palette))
        low, high = hanim.posed_bounds(reach, palette)
        posed = hanim.skin_points(points, joints, weights, palette)
        assert (posed >= low - 1e-9).all() and (posed <= high + 1e-9).all()

    def test_negative_weights_are_not_convex(self):
        assert not hanim.convex(np.array([[1.0, -0.5, 0.5, 0.0]]))
        assert hanim.convex(np.array([[0.5, 0.5, 0.0, 0.0]]))


class TestDisplacement:
    def test_each_index_is_moved_by_its_displacement(self):
        found = hanim.displacement(3, [2, 0], [(0, 1, 0), (1, 0, 0)])
        np.testing.assert_allclose(found, [(1, 0, 0), (0, 0, 0), (0, 1, 0)])

    def test_an_index_without_a_displacement_or_past_the_points_is_left_out(self):
        found = hanim.displacement(2, [0, 7, 1], [(0, 1, 0), (1, 0, 0)])
        np.testing.assert_allclose(found, [(0, 1, 0), (0, 0, 0)])


class TestBinding:
    def test_a_binding_matrix_scales_turns_then_moves(self):
        matrix = hanim.binding_matrix((1, 2, 3), (0, 0, 1, math.pi / 2), (2, 2, 2))
        np.testing.assert_allclose(np.array([1, 0, 0, 1]) @ matrix, [1, 4, 3, 1], atol=1e-6)

    def test_missing_values_bind_at_the_identity(self):
        np.testing.assert_allclose(hanim.binding_matrix(None, None, None), np.eye(4))

    def test_one_matrix_per_joint(self):
        found = hanim.binding_matrices(3, [(1, 0, 0)], [], [(2, 2, 2), (1, 1, 1)])
        assert found.shape == (3, 4, 4)
        np.testing.assert_allclose(found[0][3, :3], [1, 0, 0])
        np.testing.assert_allclose(found[0][0, 0], 2)
        np.testing.assert_allclose(found[2], np.eye(4))


CHANNELS = '6 Xposition Yposition Zposition Zrotation Xrotation Yrotation 3 Zrotation Xrotation Yrotation'


class TestMotionChannels:
    def make(self, values=None, joints='HumanoidRoot l_hip'):
        values = values if values is not None else [
            1, 2, 3, 90, 0, 0, 0, 0, 0,
            3, 2, 1, 0, 0, 0, 0, 90, 0,
        ]
        return hanim.MotionChannels(joints, CHANNELS, values)

    def test_the_groups_are_the_joints_in_order(self):
        motion = self.make()
        assert motion.names == ['humanoid_root', 'l_hip']
        assert motion.frames == 2

    def test_a_frame_gives_each_joint_its_values(self):
        translation, rotation, scale = self.make().sample(0.0)[0]
        np.testing.assert_allclose(translation, (1, 2, 3))
        assert rotation[3] == pytest.approx(math.pi / 2)
        np.testing.assert_allclose(np.abs(rotation[:3]), (0, 0, 1), atol=1e-9)
        assert scale is None

    def test_between_frames_the_values_are_interpolated(self):
        translation, rotation, _scale = self.make().sample(0.5)[0]
        np.testing.assert_allclose(translation, (2, 2, 2))
        assert rotation[3] == pytest.approx(math.pi / 4)

    def test_rotations_compose_in_the_order_the_channels_list_them(self):
        """Zrotation Xrotation Yrotation is Rz Rx Ry: Y turns the vertex first."""
        motion = hanim.MotionChannels('j', '3 Zrotation Xrotation Yrotation', [90, 90, 0])
        rotation = motion.sample(0)[0][1]
        turned = np.array([0, 1, 0, 1]) @ transformmatrix.transformMatrix(
            rotation=tuple(rotation))
        # Rx(90) takes +Y to +Z, then Rz(90) leaves +Z alone.
        np.testing.assert_allclose(turned[:3], (0, 0, 1), atol=1e-6)

    def test_a_name_without_channels_is_ignored_and_ignored_names_are_none(self):
        motion = hanim.MotionChannels('IGNORED j', '3 Xrotation Yrotation Zrotation 1 Xscale',
                                      [0, 0, 0, 2])
        assert motion.names == [None, 'j']
        assert motion.sample(0)[1][2] == pytest.approx((2, 1, 1))

    def test_too_few_values_make_no_frame(self):
        assert self.make(values=[1, 2]).frames == 0
        assert self.make(values=[1, 2]).sample(0) == []

    def test_a_position_past_the_end_holds_the_last_frame(self):
        translation = self.make().sample(7.0)[0][0]
        np.testing.assert_allclose(translation, (3, 2, 1))


class TestMotionFrame:
    def test_frames_advance_at_the_frame_duration(self):
        assert hanim.motion_frame(0.25, 0, 0.1, 1, 0, 10, False) == (2.5, False, 0)

    def test_without_loop_play_ends_at_the_last_frame(self):
        assert hanim.motion_frame(5.0, 0, 0.1, 1, 0, 10, False) == (10, True, 0)

    def test_a_loop_starts_again_from_the_first_frame(self):
        position, finished, cycles = hanim.motion_frame(1.25, 0, 0.1, 1, 0, 10, True)
        assert position == pytest.approx(2.5) and not finished and cycles == 1

    def test_a_negative_increment_plays_backwards(self):
        position, finished, _cycles = hanim.motion_frame(0.3, 10, 0.1, -1, 0, 10, False)
        assert position == pytest.approx(7.0) and not finished
        assert hanim.motion_frame(5, 10, 0.1, -1, 0, 10, False) == (0, True, 0)

    def test_a_backwards_loop_wraps_to_the_last_frame(self):
        position, finished, cycles = hanim.motion_frame(0.3, 2, 0.1, -1, 0, 10, True)
        assert position == pytest.approx(9.0) and not finished and cycles == 1

    def test_an_increment_of_two_skips_frames(self):
        assert hanim.motion_frame(0.2, 0, 0.1, 2, 0, 10, False)[0] == pytest.approx(4.0)

    def test_an_increment_of_zero_holds_the_frame(self):
        assert hanim.motion_frame(3.0, 4, 0.1, 0, 0, 10, True) == (4, False, 0)

    def test_a_single_frame_range_holds_it(self):
        assert hanim.motion_frame(3.0, 4, 0.1, 1, 4, 4, False) == (4, True, 0)


class TestPose:
    def test_a_blend_runs_from_the_start_to_the_target(self):
        start = hanim.JointValues.of([(0, 0, 0)], [(0, 0, 1, 0)], [(1, 1, 1)])
        target = hanim.JointValues.of([(2, 0, 0)], [(0, 0, 1, 1.0)], [(3, 3, 3)])
        half = hanim.blend_values(start, target, 0.5)
        np.testing.assert_allclose(half.translations[0], (1, 0, 0))
        np.testing.assert_allclose(half.scales[0], (2, 2, 2))
        assert half.rotations[0][3] == pytest.approx(0.5)
        np.testing.assert_allclose(hanim.blend_values(start, target, 1.0).translations,
                                   target.translations)

    def test_a_fraction_outside_zero_to_one_is_clamped(self):
        start = hanim.JointValues.of([(0, 0, 0)], [(0, 0, 1, 0)], [(1, 1, 1)])
        target = hanim.JointValues.of([(2, 0, 0)], [(0, 0, 1, 1.0)], [(1, 1, 1)])
        np.testing.assert_allclose(hanim.blend_values(start, target, 4).translations[0],
                                   (2, 0, 0))


class TestLimits:
    def test_a_rotation_within_the_limits_is_kept(self):
        found = hanim.limited_rotation((1, 0, 0, 0.2), (-1, 0, 0), (1, 0, 0), (0, 0, 1, 0))
        np.testing.assert_allclose(found, (1, 0, 0, 0.2), atol=1e-9)

    def test_a_rotation_past_a_limit_stops_at_it(self):
        found = hanim.limited_rotation((1, 0, 0, 1.2), (-0.5, 0, 0), (0.5, 0, 0),
                                       (0, 0, 1, 0))
        assert found[3] == pytest.approx(0.5)
        np.testing.assert_allclose(found[:3], (1, 0, 0), atol=1e-6)

    def test_an_axis_whose_limits_are_equal_is_free(self):
        found = hanim.limited_rotation((0, 1, 0, 1.2), (0, 0, 0), (0, 0, 0), (0, 0, 1, 0))
        np.testing.assert_allclose(found, (0, 1, 0, 1.2), atol=1e-9)

    def test_limits_are_measured_in_the_limit_orientation(self):
        """Turned a quarter about Z, the limit frame's X axis is the world's Y."""
        found = hanim.limited_rotation((0, 1, 0, 1.2), (-0.5, 0, 0), (0.5, 0, 0),
                                       (0, 0, 1, math.pi / 2))
        assert found[3] == pytest.approx(0.5)
        np.testing.assert_allclose(found[:3], (0, 1, 0), atol=1e-6)
