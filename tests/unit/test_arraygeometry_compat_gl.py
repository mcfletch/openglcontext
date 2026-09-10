"""``ArrayGeometry`` draws through the fixed-function vertex arrays.

This is the compatibility-profile path an ``IndexedFaceSet`` takes: one array
per attribute, handed to ``glVertexPointer`` and friends and drawn with
``glDrawArrays``.  The component count of each array is what those calls have to
be told, and it varies -- three for a position or a normal, two for a texture
coordinate -- so the node records it while it still has the arrays, before they
become buffer objects that no longer carry a shape.

The transparent path draws the same triangles through ``glDrawElements`` with a
depth-sorted index instead.
"""

import numpy as np
import pytest

pytest.importorskip("glfw")

from OpenGL.GL import (  # noqa: E402
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_LIGHTING, GL_MODELVIEW,
    GL_NO_ERROR, GL_PROJECTION, GL_RGB, GL_UNSIGNED_BYTE, glClear,
    glClearColor, glDisable, glFinish, glGetError, glLoadIdentity,
    glMatrixMode, glReadPixels,
)

from OpenGLContext.scenegraph import arraygeometry  # noqa: E402

SIZE = 64
POSITIONS = np.array([[-1, -1, 0], [1, -1, 0], [0, 1, 0]], 'f')
COLORS = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'f')
NORMALS = np.array([[0, 0, 1]] * 3, 'f')
TEXCOORDS = np.array([[0, 0], [1, 0], [0.5, 1]], 'f')


class _Mode:
    """The little of a render pass that the fixed-function path asks for."""

    matrix = None

    def getModelView(self):
        return np.identity(4, 'f')

    def getProjection(self):
        return np.identity(4, 'f')

    def getViewport(self):
        return [0, 0, SIZE, SIZE]


@pytest.fixture
def gl_context(gl_window):
    return gl_window('arraygeometry', size=(SIZE, SIZE), profile='compatibility')


@pytest.fixture
def geometry(gl_context):
    return arraygeometry.ArrayGeometry(POSITIONS, COLORS, NORMALS, TEXCOORDS)


def _drawn(geometry, **named):
    """Fraction of the framebuffer the geometry put something into."""
    glClearColor(0, 0, 0, 1)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
    glDisable(GL_LIGHTING)
    geometry.render(mode=_Mode(), **named)
    glFinish()
    assert glGetError() == GL_NO_ERROR
    raw = glReadPixels(0, 0, SIZE, SIZE, GL_RGB, GL_UNSIGNED_BYTE, outputType=None)
    pixels = np.frombuffer(raw, dtype='u1').reshape(SIZE, SIZE, 3)
    return float((pixels.sum(axis=2) > 0).mean())


def test_each_array_reports_its_own_component_count(geometry):
    """Positions and normals are three-component, texture coordinates two."""
    assert geometry.componentCounts == (3, 3, 3, 2)


def test_the_triangle_reaches_the_framebuffer(geometry):
    assert _drawn(geometry) > 0.4


def test_the_sorted_transparent_draw_covers_the_same_triangle(geometry):
    assert _drawn(geometry, transparent=1) > 0.4


def test_a_geometry_without_the_optional_arrays_still_draws(gl_context):
    """Colour, normal and texture arrays are optional; a position array is not."""
    plain = arraygeometry.ArrayGeometry(POSITIONS)
    assert plain.componentCounts == (3, 0, 0, 0)
    assert _drawn(plain) > 0.4
