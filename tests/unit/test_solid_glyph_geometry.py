"""Geometry a solid glyph hands to the core-profile shader path.

The vertices carry their own normals and are drawn with face culling on, so
the two have to agree: a triangle whose winding says it faces one way and
whose normals say the other is either culled or lit from behind.
"""

import numpy as np
import pytest
from ttfquery import findsystem

from OpenGLContext.scenegraph.text import toolsfont

# Interleaved as normal(3) + position(3); see ToolsSolidFont.renderShader.
NORMAL = slice(0, 3)
POSITION = slice(3, 6)


@pytest.fixture(scope='module')
def font_file():
    """Any TrueType file this machine has: the test is about geometry."""
    files = [f for f in findsystem.findFonts() if f.lower().endswith('.ttf')]
    if not files:
        pytest.skip("no TrueType font files on this machine")
    return sorted(files)[0]


@pytest.fixture
def glyph(font_file, gl_context):
    """The 'O' of some font: an outer contour plus a hole."""
    font = toolsfont._SolidFont(font_file, quality=3)
    font.ensureGlyphs('O')
    glyph = font.getGlyph('O')
    if not (glyph and glyph.outlines and glyph.contours):
        pytest.skip("font carries no outline for 'O'")
    return glyph


def _triangles(vertices):
    """Group the flat vertex list into (3, 6) triangles."""
    data = np.asarray(vertices, dtype='d')
    assert len(data) % 3 == 0, "geometry is not a whole number of triangles"
    return data.reshape((-1, 3, 6))


def _facing(triangles):
    """Cosine between each triangle's winding normal and its vertex normals."""
    a, b, c = triangles[:, 0, POSITION], triangles[:, 1, POSITION], triangles[:, 2, POSITION]
    winding = np.cross(b - a, c - a)
    lengths = np.linalg.norm(winding, axis=-1)
    winding = winding[lengths > 0] / lengths[lengths > 0, None]
    stored = triangles[lengths > 0][:, :, NORMAL].mean(axis=1)
    return np.sum(winding * stored, axis=-1)


def test_extruded_sides_wind_towards_their_normals(glyph):
    """Each side quad faces the way its contour normal points."""
    triangles = _triangles(glyph._buildExtrusionGeometry(scale=400.0, thickness=0.25))

    facing = _facing(triangles)
    assert (facing > 0).all(), "%d of %d side triangles wind inward" % (
        int((facing <= 0).sum()), len(facing),
    )


def test_caps_wind_towards_their_normals(glyph):
    """The front cap faces +z and the back cap -z, winding to match."""
    for front, z_offset in ((True, 0.0), (False, -0.25)):
        triangles = _triangles(
            glyph._buildCapGeometry(scale=400.0, front=front, z_offset=z_offset)
        )

        facing = _facing(triangles)
        assert (facing > 0).all(), "%d of %d %s-cap triangles wind backwards" % (
            int((facing <= 0).sum()), len(facing), 'front' if front else 'back',
        )


def test_shader_geometry_covers_caps_and_sides(glyph):
    """The assembled buffer is the caps and the sides together."""
    thickness = 0.25
    everything = glyph.buildShaderGeometry(scale=400.0, thickness=thickness)
    caps_only = glyph.buildShaderGeometry(
        scale=400.0, thickness=thickness, renderSides=False
    )

    sides = len(glyph._buildExtrusionGeometry(scale=400.0, thickness=thickness))
    assert everything['vertex_count'] == caps_only['vertex_count'] + sides
    assert everything['advance'] == pytest.approx(glyph.width / 400.0)
