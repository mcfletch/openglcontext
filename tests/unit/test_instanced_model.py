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
