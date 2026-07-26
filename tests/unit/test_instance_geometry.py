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


class TestTeapotInstancing:
    def _teapot(self, **kw):
        from OpenGLContext.scenegraph.teapot import Teapot
        return Teapot(**kw)

    def test_content_key_equal_for_identical_teapots(self):
        # Distinct Teapot nodes with the same size/lid batch into one draw.
        a, b = self._teapot(size=0.2), self._teapot(size=0.2)
        assert a is not b
        assert a.instanceContentKey() is not None
        assert a.instanceContentKey() == b.instanceContentKey()

    def test_content_key_differs_by_size(self):
        # size is baked into the mesh, so different sizes must not share a batch.
        assert self._teapot(size=0.2).instanceContentKey() \
            != self._teapot(size=0.5).instanceContentKey()

    def test_content_key_differs_by_lid(self):
        assert self._teapot(lid=True).instanceContentKey() \
            != self._teapot(lid=False).instanceContentKey()

    def test_instance_arrays_expand_to_triangle_soup(self):
        positions, normals, texcoords = self._teapot(size=1.0)._instanceArrays()
        # Non-indexed triangle soup: a multiple of three vertices, matched arrays.
        assert positions.shape[0] > 0
        assert positions.shape[0] % 3 == 0
        assert positions.shape == normals.shape
        assert texcoords.shape == (positions.shape[0], 2)

    def test_size_scales_baked_positions(self):
        small = self._teapot(size=0.5)._instanceArrays()[0]
        big = self._teapot(size=1.0)._instanceArrays()[0]
        # Same tessellation, positions scaled by the size ratio.
        assert small.shape == big.shape
        assert np.allclose(big * 0.5, small, atol=1e-5)

    def test_omitting_lid_drops_vertices(self):
        with_lid = self._teapot(lid=True)._instanceArrays()[0]
        without_lid = self._teapot(lid=False)._instanceArrays()[0]
        assert without_lid.shape[0] < with_lid.shape[0]


class TestTheInstancedMeshFollowsItsFields:
    """A cached instance mesh is rebuilt when what it was baked from changes.

    ``build_mesh_gpu`` bakes ``size`` into the vertex positions, so a teapot
    that changed size and kept its mesh would draw at the old one for the rest
    of the session.  The dependency is registered by field *name*, and the
    registration is wrapped in a guard that swallows anything that goes wrong
    -- so "the names are right" is a claim worth pinning rather than assuming.
    """

    @pytest.fixture
    def cached(self):
        """A cache holding a value for a teapot, wired the way build_mesh_gpu
        wires one: a holder keyed ``instance_gpu`` depending on named fields."""
        from vrml.cache import Cache
        from OpenGLContext.scenegraph.teapot import Teapot

        teapot = Teapot(size=1.0)
        cache = Cache()
        # Exactly what build_mesh_gpu does, minus the GL.
        holder = cache.holder(teapot, 'a baked mesh', key='instance_gpu')
        for name in Teapot.instanceGPU_depend_fields:
            holder.depend(teapot, name)
        return teapot, cache

    def test_the_names_resolve_to_real_fields(self):
        """A name that is not a field would be swallowed by the guard."""
        from vrml import protofunctions
        from OpenGLContext.scenegraph.teapot import Teapot

        teapot = Teapot()
        for name in Teapot.instanceGPU_depend_fields:
            assert protofunctions.getField(teapot, name) is not None, name

    def test_the_mesh_is_cached_until_something_changes(self, cached):
        teapot, cache = cached
        assert cache.getData(teapot, key='instance_gpu') == 'a baked mesh'

    def test_changing_size_invalidates_the_cached_mesh(self, cached):
        teapot, cache = cached
        teapot.size = 2.0
        assert cache.getData(teapot, key='instance_gpu') is None, \
            "the mesh baked at the old size is still cached"

    def test_changing_lid_invalidates_the_cached_mesh(self, cached):
        teapot, cache = cached
        teapot.lid = not teapot.lid
        assert cache.getData(teapot, key='instance_gpu') is None

    def test_an_unrelated_field_leaves_the_mesh_alone(self, cached):
        teapot, cache = cached
        teapot.solid = not teapot.solid
        assert cache.getData(teapot, key='instance_gpu') == 'a baked mesh'
