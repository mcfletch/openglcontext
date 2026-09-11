"""The quaternion class, which nothing else covered.

`tests/unit/test_quaternion_arrays.py` looks like it does, and does not: that
covers the array helpers in `OpenGLContext.loaders.gltf.animation`, which are a
separate implementation. This module had only the `test()` function inside it,
which nothing runs.

Written before reworking the module's imports, so that a change of which
`sqrt` and which `acos` it reaches for is held to the behaviour it had.
"""

import math

import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.quaternion import Quaternion, fromEuler, fromMatrix, fromXYZR


def unit(q):
    """The quaternion's elements, as a plain list."""
    return [float(x) for x in q.internal]


class TestFromXYZR:
    """A VRML rotation: an axis and an angle in radians."""

    def test_the_scalar_part_is_the_half_angle_cosine(self):
        angle = 1.2
        q = fromXYZR(0, 1, 0, angle)
        assert unit(q)[0] == pytest.approx(math.cos(angle / 2.0))

    def test_the_axis_is_normalised_first(self):
        """A caller's axis need not be unit; the rotation is the same."""
        assert unit(fromXYZR(0, 3, 0, 0.7)) == pytest.approx(unit(fromXYZR(0, 1, 0, 0.7)))

    def test_a_zero_angle_is_the_identity(self):
        assert unit(fromXYZR(0, 1, 0, 0)) == pytest.approx([1, 0, 0, 0])

    def test_the_axis_keeps_double_precision(self):
        """An axis whose unit form is not exact in single precision -- and a
        camera orientation or an animated rotation is rarely axis-aligned. The
        rounding is invisible in one rotation and accumulates over a chain of
        them, so it has to not happen at all rather than be small."""
        axis = np.array([1.0, 2.0, 3.0])
        expected = axis / np.linalg.norm(axis)
        recovered = np.array(fromXYZR(1.0, 2.0, 3.0, 0.7).XYZR()[:3])
        assert np.allclose(recovered, expected, rtol=0, atol=1e-15)

    def test_the_angle_comes_back_to_double_precision(self):
        assert fromXYZR(1.0, 2.0, 3.0, 0.7).XYZR()[3] == pytest.approx(
            0.7, rel=0, abs=1e-15)


class TestFromEuler:
    """Rotations about x, then y, then z."""

    def test_one_axis_matches_the_axis_angle_form(self):
        assert unit(fromEuler(x=0.4)) == pytest.approx(unit(fromXYZR(1, 0, 0, 0.4)))

    def test_no_rotation_at_all_is_the_identity(self):
        assert unit(fromEuler()) == pytest.approx([1, 0, 0, 0])

    def test_two_axes_compose_in_order(self):
        composed = fromXYZR(1, 0, 0, 0.4) * fromXYZR(0, 1, 0, 0.6)
        assert unit(fromEuler(x=0.4, y=0.6)) == pytest.approx(unit(composed))


class TestFromMatrix:
    """The inverse of :meth:`Quaternion.matrix`."""

    @pytest.mark.parametrize('axis,angle', [
        ((0, 1, 0), 0.7), ((1, 0, 0), 2.0), ((0, 0, 1), -1.1),
        ((1, 1, 0), 0.3),
    ])
    def test_it_round_trips_a_rotation(self, axis, angle):
        original = fromXYZR(*axis, angle)
        assert np.allclose(original.matrix('d'),
                           fromMatrix(original.matrix('d')).matrix('d'),
                           atol=1e-9)

    def test_a_half_turn_round_trips(self):
        """Where the axis terms vanish, which is what the branches are for."""
        original = fromXYZR(0, 1, 0, math.pi)
        assert np.allclose(original.matrix('d'), fromMatrix(original.matrix('d')).matrix('d'),
                           atol=1e-6)

    def test_a_4x4_has_its_translation_ignored(self):
        matrix = fromXYZR(0, 1, 0, 0.5).matrix('d')
        matrix[3][:3] = [10.0, 20.0, 30.0]
        assert np.allclose(fromMatrix(matrix).matrix('d'),
                           fromXYZR(0, 1, 0, 0.5).matrix('d'), atol=1e-9)


class TestConstruction:
    def test_the_default_is_the_identity(self):
        assert unit(Quaternion()) == pytest.approx([1, 0, 0, 0])

    def test_elements_are_normalised(self):
        q = Quaternion((2, 0, 0, 0))
        assert unit(q) == pytest.approx([1, 0, 0, 0])
        assert float(np.sqrt(np.sum(q.internal * q.internal))) == pytest.approx(1.0)

    def test_length_and_indexing(self):
        q = fromXYZR(0, 1, 0, 0.5)
        assert len(q) == 4
        assert q[0] == pytest.approx(math.cos(0.25))

    def test_the_representation_names_the_axis_and_angle(self):
        assert 'XYZR' in repr(fromXYZR(0, 1, 0, 0.5))


class TestMultiply:
    def test_by_the_identity_is_unchanged(self):
        q = fromXYZR(0, 1, 0, 0.5)
        assert unit(q * Quaternion()) == pytest.approx(unit(q))

    def test_two_turns_about_one_axis_add(self):
        combined = fromXYZR(0, 1, 0, 0.3) * fromXYZR(0, 1, 0, 0.4)
        assert unit(combined) == pytest.approx(unit(fromXYZR(0, 1, 0, 0.7)))

    def test_by_a_matrix_rotates_it(self):
        """The other branch: not a quaternion, so the matrices are combined."""
        q = fromXYZR(0, 1, 0, 0.5)
        product = q * np.identity(4, 'd')
        assert np.allclose(product, q.matrix('d'), atol=1e-6)


class TestInverse:
    def test_it_undoes_the_rotation(self):
        q = fromXYZR(1, 2, 3, 0.9)
        assert unit(q * q.inverse()) == pytest.approx([1, 0, 0, 0], abs=1e-9)

    def test_it_conjugates(self):
        w, x, y, z = unit(fromXYZR(1, 0, 0, 0.5))
        assert unit(fromXYZR(1, 0, 0, 0.5).inverse()) == pytest.approx([w, -x, -y, -z])


class TestMatrix:
    def test_the_identity_rotation_is_the_identity_matrix(self):
        assert np.allclose(Quaternion().matrix('d'), np.identity(4, 'd'), atol=1e-9)

    def test_the_inverse_flag_gives_the_transpose_rotation(self):
        q = fromXYZR(0, 1, 0, 0.6)
        assert np.allclose(q.matrix('d', inverse=True)[:3, :3],
                           q.matrix('d')[:3, :3].T, atol=1e-9)

    def test_it_rotates_a_point_by_the_angle_asked_for(self):
        """A quarter turn about y sends +x to -z, in this row-vector convention."""
        turned = np.dot(np.array([1.0, 0, 0, 1]), fromXYZR(0, 1, 0, math.pi / 2).matrix('d'))
        assert turned[:3] == pytest.approx([0, 0, -1], abs=1e-9)

    def test_the_default_dtype_is_single_precision(self):
        assert fromXYZR(0, 1, 0, 0.5).matrix().dtype == np.dtype('f')


class TestXYZR:
    """The VRML axis-plus-angle form, which is what a rotation field holds."""

    def test_it_round_trips_an_axis_and_angle(self):
        x, y, z, r = fromXYZR(0, 1, 0, 0.8).XYZR()
        assert [x, y, z] == pytest.approx([0, 1, 0], abs=1e-9)
        assert r == pytest.approx(0.8)

    def test_no_rotation_reports_the_default_axis(self):
        assert Quaternion().XYZR() == (0, 1, 0, 0)

    def test_a_scalar_part_just_over_one_is_no_rotation(self):
        """Rounding puts `w` above 1, and the arc cosine of that is undefined.

        The module has always meant to treat it as no rotation -- the comment
        beside the guard says so -- but the guard catches `ValueError`, which
        is what `math.acos` raises and what the array one does not: it answers
        `nan`, and `nan` is what came back out.
        """
        q = Quaternion.__new__(Quaternion)
        q.internal = np.array([1.00000000002, 0.0, 0.0, 0.0], 'd')
        assert not any(math.isnan(v) for v in q.XYZR())


class TestDelta:
    def test_the_angle_to_itself_is_nothing(self):
        q = fromXYZR(0, 1, 0, 0.5)
        assert q.delta(q) == pytest.approx(0.0, abs=1e-6)

    def test_it_measures_the_angle_between_two_rotations(self):
        first, second = fromXYZR(0, 1, 0, 0.5), fromXYZR(0, 1, 0, 0.9)
        assert q_angle(first, second) == pytest.approx(0.4, abs=1e-6)


def q_angle(first, second):
    """`delta`, as the docstring describes it: an angle in 0..pi."""
    return first.delta(second)


class TestSlerp:
    def test_a_fraction_of_nothing_is_the_start(self):
        first, second = fromXYZR(0, 1, 0, 0.2), fromXYZR(0, 1, 0, 1.2)
        assert unit(first.slerp(second, 0.0)) == pytest.approx(unit(first), abs=1e-9)

    def test_the_whole_of_it_is_the_end(self):
        first, second = fromXYZR(0, 1, 0, 0.2), fromXYZR(0, 1, 0, 1.2)
        assert unit(first.slerp(second, 1.0)) == pytest.approx(unit(second), abs=1e-9)

    def test_half_way_is_the_half_angle(self):
        first, second = fromXYZR(0, 1, 0, 0.2), fromXYZR(0, 1, 0, 1.2)
        assert unit(first.slerp(second, 0.5)) == pytest.approx(
            unit(fromXYZR(0, 1, 0, 0.7)), abs=1e-9)

    def test_the_result_is_a_unit_quaternion(self):
        first, second = fromXYZR(1, 0, 0, 0.3), fromXYZR(0, 0, 1, 2.0)
        got = first.slerp(second, 0.4).internal
        assert float(np.sqrt(np.sum(got * got))) == pytest.approx(1.0)

    def test_two_rotations_all_but_identical_take_the_linear_path(self):
        """The branch that avoids dividing by a vanishing sine."""
        first, second = fromXYZR(0, 1, 0, 0.5), fromXYZR(0, 1, 0, 0.5000001)
        assert unit(first.slerp(second, 0.5)) == pytest.approx(unit(first), abs=1e-6)


class TestWhichImplementation:
    """The module reaches for one `sqrt` and one `acos`, and it matters which.

    `math.acos` raises on an argument just outside its domain; the array one
    answers `nan`.  The class's own guards were written for the first, so the
    module has to be explicit about which it means.
    """

    def test_the_module_names_the_array_implementation(self):
        assert quaternion.ar.implementation_name == 'numpy'
