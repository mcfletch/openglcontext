"""The glyph debug renderers in
:mod:`OpenGLContext.scenegraph.text.toolsfont`.

``OutlineGlyph`` carries two developer switches --
``DEBUG_RENDER_CONTOUR_HULLS`` and ``DEBUG_RENDER_CONTROL_POINTS`` -- that a
maintainer flips on to see the outline a glyph was built from.  Both draw with
the fixed-function pipeline, so they need a compatibility-profile context.

What they show has to be readable: the control-point pass ramps blue along
each contour so the winding order can be followed, and reds the off-curve
control points so a quadratic's handles stand out from the points the curve
passes through.
"""
import pytest

from OpenGLContext.scenegraph.text import toolsfont

#: A square, as ttfquery reports a contour: ((x, y), on_curve) per point.
SQUARE = [
    ((0.0, 0.0), 1), ((100.0, 0.0), 0), ((100.0, 100.0), 1), ((0.0, 100.0), 0),
]


@pytest.fixture
def glyph():
    """An ``OutlineGlyph`` with contours and nothing else.

    The class reads only ``contours`` for these two methods, and building a
    real one needs a font file this machine may not have.
    """
    instance = toolsfont.OutlineGlyph.__new__(toolsfont.OutlineGlyph)
    instance.contours = [SQUARE]
    return instance


@pytest.fixture
def colours(monkeypatch):
    """Record what colour each point was given, leaving the rest of GL real."""
    recorded = []
    real = toolsfont.glColor3f

    def glColor3f(r, g, b):
        recorded.append((float(r), float(g), float(b)))
        return real(r, g, b)

    monkeypatch.setattr(toolsfont, 'glColor3f', glColor3f)
    return recorded


class TestTheControlPointRamp:
    def test_one_colour_per_point(self, gl_context_compat, glyph, colours):
        glyph.renderControlPoints()
        assert len(colours) == len(SQUARE)

    def test_the_blue_channel_rises_along_the_contour(self, gl_context_compat,
                                                      glyph, colours):
        glyph.renderControlPoints()
        blues = [b for (_r, _g, b) in colours]
        assert blues == sorted(blues), blues
        assert blues[0] == 0.0
        assert blues[-1] > blues[0], blues

    def test_no_channel_leaves_the_unit_range(self, gl_context_compat, glyph, colours):
        glyph.renderControlPoints()
        for colour in colours:
            for channel in colour:
                assert 0.0 <= channel <= 1.0, colour

    def test_off_curve_points_are_red(self, gl_context_compat, glyph, colours):
        glyph.renderControlPoints()
        for (_point, on_curve), (red, _g, _b) in zip(SQUARE, colours):
            assert red == (0.0 if on_curve else 1.0)

    def test_an_empty_contour_draws_nothing(self, gl_context_compat, glyph, colours):
        glyph.contours = [[]]
        glyph.renderControlPoints()
        assert colours == []


class TestTheContourHulls:
    """The hull pass draws each segment twice, as a GL_LINES pair."""

    def test_it_emits_a_colour_per_vertex(self, gl_context_compat, glyph, colours):
        glyph.renderContours()
        # first point, then both ends of each interior point, then the last
        assert len(colours) == 1 + 2 * (len(SQUARE) - 2) + 1

    def test_off_curve_points_are_the_yellow_ones(self, gl_context_compat,
                                                  glyph, colours):
        glyph.renderContours()
        assert (1.0, 1.0, 0.0) in colours
        assert (0.3, 0.5, 0.0) in [
            (round(r, 4), round(g, 4), round(b, 4)) for (r, g, b) in colours
        ]
