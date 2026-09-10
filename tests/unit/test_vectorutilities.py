"""`OpenGLContext.vectorutilities`, the array-of-vectors helpers."""
import math
import random

import pytest

import numpy

from OpenGLContext.arrays import allclose, asarray
from OpenGLContext.vectorutilities import (
    colinear, crossProduct, crossProduct4, magnitude, normalise, orientToXYZR,
)


def test_orient_of_two_equal_vectors_is_no_rotation():
    assert orientToXYZR((0, 0, 1), (0, 0, 1)) == (0, 1, 0, 0)


def test_orient_of_opposed_vectors_is_a_half_turn():
    x, y, z, angle = orientToXYZR((0, 0, -1), (0, 0, 1))
    assert allclose(angle, math.pi)


@pytest.mark.parametrize('seed', [1, 2, 3])
def test_orient_of_nearly_opposed_vectors_has_an_angle(seed):
    """Rounding must not push the arc cosine past its domain.

    Two vectors that are almost exactly opposed give a dot product a hair
    outside -1, and the arc cosine of that is not a number -- which reaches a
    scene as a rotation field, where it makes the node it turns disappear.
    """
    rng = random.Random(seed)
    for _ in range(2000):
        a = tuple(rng.uniform(-1, 1) for _ in range(3))
        b = tuple(-v * rng.uniform(0.999, 1.001) for v in a)
        result = asarray(orientToXYZR(a, b), 'd')
        assert not numpy.isnan(result).any(), (a, b, result)


def test_magnitude_of_a_set_of_vectors():
    assert allclose(magnitude([[3, 4, 0], [0, 0, 2]]), [5.0, 2.0])


def test_normalise_leaves_a_zero_vector_alone():
    assert allclose(normalise([[0, 0, 0]]), [[0, 0, 0]])


def test_cross_product_of_axes():
    assert allclose(crossProduct([1, 0, 0], [0, 1, 0]), [[0, 0, 1]])


def test_cross_product_of_four_component_vectors_keeps_w():
    result = crossProduct4([1, 0, 0, 1], [0, 1, 0, 1])
    assert allclose(result, [[0, 0, 1, 1]])


def test_colinear_points_are_reported():
    points = asarray([[0, 0, 0], [1, 1, 1], [2, 2, 2]], 'f')
    assert colinear(points) is not None
    bent = asarray([[0, 0, 0], [1, 1, 1], [2, 0, 2]], 'f')
    assert colinear(bent) is None
