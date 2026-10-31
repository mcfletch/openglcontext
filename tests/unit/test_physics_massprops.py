"""A proxy's bounds and inertia, against the formulas and against omi_physics' massprops."""
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


@pytest.mark.parametrize('name', sorted(shapes()))
def test_the_inertia_is_omis(name):
    """Bodies weigh and turn as they do on the omi engine."""
    pytest.importorskip('omi_physics', reason='omi_physics (the omi extra) is not installed')
    from omi_physics.massprops import inertia_diagonal  # noqa: PLC0415 the reference, where installed

    from OpenGLContext.physics.omi_adapter import omi_shape  # noqa: PLC0415 the reference, where installed

    proxy = shapes()[name]
    assert np.allclose(massprops.inertia_diagonal(proxy, 3.0), inertia_diagonal(omi_shape(proxy), 3.0))


@pytest.mark.parametrize('name', sorted(shapes()))
def test_the_bounds_are_omis(name):
    pytest.importorskip('omi_physics', reason='omi_physics (the omi extra) is not installed')
    from omi_physics.body import world_aabb  # noqa: PLC0415 the reference, where installed

    from OpenGLContext.physics.omi_adapter import omi_shape  # noqa: PLC0415 the reference, where installed

    proxy = shapes()[name]
    mine = massprops.bounds(proxy, (1.0, 2.0, 3.0), TURN)
    theirs = world_aabb(omi_shape(proxy), (1.0, 2.0, 3.0), np.asarray(TURN))
    assert np.allclose(mine, theirs, atol=1e-9)


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
