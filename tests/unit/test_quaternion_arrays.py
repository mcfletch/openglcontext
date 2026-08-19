"""The row-at-a-time quaternion helpers, against the one-at-a-time ones.

Every one of these has a scalar sibling that has been the definition of the
answer for as long as there has been an animation player, so the test for the
array form is that it agrees with the scalar form on the same input -- for
every row, including the awkward ones: a pair a hair apart (where the ``sin``
denominator underflows), a pair pointing opposite ways (where the shorter arc
is the other one), and a half turn (where the rotation axis vanishes).
"""
import numpy as np
import pytest

from OpenGLContext.loaders.gltf.animation import (
    quat_multiply, quat_multiply_rows, quat_normalize, quat_normalize_rows,
    quat_slerp, quat_slerp_rows, quat_xyzw_to_vrml, quat_xyzw_to_vrml_rows,
)


def _awkward_pairs():
    """Pairs chosen for the branches each helper has to take."""
    identity = [0.0, 0.0, 0.0, 1.0]
    tiny = [1e-5, 0.0, 0.0, 1.0]                    # nearly parallel
    half = [0.0, 0.0, 1.0, 0.0]                     # a half turn about z
    quarter = [0.0, 0.0, np.sin(np.pi / 4), np.cos(np.pi / 4)]
    opposed = [0.0, 0.0, -np.sin(np.pi / 4), -np.cos(np.pi / 4)]
    unnormalised = [0.0, 3.0, 0.0, 4.0]
    return [
        (identity, quarter), (identity, tiny), (quarter, opposed),
        (identity, half), (half, half), (unnormalised, quarter),
        (quarter, quarter),
    ]


def _rows(pairs):
    return (np.array([a for a, _ in pairs], dtype='d'),
            np.array([b for _, b in pairs], dtype='d'))


class TestNormalize:
    def test_agrees_with_the_scalar_helper(self):
        first, _ = _rows(_awkward_pairs())

        got = quat_normalize_rows(first)

        for row, want in zip(got, [quat_normalize(q) for q in first], strict=True):
            assert np.allclose(row, want)

    def test_a_zero_quaternion_becomes_the_identity(self):
        got = quat_normalize_rows(np.zeros((2, 4)))

        assert np.allclose(got, [[0, 0, 0, 1], [0, 0, 0, 1]])


class TestSlerp:
    @pytest.mark.parametrize('u', [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_agrees_with_the_scalar_helper_at_one_fraction(self, u):
        pairs = _awkward_pairs()
        first, second = _rows(pairs)

        got = quat_slerp_rows(first, second, u)

        for row, (a, b) in zip(got, pairs, strict=True):
            assert np.allclose(row, quat_slerp(np.array(a), np.array(b), u),
                               atol=1e-12)

    def test_agrees_with_the_scalar_helper_at_a_fraction_per_row(self):
        """A cross-fade weights each joint by what drove it, so the fraction
        is a column of its own rather than one number for the skeleton."""
        pairs = _awkward_pairs()
        first, second = _rows(pairs)
        fractions = np.linspace(0.0, 1.0, len(pairs))

        got = quat_slerp_rows(first, second, fractions)

        for row, (a, b), u in zip(got, pairs, fractions, strict=True):
            assert np.allclose(row, quat_slerp(np.array(a), np.array(b), u),
                               atol=1e-12)

    def test_the_result_is_a_unit_quaternion(self):
        first, second = _rows(_awkward_pairs())

        got = quat_slerp_rows(first, second, 0.3)

        assert np.allclose(np.linalg.norm(got, axis=1), 1.0)


class TestMultiply:
    def test_agrees_with_the_scalar_helper(self):
        pairs = _awkward_pairs()
        first, second = _rows(pairs)

        got = quat_multiply_rows(first, second)

        for row, (a, b) in zip(got, pairs, strict=True):
            assert np.allclose(row, quat_multiply(np.array(a), np.array(b)))


class TestToVRML:
    def test_agrees_with_the_scalar_helper(self):
        first, _ = _rows(_awkward_pairs())

        got = quat_xyzw_to_vrml_rows(first)

        for row, q in zip(got, first, strict=True):
            assert np.allclose(row, quat_xyzw_to_vrml(q))

    def test_a_vanishing_axis_gets_the_default_axis(self):
        """At no rotation the axis terms cancel, so an axis has to be chosen."""
        got = quat_xyzw_to_vrml_rows(np.array([[0.0, 0.0, 0.0, 1.0]]))

        assert np.allclose(got[0], [0.0, 1.0, 0.0, 0.0])
