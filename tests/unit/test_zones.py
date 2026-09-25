"""The arithmetic of zones: distances, classification and layering."""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import zones
from OpenGLContext.scenegraph.zones import (
    BOX, CAPSULE, CYLINDER, ELLIPSOID, INSIDE, OUTSIDE, SPHERE, STRADDLES,
    ShapeSpec, layers, named_shares, place, shares, weight,
)


def translated(x, y, z):
    matrix = np.identity(4)
    matrix[3, :3] = (x, y, z)
    return matrix


def turned_about_y(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0, -s, 0], [0, 1, 0, 0], [s, 0, c, 0], [0, 0, 0, 1]], 'd')


def scaled(x, y, z):
    return np.diag([x, y, z, 1.0])


def distance(shape, point, matrix=None):
    return float(place(shape, matrix).distance(point))


class TestBox:
    shape = ShapeSpec(BOX, size=(4.0, 2.0, 6.0))

    def test_the_centre_is_as_deep_as_the_nearest_face(self):
        assert distance(self.shape, (0, 0, 0)) == pytest.approx(-1.0)

    def test_a_point_off_a_face(self):
        assert distance(self.shape, (5.0, 0, 0)) == pytest.approx(3.0)

    def test_a_point_off_an_edge_measures_to_the_edge(self):
        assert distance(self.shape, (3.0, 2.0, 0)) == pytest.approx(math.hypot(1, 1))

    def test_the_node_translation_moves_it(self):
        assert distance(self.shape, (10.0, 0, 0), translated(10, 0, 0)) == pytest.approx(-1.0)

    def test_it_is_an_oriented_box(self):
        turned = turned_about_y(math.pi / 2)
        # Turned a quarter, its six-metre side lies along x.
        assert distance(self.shape, (2.9, 0, 0), turned) < 0.0
        assert distance(self.shape, (0, 0, 2.9), turned) > 0.0

    def test_a_non_uniform_scale_is_exact(self):
        placed = place(self.shape, scaled(2.0, 1.0, 1.0))
        assert placed.params == (4.0, 1.0, 3.0)
        assert float(placed.distance((6.0, 0, 0))) == pytest.approx(2.0)

    def test_its_volume(self):
        assert place(self.shape).volume == pytest.approx(48.0)


class TestSphere:
    shape = ShapeSpec(SPHERE, radius=2.0)

    def test_inside_and_out(self):
        assert distance(self.shape, (0, 0, 0)) == pytest.approx(-2.0)
        assert distance(self.shape, (0, 5.0, 0)) == pytest.approx(3.0)

    def test_a_uniform_scale_keeps_it_a_sphere(self):
        placed = place(self.shape, scaled(3.0, 3.0, 3.0))
        assert placed.kind == SPHERE and placed.params == (6.0,)

    def test_an_uneven_scale_makes_an_ellipsoid(self):
        placed = place(self.shape, scaled(2.0, 1.0, 1.0))
        assert placed.kind == ELLIPSOID
        assert float(placed.distance((4.0, 0, 0))) == pytest.approx(0.0, abs=1e-9)
        assert float(placed.distance((0, 2.0, 0))) == pytest.approx(0.0, abs=1e-9)
        assert float(placed.distance((5.0, 0, 0))) == pytest.approx(1.0, abs=0.05)
        assert float(placed.distance((0, 0, 0))) < 0.0


class TestCapsule:
    shape = ShapeSpec(CAPSULE, height=4.0, radius_top=1.0, radius_bottom=1.0)

    def test_the_side(self):
        assert distance(self.shape, (3.0, 0, 0)) == pytest.approx(2.0)

    def test_the_caps_are_round(self):
        assert distance(self.shape, (0, 5.0, 0)) == pytest.approx(2.0)
        assert distance(self.shape, (0, -4.0, 0)) == pytest.approx(1.0)

    def test_the_axis_is_inside(self):
        assert distance(self.shape, (0, 1.5, 0)) == pytest.approx(-1.0)

    def test_ends_of_different_sizes(self):
        cone = ShapeSpec(CAPSULE, height=4.0, radius_top=0.5, radius_bottom=1.5)
        assert distance(cone, (0, -3.5, 0)) == pytest.approx(0.0, abs=1e-9)
        assert distance(cone, (0, 2.5, 0)) == pytest.approx(0.0, abs=1e-9)


class TestCylinder:
    shape = ShapeSpec(CYLINDER, height=4.0, radius_top=1.0, radius_bottom=1.0)

    def test_the_side(self):
        assert distance(self.shape, (3.0, 0, 0)) == pytest.approx(2.0)

    def test_the_ends_are_flat(self):
        assert distance(self.shape, (0.5, 3.0, 0)) == pytest.approx(1.0)

    def test_off_the_rim(self):
        assert distance(self.shape, (2.0, 3.0, 0)) == pytest.approx(math.hypot(1, 1))

    def test_inside(self):
        assert distance(self.shape, (0, 0, 0)) == pytest.approx(-1.0)

    def test_a_tapered_cylinder(self):
        cone = ShapeSpec(CYLINDER, height=2.0, radius_top=0.0, radius_bottom=2.0)
        assert distance(cone, (2.0, -1.0, 0)) == pytest.approx(0.0, abs=1e-9)
        assert distance(cone, (0.0, 1.0, 0)) == pytest.approx(0.0, abs=1e-9)
        assert distance(cone, (0.0, 0.0, 0)) < 0.0


def test_an_unknown_shape_is_refused():
    with pytest.raises(ValueError):
        ShapeSpec('plane')


class TestWeight:
    def test_inside_is_whole(self):
        assert weight(-3.0, 2.0) == 1.0
        assert weight(0.0, 2.0) == 1.0

    def test_it_falls_away_over_the_blend(self):
        assert weight(1.0, 2.0) == pytest.approx(0.5)
        assert 0.5 < weight(0.5, 2.0) < 1.0
        assert weight(2.0, 2.0) == 0.0
        assert weight(9.0, 2.0) == 0.0

    def test_with_no_blend_the_edge_is_hard(self):
        assert weight(0.0, 0.0) == 1.0
        assert weight(0.01, 0.0) == 0.0


class TestClassify:
    room = place(ShapeSpec(BOX, size=(10.0, 4.0, 10.0)))

    def test_an_object_inside(self):
        assert self.room.classify((-1, -1, -1), (1, 1, 1)) == INSIDE

    def test_an_object_far_away(self):
        assert self.room.classify((20, 0, 0), (22, 1, 1), blend=2.0) == OUTSIDE

    def test_an_object_in_the_blend_band_straddles(self):
        assert self.room.classify((6, 0, 0), (6.5, 1, 1), blend=2.0) == STRADDLES
        assert self.room.classify((6, 0, 0), (6.5, 1, 1), blend=0.5) == OUTSIDE

    def test_a_wall_across_the_surface_straddles(self):
        assert self.room.classify((4.5, -2, -5), (5.5, 2, 5)) == STRADDLES

    def test_an_object_enclosing_the_zone_straddles(self):
        assert self.room.classify((-50, -50, -50), (50, 50, 50)) == STRADDLES

    def test_a_turned_zone(self):
        slab = place(ShapeSpec(BOX, size=(20.0, 2.0, 2.0)), turned_about_y(math.pi / 2))
        assert slab.classify((-0.5, -0.5, 8.0), (0.5, 0.5, 9.0)) == INSIDE
        assert slab.classify((8.0, -0.5, -0.5), (9.0, 0.5, 0.5)) == OUTSIDE


class TestLayers:
    def test_one_zone_takes_its_weight(self):
        stack = layers([('room', 'dim', 0.25, 0, 10.0)])
        assert [(layer.key, layer.share) for layer in stack] == [('room', 0.25)]

    def test_higher_priority_wins(self):
        stack = layers([('high', 'a', 1.0, 5, 1000.0), ('low', 'b', 1.0, 0, 1.0)])
        assert shares(stack) == {'high': 1.0, 'low': 0.0}

    def test_a_tie_goes_to_the_smaller_zone(self):
        stack = layers([('small', 'a', 1.0, 0, 1.0), ('large', 'b', 1.0, 0, 50.0)])
        assert shares(stack) == {'small': 1.0, 'large': 0.0}

    def test_the_upper_zone_fades_over_the_lower(self):
        stack = layers([('forest', 'a', 1.0, 0, 50.0), ('tunnel', 'b', 0.25, 1, 5.0)])
        assert shares(stack) == pytest.approx({'forest': 0.75, 'tunnel': 0.25})

    def test_a_zone_the_place_is_outside_is_left_out(self):
        assert layers([('far', 'a', 0.0, 0, 1.0)]) == []

    def test_the_stack_runs_from_the_bottom(self):
        stack = layers([('top', 'a', 1.0, 3, 1.0), ('bottom', 'b', 1.0, 0, 1.0)])
        assert [layer.key for layer in stack] == ['bottom', 'top']


class TestNamedShares:
    def test_a_thing_named_where_the_place_is_is_on(self):
        stack = layers([('room', {'nodes': [3]}, 1.0, 0, 1.0)])
        assert named_shares(stack, {'room': [3]}) == {3: 1.0}

    def test_off_under_a_zone_that_switches_the_setting_off(self):
        stack = layers([('room', {'nodes': [3]}, 1.0, 0, 50.0),
                        ('cupboard', None, 1.0, 0, 1.0)])
        assert named_shares(stack, {'room': [3]}) == {3: 0.0}

    def test_two_zones_naming_it_add_up_to_no_more_than_whole(self):
        stack = layers([('a', {}, 0.6, 0, 1.0), ('b', {}, 0.7, 0, 2.0)])
        found = named_shares(stack, {'a': ['bird'], 'b': ['bird']})
        assert found['bird'] == pytest.approx(0.6 + 0.7 * 0.4)

    def test_two_settings_can_be_won_by_different_zones(self):
        light = layers([('naos', 'dim', 1.0, 0, 100.0), ('west', None, 0.0, 0, 50.0)])
        sound = layers([('west', 'fountain', 0.5, 0, 50.0)])
        assert shares(light) == {'naos': 1.0}
        assert shares(sound) == {'west': 0.5}


def test_the_shader_knows_every_shape():
    for kind in zones.SHAPES + (ELLIPSOID,):
        assert zones.shader_kind(kind) > 0
