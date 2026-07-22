"""Headless tests that make the general geometry types instanceable.

Each geometry node that wants to batch through the instanced draw path exposes
two hooks (see ``plans/INSTANCED-GEOMETRY.md``):

  ``instanceContentKey()``  -- a hashable signature so two *distinct* nodes with
                               identical geometry collapse into one draw; equal
                               content -> equal key, different content -> different
                               key.
  ``_instanceArrays()``     -- the expanded (positions, normals, texcoords) the
                               shared mesh-GPU is built from; ``instanceGPU(mode)``
                               wraps these for GL (tested separately under GL).

These run without a GL context: they exercise the CPU tessellation/array build,
not the VBO upload.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes


def _quad_ifs(z=0.0, shift=0.0):
    return basenodes.IndexedFaceSet(
        coord=basenodes.Coordinate(point=[
            (-0.5 + shift, -0.5, z), (0.5 + shift, -0.5, z),
            (0.5 + shift, 0.5, z), (-0.5 + shift, 0.5, z)]),
        coordIndex=[0, 1, 2, 3, -1])


class TestIndexedFaceSetInstancing:
    def test_content_key_equal_for_identical_nodes(self):
        # The molecular/scatter case: distinct IFS nodes, identical data -> one draw.
        a, b = _quad_ifs(), _quad_ifs()
        assert a is not b
        assert a.instanceContentKey() is not None
        assert a.instanceContentKey() == b.instanceContentKey()

    def test_content_key_differs_for_different_geometry(self):
        assert _quad_ifs().instanceContentKey() != _quad_ifs(shift=2.0).instanceContentKey()

    def test_content_key_tracks_topology(self):
        # Same points, different coordIndex -> different geometry -> different key.
        a = _quad_ifs()
        b = _quad_ifs()
        b.coordIndex = [0, 1, 2, -1]   # a triangle, not a quad
        assert a.instanceContentKey() != b.instanceContentKey()

    def test_instance_arrays_expand_to_triangle_soup(self):
        positions, normals, texcoords = _quad_ifs()._instanceArrays()
        # A quad tessellates to two triangles = six expanded vertices.
        assert positions.shape == (6, 3)
        assert normals.shape == (6, 3)
        # A front-facing quad (CCW in the xy plane) has +z normals.
        assert np.allclose(normals[:, 2], 1.0, atol=1e-3)

    def test_empty_ifs_has_no_instance_arrays(self):
        empty = basenodes.IndexedFaceSet(coordIndex=[])
        assert empty._instanceArrays() is None
