"""Where the shader path puts each line of a solid Text node.

Layout is the font's job in both profiles, so the core-profile path has to
place lines by the same rules the fixed-function one does: the FontStyle's
spacing between them, and its minor justification for where the block as a
whole sits against the origin.
"""

import numpy as np
import pytest
from ttfquery import findsystem

from OpenGLContext.scenegraph.text import fontstyle3d, toolsfont

LINES = ['one', 'two', 'three']


class _Mode:
    """The parts of a render pass the layout code reads."""
    shader_mode = True

    def __init__(self):
        self.matrix = np.identity(4, dtype='f')


@pytest.fixture(scope='module')
def font_file():
    files = [f for f in findsystem.findFonts() if f.lower().endswith('.ttf')]
    if not files:
        pytest.skip("no TrueType font files on this machine")
    return sorted(files)[0]


@pytest.fixture
def placements(font_file, monkeypatch):
    """Draw a string and report where each line was drawn, by fontStyle."""
    def place(**style):
        fontStyle = fontstyle3d.FontStyle3D(family=['SANS'], size=1.0, **style)
        font = toolsfont.ToolsSolidFont(fontStyle, font=font_file)
        drawn = []
        monkeypatch.setattr(
            font, 'renderShader',
            lambda text, mode: drawn.append((text, mode.matrix[3].copy())),
        )
        mode = _Mode()
        lines = font.toLines('\n'.join(LINES), mode=mode)
        font._renderShaderJustified(lines, fontStyle, mode)
        return font, fontStyle, lines, drawn
    return place


def test_every_line_is_drawn_in_order(placements):
    """Each line of the string reaches the draw call once, top to bottom."""
    _, _, _, drawn = placements()

    assert [text for text, _ in drawn] == LINES


def test_lines_step_down_by_the_spaced_line_height(placements):
    """Consecutive baselines are one spaced line-height apart."""
    _, _, lines, drawn = placements(spacing=2.0)

    step = lines[0].height * 2.0
    ys = [translation[1] for _, translation in drawn]
    assert np.allclose(np.diff(ys), -step)


def test_minor_justification_moves_the_whole_block(placements):
    """A MIDDLE minor justification centres the lines on the origin."""
    font, fontStyle, lines, drawn = placements(justify=['MIDDLE', 'MIDDLE'])

    expected = font.verticalAdjust(1.0, lines, fontStyle)
    assert expected != 0.0, "the case has to be one the default would get wrong"
    assert drawn[0][1][1] == pytest.approx(expected)


def test_major_justification_offsets_each_line_by_its_own_width(placements):
    """Centring is per line, so lines of different widths still share an axis."""
    _, _, lines, drawn = placements(justify=['MIDDLE'])

    for line, (_, translation) in zip(lines, drawn, strict=True):
        assert translation[0] == pytest.approx(-line.width / 2.0)
