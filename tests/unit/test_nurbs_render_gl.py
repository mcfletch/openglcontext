"""What a tessellated NURBS surface does once it reaches GL (needs a context).

The evaluation itself is pure NumPy and covered by ``test_nurbstess.py``; what
needs a live context is the rest: uploading a tessellation into a vertex and an
index buffer, and drawing it. The fixed-function draw is checked by rendering a
surface and reading the pixels back, so it is the picture that is asserted
rather than the calls that were made.
"""

import numpy as np
import pytest
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST, GL_LIGHTING,
    GL_MODELVIEW, GL_PROJECTION, GL_RGBA, GL_UNSIGNED_BYTE, glClear,
    glClearColor, glColor4f, glDisable, glEnable, glLoadIdentity, glMatrixMode,
    glOrtho, glReadPixels, glViewport,
)

from OpenGLContext.scenegraph import nurbs
from OpenGLContext.scenegraph.nurbssampling import NurbsDomainDistanceSample
from OpenGLContext.scenegraph.nurbstess import build_surface_vbo, tessellate_surface

_KNOT = [0, 0, 0, 0, 1, 1, 1, 1]

#: A plane covering the unit square in xy, so an orthographic view of it fills
#: the viewport and every pixel read back is on the surface. ``controlPoint`` is
#: v-major, and a surface's normal is ``dp/dv x dp/du``, so laying v along x and
#: u along y turns the front face towards the camera -- which is what lets the
#: draws below run with the default ``solid`` culling, as a scene does.
_PLANE = [[v / 3.0, u / 3.0, 0.0] for v in range(4) for u in range(4)]

#: The same plane with u and v the other way round, so it faces away.
_AWAY = [[u / 3.0, v / 3.0, 0.0] for v in range(4) for u in range(4)]


def _surface(control=None, **overrides):
    fields = dict(controlPoint=control or _PLANE, uDimension=4, vDimension=4,
                  uKnot=_KNOT, vKnot=_KNOT)
    fields.update(overrides)
    return nurbs.NurbsSurface(**fields)


@pytest.fixture
def gl_context(gl_window):
    """Compatibility profile: the fixed-function draw is what is checked here."""
    return gl_window('nurbs', profile='compatibility')


def _drawn(surface, **render):
    """The brightest pixel near the middle of a surface drawn over black.

    A 4x4 block rather than one pixel, so a line landing on a pixel boundary is
    still seen; 0..255 RGBA.
    """
    glViewport(0, 0, 32, 32)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    glOrtho(0, 1, 0, 1, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
    glDisable(GL_LIGHTING)
    glDisable(GL_DEPTH_TEST)
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glColor4f(1.0, 1.0, 1.0, 1.0)
    surface.render(**render)
    pixels = glReadPixels(14, 14, 4, 4, GL_RGBA, GL_UNSIGNED_BYTE)
    return np.frombuffer(pixels, dtype='B').astype(int).reshape(-1, 4).max(axis=0)


def _coverage(surface, **render):
    """The fraction of the viewport a surface draws anything into."""
    _drawn(surface, **render)
    pixels = glReadPixels(0, 0, 32, 32, GL_RGBA, GL_UNSIGNED_BYTE)
    lit = np.frombuffer(pixels, dtype='B').reshape(-1, 4)[:, :3].max(axis=1)
    return float((lit > 8).mean())


class TestTheUpload:
    def test_it_reports_what_it_uploaded(self, gl_context):
        tessellation = tessellate_surface(_surface(), u_step=4, v_step=4)
        vertices, indices, count, has_colors = build_surface_vbo(tessellation)
        assert vertices is not None and indices is not None
        assert count == tessellation.triangle_count * 3
        assert has_colors is False

    def test_the_vertex_buffer_is_the_interleaved_rows(self, gl_context):
        tessellation = tessellate_surface(_surface(), u_step=4, v_step=4)
        vertices, _indices, _count, _colors = build_surface_vbo(tessellation)
        data = np.asarray(vertices.data).reshape(-1, 6)
        assert len(data) == tessellation.vertex_count
        assert np.allclose(data[:, 3:], tessellation.positions)

    def test_colours_widen_the_row(self, gl_context):
        colors = [[x / 3.0, y / 3.0, 0.5] for y in range(4) for x in range(4)]
        tessellation = tessellate_surface(_surface(color=colors), u_step=4, v_step=4)
        vertices, _indices, _count, has_colors = build_surface_vbo(tessellation)
        assert has_colors is True
        assert np.asarray(vertices.data).reshape(-1, 10).shape[0] == \
            tessellation.vertex_count

    def test_an_empty_tessellation_uploads_nothing(self, gl_context):
        empty = tessellate_surface(_surface(), trimming_contours=[
            nurbs.Contour2D(children=[nurbs.Polyline2D(
                point=[[0.9, 0.1], [0.1, 0.1], [0.1, 0.9], [0.9, 0.9]])]),
        ], u_step=8, v_step=8)                       # clockwise: encloses nothing
        assert build_surface_vbo(empty) == (None, None, 0, False)


class TestTheFixedFunctionDraw:
    def test_a_surface_covers_the_viewport(self, gl_context):
        assert _drawn(_surface())[:3] == pytest.approx((255, 255, 255), abs=2)

    def test_a_solid_surface_facing_away_is_culled(self, gl_context):
        assert _drawn(_surface(control=_AWAY))[:3] == pytest.approx((0, 0, 0), abs=2)

    def test_the_same_surface_draws_where_it_is_not_solid(self, gl_context):
        assert _drawn(_surface(control=_AWAY, solid=0))[:3] == \
            pytest.approx((255, 255, 255), abs=2)

    def test_nothing_is_drawn_where_a_trim_cut_it_away(self, gl_context):
        """The middle is inside the hole, so the clear colour shows through."""
        outer = nurbs.Contour2D(children=[nurbs.Polyline2D(
            point=[[0, 0], [1, 0], [1, 1], [0, 1]])])
        hole = nurbs.Contour2D(children=[nurbs.Polyline2D(
            point=[[0.7, 0.3], [0.3, 0.3], [0.3, 0.7], [0.7, 0.7]])])
        trimmed = nurbs.TrimmedSurface(
            surface=_surface(), trimmingContour=[outer, hole])
        assert _drawn(trimmed)[:3] == pytest.approx((0, 0, 0), abs=2)

    def test_a_per_vertex_colour_reaches_the_pixel(self, gl_context):
        """Every control point red, so the whole surface draws red."""
        red = [[1.0, 0.0, 0.0]] * 16
        assert _drawn(_surface(color=red))[:3] == pytest.approx((255, 0, 0), abs=2)

    def test_an_edge_geometry_type_draws_lines_not_a_fill(self, gl_context):
        """Wireframe: the same faces, drawn as their edges, cover far less."""
        coarse = NurbsDomainDistanceSample(uStep=3, vStep=3)
        filled = _coverage(_surface(sampling=coarse))
        wire = _coverage(_surface(geometryType='edge', sampling=coarse))
        assert filled == pytest.approx(1.0, abs=0.02)
        assert 0.0 < wire < 0.5

    def test_a_curve_draws(self, gl_context):
        """A NURBS curve straight across the middle of the viewport."""
        curve = nurbs.NurbsCurve(
            knot=_KNOT,
            controlPoint=[[0.0, 0.5, 0.0], [0.33, 0.5, 0.0],
                          [0.66, 0.5, 0.0], [1.0, 0.5, 0.0]],
        )
        assert _drawn(curve)[:3] == pytest.approx((255, 255, 255), abs=2)

    def test_a_curve_with_no_knots_draws_nothing(self, gl_context):
        assert nurbs.NurbsCurve().render() == 0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
