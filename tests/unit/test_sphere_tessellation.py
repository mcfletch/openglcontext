"""A Sphere's ``phi`` decides how finely it is tessellated.

``phi`` is the angular step between latitude rings, so a small one makes a
smooth sphere out of many triangles and a large one a faceted sphere out of few.
The unit meshes are shared between nodes, because a scene of a thousand
identical atoms should tessellate one sphere -- but the share has to be by
tessellation, so that two spheres asking for different detail get it.
"""

from math import pi

import pytest

from OpenGLContext.scenegraph.quadrics import Sphere


def vertex_count(node, level=0):
    coords, _indices = node.compileArrays(level)
    return len(coords)


class TestPhiDecidesTheDetail:
    def test_a_smaller_phi_makes_more_vertices(self):
        assert vertex_count(Sphere(phi=pi / 32)) > vertex_count(Sphere(phi=pi / 4))

    def test_the_order_the_spheres_are_compiled_in_does_not_matter(self):
        """Whichever is built first, each keeps its own tessellation."""
        coarse, fine = vertex_count(Sphere(phi=pi / 4)), vertex_count(Sphere(phi=pi / 32))
        assert coarse < fine
        fine_again = vertex_count(Sphere(phi=pi / 32))
        coarse_again = vertex_count(Sphere(phi=pi / 4))
        assert (coarse_again, fine_again) == (coarse, fine)

    def test_two_spheres_of_the_same_phi_share_one_mesh(self):
        first = Sphere(phi=pi / 8).compileArrays(0)[1]
        second = Sphere(phi=pi / 8).compileArrays(0)[1]
        assert first is second


class TestRadiusScalesTheSharedMesh:
    def test_the_radius_does_not_change_the_vertex_count(self):
        assert vertex_count(Sphere(radius=1.0)) == vertex_count(Sphere(radius=7.0))

    def test_the_radius_scales_the_positions(self):
        one = Sphere(radius=1.0).compileArrays(0)[0]
        seven = Sphere(radius=7.0).compileArrays(0)[0]
        assert seven[:, 0:3].max() == pytest.approx(one[:, 0:3].max() * 7.0)

    def test_the_shared_mesh_is_not_scaled_in_place(self):
        """A radius-7 sphere must not leave the shared unit mesh seven times too big."""
        Sphere(radius=7.0).compileArrays(0)
        assert Sphere(radius=1.0).compileArrays(0)[0][:, 0:3].max() == pytest.approx(1.0)
