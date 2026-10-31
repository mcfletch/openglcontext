"""Which way a character faces, how it lies on the ground, and how big it is."""
import math

import numpy as np
import pytest

from OpenGLContext.character.facing import Facing, Fit, fit_to_height, model_bounds
from OpenGLContext.scenegraph.transform import Transform

UP = np.array([0.0, 1.0, 0.0])


def rotate(rotation, vector):
    """``vector`` turned by a VRML axis-angle ``rotation``."""
    x, y, z, angle = rotation
    axis = np.array([x, y, z], dtype='d')
    axis = axis / np.linalg.norm(axis)
    vector = np.asarray(vector, dtype='d')
    return (vector * math.cos(angle) + np.cross(axis, vector) * math.sin(angle)
            + axis * (axis @ vector) * (1.0 - math.cos(angle)))


def angle_between(a, b):
    a, b = np.asarray(a, 'd'), np.asarray(b, 'd')
    cosine = a @ b / (np.linalg.norm(a) * np.linalg.norm(b))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def slope(degrees, facing='up'):
    """The normal of a ground rising at ``degrees`` along +Z."""
    angle = math.radians(degrees)
    return np.array([0.0, math.cos(angle), -math.sin(angle)])


def settle(facing, seconds=2.0, dt=1 / 60, **named):
    pose = None
    for _ in range(int(seconds / dt)):
        pose = facing.update(dt, **named)
    return pose


class TestHeading:
    def test_it_turns_toward_the_direction_of_travel_at_the_turn_rate(self):
        facing = Facing(turn_rate=math.pi)
        pose = facing.update(0.25, velocity=(3.0, 0.0, 0.0))
        assert pose.heading == pytest.approx(math.pi / 4)

    def test_it_arrives_and_stays(self):
        facing = Facing(turn_rate=math.pi)
        pose = settle(facing, 2.0, velocity=(3.0, 0.0, 0.0))
        assert pose.heading == pytest.approx(math.pi / 2)

    def test_heading_is_measured_from_plus_z_about_up(self):
        pose = settle(Facing(), velocity=(0.0, 0.0, -3.0))
        assert abs(pose.heading) == pytest.approx(math.pi)
        forward = rotate(pose.rotation, (0.0, 0.0, 1.0))
        assert forward == pytest.approx((0.0, 0.0, -1.0), abs=1e-6)

    def test_it_turns_the_short_way_round(self):
        facing = Facing(turn_rate=math.pi, heading=math.radians(170))
        pose = facing.update(0.1, velocity=(-1.0, 0.0, -3.0))
        turned = (pose.heading - math.radians(170) + math.pi) % (2 * math.pi) - math.pi
        assert 0 < turned <= math.pi * 0.1 + 1e-9

    def test_a_character_standing_still_keeps_its_heading(self):
        facing = Facing(heading=1.0)
        assert settle(facing, 1.0, velocity=(0.0, 0.0, 0.0)).heading == 1.0

    def test_height_in_the_velocity_does_not_turn_it(self):
        facing = Facing(heading=0.0)
        assert settle(facing, 1.0, velocity=(0.0, 9.0, 0.0)).heading == 0.0

    def test_aim_beats_the_direction_of_travel(self):
        facing = Facing(turn_rate=100.0)
        pose = settle(facing, 0.5, velocity=(3.0, 0.0, 0.0), aim=(0.0, 0.0, 1.0))
        assert pose.heading == pytest.approx(0.0)

    def test_an_aim_given_as_two_components_is_x_and_z(self):
        facing = Facing(turn_rate=100.0)
        assert settle(facing, 0.5, aim=(1.0, 0.0)).heading == pytest.approx(math.pi / 2)

    def test_an_aim_of_nothing_is_ignored(self):
        facing = Facing(heading=0.5)
        assert settle(facing, 0.5, aim=(0.0, 0.0, 0.0)).heading == 0.5

    def test_no_time_passing_turns_nothing(self):
        facing = Facing()
        assert facing.update(0.0, velocity=(3.0, 0.0, 0.0)).heading == 0.0


class TestGround:
    def test_a_body_on_a_slope_is_pitched_to_it_once_eased(self):
        facing = Facing()
        pose = settle(facing, 1.0, normal=slope(30.0))
        assert angle_between(rotate(pose.rotation, UP), slope(30.0)) < 2.0
        assert math.degrees(pose.pitch) == pytest.approx(-30.0, abs=2.0)

    def test_facing_downhill_pitches_the_other_way(self):
        facing = Facing(heading=math.pi)
        pose = settle(facing, 1.0, normal=slope(30.0))
        assert math.degrees(pose.pitch) == pytest.approx(30.0, abs=2.0)
        assert angle_between(rotate(pose.rotation, UP), slope(30.0)) < 2.0

    def test_a_cross_slope_rolls_the_body(self):
        normal = np.array([math.sin(math.radians(20)), math.cos(math.radians(20)), 0.0])
        pose = settle(Facing(), 1.0, normal=normal)
        assert angle_between(rotate(pose.rotation, UP), normal) < 2.0
        assert abs(pose.roll) > math.radians(15)

    def test_it_eases_rather_than_snapping(self):
        pose = Facing().update(1 / 60, normal=slope(30.0))
        assert 0 < abs(pose.pitch) < math.radians(15)

    def test_it_can_be_switched_off(self):
        pose = settle(Facing(align_to_ground=False), 1.0, normal=slope(30.0))
        assert (pose.pitch, pose.roll) == (0.0, 0.0)

    def test_level_ground_leaves_it_upright(self):
        pose = settle(Facing(), 1.0, normal=(0.0, 1.0, 0.0))
        assert rotate(pose.rotation, UP) == pytest.approx(UP, abs=1e-9)

    def test_a_normal_that_is_not_unit_length_still_means_a_direction(self):
        pose = settle(Facing(), 1.0, normal=slope(30.0) * 7.0)
        assert math.degrees(pose.pitch) == pytest.approx(-30.0, abs=2.0)

    def test_a_normal_of_nothing_leaves_it_upright(self):
        pose = settle(Facing(), 1.0, normal=(0.0, 0.0, 0.0))
        assert (pose.pitch, pose.roll) == (0.0, 0.0)

    def test_a_vertical_wall_is_kept_within_the_limit(self):
        pose = settle(Facing(max_tilt=math.radians(45)), 1.0, normal=(0.0, 0.0, -1.0))
        assert abs(pose.pitch) <= math.radians(45) + 1e-9


class TestLean:
    def test_there_is_no_lean_unless_asked_for(self):
        pose = settle(Facing(), 1.0, acceleration=(5.0, 0.0, 0.0))
        assert pose.roll == 0.0

    def test_the_body_leans_into_a_sideways_acceleration(self):
        pose = settle(Facing(lean=0.05), 1.0, acceleration=(4.0, 0.0, 0.0))
        up = rotate(pose.rotation, UP)
        assert up[0] > 0.1
        assert pose.roll == pytest.approx(-0.2, abs=0.01)

    def test_the_other_side_leans_the_other_way(self):
        pose = settle(Facing(lean=0.05), 1.0, acceleration=(-4.0, 0.0, 0.0))
        assert rotate(pose.rotation, UP)[0] < -0.1

    def test_the_lean_is_measured_across_the_heading(self):
        pose = settle(Facing(lean=0.05, heading=math.pi / 2), 1.0,
                      acceleration=(4.0, 0.0, 0.0))
        assert pose.roll == pytest.approx(0.0, abs=1e-6)

    def test_the_lean_is_limited(self):
        pose = settle(Facing(lean=1.0, max_lean=math.radians(20)), 1.0,
                      acceleration=(40.0, 0.0, 0.0))
        assert abs(pose.roll) == pytest.approx(math.radians(20), abs=1e-3)

    def test_the_lean_eases_back_out(self):
        facing = Facing(lean=0.05)
        settle(facing, 1.0, acceleration=(4.0, 0.0, 0.0))
        assert settle(facing, 1.0, acceleration=(0.0, 0.0, 0.0)).roll == pytest.approx(
            0.0, abs=0.01)


class TestReset:
    def test_a_character_put_somewhere_else_faces_where_it_is_told(self):
        facing = Facing()
        settle(facing, 1.0, velocity=(3.0, 0.0, 0.0), normal=slope(30.0))
        facing.reset(heading=1.5)
        assert (facing.heading, facing.pitch, facing.roll) == (1.5, 0.0, 0.0)


class TestFitting:
    def test_a_model_three_tall_in_a_capsule_one_eight_tall_is_scaled_by_point_six(self):
        fit = fit_to_height((-1.0, 0.0, -1.0), (1.0, 3.0, 1.0), 1.8)
        assert fit.scale == pytest.approx(0.6)

    def test_its_feet_stand_at_the_capsule_base(self):
        fit = fit_to_height((-1.0, -0.5, -1.0), (1.0, 2.5, 1.0), 1.8)
        assert fit.scale * -0.5 + fit.translation[1] == pytest.approx(0.0)
        assert fit.scale * 2.5 + fit.translation[1] == pytest.approx(1.8)

    def test_the_base_may_be_somewhere_else(self):
        fit = fit_to_height((0.0, 0.0, 0.0), (1.0, 2.0, 1.0), 2.0, base=-1.0)
        assert fit.translation[1] == pytest.approx(-1.0)

    def test_it_is_placed_on_a_transform(self):
        node = Transform()
        Fit(0.5, (0.0, 0.25, 0.0)).place(node)
        assert tuple(node.scale) == (0.5, 0.5, 0.5)
        assert tuple(node.translation) == (0.0, 0.25, 0.0)

    @pytest.mark.parametrize('low, high', [
        ((0, 1, 0), (0, 1, 0)), ((0, 2, 0), (0, 1, 0)),
        ((0, 0, 0), (0, float('inf'), 0)), ((0, float('nan'), 0), (0, 1, 0))])
    def test_a_model_with_no_height_is_left_as_it_is(self, low, high):
        assert fit_to_height(low, high, 1.8) == Fit(1.0, (0.0, 0.0, 0.0))

    def test_a_capsule_with_no_height_leaves_the_model_as_it_is(self):
        assert fit_to_height((0, 0, 0), (1, 2, 1), 0.0) == Fit(1.0, (0.0, 0.0, 0.0))


class TestModelBounds:
    def test_the_bounds_are_those_of_the_models_vertices(self):
        from OpenGLContext.character import CharacterModel

        from ._character_assets import character_glb
        low, high = model_bounds(CharacterModel.load(character_glb()))
        assert (low[1], high[1]) == (-1.0, 1.0)

    def test_a_model_with_no_triangles_has_none(self):
        from OpenGLContext.character import CharacterModel

        from ._character_assets import skeleton_glb
        assert model_bounds(CharacterModel.load(skeleton_glb())) is None
