"""A model drawn many times costs its parts, not its parts times its copies.

:class:`~OpenGLContext.scenegraph.instancedshape.InstancedModel` stands for a
whole loaded model placed repeatedly. What it has to get right is that the
picture is the one the hierarchy would have drawn -- a part ends up where the
transforms above it would have put it -- while the number of objects the render
pass sees stops depending on how many copies there are.
"""

import numpy as np
import pytest

from OpenGLContext import visitor
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.instancedshape import (
    InstancedModel, model_parts,
)
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform
from OpenGLContext.scenegraph.box import Box
from vrml.vrml97 import nodetypes


def a_model():
    """Two parts under a scaled root, each offset a different way."""
    return Transform(scale=(2.0, 2.0, 2.0), children=[
        Transform(translation=(1.0, 0.0, 0.0), children=[
            Shape(geometry=Box(size=(1, 1, 1)))]),
        Transform(translation=(0.0, 3.0, 0.0), children=[
            Shape(geometry=Box(size=(1, 1, 1)))]),
    ])


def carried(point, matrix):
    """Where ``point`` lands under ``matrix``, row-vector convention."""
    return (np.append(np.asarray(point, 'f'), 1.0) @ np.asarray(matrix, 'f'))[:3]


class TestFlatteningAModel:
    """``model_parts`` composes the transforms above each shape away."""

    def test_every_shape_is_found(self):
        assert len(model_parts(a_model())) == 2

    def test_a_part_carries_the_transforms_above_it(self):
        parts = model_parts(a_model())
        # The first part sits at x=1 inside a root scaled by two.
        assert np.allclose(carried((0, 0, 0), parts[0][1]), (2, 0, 0))
        assert np.allclose(carried((0, 0, 0), parts[1][1]), (0, 6, 0))

    def test_a_bare_shape_is_its_own_part_at_the_identity(self):
        shape = Shape(geometry=Box(size=(1, 1, 1)))
        parts = model_parts(shape)
        assert len(parts) == 1
        assert np.allclose(parts[0][1], np.identity(4))

    def test_a_model_with_no_geometry_has_no_parts(self):
        assert model_parts(Transform(children=[Transform()])) == []


class TestPlacingCopies:
    """Where a part of a copy ends up, against where the hierarchy put it."""

    def placement_of(self, pool, part, copy=0):
        return np.asarray(pool.children[part].placements, 'f').reshape(-1, 4, 4)[copy]

    def test_a_copy_is_the_part_matrix_composed_with_the_copys(self):
        pool = InstancedModel(model=a_model())
        move = np.identity(4, dtype='f')
        move[3, :3] = (10.0, 0.0, 0.0)
        pool.place(move[None])
        # Part one sits at x=2 within the model; a copy moved to x=10 puts it
        # at x=12, which is what a Transform around the whole model would do.
        assert np.allclose(carried((0, 0, 0), self.placement_of(pool, 0)),
                           (12, 0, 0))
        assert np.allclose(carried((0, 0, 0), self.placement_of(pool, 1)),
                           (10, 6, 0))

    def test_every_copy_gets_every_part(self):
        pool = InstancedModel(model=a_model())
        copies = np.stack([np.identity(4, dtype='f') for _ in range(5)])
        pool.place(copies)
        for shape in pool.children:
            assert len(np.asarray(shape.placements).reshape(-1, 4, 4)) == 5

    def test_placing_nothing_draws_nothing(self):
        pool = InstancedModel(model=a_model())
        pool.place(np.stack([np.identity(4, dtype='f')]))
        pool.place([])
        for shape in pool.children:
            assert shape.instancePlacements() is None

    def test_the_copies_can_be_replaced_with_a_different_number(self):
        pool = InstancedModel(model=a_model())
        pool.place(np.stack([np.identity(4, dtype='f') for _ in range(3)]))
        pool.place(np.stack([np.identity(4, dtype='f') for _ in range(7)]))
        placed = np.asarray(pool.children[0].placements, 'f').reshape(-1, 4, 4)
        assert len(placed) == 7


class TestWhatTheRenderPassSees:
    """The point of the whole thing, stated as a count."""

    def rendering_paths(self, node):
        return len(visitor.find(node, nodetypes.Rendering))

    @pytest.mark.parametrize('copies', [1, 8, 64, 512])
    def test_the_object_count_does_not_follow_the_copy_count(self, copies):
        pool = InstancedModel(model=a_model())
        pool.place(np.stack([np.identity(4, dtype='f') for _ in range(copies)]))
        assert self.rendering_paths(pool) == 2

    def test_the_hierarchy_it_replaces_does_follow_it(self):
        """The cost being avoided, so the comparison is not taken on trust."""
        copies = Group(children=[
            Transform(children=[a_model()]) for _ in range(64)])
        assert self.rendering_paths(copies) == 128


class TestABlendedSetDrawsEveryCopy:
    """A translucent instanced shape draws once per placement, like an opaque one.

    The transparent pass draws record by record rather than in batches, so it
    reaches the node's own draw and nothing else. A set that did not expand its
    placements there would put one copy at the set's origin and lose the rest --
    and every pickup with a glass shell around it is such a set.
    """

    class _Recorder:
        """Stands in for the pass: remembers the matrix each draw was given."""

        def __init__(self):
            self.matrix = np.identity(4, dtype='f')
            self.projection = np.identity(4, dtype='f')
            self.seen = []

    def shape(self, copies):
        from OpenGLContext.scenegraph.instancedshape import InstancedShape
        moves = np.stack([np.identity(4, dtype='f') for _ in range(copies)])
        for at in range(copies):
            moves[at][3, 0] = float(at)
        return InstancedShape(geometry=Box(size=(1, 1, 1)), placements=moves)

    def drawn(self, shape, method):
        mode = self._Recorder()
        original = getattr(type(shape).__mro__[1], method)

        def record(self_, mode=None):
            mode.seen.append(np.asarray(mode.matrix, 'f').copy())

        setattr(type(shape).__mro__[1], method, record)
        try:
            getattr(shape, method)(mode=mode)
        finally:
            setattr(type(shape).__mro__[1], method, original)
        return mode.seen

    def test_the_opaque_draw_visits_every_placement(self):
        assert len(self.drawn(self.shape(4), 'Render')) == 4

    def test_the_blended_draw_visits_every_placement(self):
        assert len(self.drawn(self.shape(4), 'RenderTransparent')) == 4

    def test_each_blended_copy_is_drawn_where_it_was_placed(self):
        seen = self.drawn(self.shape(3), 'RenderTransparent')
        assert [float(m[3, 0]) for m in seen] == [0.0, 1.0, 2.0]

    def test_a_blended_set_with_nothing_placed_draws_nothing(self):
        from OpenGLContext.scenegraph.instancedshape import InstancedShape
        empty = InstancedShape(geometry=Box(size=(1, 1, 1)))
        assert self.drawn(empty, 'RenderTransparent') == []
        assert empty.drawsNothing()


class TestCullingTheCopiesOfASet:
    """Being one object need not cost the per-copy culling.

    A set's bounding box covers every placement, so a set spread through a level
    is never outside the frustum and every copy would be drawn. Asking the set
    which of its copies a given frustum keeps gives that culling back without
    giving up the single draw.
    """

    def shape(self, xs):
        from OpenGLContext.scenegraph.instancedshape import InstancedShape
        moves = np.stack([np.identity(4, dtype='f') for _ in xs])
        for at, x in enumerate(xs):
            moves[at][3, 0] = float(x)
        return InstancedShape(geometry=Box(size=(1, 1, 1)), placements=moves)

    def frustum(self, low, high):
        """A slab keeping only ``low <= x <= high``, as two clipping planes."""
        class _Frustum:
            planes = np.array([(1.0, 0.0, 0.0, -low),
                               (-1.0, 0.0, 0.0, high)], dtype='f')
        return _Frustum()

    def kept(self, shape, frustum):
        found = shape.visiblePlacements(frustum, np.identity(4, dtype='f'))
        return None if found is None else sorted(
            round(float(m[3, 0])) for m in found)

    def test_copies_outside_the_frustum_are_dropped(self):
        shape = self.shape([-100, 0, 100])
        assert self.kept(shape, self.frustum(-10, 10)) == [0]

    def test_copies_inside_are_all_kept(self):
        shape = self.shape([-2, 0, 2])
        assert self.kept(shape, self.frustum(-10, 10)) == [-2, 0, 2]

    def test_a_set_wholly_outside_keeps_none(self):
        shape = self.shape([100, 200])
        assert self.kept(shape, self.frustum(-10, 10)) == []

    def test_a_copy_straddling_the_edge_is_kept(self):
        """Its box crosses the plane, so some of it is on screen."""
        shape = self.shape([10])
        assert self.kept(shape, self.frustum(-10, 10)) == [10]

    def test_no_frustum_is_no_answer_rather_than_no_copies(self):
        """Not knowing where the edges are has to mean drawing everything."""
        assert self.shape([0, 1]).visiblePlacements(None, np.identity(4)) is None

    def test_a_set_with_nothing_placed_has_no_answer(self):
        from OpenGLContext.scenegraph.instancedshape import InstancedShape
        empty = InstancedShape(geometry=Box(size=(1, 1, 1)))
        assert empty.visiblePlacements(self.frustum(-1, 1),
                                       np.identity(4)) is None

    def test_the_world_matrix_moves_the_whole_set(self):
        """A set under a transform is culled where the transform puts it."""
        shape = self.shape([0])
        far = np.identity(4, dtype='f')
        far[3, 0] = 100.0
        assert len(shape.visiblePlacements(self.frustum(-10, 10), far)) == 0
