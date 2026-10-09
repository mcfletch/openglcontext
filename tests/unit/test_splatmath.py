"""Gaussian splats' arithmetic, with no GL: covariance, colour, footprint and order.

The formulas are the ones KHR_gaussian_splatting states (the splat's 3D
covariance from its scale and rotation, the spherical-harmonic colour to
degree 3 with its 0.5 bias, the 3-sigma footprint) and the projection of the
3D Gaussian splatting paper (Kerbl et al. 2023, section 4).
"""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import splatmath

IDENTITY = (0.0, 0.0, 0.0, 1.0)


def _about(axis, angle):
    """The unit quaternion (x, y, z, w) turning by `angle` radians about `axis`."""
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    return tuple(axis * math.sin(angle / 2)) + (math.cos(angle / 2),)


# --- rotations and covariances ----------------------------------------------


def test_the_identity_quaternion_is_no_turn():
    assert np.allclose(splatmath.rotations([IDENTITY]), np.identity(3))


def test_a_quarter_turn_about_z_takes_x_to_y():
    turned = splatmath.rotations([_about((0, 0, 1), math.pi / 2)])[0]
    assert np.allclose(turned @ (1, 0, 0), (0, 1, 0))


def test_a_quaternion_of_any_length_is_its_direction():
    q = np.asarray(_about((1, 2, 3), 0.7))
    assert np.allclose(splatmath.rotations([q * 5.0]), splatmath.rotations([q]))


def test_a_quaternion_and_its_negation_are_one_turn():
    q = np.asarray(_about((1, 0, 1), 1.1))
    assert np.allclose(splatmath.rotations([-q]), splatmath.rotations([q]))


def test_a_zero_quaternion_is_no_turn():
    assert np.allclose(splatmath.rotations([(0, 0, 0, 0)]), np.identity(3))


def test_a_rotation_is_orthonormal():
    turned = splatmath.rotations([_about((0.3, -1, 2), 2.5)])[0]
    assert np.allclose(turned @ turned.T, np.identity(3))
    assert np.isclose(np.linalg.det(turned), 1.0)


def test_an_unturned_covariance_is_the_squared_scales():
    found = splatmath.covariances([(1.0, 2.0, 3.0)], [IDENTITY])[0]
    assert np.allclose(found, np.diag((1.0, 4.0, 9.0)))


def test_a_turned_covariance_swaps_its_axes():
    found = splatmath.covariances([(1.0, 2.0, 0.5)],
                                  [_about((0, 0, 1), math.pi / 2)])[0]
    assert np.allclose(found, np.diag((4.0, 1.0, 0.25)))


def test_a_negative_scale_spreads_as_its_magnitude():
    assert np.allclose(splatmath.covariances([(-1.0, 2.0, -3.0)], [IDENTITY]),
                       splatmath.covariances([(1.0, 2.0, 3.0)], [IDENTITY]))


def test_a_zero_scale_is_flat_along_that_axis():
    found = splatmath.covariances([(0.0, 1.0, 1.0)], [IDENTITY])[0]
    assert found[0, 0] == 0.0 and found[1, 1] == 1.0


def test_a_covariance_is_symmetric():
    found = splatmath.covariances([(0.2, 0.7, 1.3)], [_about((1, 1, 0), 0.9)])[0]
    assert np.allclose(found, found.T)
    assert np.all(np.linalg.eigvalsh(found) >= -1e-12)


# --- spherical harmonics ----------------------------------------------------


def test_degree_zero_is_the_constant_term_plus_one_half():
    coefficients = np.array([[[1.0, -1.0, 0.0]]])
    found = splatmath.colours(coefficients, [(0.0, 0.0, -1.0)])
    expected = np.array([0.5 + splatmath.SH_C0, 0.5 - splatmath.SH_C0, 0.5])
    assert np.allclose(found, expected)


def test_a_colour_below_zero_is_clamped():
    found = splatmath.colours(np.array([[[-10.0, 0.0, 0.0]]]), [(0.0, 0.0, 1.0)])
    assert found[0, 0] == 0.0


def test_degree_one_follows_the_view_direction():
    coefficients = np.zeros((2, 4, 3))
    coefficients[:, 3, 0] = 1.0                # m = 1 reads -x
    found = splatmath.colours(coefficients, [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)])
    assert np.isclose(found[0, 0], 0.5 - splatmath.SH_C1)
    assert np.isclose(found[1, 0], 0.5 + splatmath.SH_C1)


def test_the_basis_has_a_term_per_coefficient():
    for degree, terms in ((0, 1), (1, 4), (2, 9), (3, 16)):
        assert splatmath.sh_basis(np.array([[0.0, 0.0, 1.0]]), degree).shape == (1, terms)


def test_the_basis_matches_the_published_constants():
    x, y, z = 0.48, 0.6, 0.64
    basis = splatmath.sh_basis(np.array([[x, y, z]]), 3)[0]
    expected = [
        0.2820947917738781,
        -0.4886025119029199 * y, 0.4886025119029199 * z, -0.4886025119029199 * x,
        1.092548430592079 * x * y, -1.092548430592079 * y * z,
        0.31539156525252005 * (2 * z * z - x * x - y * y),
        -1.092548430592079 * x * z, 0.5462742152960395 * (x * x - y * y),
        -0.5900435899266435 * y * (3 * x * x - y * y), 2.890611442640554 * x * y * z,
        -0.4570457994644657 * y * (4 * z * z - x * x - y * y),
        0.3731763325901154 * z * (2 * z * z - 3 * x * x - 3 * y * y),
        -0.4570457994644657 * x * (4 * z * z - x * x - y * y),
        1.445305721320277 * z * (x * x - y * y),
        -0.5900435899266435 * x * (x * x - 3 * y * y),
    ]
    assert np.allclose(basis, expected)


def test_the_basis_is_orthonormal_over_the_sphere():
    """Each pair of basis functions integrates to 0 over the sphere, each square to 1."""
    rng = np.random.default_rng(3)
    points = rng.normal(size=(200000, 3))
    points /= np.linalg.norm(points, axis=1)[:, None]
    basis = splatmath.sh_basis(points, 3)
    gram = basis.T @ basis * (4.0 * math.pi / len(points))
    assert np.allclose(gram, np.identity(16), atol=0.03)


def test_a_zero_direction_reads_only_degree_zero():
    coefficients = np.ones((1, 16, 3))
    found = splatmath.colours(coefficients, [(0.0, 0.0, 0.0)])
    assert np.allclose(found, 0.5 + splatmath.SH_C0)


def test_a_direction_is_normalised_before_the_basis():
    coefficients = np.zeros((1, 4, 3))
    coefficients[0, 2] = 0.2
    assert np.allclose(splatmath.colours(coefficients, [(0, 0, 7.0)]),
                       splatmath.colours(coefficients, [(0, 0, 1.0)]))


@pytest.mark.parametrize('counts, degree', [
    ((), -1),
    ((5,), 0),
    ((5, 5, 5, 5), 1),
    ((5, 5, 5), 0),                        # degree one is three fields, or none
    ((5, 5, 5, 5) + (5,) * 5 + (5,) * 7, 3),
    ((5, 0, 0, 0, 5, 5, 5, 5, 5), 0),      # a degree above a missing one is not read
    ((0, 5, 5, 5), -1),
    ((5, 5, 3, 5), 0),                     # a short field is not complete
])
def test_the_degree_is_the_last_complete_one(counts, degree):
    assert splatmath.complete_degree(counts, 5) == degree


# --- projection and footprint ----------------------------------------------


def test_a_sphere_projects_to_its_angular_size():
    """A round splat of deviation s at distance d spreads f*s/d pixels."""
    sigma, distance, focal = 0.1, 4.0, 500.0
    found = splatmath.projected(np.identity(3) * sigma ** 2,
                                [(0.0, 0.0, -distance)], np.identity(3),
                                (focal, focal), dilation=0.0)[0]
    expected = (focal * sigma / distance) ** 2
    assert np.allclose(found, (expected, 0.0, expected))


def test_projection_adds_the_dilation_to_each_axis():
    found = splatmath.projected(np.zeros((3, 3)), [(0.0, 0.0, -1.0)],
                                np.identity(3), (100.0, 100.0))[0]
    assert np.allclose(found, (splatmath.DILATION, 0.0, splatmath.DILATION))


def test_an_orthographic_projection_ignores_distance():
    covariance = np.diag((0.04, 0.01, 0.0))
    near, far = (splatmath.projected(covariance, [(0, 0, -z)], np.identity(3),
                                     (50.0, 50.0), perspective=False, dilation=0.0)[0]
                 for z in (1.0, 10.0))
    assert np.allclose(near, far)
    assert np.allclose(near, (0.04 * 2500, 0.0, 0.01 * 2500))


def test_a_view_turn_turns_the_footprint():
    """The view's rotation turns the covariance before it is projected."""
    covariance = np.diag((1.0, 0.01, 0.01))
    quarter = splatmath.rotations([_about((0, 0, 1), math.pi / 2)])[0]
    plain = splatmath.projected(covariance, [(0, 0, -5)], np.identity(3),
                                (10.0, 10.0), dilation=0.0)[0]
    turned = splatmath.projected(covariance, [(0, 0, -5)], quarter,
                                 (10.0, 10.0), dilation=0.0)[0]
    assert np.allclose(turned, (plain[2], 0.0, plain[0]))


def test_off_axis_splats_are_clamped_to_beyond_the_frustum():
    covariance = np.identity(3) * 0.01
    far_out = splatmath.projected(covariance, [(1000.0, 0.0, -1.0)], np.identity(3),
                                  (100.0, 100.0), dilation=0.0, limit=(1.3, 1.3))[0]
    edge = splatmath.projected(covariance, [(1.3, 0.0, -1.0)], np.identity(3),
                               (100.0, 100.0), dilation=0.0, limit=(1.3, 1.3))[0]
    assert np.allclose(far_out, edge)


def test_the_footprint_of_a_round_splat_is_round():
    major, minor = splatmath.footprint(np.array([(4.0, 0.0, 4.0)]))
    assert np.allclose(np.linalg.norm(major), 6.0)
    assert np.allclose(np.linalg.norm(minor), 6.0)
    assert np.isclose(float(np.dot(major[0], minor[0])), 0.0)


def test_the_footprint_follows_the_long_axis():
    """A spread of 9 px^2 along (1, 1) and 1 px^2 across it."""
    a = c = 5.0
    b = 4.0
    major, minor = splatmath.footprint(np.array([(a, b, c)]))
    assert np.allclose(np.abs(major[0]), 9.0 / math.sqrt(2.0))
    assert np.allclose(np.abs(minor[0]), 3.0 / math.sqrt(2.0))


def test_a_degenerate_footprint_has_no_minor_axis():
    major, minor = splatmath.footprint(np.array([(1.0, 1.0, 1.0)]))
    assert np.allclose(np.linalg.norm(minor[0]), 0.0)
    assert np.isclose(np.linalg.norm(major[0]), 3.0 * math.sqrt(2.0))


# --- order ------------------------------------------------------------------


def test_eye_depth_is_the_row_vector_product():
    modelview = np.identity(4)
    modelview[3, :3] = (0.0, 0.0, -10.0)
    found = splatmath.depths(np.array([(0, 0, 1.0), (0, 0, -1.0)]), modelview)
    assert np.allclose(found, (-9.0, -11.0))


def test_back_to_front_draws_the_farthest_first():
    order = splatmath.back_to_front(np.array([-1.0, -5.0, -3.0, -2.0]))
    assert list(order) == [1, 2, 3, 0]
    assert order.dtype == np.uint32


def test_back_to_front_keeps_ties_in_index_order():
    assert list(splatmath.back_to_front(np.zeros(5))) == [0, 1, 2, 3, 4]


def test_back_to_front_resolves_the_quantised_steps():
    """Depths a 65536th of the range apart still sort."""
    depths = -np.linspace(0.0, 1.0, 1000)
    rng = np.random.default_rng(1)
    shuffled = rng.permutation(1000)
    order = splatmath.back_to_front(depths[shuffled])
    assert np.all(np.diff(depths[shuffled][order]) >= 0)


def test_back_to_front_of_nothing_is_nothing():
    assert len(splatmath.back_to_front(np.zeros(0))) == 0


def test_back_to_front_takes_extreme_depths():
    order = splatmath.back_to_front(np.array([1e308, -1e308, 0.0]))
    assert list(order) == [1, 2, 0]


def test_distance_is_the_length_of_the_eye_space_position():
    modelview = np.identity(4)
    modelview[3, :3] = (0.0, 0.0, -10.0)
    found = splatmath.distances(np.array([(0, 0, 1.0), (3.0, 4.0, 10.0)]), modelview)
    assert np.allclose(found, (9.0, 5.0))


def test_a_perspective_order_is_by_distance_from_the_camera():
    """Off to the side is farther by distance though nearer by depth."""
    positions = np.array([(0.8, 0.0, -2.0), (0.3, 0.0, -2.1)])
    order, _sorted = splatmath.DepthOrder().update(positions, np.identity(4), 1)
    assert list(order) == [0, 1]
    order, _sorted = splatmath.DepthOrder().update(positions, np.identity(4), 1,
                                                   perspective=False)
    assert list(order) == [1, 0]


def _camera_at(position):
    """The row-vector modelview of an unturned camera at `position`"""
    modelview = np.identity(4)
    modelview[3, :3] = -np.asarray(position, float)
    return modelview


def test_a_perspective_order_is_kept_while_the_camera_only_turns():
    positions = np.random.default_rng(2).normal(size=(50, 3))
    keeper = splatmath.DepthOrder()
    view = _camera_at((0.0, 0.0, 10.0))
    first, sorted_first = keeper.update(positions, view, generation=1)
    turned = view.copy()
    turned[:3, :3] = splatmath.rotations([_about((0, 1, 0), 0.7)])[0].T
    turned[3, :3] = (0.0, 0.0, -10.0) @ turned[:3, :3]
    second, sorted_second = keeper.update(positions, turned, generation=1)
    assert sorted_first and not sorted_second
    assert second is first


def test_a_perspective_order_is_kept_through_a_scale():
    positions = np.random.default_rng(2).normal(size=(50, 3))
    keeper = splatmath.DepthOrder()
    view = _camera_at((0.0, 0.0, 10.0))
    keeper.update(positions, view, generation=1)
    _order, resorted = keeper.update(positions, view @ np.diag((3.0, 3.0, 3.0, 1.0)), 1)
    assert not resorted


def test_a_move_within_the_tolerance_keeps_the_perspective_order():
    """The tolerance is a fraction of the distance to the nearest of the splats' box."""
    positions = np.random.default_rng(2).uniform(-1.0, 1.0, size=(50, 3))
    keeper = splatmath.DepthOrder(tolerance=0.01)
    keeper.update(positions, _camera_at((0.0, 0.0, 11.0)), generation=1)
    assert not keeper.update(positions, _camera_at((0.09, 0.0, 11.0)), generation=1)[1]
    order, resorted = keeper.update(positions, _camera_at((0.11, 0.0, 11.0)), generation=1)
    assert resorted
    distances = splatmath.distances(positions, _camera_at((0.11, 0.0, 11.0)))
    assert np.all(np.diff(distances[order]) <= 0)


def test_any_move_among_the_splats_sorts_again():
    positions = np.random.default_rng(2).uniform(-1.0, 1.0, size=(50, 3))
    keeper = splatmath.DepthOrder()
    keeper.update(positions, _camera_at((0.0, 0.0, 0.5)), generation=1)
    assert not keeper.update(positions, _camera_at((0.0, 0.0, 0.5)), generation=1)[1]
    assert keeper.update(positions, _camera_at((0.0, 0.0, 0.5001)), generation=1)[1]


def test_an_orthographic_order_is_kept_while_the_view_only_moves():
    positions = np.random.default_rng(2).normal(size=(50, 3))
    keeper = splatmath.DepthOrder()
    first, sorted_first = keeper.update(positions, np.identity(4), 1, perspective=False)
    moved = np.identity(4)
    moved[3, :3] = (3.0, -2.0, -7.0)
    second, sorted_second = keeper.update(positions, moved, 1, perspective=False)
    assert sorted_first and not sorted_second
    assert second is first


def test_an_orthographic_order_is_kept_through_a_scale():
    positions = np.random.default_rng(2).normal(size=(50, 3))
    keeper = splatmath.DepthOrder()
    keeper.update(positions, np.identity(4), 1, perspective=False)
    _order, resorted = keeper.update(positions, np.identity(4) * 3.0, 1, perspective=False)
    assert not resorted


def test_a_turn_beyond_the_tolerance_sorts_an_orthographic_order_again():
    positions = np.random.default_rng(2).normal(size=(50, 3))
    keeper = splatmath.DepthOrder(tolerance=math.radians(0.25))
    keeper.update(positions, np.identity(4), 1, perspective=False)
    small = np.identity(4)
    small[:3, :3] = splatmath.rotations([_about((0, 1, 0), math.radians(0.1))])[0]
    assert not keeper.update(positions, small, 1, perspective=False)[1]
    large = np.identity(4)
    large[:3, :3] = splatmath.rotations([_about((0, 1, 0), math.radians(1.0))])[0]
    order, resorted = keeper.update(positions, large, 1, perspective=False)
    assert resorted
    depths = splatmath.depths(positions, large)
    assert np.all(np.diff(depths[order]) >= 0)


def test_the_tolerance_is_measured_from_the_last_sort():
    """Small turns that add up past the tolerance sort again."""
    positions = np.random.default_rng(2).normal(size=(20, 3))
    keeper = splatmath.DepthOrder(tolerance=math.radians(0.25))
    keeper.update(positions, np.identity(4), 1, perspective=False)
    sorts = 0
    for step in range(1, 11):
        view = np.identity(4)
        view[:3, :3] = splatmath.rotations([_about((0, 1, 0), math.radians(0.1 * step))])[0]
        sorts += keeper.update(positions, view, 1, perspective=False)[1]
    assert sorts == 3


def test_a_change_of_projection_sorts_again():
    positions = np.random.default_rng(2).normal(size=(50, 3))
    keeper = splatmath.DepthOrder()
    keeper.update(positions, np.identity(4), 1, perspective=False)
    assert keeper.update(positions, np.identity(4), 1)[1]
    assert keeper.update(positions, np.identity(4), 1, perspective=False)[1]


def test_new_splats_sort_again():
    positions = np.random.default_rng(2).normal(size=(50, 3))
    keeper = splatmath.DepthOrder()
    keeper.update(positions, np.identity(4), generation=1)
    assert keeper.update(positions, np.identity(4), generation=2)[1]


def test_a_mirrored_view_sorts_an_orthographic_order_again():
    positions = np.random.default_rng(2).normal(size=(50, 3))
    keeper = splatmath.DepthOrder()
    keeper.update(positions, np.identity(4), 1, perspective=False)
    flipped = np.diag((1.0, 1.0, -1.0, 1.0))
    order, resorted = keeper.update(positions, flipped, 1, perspective=False)
    assert resorted
    assert np.all(np.diff(splatmath.depths(positions, flipped)[order]) >= 0)


def test_an_empty_set_sorts_to_nothing():
    order, _sorted = splatmath.DepthOrder().update(np.zeros((0, 3)), np.identity(4), 1)
    assert len(order) == 0


# --- view directions --------------------------------------------------------


def test_the_turn_is_the_linear_part_with_unit_columns():
    linear = splatmath.rotations([_about((0, 0, 1), 0.4)])[0] @ np.diag((2.0, 3.0, 0.5))
    turn = splatmath.turn_of(linear)
    assert np.allclose(turn, splatmath.rotations([_about((0, 0, 1), 0.4)])[0])


def test_a_mirror_keeps_its_reflection_in_the_turn():
    turn = splatmath.turn_of(np.diag((-2.0, 1.0, 1.0)))
    assert np.allclose(turn, np.diag((-1.0, 1.0, 1.0)))


def test_a_flattened_axis_is_kept_as_it_is():
    turn = splatmath.turn_of(np.diag((2.0, 0.0, 1.0)))
    assert np.allclose(turn, np.diag((1.0, 0.0, 1.0)))


def test_the_view_direction_is_from_the_camera_to_the_splat_in_its_own_turn():
    """A scale stretches the centres but not the direction the colour is read along."""
    turn = splatmath.rotations([_about((0, 1, 0), math.pi / 2)])[0]
    eye = np.array([(2.0, 0.0, -2.0)])
    found = splatmath.view_directions(eye, turn)
    expected = turn.T @ (np.array((2.0, 0.0, -2.0)) / math.sqrt(8.0))
    assert np.allclose(found, [expected])


def test_an_orthographic_view_direction_is_the_view_axis():
    found = splatmath.view_directions(np.array([(5.0, 1.0, -2.0)]), np.identity(3),
                                      perspective=False)
    assert np.allclose(found, [(0.0, 0.0, -1.0)])


def test_a_splat_at_the_camera_reads_degree_zero():
    assert np.allclose(splatmath.view_directions(np.zeros((1, 3)), np.identity(3)), 0.0)


# --- the packed set ---------------------------------------------------------


def _fields(count=3, **named):
    rng = np.random.default_rng(5)
    fields = dict(
        positions=rng.normal(size=(count, 3)),
        orientations=np.tile(IDENTITY, (count, 1)),
        scales=np.full((count, 3), 0.1),
        opacities=np.full(count, 0.8),
        harmonics=[rng.normal(size=(count, 3))],
    )
    fields.update(named)
    return fields


def test_a_set_packs_each_splat_into_three_texels():
    found = splatmath.SplatSet.from_fields(**_fields())
    rows = found.geometry_rows()
    assert rows.shape == (3, 12) and rows.dtype == np.float32
    assert np.allclose(rows[:, :3], found.centres)
    assert np.allclose(rows[:, 3], 0.8)
    assert np.allclose(rows[:, 4:10], [[0.01, 0, 0, 0.01, 0, 0.01]] * 3)


def test_a_set_packs_its_harmonics_by_the_texel():
    fields = _fields(harmonics=[np.ones((3, 3))] + [np.full((3, 3), k) for k in (1, 2, 3)])
    found = splatmath.SplatSet.from_fields(**fields)
    assert found.degree == 1
    rows = found.harmonic_rows()
    assert rows.shape == (3, 12)                     # 4 coefficients, 3 texels of 4
    assert np.allclose(rows[0], [1, 1, 1, 1, 1, 1, 2, 2, 2, 3, 3, 3])


def test_degree_zero_harmonics_pad_to_a_texel():
    found = splatmath.SplatSet.from_fields(**_fields())
    assert found.harmonic_rows().shape == (3, 4)


def test_missing_orientations_are_unturned():
    found = splatmath.SplatSet.from_fields(**_fields(orientations=[]))
    assert found.count == 3
    assert np.allclose(found.covariances[:, [0, 3, 5]], 0.01)


def test_missing_opacities_are_opaque():
    assert np.allclose(splatmath.SplatSet.from_fields(**_fields(opacities=[])).opacities, 1.0)


def test_missing_harmonics_are_mid_grey():
    found = splatmath.SplatSet.from_fields(**_fields(harmonics=[]))
    assert found.degree == 0
    assert np.allclose(splatmath.colours(found.harmonics, np.zeros((3, 3))), 0.5)


def test_a_short_field_shortens_the_set():
    found = splatmath.SplatSet.from_fields(**_fields(opacities=[0.5, 0.5]))
    assert found.count == 2
    assert found.short == {'opacities': 2}


def test_no_scales_is_no_splats():
    assert splatmath.SplatSet.from_fields(**_fields(scales=[])).count == 0


def test_opacity_is_held_to_zero_and_one():
    found = splatmath.SplatSet.from_fields(**_fields(opacities=[-1.0, 0.5, 4.0]))
    assert list(found.opacities) == [0.0, 0.5, 1.0]


def test_a_splat_with_a_non_finite_value_is_left_out():
    positions = np.zeros((4, 3))
    positions[1, 0] = np.nan
    scales = np.full((4, 3), 0.1)
    scales[2, 2] = np.inf
    opacities = np.array([1.0, 1.0, 1.0, np.nan])
    found = splatmath.SplatSet.from_fields(**_fields(
        count=4, positions=positions, scales=scales, opacities=opacities))
    assert found.count == 1
    assert found.dropped == 3


def test_huge_harmonics_are_held_to_half_precision():
    found = splatmath.SplatSet.from_fields(**_fields(harmonics=[np.full((3, 3), 1e9)]))
    assert np.all(np.isfinite(found.harmonic_rows().astype(np.float16)))


def test_the_bounds_hold_each_ellipsoid_to_three_deviations():
    found = splatmath.SplatSet.from_fields(
        positions=[(0, 0, 0), (10, 0, 0)], orientations=[IDENTITY, IDENTITY],
        scales=[(1, 2, 3), (0.5, 0.5, 0.5)], opacities=[1, 1], harmonics=[])
    low, high = found.bounds()
    assert np.allclose(low, (-3, -6, -9))
    assert np.allclose(high, (11.5, 6, 9))


def test_a_turned_ellipsoid_is_bounded_as_turned():
    found = splatmath.SplatSet.from_fields(
        positions=[(0, 0, 0)], orientations=[_about((0, 0, 1), math.pi / 2)],
        scales=[(1, 2, 3)], opacities=[1], harmonics=[])
    low, high = found.bounds()
    assert np.allclose(high, (6, 3, 9))


def test_an_empty_set_has_no_bounds():
    assert splatmath.SplatSet.from_fields(**_fields(count=0)).bounds() is None


# --- making splats ----------------------------------------------------------


def test_sphere_directions_are_unit_and_spread_evenly():
    directions = splatmath.sphere_directions(500)
    assert directions.shape == (500, 3)
    assert np.allclose(np.linalg.norm(directions, axis=1), 1.0)
    assert np.allclose(directions.mean(axis=0), 0.0, atol=0.01)


@pytest.mark.parametrize('degree', [0, 1, 2, 3])
def test_fitted_harmonics_recover_the_coefficients_that_made_the_colours(degree):
    rng = np.random.default_rng(degree)
    coefficients = rng.normal(scale=0.03, size=(4, (degree + 1) ** 2, 3))
    directions = splatmath.sphere_directions(200)
    seen = np.stack([splatmath.colours(np.repeat(coefficients[[index]], 200, axis=0),
                                       directions) for index in range(4)])
    fitted = splatmath.fit_harmonics(directions, seen, degree)
    assert fitted.shape == coefficients.shape
    assert np.allclose(fitted, coefficients, atol=1e-9)


def test_a_fit_of_a_lower_degree_keeps_the_mean_colour():
    directions = splatmath.sphere_directions(400)
    seen = np.clip(0.5 + 0.4 * directions[None, :, :1], 0.0, 1.0).repeat(3, axis=2)
    fitted = splatmath.fit_harmonics(directions, seen, 0)
    assert np.allclose(fitted[0, 0] * splatmath.SH_C0 + 0.5, seen[0].mean(axis=0), atol=1e-3)


def test_a_fit_needs_as_many_directions_as_coefficients():
    with pytest.raises(ValueError, match='16 coefficients'):
        splatmath.fit_harmonics(splatmath.sphere_directions(10), np.zeros((1, 10, 3)), 3)


def test_a_splat_facing_a_normal_lies_across_it():
    normals = np.array([(0, 0, 1.0), (1.0, 0, 0), (0, 0, -1.0), (0, 3.0, 4.0)])
    turns = splatmath.facing(normals)
    across = splatmath.rotations(turns) @ np.array((0.0, 0.0, 1.0))
    assert np.allclose(across, normals / np.linalg.norm(normals, axis=1)[:, None])
    assert np.allclose(np.linalg.norm(turns, axis=1), 1.0)


def test_a_zero_normal_faces_as_it_is():
    assert np.allclose(splatmath.facing(np.zeros((1, 3))), [(0, 0, 0, 1)])
