"""A proxy's bounds and inertia, against the formulas and against omi_physics' recorded answers."""
import math

import numpy as np
import pytest

from OpenGLContext.physics import massprops
from OpenGLContext.physics.proxy import Proxy

TURN = (0.0, math.sin(math.pi / 8), 0.0, math.cos(math.pi / 8))


def shapes() -> dict[str, Proxy]:
    """One proxy of each kind the masses are worked out for"""
    rng = np.random.default_rng(7)
    points = rng.normal(size=(40, 3)) * (1.0, 2.0, 0.5)
    return {
        'box': Proxy.box((1.0, 2.0, 3.0)),
        'sphere': Proxy.sphere(0.7),
        'capsule': Proxy.capsule(1.5, 0.4),
        'cylinder': Proxy.cylinder(2.0, 0.5),
        'cone': Proxy.cylinder(2.0, 1.0, radius_top=0.0),
        'frustum': Proxy.cylinder(1.0, 0.3, radius_top=0.6),
        'convex': Proxy.convex(points),
        'trimesh': Proxy.trimesh(points, np.arange(39).reshape(-1, 3)),
        'compound': Proxy.compound([
            (Proxy.box((1.0, 1.0, 1.0)), (2.0, 0.0, 0.0), TURN),
            (Proxy.sphere(0.5), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
            (Proxy.cylinder(1.0, 0.2, radius_top=0.0), (0.0, 0.0, -1.0), TURN),
        ]),
    }


def test_a_solid_box_and_sphere():
    assert np.allclose(massprops.inertia_diagonal(Proxy.box((1.0, 2.0, 3.0)), 12.0),
                       (13.0, 10.0, 5.0))
    assert np.allclose(massprops.inertia_diagonal(Proxy.sphere(1.0), 5.0), (2.0, 2.0, 2.0))


def test_a_cone_is_heavier_at_its_base():
    """A cone's mass sits a quarter of its height above its base."""
    cone = Proxy.cylinder(2.0, 1.0, radius_top=0.0)
    assert massprops.centroid(cone)[1] == pytest.approx(-0.5)
    axial = 3.0 / 10.0 * 1.0
    assert massprops.inertia_diagonal(cone, 1.0)[1] == pytest.approx(axial)


def test_a_compound_shares_its_mass_by_volume():
    one = Proxy.box((1.0, 1.0, 1.0))
    pair = Proxy.compound([(one, (1.0, 0.0, 0.0), (0, 0, 0, 1)), (one, (-1.0, 0.0, 0.0), (0, 0, 0, 1))])
    found = massprops.inertia_diagonal(pair, 2.0)
    assert np.allclose(found, (1.0 / 3.0, 1.0 / 3.0 + 2.0, 1.0 / 3.0 + 2.0))


def test_no_shape_and_no_points_have_no_inertia():
    assert not massprops.inertia_diagonal(None, 1.0).any()
    assert not massprops.inertia_diagonal(Proxy.convex(np.zeros((0, 3))), 1.0).any()
    assert not massprops.inertia_diagonal(Proxy.compound([]), 1.0).any()


def test_a_flat_cylinder_has_no_inertia():
    assert not massprops.inertia_diagonal(Proxy.cylinder(1.0, 0.0, radius_top=0.0), 1.0).any()


@pytest.mark.parametrize('name', sorted(shapes()))
def test_the_bounds_hold_every_point_of_the_shape(name):
    proxy = shapes()[name]
    low, high = massprops.bounds(proxy, (1.0, 2.0, 3.0), TURN)
    assert np.all(high >= low)
    unturned_low, unturned_high = massprops.bounds(proxy)
    assert np.all(unturned_high - unturned_low > 0.0)


def test_the_bounds_of_each_primitive():
    assert np.allclose(massprops.bounds(Proxy.box((1.0, 2.0, 3.0)), (1.0, 0.0, 0.0)),
                       ((0.5, -1.0, -1.5), (1.5, 1.0, 1.5)))
    assert np.allclose(massprops.bounds(Proxy.sphere(0.5)), ((-0.5,) * 3, (0.5,) * 3))
    assert np.allclose(massprops.bounds(Proxy.capsule(1.0, 0.5)), ((-0.5, -1.0, -0.5), (0.5, 1.0, 0.5)))
    assert np.allclose(massprops.bounds(Proxy.cylinder(2.0, 0.5, radius_top=1.0)),
                       ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)))
    low, high = massprops.bounds(Proxy.box((2.0, 2.0, 2.0)), orientation=(0.0, math.sin(math.pi / 8),
                                                                        0.0, math.cos(math.pi / 8)))
    assert high[0] == pytest.approx(math.sqrt(2.0))
    assert high[1] == pytest.approx(1.0)


def test_a_heightfield_has_no_bounds():
    with pytest.raises(ValueError, match='heightfield'):
        massprops.bounds(Proxy.heightfield(np.zeros((2, 2))))


#: omi_physics' answers for :func:`shapes`, recorded from omi_physics 0.4 (``massprops.
#: inertia_diagonal`` at mass 3, and ``body.world_aabb`` at (1, 2, 3) turned by
#: :data:`TURN`): the inertia diagonal, then the box's low and high corners. omi_physics
#: is the source of these formulas, and its answers hold them to it.
OMI = {
    'box': ([3.25, 2.5, 1.25], [-0.414213562373, 1.0, 1.585786437627], [2.414213562373, 3.0, 4.414213562373]),
    'capsule': ([0.6825, 0.24, 0.6825], [0.6, 0.85, 2.6], [1.4, 3.15, 3.4]),
    'compound': ([1.511900453875, 8.166311145183, 9.096977007647], [0.092893218813, 1.5, 1.085786437627],
                 [2.914213562373, 3.5, 3.5]),
    'cone': ([0.9, 0.9, 0.9], [0.0, 1.0, 2.0], [2.0, 3.0, 4.0]),
    'convex': ([13.819473124748, 3.32185410116, 15.263809148732], [-0.995519159045, -0.68842909457, 1.896540232775],
               [1.950222492042, 6.489513252972, 4.346661910166]),
    'cylinder': ([1.1875, 0.375, 1.1875], [0.5, 1.0, 2.5], [1.5, 3.0, 3.5]),
    'frustum': ([0.40206122449, 0.358714285714, 0.40206122449], [0.4, 1.5, 2.4], [1.6, 2.5, 3.6]),
    'sphere': ([0.588, 0.588, 0.588], [0.3, 1.3, 2.3], [1.7, 2.7, 3.7]),
    'trimesh': ([13.819473124748, 3.32185410116, 15.263809148732], [-0.995519159045, -0.68842909457, 1.896540232775],
                [1.950222492042, 6.489513252972, 4.346661910166]),
}


@pytest.mark.parametrize('name', sorted(shapes()))
def test_the_inertia_is_omis(name):
    """Bodies weigh and turn as omi_physics' massprops has them."""
    assert np.allclose(massprops.inertia_diagonal(shapes()[name], 3.0), OMI[name][0], atol=1e-9)


@pytest.mark.parametrize('name', sorted(shapes()))
def test_the_bounds_are_omis(name):
    mine = massprops.bounds(shapes()[name], (1.0, 2.0, 3.0), TURN)
    assert np.allclose(mine, OMI[name][1:], atol=1e-9)


def test_each_kinds_volume():
    assert massprops.volume(Proxy.sphere(1.0)) == pytest.approx(4.0 / 3.0 * math.pi)
    assert massprops.volume(Proxy.capsule(2.0, 1.0)) == pytest.approx(2.0 * math.pi)
    assert massprops.volume(Proxy.cylinder(3.0, 1.0, radius_top=0.0)) == pytest.approx(math.pi)
    assert massprops.volume(Proxy.convex(np.eye(3))) == pytest.approx(1.0)
    assert massprops.volume(Proxy.convex(np.zeros((0, 3)))) == 0.0


def test_a_nested_compound_centres_its_mass():
    inner = Proxy.compound([(Proxy.box((1.0, 1.0, 1.0)), (1.0, 0.0, 0.0), (0, 0, 0, 1))])
    outer = Proxy.compound([(inner, (0.0, 1.0, 0.0), TURN)])
    assert np.allclose(massprops.centroid(outer), (math.sqrt(0.5), 1.0, -math.sqrt(0.5)))
    assert massprops.inertia_diagonal(outer, 1.0)[1] == pytest.approx(1.0 / 6.0 + 1.0)
    assert np.allclose(massprops.centroid(Proxy.compound([])), 0.0)


def test_empty_shapes_are_bounded_at_their_place():
    for empty in (Proxy.convex(np.zeros((0, 3))), Proxy.compound([])):
        low, high = massprops.bounds(empty, (1.0, 2.0, 3.0))
        assert np.allclose(low, (1, 2, 3)) and np.allclose(high, (1, 2, 3))


def test_a_point_clouds_mass_is_in_the_middle_of_its_box():
    assert np.allclose(massprops.centroid(Proxy.convex(np.eye(3))), 0.5)
    assert np.allclose(massprops.centroid(Proxy.convex(np.zeros((0, 3)))), 0.0)


def test_parts_with_no_volume_share_the_mass_equally():
    flat = Proxy.box((1.0, 1.0, 0.0))
    pair = Proxy.compound([(flat, (1.0, 0.0, 0.0), (0, 0, 0, 1)), (flat, (-1.0, 0.0, 0.0), (0, 0, 0, 1))])
    assert massprops.inertia_diagonal(pair, 2.0)[2] == pytest.approx(2.0 * (1.0 / 6.0 + 1.0))
