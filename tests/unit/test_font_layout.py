"""Where a font puts the lines of a Text node.

``Font.layout`` is the one place the VRML97 justify/spacing rules are applied,
so that a glyph set drawn as bitmaps, as display lists or from a vertex buffer
all put the same string in the same place.
"""

import pytest
from vrml.vrml97 import basenodes

from OpenGLContext.scenegraph.text import font as fontmodule


class _Line:
    """A line of measured text, as Font.layout reads one."""
    def __init__(self, base, width, height=2.0):
        self.base = base
        self.width = width
        self.height = height


@pytest.fixture
def font():
    return fontmodule.Font()


@pytest.fixture
def lines():
    return [_Line('one', 3.0), _Line('two', 5.0), _Line('three', 9.0)]


def style(**named):
    return basenodes.FontStyle(**named)


def test_lines_step_down_by_the_spaced_line_height(font, lines):
    """spacing multiplies the gap between successive baselines."""
    placed = list(font.layout(lines, style(spacing=1.5)))

    assert [line for line, _, _ in placed] == lines
    assert [y for _, _, y in placed] == [0.0, -3.0, -6.0]


def test_bottom_to_top_reverses_the_step(font, lines):
    """topToBottom false runs the lines up the page instead of down."""
    placed = list(font.layout(lines, style(topToBottom=0)))

    assert [y for _, _, y in placed] == [0.0, 2.0, 4.0]


def test_no_font_style_leaves_the_block_on_the_baseline(font, lines):
    """Without a fontStyle the first line sits on the origin, single-spaced."""
    placed = list(font.layout(lines, None))

    assert [x for _, x, _ in placed] == [0.0, 0.0, 0.0]
    assert [y for _, _, y in placed] == [0.0, -2.0, -4.0]


@pytest.mark.parametrize('justify,expected', [
    (['BEGIN'], [0.0, 0.0, 0.0]),
    (['MIDDLE'], [-1.5, -2.5, -4.5]),
    (['END'], [-3.0, -5.0, -9.0]),
])
def test_major_justification_shifts_each_line_by_its_own_width(
    font, lines, justify, expected
):
    """Major justification is per line, measured against that line's width."""
    placed = list(font.layout(lines, style(justify=justify)))

    assert [x for _, x, _ in placed] == expected


@pytest.mark.parametrize('minor,expected_first', [
    ('FIRST', 0.0),
    ('BEGIN', -2.0),
    ('MIDDLE', 1.0),
    ('END', 4.0),
])
def test_minor_justification_moves_the_whole_block(
    font, lines, minor, expected_first
):
    """Minor justification decides where the block sits against the origin."""
    placed = list(font.layout(lines, style(justify=['BEGIN', minor])))

    assert placed[0][2] == pytest.approx(expected_first)
    # whatever the block's origin, the lines keep their spacing
    assert [y for _, _, y in placed] == pytest.approx(
        [expected_first, expected_first - 2.0, expected_first - 4.0]
    )


class TestTheRenderWrappersHandBackWhatTheyDrew:
    """``Font.render`` answers with the lines it laid out.

    ``Text.render`` passes that answer on as the geometry's, and the two
    GL-state wrappers a bitmap font is built from sit in front of it, so each
    has to carry the answer back out rather than swallow it.
    """

    def test_the_depth_mask_wrapper_returns_the_lines(self, gl_context_compat, lines):
        class _Font(fontmodule.NoDepthBufferMixIn, fontmodule.Font):
            pass

        assert _Font().render(lines) is lines

    def test_the_blending_wrapper_returns_the_lines(self, gl_context_compat):
        class _Font(fontmodule.BitmapFontMixIn, fontmodule.Font):
            pass

        empty = []
        assert _Font().render(empty) is empty

    def test_both_wrappers_together_return_the_lines(self, gl_context_compat):
        class _Font(
            fontmodule.NoDepthBufferMixIn, fontmodule.BitmapFontMixIn, fontmodule.Font
        ):
            pass

        empty = []
        assert _Font().render(empty) is empty


class TestTheAbstractCustomisationPoints:
    """What the base class does for a font that has not filled them in."""

    def test_creating_a_character_says_the_font_has_not_implemented_it(self, font):
        with pytest.raises(NotImplementedError):
            font.createChar('a')

    def test_the_base_font_compiles_no_display_lists(self, font):
        assert font.lists('abc') == []
