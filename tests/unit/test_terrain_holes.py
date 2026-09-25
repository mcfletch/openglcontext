"""Cutting a surface back to the edge of the opening in it.

A height field is drawn as a grid of triangles, and an opening in the ground --
the mouth of a tunnel's bore -- has an edge of its own that runs wherever it
runs. :func:`OpenGLContext.scenegraph.terrain.holes.cut` is what brings the two
together: the triangles the edge crosses are cut on the edge itself, so the
ground stops where the opening starts rather than a cell either side of it.

The cases measure that where it shows: the area that survives, whether anything
kept reaches into the opening, and whether the cut surface is still the surface
the field reports.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain import HeightField
from OpenGLContext.scenegraph.terrain.holes import cut
from OpenGLContext.physics.heightfield import HeightFieldColliders

EXTENT = 160.0
RADIUS = 37.0


def flat(res=17, extent=EXTENT):
    """A level field: area in the ground plane is area on the surface."""
    return HeightField(np.zeros((res, res)), extent=extent, relief=10.0)


def ramp(res=17, extent=EXTENT):
    """Ground that leans, so a vertex off the grid has a height to get right."""
    axis = np.linspace(0.0, 1.0, res)
    _, tilt = np.meshgrid(axis, axis)
    return HeightField(tilt, extent=extent, relief=40.0)


def circle(x, z):
    """A round opening through the middle of the world."""
    return np.hypot(np.asarray(x, 'd'), np.asarray(z, 'd')) < RADIUS


def nowhere(x, z):
    return np.zeros(np.shape(np.asarray(x)), dtype=bool)


def area_of(vertices, triangles):
    """How much ground the mesh covers, measured in the ground plane."""
    if not len(triangles):
        return 0.0
    p = np.asarray(vertices, 'd')[:, [0, 2]][np.asarray(triangles)]
    return float(0.5 * np.abs(
        (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
        - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0])).sum())


def surface(field, holes=None):
    """The field's mesh as (vertices, triangles), cut by ``holes``."""
    inter, idx = field.mesh()
    triangles = np.asarray(idx).reshape(-1, 3)
    if holes is None:
        return inter, triangles
    return cut(inter, triangles, holes)


class TestAnOpeningWithNothingInIt:
    def test_ground_no_opening_touches_is_left_as_it_was(self) -> None:
        field = flat()
        inter, triangles = field.mesh()
        vertices, kept = cut(inter, triangles.reshape(-1, 3), nowhere)
        assert np.array_equal(kept, triangles.reshape(-1, 3))
        assert np.array_equal(vertices, inter)

    def test_an_opening_over_everything_leaves_nothing(self) -> None:
        field = flat()
        inter, triangles = field.mesh()
        _, kept = cut(inter, triangles.reshape(-1, 3),
                      lambda x, _z: np.ones(np.shape(x), dtype=bool))
        assert not len(kept)

    def test_an_opening_that_leaves_only_slivers_leaves_none(self) -> None:
        """Everything is cut, and every piece a cut left is in the opening: the
        answer is an empty mesh rather than an empty concatenation."""
        field = flat(res=5)
        inter, triangles = field.mesh()
        _, kept = cut(inter, triangles.reshape(-1, 3),
                      lambda x, _z: np.asarray(x) > -EXTENT / 2 + 1e-9)
        assert not len(kept)
        assert np.asarray(kept).shape[1:] == (3,)


class TestTheGroundStopsWhereTheOpeningStarts:
    def test_the_area_left_is_the_area_outside_the_opening(self) -> None:
        """Cell-sized rounding would leave a percent or two of it behind."""
        field = flat()
        vertices, kept = surface(field, circle)
        wanted = EXTENT ** 2 - np.pi * RADIUS ** 2
        assert area_of(vertices, kept) == pytest.approx(wanted, rel=0.002)

    def test_no_ground_is_left_inside_the_opening(self) -> None:
        field = flat()
        vertices, kept = surface(field, circle)
        points = np.asarray(vertices, 'd')[kept][:, :, [0, 2]]
        # The middle of each triangle, and a point close to each of its corners:
        # ground that poked into the opening would show at one or the other.
        middle = points.mean(axis=1)
        for probe in [middle] + [0.9 * points[:, i] + 0.1 * middle
                                 for i in range(3)]:
            assert not circle(probe[:, 0], probe[:, 1]).any()

    def test_the_edge_of_what_is_left_follows_the_opening(self) -> None:
        field = flat()
        vertices, kept = surface(field, circle)
        points = np.asarray(vertices, 'd')[kept][:, :, [0, 2]]
        radius = np.hypot(points[..., 0], points[..., 1])
        # Every corner is outside the opening, and the closest of them sits on
        # its edge rather than a cell short of it. A cell here is ten metres.
        assert radius.min() >= RADIUS
        assert radius.min() < RADIUS + 0.01

    def test_an_opening_smaller_than_a_cell_still_takes_its_triangle(self) -> None:
        """The rule the collider has always used, kept: a triangle whose centre
        is in an opening goes, however small the opening is."""
        field = flat(res=5)
        cell = EXTENT / 4.0
        inter, indices = field.mesh()
        whole = indices.reshape(-1, 3)
        centre = inter[whole[7]][:, [0, 2]].mean(axis=0)

        def speck(x, z):
            return (np.hypot(np.asarray(x, 'd') - centre[0],
                             np.asarray(z, 'd') - centre[1]) < cell * 0.05)

        _, kept = cut(inter, whole, speck)
        assert len(kept) == len(whole) - 1


class TestTheCutSurfaceIsStillTheSurface:
    def test_a_new_corner_stands_on_the_ground_the_field_reports(self) -> None:
        field = ramp()
        vertices, kept = surface(field, circle)
        new = np.asarray(vertices, 'd')[len(field.mesh()[0]):]
        assert len(new) > 8
        assert new[:, 1] == pytest.approx(
            np.asarray(field.sample(new[:, 0], new[:, 2]), 'd'), abs=1e-3)

    def test_the_vertices_that_were_there_are_still_there_and_in_place(self) -> None:
        field = ramp()
        inter, _ = field.mesh()
        vertices, _ = surface(field, circle)
        assert np.array_equal(vertices[:len(inter)], inter)

    def test_every_attribute_comes_across_not_only_the_position(self) -> None:
        """A new corner carries an interpolated normal, so the shading over the
        cut cell is the shading the whole cell had."""
        field = ramp()
        inter, _ = field.mesh()
        vertices, _ = surface(field, circle)
        new = np.asarray(vertices, 'd')[len(inter):]
        assert np.linalg.norm(new[:, 3:], axis=1) == pytest.approx(1.0, abs=1e-6)

    def test_the_two_triangles_on_a_cut_edge_meet_exactly(self) -> None:
        """Watertight by construction: a crossing belongs to the edge, not to
        the triangle that asked for it, so both sides get the same vertex."""
        field = flat()
        vertices, kept = surface(field, circle)
        edges = np.sort(np.stack([kept[:, [0, 1]], kept[:, [1, 2]],
                                  kept[:, [2, 0]]], axis=1).reshape(-1, 2),
                        axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        # Every interior edge is shared; the rest are the border of the field
        # and the rim of the opening.
        assert (counts <= 2).all()
        assert (counts == 2).sum() > len(kept)


class TestTheFieldAndTheColliderCutTheSame:
    def test_the_drawn_ground_and_the_driven_ground_have_the_same_area(self) -> None:
        field = flat()
        vertices, indices = field.mesh(holes=circle)
        drawn = area_of(vertices, np.asarray(indices).reshape(-1, 3))
        world = _NoWorld()
        colliders = HeightFieldColliders(world, field, chunk=field.extent,
                                         holes=circle)
        total = 0.0
        for i in range(colliders._across):
            for j in range(colliders._across):
                points, indices = colliders._patch(i, j)
                total += area_of(points, indices)
        assert total == pytest.approx(drawn, rel=1e-6)


class _NoWorld:
    def add_body(self, *args, **named):
        return object()

    def remove_body(self, *args, **named):
        pass
