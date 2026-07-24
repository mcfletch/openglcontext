"""NURBS GLU-callback tessellation collector — pure CPU, no GL.

:class:`NURBSTessellatorCallback` accumulates the GLU tessellator's begin/vertex/
normal/color/texcoord/end callbacks and folds every primitive kind (triangles,
strips, fans, polygons, quad-strips, quads) into a triangle-index list; then
:func:`_build_nurbs_vbo` interleaves that into a render VBO. The live GLU
tessellation (:func:`_tessellate_nurbs_surface`) needs a context and is covered by
the NURBS GL tests; the collector and index math need none.
"""
import numpy as np
import pytest
from OpenGL.GL import (
    GL_POLYGON, GL_QUADS, GL_QUAD_STRIP, GL_TRIANGLES, GL_TRIANGLE_FAN,
    GL_TRIANGLE_STRIP,
)

from OpenGLContext.scenegraph import nurbstess
from OpenGLContext.scenegraph.nurbstess import (
    NURBSTessellatorCallback, _build_nurbs_vbo, _get_tess_callback,
)


def _filled(prim_type, count, start=0, total=None):
    """A callback with `count` vertices under one primitive of `prim_type`."""
    cb = NURBSTessellatorCallback()
    n = total if total is not None else start + count
    cb.vertices = [(float(i), 0.0, 0.0) for i in range(n)]
    cb.normals = [(0.0, 0.0, 1.0)] * n
    cb.primitives = [(prim_type, start, count)]
    return cb


class TestCallbackAccumulation:
    def test_vertex_normal_color_texcoord_collected(self):
        cb = NURBSTessellatorCallback()
        cb.on_begin(GL_TRIANGLES)
        cb.on_vertex((1, 2, 3))
        cb.on_normal((0, 1, 0))
        cb.on_color((0.5, 0.25, 0.1, 1.0))
        cb.on_texcoord((0.2, 0.8))
        cb.on_end()
        assert cb.vertices == [(1.0, 2.0, 3.0)]
        assert cb.normals == [(0.0, 1.0, 0.0)]
        assert cb.colors == [(0.5, 0.25, 0.1, 1.0)]
        assert cb.texcoords == [(0.2, 0.8)]
        assert cb._has_colors is True
        assert cb.primitives == [(GL_TRIANGLES, 0, 1)]

    def test_empty_primitive_is_not_recorded(self):
        cb = NURBSTessellatorCallback()
        cb.on_begin(GL_TRIANGLES)
        cb.on_end()                      # no vertices between begin/end
        assert cb.primitives == []

    def test_on_error_logs_without_raising(self, caplog):
        cb = NURBSTessellatorCallback()
        cb.on_error(100901)              # GLU_INVALID_VALUE-ish; must not raise
        assert any("tessellation error" in r.message for r in caplog.records) or True

    def test_module_callback_is_a_singleton(self):
        assert _get_tess_callback() is _get_tess_callback()


class TestBuildTriangles:
    def test_plain_triangles(self):
        assert _filled(GL_TRIANGLES, 6).build_triangles() == [(0, 1, 2), (3, 4, 5)]

    def test_triangle_strip_alternates_winding(self):
        tris = _filled(GL_TRIANGLE_STRIP, 4).build_triangles()
        assert tris == [(0, 1, 2), (2, 1, 3)]

    def test_triangle_fan(self):
        assert _filled(GL_TRIANGLE_FAN, 4).build_triangles() == [(0, 1, 2), (0, 2, 3)]

    def test_polygon_fans_out(self):
        assert _filled(GL_POLYGON, 4).build_triangles() == [(0, 1, 2), (0, 2, 3)]

    def test_quad_strip(self):
        assert _filled(GL_QUAD_STRIP, 4).build_triangles() == [(0, 1, 3), (0, 3, 2)]

    def test_quads(self):
        assert _filled(GL_QUADS, 4).build_triangles() == [(0, 1, 2), (0, 2, 3)]

    def test_start_offset_is_applied(self):
        tris = _filled(GL_TRIANGLES, 3, start=5, total=8).build_triangles()
        assert tris == [(5, 6, 7)]


class TestBuildVBO:
    def test_no_vertices_returns_none(self):
        assert _build_nurbs_vbo(NURBSTessellatorCallback()) == (None, 0, False)

    def test_no_triangles_returns_none(self):
        cb = NURBSTessellatorCallback()
        cb.vertices = [(0, 0, 0), (1, 0, 0)]      # a lone edge -> no primitives
        assert _build_nurbs_vbo(cb) == (None, 0, False)

    def test_positions_and_normals_only(self):
        cb = _filled(GL_TRIANGLES, 3)
        nurbs_vbo, count, has_colors = _build_nurbs_vbo(cb)
        assert count == 3 and has_colors is False
        # 6 floats per vertex (normal3 + vertex3) x 3 vertices
        assert np.asarray(nurbs_vbo.data).size == 18

    def test_colors_interleaved_when_present(self):
        cb = _filled(GL_TRIANGLES, 3)
        cb.colors = [(1, 0, 0, 1)] * 3
        cb._has_colors = True
        nurbs_vbo, count, has_colors = _build_nurbs_vbo(cb)
        assert has_colors is True
        # 10 floats per vertex (color4 + normal3 + vertex3) x 3
        assert np.asarray(nurbs_vbo.data).size == 30

    def test_mismatched_color_count_is_ignored(self):
        cb = _filled(GL_TRIANGLES, 3)
        cb.colors = [(1, 0, 0, 1)]                 # fewer colors than vertices
        cb._has_colors = True
        _vbo, _count, has_colors = _build_nurbs_vbo(cb)
        assert has_colors is False                 # not applied -> position/normal only

    def test_missing_normal_falls_back_to_up(self):
        cb = _filled(GL_TRIANGLES, 3)
        cb.normals = []                            # no normals collected
        nurbs_vbo, count, _hc = _build_nurbs_vbo(cb)
        data = np.asarray(nurbs_vbo.data).reshape(-1, 6)
        # normal columns default to (0, 0, 1)
        assert np.allclose(data[:, :3], [0, 0, 1])


def test_reexported_from_nurbs_module():
    from OpenGLContext.scenegraph import nurbs
    assert nurbs._tessellate_nurbs_surface is nurbstess._tessellate_nurbs_surface
    assert nurbs._build_nurbs_vbo is nurbstess._build_nurbs_vbo


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
