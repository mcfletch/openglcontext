"""Tests for MatrixTransform and the glTF matrix-node path.

A glTF node `matrix` is applied exactly rather than decomposed into TRS. The
old decomposition silently dropped 180-degree rotations (ambiguous axis) and
could not represent mirrors -- which misplaced a subset of parts in CAD
assemblies (Buggy, GearboxAssy, ReciprocatingSaw, 2CylinderEngine).
"""
import numpy as np
import pytest

from vrml.vrml97 import nodepath

from OpenGLContext.scenegraph.transform import MatrixTransform
from OpenGLContext.loaders import gltf


def _applied(matrix_transform):
    return np.asarray(nodepath.NodePath([matrix_transform]).transformMatrix())


def _gltf_flat(col_major_matrix):
    """Column-major flat array as glTF stores a node `matrix`."""
    return np.asarray(col_major_matrix, 'd').T.flatten()


def test_identity_matrix_is_identity():
    mt = MatrixTransform(localMatrix=np.identity(4))
    assert np.allclose(_applied(mt), np.identity(4))


def test_180_degree_rotation_preserved():
    """A 180-degree rotation about Z must survive (the decomposition lost it)."""
    flat = _gltf_flat(np.diag([-1.0, -1.0, 1.0, 1.0]))
    mt = MatrixTransform(localMatrix=np.asarray(flat).reshape(4, 4))
    applied = _applied(mt)
    p = np.array([1.0, 0.0, 0.0, 1.0])
    assert np.allclose((p @ applied)[:3], [-1.0, 0.0, 0.0])


def test_mirror_matrix_preserved():
    """A negative-determinant (mirror) basis is applied, not turned into a rotation."""
    flat = _gltf_flat(np.diag([-1.0, 1.0, 1.0, 1.0]))
    mt = MatrixTransform(localMatrix=np.asarray(flat).reshape(4, 4))
    applied = _applied(mt)
    assert float(np.linalg.det(applied[:3, :3])) < 0


def test_translation_in_matrix():
    col = np.identity(4)
    col[:3, 3] = [5.0, -2.0, 3.0]      # column-vector translation column
    mt = MatrixTransform(localMatrix=np.asarray(_gltf_flat(col)).reshape(4, 4))
    applied = _applied(mt)
    p = np.array([0.0, 0.0, 0.0, 1.0])
    assert np.allclose((p @ applied)[:3], [5.0, -2.0, 3.0])


def test_inverse_is_consistent():
    rng = np.array([[0.0, -1.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [2.0, 3.0, 4.0, 1.0]])   # row-vector rot+translation
    mt = MatrixTransform(localMatrix=rng)
    fwd = np.asarray(nodepath.NodePath([mt]).transformMatrix(inverse=False))
    inv = np.asarray(nodepath.NodePath([mt]).transformMatrix(inverse=True))
    assert np.allclose(fwd @ inv, np.identity(4), atol=1e-9)


def test_setLocalMatrix_invalidates_cache():
    mt = MatrixTransform(localMatrix=np.identity(4))
    assert np.allclose(_applied(mt), np.identity(4))
    shift = np.identity(4)
    shift[3, :3] = [1.0, 2.0, 3.0]    # row-vector translation
    mt.setLocalMatrix(shift)
    assert np.allclose(_applied(mt), shift)


# -- loader integration -----------------------------------------------------

def test_loader_uses_matrix_transform_for_matrix_nodes():
    """A node carrying `matrix` becomes a MatrixTransform applying it exactly."""
    Rz180_col = np.diag([-1.0, -1.0, 1.0, 1.0])

    class FakeNode:
        matrix = list(_gltf_flat(Rz180_col))
        translation = scale = rotation = None

    t = gltf.transforms._transform_for(FakeNode())
    assert isinstance(t, MatrixTransform)
    applied = _applied(t)
    p = np.array([1.0, 0.0, 0.0, 1.0])
    assert np.allclose((p @ applied)[:3], [-1.0, 0.0, 0.0])


def test_loader_uses_trs_when_no_matrix():
    from OpenGLContext.scenegraph.transform import Transform

    class FakeNode:
        matrix = None
        translation = [1.0, 2.0, 3.0]
        scale = None
        rotation = None

    t = gltf.transforms._transform_for(FakeNode())
    assert isinstance(t, Transform) and not isinstance(t, MatrixTransform)
    assert tuple(t.translation) == (1.0, 2.0, 3.0)


def test_local_matrix_rv_uses_baked_matrix():
    """Bounds use the exact baked matrix for MatrixTransform nodes."""
    flat = _gltf_flat(np.diag([-1.0, -1.0, 1.0, 1.0]))
    mt = MatrixTransform(localMatrix=np.asarray(flat).reshape(4, 4))
    rv = gltf.transforms._local_matrix_rv(mt)
    assert np.allclose(rv, np.asarray(flat).reshape(4, 4))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
