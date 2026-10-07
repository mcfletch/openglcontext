"""Billboard: a group its children are drawn in, where its parent places it.

The children are not yet turned toward the viewer; a path through a Billboard
has its parent's transform, so the scene it is in is drawn.
"""
import numpy as np

from OpenGLContext.scenegraph import nodepath
from OpenGLContext.scenegraph.basenodes import Billboard, Shape, Sphere, Transform, sceneGraph


def test_a_path_through_one_has_its_parents_transform():
    shape = Shape(geometry=Sphere())
    billboard = Billboard(children=[shape])
    moved = Transform(translation=(1, 2, 3), children=[billboard])
    graph = sceneGraph(children=[moved])
    through = nodepath.NodePath([]) + graph + moved + billboard + shape
    beside = nodepath.NodePath([]) + graph + moved
    assert np.allclose(through.transformMatrix(), beside.transformMatrix())


def test_its_own_matrices_are_none():
    assert Billboard().localMatrices().data == (None, None)
