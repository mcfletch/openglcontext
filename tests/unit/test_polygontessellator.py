"""Winding of the triangle sets PolygonTessellator produces.

``forceTriangles`` flattens the GLU tessellator's fans and strips into a plain
GL_TRIANGLES sequence.  GLU orders every primitive counter-clockwise about the
normal it was given, and the flattened form has to keep that: a caller drawing
the result with face culling on sees only the triangles whose winding survived.
"""

import math

import pytest
from OpenGL.GL import GL_TRIANGLE_STRIP
from OpenGL.GLU import gluTessNormal

from OpenGLContext.scenegraph import polygontessellator
from OpenGLContext.scenegraph.vertex import Vertex


def _ring(outer=2.0, inner=1.0, steps=16):
    """An annulus: outer contour counter-clockwise, hole clockwise.

    This is the shape of a glyph like 'O', and it is what makes the GLU
    tessellator emit triangle strips rather than a single fan.
    """
    def circle(radius, direction):
        return [
            Vertex(point=(
                math.cos(direction * i * 2 * math.pi / steps) * radius,
                math.sin(direction * i * 2 * math.pi / steps) * radius,
                0.0,
            ))
            for i in range(steps)
        ]
    return [circle(outer, 1), circle(inner, -1)]


def _signed_area(triangle):
    """Twice the signed area in the xy-plane: positive when counter-clockwise."""
    (ax, ay, _), (bx, by, _), (cx, cy, _) = [v.point for v in triangle]
    return (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)


@pytest.fixture
def tessellator(gl_context):
    """A tessellator with the GLU controller a live GL context provides."""
    tess = polygontessellator.PolygonTessellator()
    gluTessNormal(tess.controller, 0.0, 0.0, 1.0)
    return tess


def test_ring_tessellates_to_strips(tessellator):
    """The shape under test is the one that exercises the strip path."""
    contours = tessellator.tessContours(_ring(), forceTriangles=0)

    assert GL_TRIANGLE_STRIP in [type for type, _ in contours]


def test_forced_triangles_all_wind_counter_clockwise(tessellator):
    """Every flattened triangle faces the normal the tessellation was given."""
    vertices = tessellator.tessContours(_ring(), forceTriangles=1)

    assert len(vertices) % 3 == 0
    triangles = [vertices[i:i + 3] for i in range(0, len(vertices), 3)]
    backwards = [t for t in triangles if _signed_area(t) < 0]
    assert not backwards, "%d of %d triangles wind clockwise" % (
        len(backwards), len(triangles),
    )


def test_forced_triangles_cover_the_same_area(tessellator):
    """Flattening changes the primitive type, not the surface described."""
    contours = tessellator.tessContours(_ring(), forceTriangles=0)
    strip_area = 0.0
    for type, verts in contours:
        if type == GL_TRIANGLE_STRIP:
            for i in range(len(verts) - 2):
                triangle = [verts[i], verts[i + 1], verts[i + 2]]
                strip_area += abs(_signed_area(triangle))
        else:
            first = verts[0]
            for i in range(1, len(verts) - 1):
                strip_area += abs(_signed_area([first, verts[i], verts[i + 1]]))

    vertices = tessellator.tessContours(_ring(), forceTriangles=1)
    triangle_area = sum(
        abs(_signed_area(vertices[i:i + 3]))
        for i in range(0, len(vertices), 3)
    )

    assert triangle_area == pytest.approx(strip_area, rel=1e-6)
