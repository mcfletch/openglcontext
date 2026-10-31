"""The wireframes of the proxy overlay (:mod:`OpenGLContext.physics.debugdraw`).

:class:`~OpenGLContext.physics.debugdraw.ProxyOverlay` places one shared unit box
and one shared unit sphere per body; ``Physics.show_proxies`` mounting it is
tested in ``test_physics_world_api.py``. These build the shared wireframes,
which need no GL context.
"""
import numpy as np

from OpenGLContext.physics.debugdraw import _ring, _sphere_edges, _unit_box_wire, _unit_sphere_wire


def test_unit_wireframes_have_expected_edge_counts():
    """The shared unit box wireframe has 12 edges; the sphere three 16-seg rings."""
    box = _unit_box_wire()
    assert len(box.coordIndex) == 12 * 3              # [a, b, -1] per edge
    sphere = _unit_sphere_wire()
    assert len(sphere.coordIndex) == 3 * 16 * 3       # three rings of 16 segments


def test_the_unit_box_spans_half_a_unit_each_way():
    points = np.asarray(_unit_box_wire().coord.point, dtype='d')
    assert np.allclose(points.min(axis=0), -0.5) and np.allclose(points.max(axis=0), 0.5)


def test_a_ring_closes_on_its_radius():
    edges = _ring(np.zeros(3), 2.0, np.array([1.0, 0, 0]), np.array([0, 0, 1.0]), n=8)
    assert len(edges) == 8
    assert np.allclose(edges[0][0], edges[-1][1])
    assert all(np.isclose(np.linalg.norm(a), 2.0) for a, _b in edges)


def test_the_sphere_rings_lie_on_the_sphere():
    centre = np.array([1.0, 2.0, 3.0])
    for a, b in _sphere_edges(centre, 0.5):
        assert np.isclose(np.linalg.norm(a - centre), 0.5)
        assert np.isclose(np.linalg.norm(b - centre), 0.5)
