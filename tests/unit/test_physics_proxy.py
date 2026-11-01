"""Tests for Proxy, the shape that stands for a node in the physics world."""
import math

import numpy as np
import pytest

from OpenGLContext.physics.proxy import DEFAULT_DENSITY, STRATEGIES, Proxy
from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.transform import Transform

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def _block(size, scale=(1, 1, 1)):
    node = surfaces.shape(surfaces.block(size), LOOK)
    node.scale = scale
    return node


def _ball(radius):
    return surfaces.shape(surfaces.sphere(radius), LOOK)


def test_each_proxy_has_an_identity_of_its_own():
    first, second = Proxy.sphere(0.5), Proxy.sphere(0.5)
    assert first.uid != second.uid


@pytest.mark.parametrize('proxy, kind', [
    (Proxy.box((1, 2, 3)), 'box'), (Proxy.sphere(2.0), 'sphere'),
    (Proxy.capsule(1.0, 0.25), 'capsule'), (Proxy.cylinder(2.0, 0.5), 'cylinder'),
    (Proxy.convex(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.0]])), 'convex'),
    (Proxy.trimesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0.0]]), [[0, 1, 2]]), 'trimesh'),
])
def test_constructors_make_the_shape_they_name(proxy, kind):
    assert proxy.kind == kind


@pytest.mark.parametrize('proxy, volume', [
    (Proxy.box((1, 2, 3)), 6.0),
    (Proxy.sphere(1.0), 4.0 / 3.0 * math.pi),
    (Proxy.capsule(2.0, 0.5), math.pi * 0.25 * 2.0 + 4.0 / 3.0 * math.pi * 0.125),
    (Proxy.cylinder(2.0, 0.5), math.pi * 0.25 * 2.0),
])
def test_volume_of_a_primitive(proxy, volume):
    assert proxy.volume() == pytest.approx(volume)


def test_volume_of_a_convex_cube_is_its_volume():
    corners = np.array([[x, y, z] for x in (0, 2) for y in (0, 2) for z in (0, 2)], dtype='d')
    assert Proxy.convex(corners).volume() == pytest.approx(8.0, rel=1e-6)


def test_volume_of_a_mesh_is_its_bounds():
    points = np.array([[0, 0, 0], [2, 0, 0], [0, 3, 0], [0, 0, 4.0]])
    assert Proxy.trimesh(points, [[0, 1, 2]]).volume() == pytest.approx(24.0)


def test_mass_follows_volume_and_density():
    assert Proxy.box((1, 1, 1)).mass() == pytest.approx(DEFAULT_DENSITY)
    assert Proxy.box((1, 1, 1)).mass(density=1000.0) == pytest.approx(1000.0)


def test_mass_never_reaches_zero():
    assert Proxy.sphere(1e-6).mass() >= 0.001


def test_a_node_drawing_a_box_cooked_as_a_box():
    proxy = Proxy.from_node(_block((1, 2, 3)), 'box')
    assert proxy.kind == 'box'
    assert np.allclose(sorted(proxy.params['size']), [1, 2, 3], atol=1e-6)


def test_a_node_drawing_a_sphere_cooked_as_a_sphere():
    proxy = Proxy.from_node(_ball(0.75), 'sphere')
    assert proxy.kind == 'sphere'
    assert proxy.params['radius'] == pytest.approx(0.75, rel=0.05)


def test_a_vrml_box_node_is_cooked_as_the_box_it_draws():
    node = Transform(children=[basenodes.Shape(geometry=basenodes.Box(size=(1, 2, 3)))])
    proxy = Proxy.from_node(node, 'auto', dynamic=True)
    assert proxy.kind == 'box'
    assert np.allclose(sorted(proxy.params['size']), [1, 2, 3], atol=1e-6)


def test_a_vrml_sphere_node_is_cooked_as_the_sphere_it_draws():
    node = Transform(children=[basenodes.Shape(geometry=basenodes.Sphere(radius=0.75))])
    proxy = Proxy.from_node(node, 'sphere')
    assert proxy.kind == 'sphere'
    assert proxy.params['radius'] == pytest.approx(0.75, rel=0.05)


def test_the_node_scale_is_part_of_the_proxy():
    proxy = Proxy.from_node(_block((1, 1, 1), scale=(2, 2, 2)), 'box')
    assert np.allclose(proxy.params['size'], (2, 2, 2), atol=1e-6)


def test_auto_gives_a_static_node_its_triangles():
    assert Proxy.from_node(_block((1, 1, 1)), 'auto', dynamic=False).kind == 'trimesh'


def test_auto_fits_a_box_to_a_dynamic_node_that_is_one():
    assert Proxy.from_node(_block((1, 2, 3)), 'auto', dynamic=True).kind == 'box'


def test_auto_fits_a_sphere_to_a_dynamic_node_that_is_one():
    proxy = Proxy.from_node(_ball(0.75), 'auto', dynamic=True)
    assert proxy.kind == 'sphere'
    assert proxy.params['radius'] == pytest.approx(0.75, rel=0.02)


def test_auto_gives_a_dynamic_node_that_is_neither_its_hull():
    chamfered = surfaces.shape(surfaces.block((1, 1, 1), chamfer=0.2), LOOK)
    assert Proxy.from_node(chamfered, 'auto', dynamic=True).kind in ('convex', 'compound')


def test_convex_takes_the_hull_of_the_mesh():
    assert Proxy.from_node(_ball(1.0), 'convex').kind == 'convex'


def test_trimesh_is_refused_for_a_dynamic_body():
    with pytest.raises(ValueError, match='trimesh'):
        Proxy.from_node(_block((1, 1, 1)), 'trimesh', dynamic=True)


def test_an_unknown_strategy_is_refused_with_the_known_ones():
    with pytest.raises(ValueError, match='auto'):
        Proxy.from_node(_block((1, 1, 1)), 'blob')


def test_a_node_that_draws_nothing_is_refused():
    with pytest.raises(ValueError, match='no triangles'):
        Proxy.from_node(Transform(), 'auto')


def test_the_strategy_names_are_listed():
    assert 'sphere' in STRATEGIES and 'auto' in STRATEGIES
