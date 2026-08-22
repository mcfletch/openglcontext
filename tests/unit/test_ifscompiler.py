"""IndexedFaceSet compile pipeline (mostly pure-CPU, no GL).

Exercises the compiler registry contract in :mod:`ifscompiler`: the three
compilers (ArrayGeometry / IndexedPolygons), the shared
tessellation + polygon walk, per-face vs per-vertex normal generation, the
crease-angle smoothing in :func:`build_normalPerVertex`, and the indexed-value
lookup edge cases in :class:`IndexedValueSource`. The display-list path needs a
real GL context and is driven through a hidden GLFW window.
"""
import types

import numpy as np
import pytest
from vrml.cache import Cache

from OpenGLContext.scenegraph import basenodes as b
from OpenGLContext.scenegraph import vertex as vertex_mod
from OpenGLContext.scenegraph.ifscompiler import (
    ArrayGeometryCompiler,
    DUMMY_RENDER,
    DummyRender,
    IFSCompiler,
    IndexedPolygonsCompiler,
    IndexedValueSource,
    build_normalPerVertex,
    getXNull,
)


def _quad(**over):
    """Two coplanar triangles forming a unit quad in z=0."""
    kw = dict(
        coord=b.Coordinate(point=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]),
        coordIndex=[0, 1, 2, -1, 0, 2, 3, -1],
    )
    kw.update(over)
    return b.IndexedFaceSet(**kw)


def _mode():
    return types.SimpleNamespace(cache=Cache())


class TestTrivialRenderers:
    def test_dummy_render_is_a_noop(self):
        assert DummyRender().render(1, 2, key=3) is None


class TestBaseCompiler:
    def test_default_weight(self):
        assert IFSCompiler.weight(_quad()) == 1.0

    def test_base_compile_is_abstract(self):
        with pytest.raises(NotImplementedError):
            IFSCompiler(_quad()).compile()

    def test_call_returns_none_for_empty_geometry(self):
        empty = b.IndexedFaceSet(coord=b.Coordinate(point=[]), coordIndex=[])
        assert ArrayGeometryCompiler(empty)(mode=_mode()) is None

    def test_call_compiles_and_caches(self):
        c = ArrayGeometryCompiler(_quad(
            color=b.Color(color=[(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0)]),
            texCoord=b.TextureCoordinate(point=[(0, 0), (1, 0), (1, 1), (0, 1)]),
            normal=b.Normal(vector=[(0, 0, 1)] * 4),
        ))
        mode = _mode()
        result = c(mode=mode)
        assert result.__class__.__name__ == 'ArrayGeometry'
        # the cache holder was populated with the compiled renderer
        assert mode.cache.getData(c.target, '') is result

    def test_call_swallows_compile_error_to_dummy(self):
        class Boom(ArrayGeometryCompiler):
            def compile(self, *a, **k):
                raise ValueError("kaboom")
        assert Boom(_quad())(mode=_mode()) is DUMMY_RENDER

    def test_tessellate_empty_returns_empty(self):
        empty = b.IndexedFaceSet(coord=b.Coordinate(point=[]), coordIndex=[])
        assert ArrayGeometryCompiler(empty).tessellate() == []


class TestPolygonWalk:
    def test_out_of_range_index_is_skipped(self):
        # coordIndex value 99 is past the end of the 3-point coordinate set, so
        # it is dropped with a log.
        ifs = b.IndexedFaceSet(
            coord=b.Coordinate(point=[(0, 0, 0), (1, 0, 0), (1, 1, 0)]),
            coordIndex=[0, 1, 99, 2, -1])
        polys = list(ArrayGeometryCompiler(ifs).polygons())
        assert len(polys) == 1
        assert len(polys[0]) == 3        # the bad index left a triangle, not a quad

    def test_out_of_range_index_skipped_when_indices_outnumber_points(self):
        # The usual shape of a real mesh: many more indices than points. An
        # index past the end of the coordinate set must be dropped, not used to
        # read past the end of the point array.
        ifs = b.IndexedFaceSet(
            coord=b.Coordinate(point=[(0, 0, 0), (1, 0, 0), (1, 1, 0)]),
            coordIndex=[0, 1, 2, -1] * 4 + [0, 1, 5, -1])
        polys = list(ArrayGeometryCompiler(ifs).polygons())
        assert len(polys) == 5
        assert [len(p) for p in polys] == [3, 3, 3, 3, 2]

    def test_valid_index_beyond_the_index_array_length_is_kept(self):
        # More points than indices: index 9 is a legitimate reference into the
        # 10-point coordinate set and must not be discarded.
        ifs = b.IndexedFaceSet(
            coord=b.Coordinate(point=[(i, 0, 0) for i in range(10)]),
            coordIndex=[0, 1, 9])
        polys = list(ArrayGeometryCompiler(ifs).polygons())
        assert len(polys) == 1 and len(polys[0]) == 3

    def test_trailing_polygon_without_terminator(self):
        # No closing -1: the final accumulated polygon must still be yielded.
        ifs = b.IndexedFaceSet(
            coord=b.Coordinate(point=[(0, 0, 0), (1, 0, 0), (1, 1, 0)]),
            coordIndex=[0, 1, 2])
        polys = list(ArrayGeometryCompiler(ifs).polygons())
        assert len(polys) == 1 and len(polys[0]) == 3


class TestExpandedArrays:
    def test_none_when_nothing_to_tessellate(self):
        empty = b.IndexedFaceSet(coord=b.Coordinate(point=[]), coordIndex=[])
        assert ArrayGeometryCompiler(empty).expandedArrays() is None

    def test_per_vertex_calculated_normals_are_unit(self):
        # normalPerVertex default (1), no explicit normal -> build_normalPerVertex.
        arrays = ArrayGeometryCompiler(_quad()).expandedArrays()
        _v, _c, normals, _t = arrays
        assert len(normals) == 6
        assert np.allclose(np.abs(normals), [0, 0, 1], atol=1e-5)

    def test_per_face_normals_when_not_per_vertex(self):
        arrays = ArrayGeometryCompiler(_quad(normalPerVertex=0)).expandedArrays()
        _v, _c, normals, _t = arrays
        assert len(normals) == 6         # repeated 3x per face
        assert np.allclose(np.abs(normals[0]), [0, 0, 1], atol=1e-5)

    def test_explicit_normals_are_used(self):
        ifs = _quad(normal=b.Normal(vector=[(0, 0, 1)] * 4),
                    normalIndex=[0, 1, 2, -1, 0, 2, 3, -1])
        _v, _c, normals, _t = ArrayGeometryCompiler(ifs).expandedArrays()
        assert np.allclose(normals, [0, 0, 1], atol=1e-6)

    def test_explicit_normals_with_unresolved_indices_fall_back(self):
        # A present normal node but all-(-1) indices leaves every vertex.normal
        # None: the first falls back to +z, the rest copy the previous one.
        ifs = _quad(normal=b.Normal(vector=[(0, 0, 1)] * 4),
                    normalIndex=[-1] * 8)
        _v, _c, normals, _t = ArrayGeometryCompiler(ifs).expandedArrays()
        assert np.allclose(normals, [0, 0, 1], atol=1e-6)

    def test_colors_and_texcoords_carried_through(self):
        ifs = _quad(
            color=b.Color(color=[(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0)]),
            texCoord=b.TextureCoordinate(point=[(0, 0), (1, 0), (1, 1), (0, 1)]))
        v, colors, _n, tex = ArrayGeometryCompiler(ifs).expandedArrays()
        assert colors is not None and colors.shape == (6, 3)
        assert tex is not None and tex.shape == (6, 2)

    def test_compile_returns_dummy_for_empty(self):
        empty = b.IndexedFaceSet(coord=b.Coordinate(point=[]), coordIndex=[])
        assert ArrayGeometryCompiler(empty).compile(mode=_mode()) is DUMMY_RENDER


class TestCompilerWeights:
    def test_indexed_polygons_requires_per_vertex_normals(self):
        # Plain quad without explicit per-vertex normals -> not applicable.
        assert IndexedPolygonsCompiler.weight(_quad()) is False

    def test_indexed_polygons_applies_with_per_vertex_normals(self):
        ifs = _quad(normal=b.Normal(vector=[(0, 0, 1)] * 4),
                    normalIndex=[0, 1, 2, -1, 0, 2, 3, -1])
        assert IndexedPolygonsCompiler.weight(ifs) == 1.05

    def test_indexed_polygons_compile_shares_indices(self):
        ifs = _quad(normal=b.Normal(vector=[(0, 0, 1)] * 4),
                    normalIndex=[0, 1, 2, -1, 0, 2, 3, -1])
        ip = IndexedPolygonsCompiler(ifs).compile(mode=_mode())
        # shared corner vertex 0/2 dedupes: 6 index refs, 4 unique coords.
        assert len(ip.index) == 6
        assert len(ip.coord.point) == 4


class TestBuildNormalPerVertex:
    def test_generates_vertex_array_when_absent(self):
        c = ArrayGeometryCompiler(_quad())
        verts = c.tessellate()
        normals = build_normalPerVertex(verts, creaseAngle=0.0)
        assert len(normals) == len(verts)

    def test_crease_angle_blends_shared_coplanar_faces(self):
        # Large creaseAngle -> the two triangles sharing an edge blend, so the
        # shared-corner normals get averaged (count > 1). Result stays unit-z.
        c = ArrayGeometryCompiler(_quad())
        verts = c.tessellate()
        blended = build_normalPerVertex(verts, creaseAngle=3.14)
        assert np.allclose(np.abs(blended), [0, 0, 1], atol=1e-5)


class TestGetXNull:
    def test_returns_attribute_when_node_present(self):
        node = b.Coordinate(point=[(1, 2, 3)])
        assert list(getXNull(node, 'point')[0]) == [1, 2, 3]

    def test_returns_empty_list_for_falsey_node(self):
        assert getXNull(None, 'point') == []


class TestIndexedValueSource:
    def test_empty_indices_fall_back_to_vertex_indices(self):
        src = IndexedValueSource([0, 1, 2], [], [(1, 0, 0), (0, 1, 0), (0, 0, 1)],
                                 False, name='color')
        # indices were replaced by the coord indices
        assert list(src.indices) == [0, 1, 2]
        assert src(0, 0) == ((1, 0, 0), 0)

    def test_per_face_uses_face_index(self):
        # perFace -> indexed by faceIndex, ignoring metaIndex.
        src = IndexedValueSource([0, 1], [1, 0], [('a',), ('b',)], True)
        assert src(0, 1) == (('a',), 0)   # faceIndex 1 -> indices[1]=0 -> values[0]
        assert src(0, 0) == (('b',), 1)   # faceIndex 0 -> indices[0]=1 -> values[1]

    def test_index_out_of_range_returns_none(self):
        src = IndexedValueSource([0], [0], [('a',)], False)
        assert src(5, 0) == (None, -1)   # metaIndex 5 beyond indices

    def test_negative_final_index_warns_and_returns_none(self):
        src = IndexedValueSource([0], [-1], [('a',)], False)
        assert src(0, 0) == (None, -1)

    def test_overflow_index_uses_last_non_null(self):
        # finalIndex 9 >= len(values)=2 -> falls back to lastNonNullIndex().
        src = IndexedValueSource([0, 1], [9, 1], [('a',), ('b',)], False)
        val, idx = src(0, 0)
        assert idx == 1 and val == ('b',)

    def test_overflow_with_no_valid_index_returns_none(self):
        src = IndexedValueSource([0], [-1, -1], [('a',), ('b',)], False)
        # metaIndex maps to index -1 -> warned/None before overflow branch
        assert src(0, 0) == (None, -1)

    def test_no_indices_but_values_warns(self):
        # both vertexIndices and indices empty, values present -> the "no indices"
        # warning path in __call__.
        src = IndexedValueSource([], [], [('a',)], False)
        assert src.indices == []
        assert src(0, 0) == (None, -1)

    def test_last_non_null_index_scans_backwards(self):
        src = IndexedValueSource([0], [3, 5, -1], [('a',)], False)
        assert src.lastNonNullIndex() == 5

    def test_last_non_null_index_all_null(self):
        src = IndexedValueSource([0], [-1, -1], [('a',)], False)
        assert src.lastNonNullIndex() is None

    def test_vertex_index_lookup(self):
        src = IndexedValueSource([0, 1, 2], [7, 8, 9], [('a',)], False)
        assert src.vertexIndex(1, 0) == 8

    def test_vertex_index_per_face(self):
        src = IndexedValueSource([0], [7, 8], [('a',)], True)
        assert src.vertexIndex(0, 1) == 8

    def test_vertex_index_overflow_uses_last_non_null(self):
        src = IndexedValueSource([0], [7, -1], [('a',)], False)
        assert src.vertexIndex(9, 0) == 7   # index >= len -> lastNonNullIndex

    def test_vertex_index_negative_out_of_range_returns_none(self):
        # A large *negative* metaIndex is out of range (IndexError) but not
        # `>= len`, so the lookup yields None rather than the last index.
        src = IndexedValueSource([0], [7, 8], [('a',)], False)
        assert src.vertexIndex(-5, 0) is None


class TestExpandedArraysDefensive:
    """Defensive arms of the tessellation-to-array expansion."""

    def test_invalid_tessellated_color_drops_color_array(self):
        # A tessellated vertex whose colour is not numeric (a tessellation bug)
        # must not abort the compile: the colour array is dropped with a warning
        # and geometry still builds.
        ifs = _quad(color=b.Color(color=[(1, 0, 0)]))

        good = vertex_mod.Vertex(point=(0, 0, 0), color=(1, 0, 0),
                                 metaIndex=0, coordIndex=0)
        good2 = vertex_mod.Vertex(point=(1, 0, 0), color=(0, 1, 0),
                                  metaIndex=1, coordIndex=1)
        bad = vertex_mod.Vertex(point=(0, 1, 0), color=(object(), 0.0, 0.0),
                                metaIndex=2, coordIndex=2)   # non-numeric channel

        class _Corrupt(ArrayGeometryCompiler):
            def tessellate(self, polygons=None, sources=None):
                return [good, good2, bad]

        result = _Corrupt(ifs).expandedArrays()
        assert result is not None
        _va, colorArray, _na, _ta = result
        assert colorArray is None            # invalid colour -> dropped

    def test_unhashable_coord_index_reraises(self):
        # build_normalPerVertex keys vertices by coordIndex; a non-hashable
        # coordIndex is a real corruption and must surface, not be swallowed.
        class _BadVertex:
            coordIndex = [1, 2]              # unhashable -> TypeError on setdefault

        vertexArray = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f')
        with pytest.raises(TypeError):
            build_normalPerVertex([_BadVertex(), _BadVertex(), _BadVertex()],
                                  creaseAngle=0.5, vertexArray=vertexArray)


@pytest.fixture
def gl(gl_window):
    """Compatibility profile: the display-list path here is ``glGenLists``."""
    return gl_window('ifs', profile='compatibility')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
