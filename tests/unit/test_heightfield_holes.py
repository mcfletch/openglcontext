"""Ground that is not there, because a road runs inside the hill.

A height field is a surface, so a tunnel through a hill has nowhere to say the
hill is hollow. ``holes(x, z)`` is where that is said, and both the drawn
surface and the collider are cut by it --
:class:`~OpenGLContext.physics.heightfield.HeightFieldColliders` takes the same
callable :meth:`~HeightField.mesh` does.

One rule, applied by one piece of code
(:func:`OpenGLContext.scenegraph.terrain.holes.cut`): agreeing by construction is
worth more than agreeing by care, since what a car drives through and what a
player sees are the same hill. The cases here hold the two to each other; what
the rule *is* -- the edge of the opening, and the centre of a triangle too small
to have one -- is in ``test_terrain_holes.py``.

The hole these use falls on the grid lines of the field they use it on, which is
where a cut needs no corners of its own and every index still means what it
meant.
"""

import numpy as np
import pytest

from OpenGLContext.physics.heightfield import HeightFieldColliders
from OpenGLContext.scenegraph.terrain import HeightField, SplatTerrain
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain


def flat(res=17, extent=160.0):
    """A level field, so a triangle's centre is decided by x and z alone."""
    return HeightField(np.zeros((res, res)), extent=extent, relief=10.0)


def middle(x, z):
    """A square hole through the centre of the world."""
    return (np.abs(np.asarray(x)) < 30.0) & (np.abs(np.asarray(z)) < 30.0)


def centres(field, indices, vertices=None):
    """Where each triangle of a mesh sits, in world XZ.

    ``vertices`` are the ones the indices go with, which is the field's own grid
    until a cut appends the corners it needed to it.
    """
    inter = field.mesh()[0] if vertices is None else vertices
    points = np.asarray(inter).reshape(-1, 6)[:, :3]
    return points[np.asarray(indices).reshape(-1, 3)].mean(axis=1)


class TestAFieldWithNothingMissing:
    def test_asking_for_no_holes_changes_nothing(self) -> None:
        field = flat()
        plain = field.mesh()[1]
        assert np.array_equal(field.mesh(holes=None)[1], plain)

    def test_a_hole_that_catches_nothing_changes_nothing(self) -> None:
        field = flat()

        def nowhere(x, z):
            return np.zeros(np.shape(x), dtype=bool)

        assert np.array_equal(field.mesh(holes=nowhere)[1], field.mesh()[1])

    def test_the_whole_field_is_two_triangles_a_cell(self) -> None:
        field = flat(res=5)
        assert field.mesh()[1].size == (5 - 1) * (5 - 1) * 6


class TestAFieldWithAHoleInIt:
    def test_the_triangles_over_the_hole_are_gone(self) -> None:
        field = flat()
        kept = field.mesh(holes=middle)[1]
        where = centres(field, kept)
        assert not middle(where[:, 0], where[:, 2]).any()

    def test_everything_else_is_still_there(self) -> None:
        field = flat()
        whole = centres(field, field.mesh()[1])
        kept = centres(field, field.mesh(holes=middle)[1])
        outside = whole[~middle(whole[:, 0], whole[:, 2])]
        assert len(kept) == len(outside)

    def test_something_was_actually_removed(self) -> None:
        """A test that passes on a hole nothing fell into proves nothing."""
        field = flat()
        assert field.mesh(holes=middle)[1].size < field.mesh()[1].size

    def test_the_vertices_are_left_alone(self) -> None:
        """Only triangles go. A vertex nothing indexes costs a little memory and
        saves renumbering every index that survives."""
        field = flat()
        assert len(field.mesh(holes=middle)[0]) == len(field.mesh()[0])

    def test_the_indices_that_remain_are_valid(self) -> None:
        field = flat()
        inter, kept = field.mesh(holes=middle)
        assert kept.max() < len(inter)


class TestTheDrawnSurfaceAndTheCollidedOneAgree:
    """The same hill, so the same rule, so the same triangles."""

    def test_a_triangle_in_a_hole_is_in_neither(self) -> None:
        field = flat()
        drawn = centres(field, field.mesh(holes=middle)[1])
        collided = self._collider_centres(field, middle)
        for where in (drawn, collided):
            assert not middle(where[:, 0], where[:, 2]).any()

    def test_they_keep_the_same_count(self) -> None:
        """Chunking lays them out differently; how many survive is the same."""
        field = flat()
        drawn = centres(field, field.mesh(holes=middle)[1])
        collided = self._collider_centres(field, middle)
        assert len(drawn) == len(collided)

    def test_they_keep_the_same_triangles(self) -> None:
        field = flat()
        drawn = centres(field, field.mesh(holes=middle)[1])
        collided = self._collider_centres(field, middle)
        # Plain floats: the drawn mesh is float32 and the collider float64, so
        # comparing numpy scalars compares their dtypes as well as their values.
        def rounded(a):
            return sorted((round(float(x), 3), round(float(z), 3))
                          for x, z in a[:, [0, 2]])
        assert rounded(drawn) == rounded(collided)

    def _collider_centres(self, field, holes):
        """Every triangle the collider would build, as world-XZ centres."""
        world = _NoWorld()
        colliders = HeightFieldColliders(world, field, chunk=field.extent,
                                         holes=holes)
        found = []
        for i in range(colliders._across):
            for j in range(colliders._across):
                points, indices = colliders._patch(i, j)
                if len(indices):
                    found.append(points[indices].mean(axis=1))
        return np.concatenate(found) if found else np.zeros((0, 3))


class _NoWorld:
    """Enough of a physics world to build patches without stepping one."""

    def add_body(self, *args, **named):
        return object()

    def remove_body(self, *args, **named):
        pass


@pytest.mark.parametrize('res', [5, 9, 33])
def test_a_hole_works_at_any_resolution(res) -> None:
    """The hole is 60 m square wherever the grid's lines happen to fall.

    Its sides are cut on the side, whatever the cell size; its four corners turn
    inside a cell, and a corner is resolved to the triangle it is in.
    """
    field = flat(res=res)
    cell = 160.0 / (res - 1)
    vertices, kept = field.mesh(holes=middle)
    where = centres(field, kept, vertices)
    assert not middle(where[:, 0], where[:, 2]).any()
    assert _ground(vertices, kept) == pytest.approx(160.0 ** 2 - 60.0 ** 2,
                                                    abs=4 * cell ** 2)


def _ground(vertices, indices):
    """How much ground a mesh covers, measured in the ground plane."""
    p = np.asarray(vertices).reshape(-1, 6)[:, [0, 2]][
        np.asarray(indices).reshape(-1, 3)]
    return float(0.5 * np.abs(
        (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
        - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0])).sum())


class TestTheTerrainNodeCarriesItThrough:
    """A game builds a `SplatTerrain`, not a bare field."""

    def make(self, holes=None):
        # The control map is a path here, as in the node's own cases: what is
        # under test is the mesh, and loading an image needs a GL context.
        return SplatTerrain(flat(), ['ground'], 'control.png',
                            material_fn=lambda *a, **k: {}, holes=holes)

    def test_it_takes_a_holes_callable(self) -> None:
        assert self.make(holes=middle).holes is middle

    def test_none_by_default_so_nothing_changes(self) -> None:
        assert self.make().holes is None

    def test_it_is_the_mesh_the_node_would_upload(self) -> None:
        """`_init_gl` needs a context; what it asks the field for does not."""
        node = self.make(holes=middle)
        inter, idx = node.hf.mesh(holes=node.holes)
        where = centres(node.hf, idx)
        assert not middle(where[:, 0], where[:, 2]).any()
        assert idx.size < node.hf.mesh()[1].size


class TestAStreamedWorldsGround:
    """`TilesTerrain` builds the ground for a world that pages its tiles.

    Its holes are settable after construction, and have to be: a game reads the
    tileset to build the terrain and reads it again to find the roads, and only
    the roads know where the bores are. The mesh is not built until the first
    draw, so setting them in between is in time.
    """

    def test_the_ground_starts_with_none(self, tmp_path) -> None:
        node = _tiles_terrain(tmp_path)
        assert node.holes is None and node.ground.holes is None

    def test_setting_them_reaches_the_ground(self, tmp_path) -> None:
        node = _tiles_terrain(tmp_path)
        node.holes = middle
        assert node.ground.holes is middle

    def test_the_mesh_it_would_upload_has_the_hole_in_it(self, tmp_path) -> None:
        node = _tiles_terrain(tmp_path)
        whole = node.field.mesh()[1].size
        node.holes = middle
        assert node.field.mesh(holes=node.holes)[1].size < whole

    def test_clearing_them_puts_the_ground_back(self, tmp_path) -> None:
        node = _tiles_terrain(tmp_path)
        node.holes = middle
        node.holes = None
        assert node.ground.holes is None


def _tiles_terrain(tmp_path):
    """A `TilesTerrain` with a field and a ground, built without a GL context."""
    node = TilesTerrain.__new__(TilesTerrain)
    node.field = flat()
    node.ground = SplatTerrain(node.field, ['ground'], 'control.png',
                               material_fn=lambda *a, **k: {})
    return node
