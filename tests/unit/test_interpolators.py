"""VRML97 interpolator nodes: a fraction in, a value out.

An interpolator holds a ``key`` of ascending fractions and a ``keyValue`` of the
values they name.  ``set_fraction`` between two keys blends the two values;
outside the range it clamps to the end.  ``on_set_fraction`` both publishes the
answer on ``value_changed`` and returns it, which is how a caller that drives an
interpolator directly -- ``OpenGLContext.move.smooth`` reads a position out of
one every frame -- gets the value without a round trip through the event.
"""

import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import interpolators


def _scalar(**named):
    return interpolators.ScalarInterpolator(
        key=[0.0, 0.5, 1.0], keyValue=[0.0, 10.0, 20.0], **named)


class TestASingleValuePerKey:
    def test_a_fraction_on_a_key_gives_that_key_s_value(self):
        node = _scalar()
        assert node.on_set_fraction(0.5) == 10.0
        assert node.value_changed == 10.0

    def test_a_fraction_between_keys_blends_the_two(self):
        node = _scalar()
        assert node.on_set_fraction(0.25) == pytest.approx(5.0)

    def test_a_fraction_past_the_last_key_clamps_to_the_last_value(self):
        node = _scalar()
        assert node.on_set_fraction(2.0) == 20.0

    def test_a_fraction_before_the_first_key_clamps_to_the_first_value(self):
        node = interpolators.ScalarInterpolator(
            key=[1.0, 2.0], keyValue=[7.0, 9.0])
        assert node.on_set_fraction(0.0) == 7.0
        assert node.value_changed == 7.0

    def test_an_interpolator_with_no_values_produces_none(self):
        node = interpolators.ScalarInterpolator()
        assert node.on_set_fraction(0.5) is None


class TestPositions:
    def test_the_midpoint_of_two_positions(self):
        node = interpolators.PositionInterpolator(
            key=[0.0, 1.0], keyValue=[[0, 0, 0], [2, 4, 6]])
        x, y, z = node.on_set_fraction(0.5)
        assert (x, y, z) == pytest.approx((1.0, 2.0, 3.0))

    def test_a_position_below_the_first_key_still_unpacks(self):
        """``move.smooth`` unpacks the answer, so every path has to give one."""
        node = interpolators.PositionInterpolator(
            key=[0.25, 1.0], keyValue=[[1, 2, 3], [4, 5, 6]])
        x, y, z = node.on_set_fraction(0.0)
        assert (x, y, z) == pytest.approx((1.0, 2.0, 3.0))


class TestOrientations:
    def test_the_midpoint_of_two_rotations_about_one_axis(self):
        node = interpolators.OrientationInterpolator(
            key=[0.0, 1.0],
            keyValue=[[0, 1, 0, 0.0], [0, 1, 0, math.pi / 2]],
        )
        x, y, z, angle = node.on_set_fraction(0.5)
        assert (x, y, z) == pytest.approx((0.0, 1.0, 0.0))
        assert angle == pytest.approx(math.pi / 4)

    def test_a_key_hit_gives_the_orientation_unchanged(self):
        node = interpolators.OrientationInterpolator(
            key=[0.0, 1.0],
            keyValue=[[0, 1, 0, 0.0], [1, 0, 0, math.pi]],
        )
        assert list(node.on_set_fraction(1.0)) == pytest.approx(
            [1.0, 0.0, 0.0, math.pi])


class TestSetsOfValuesPerKey:
    """A CoordinateInterpolator names several points at each key."""

    def _node(self):
        return interpolators.CoordinateInterpolator(
            key=[0.0, 1.0],
            keyValue=[[0, 0, 0], [1, 0, 0],
                      [0, 2, 0], [1, 2, 0]],
        )

    def test_a_key_hit_gives_that_key_s_whole_set(self):
        result = self._node().on_set_fraction(0.0)
        assert np.asarray(result).tolist() == [[0, 0, 0], [1, 0, 0]]

    def test_the_midpoint_blends_every_point_in_the_set(self):
        result = self._node().on_set_fraction(0.5)
        assert np.allclose(np.asarray(result), [[0, 1, 0], [1, 1, 0]])

    def test_a_fraction_past_the_last_key_gives_the_last_set(self):
        result = self._node().on_set_fraction(2.0)
        assert np.asarray(result).tolist() == [[0, 2, 0], [1, 2, 0]]

    def test_a_fraction_before_the_first_key_gives_the_first_set(self):
        node = interpolators.CoordinateInterpolator(
            key=[0.5, 1.0],
            keyValue=[[0, 0, 0], [1, 0, 0],
                      [0, 2, 0], [1, 2, 0]],
        )
        result = node.on_set_fraction(0.0)
        assert np.asarray(result).tolist() == [[0, 0, 0], [1, 0, 0]]

    def test_an_interpolator_with_no_values_produces_none(self):
        assert interpolators.CoordinateInterpolator().on_set_fraction(0.5) is None
