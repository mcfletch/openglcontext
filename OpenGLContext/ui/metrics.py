"""Measuring text for the overlay UI, and the scale everything else follows.

Every widget's natural size comes from measured text rather than a guess, which
is what keeps a label inside its own button.  The shader font
(:mod:`OpenGLContext.scenegraph.text.shadertext`) is a fixed-size monospaced
bitmap atlas, so a character width and height describe it completely and the
measurement is exact arithmetic -- testable with no GL context.

**The font is also what sets the size of everything that is not text.**  A
screen laid out in fixed pixels is comfortable at one resolution and unusable at
the next, so :func:`font_size_for` picks an atlas from the window's height and
the player's own preference, and the :attr:`FontMetrics.scale` that comes back
with it multiplies every pixel measurement in the skin
(:meth:`OpenGLContext.ui.skin.Skin.scaled`) and every ``maximumWidth`` in the
layout.  A switch that is a comfortable target at 1080p is a comfortable target
at 4K because it is the same fraction of the screen, not the same number of
pixels.

:func:`metrics_for` adapts a live text renderer; construct a
:class:`FontMetrics` directly to lay out or test without one, where the scale
defaults to 1 and pixel measurements mean what they say.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

#: Appended to text that was cut to fit.
ELLIPSIS = '…'
#: The atlas the skin's pixel measurements are authored against: at this size
#: the scale is 1 and a padding of 16 is 16 pixels.
REFERENCE_FONT_SIZE = 16
#: The window height that font size is meant for.  A taller window gets a
#: proportionally larger font, so the screen is the same size in the eye
#: whatever the display.
REFERENCE_HEIGHT = 1080
#: Blank pixels between lines at the reference size.
REFERENCE_LINE_GAP = 2


class FontMetrics:
    """Character measurements for one monospaced font size."""

    def __init__(self, char_width: int, char_height: int,
                 line_gap: int = REFERENCE_LINE_GAP, scale: float = 1.0) -> None:
        self.char_width = int(char_width)
        self.char_height = int(char_height)
        #: Blank pixels between one line's cell and the next.
        self.line_gap = int(line_gap)
        #: How much larger this font is than the reference one, and therefore
        #: how much larger everything measured in pixels should be.
        self.scale = float(scale)

    @property
    def line_height(self) -> int:
        """Baseline-to-baseline distance: a character cell plus the gap."""
        return self.char_height + self.line_gap

    def pixels(self, value: Any) -> int:
        """A measurement authored at the reference size, in real pixels."""
        return int(round(float(value) * self.scale))

    def text_width(self, text: str) -> int:
        """Width of one line of text."""
        return len(text) * self.char_width

    def text_size(self, text: str) -> Tuple[int, int]:
        """Width and height of possibly multi-line text.

        Empty text measures zero rather than one blank line, so an unset label
        takes no room in a layout.
        """
        if not text:
            return (0, 0)
        lines = text.split('\n')
        return (max(self.text_width(line) for line in lines),
                len(lines) * self.line_height)

    def lines_size(self, lines: Sequence[str]) -> Tuple[int, int]:
        """Width and height of already-wrapped lines."""
        if not lines:
            return (0, 0)
        return (max(self.text_width(line) for line in lines),
                len(lines) * self.line_height)

    def characters_for(self, width: int) -> int:
        """How many characters fit in a pixel width."""
        if self.char_width <= 0:
            return 0
        return max(0, int(width) // self.char_width)

    def wrap(self, text: str, width: int) -> List[str]:
        """Break text into lines that each fit within ``width`` pixels.

        Breaks between words where it can and inside a word where it cannot: a
        word wider than the panel has to be split, because the alternative is
        text running out past the edge, which is the failure this exists to
        prevent.  Explicit newlines are kept, blank lines included, so a
        paragraph break survives wrapping.

        A width too narrow for even one character puts each word on its own
        line rather than one letter per line: the layout is already broken at
        that size, and unreadable-but-whole beats shredded.
        """
        columns = self.characters_for(width)
        lines: List[str] = []
        for paragraph in text.split('\n'):
            if not paragraph.strip():
                lines.append('')
                continue
            lines.extend(self._wrap_paragraph(paragraph, columns))
        return lines

    @staticmethod
    def _wrap_paragraph(paragraph: str, columns: int) -> List[str]:
        if columns <= 0:
            return paragraph.split()
        lines: List[str] = []
        current = ''
        for word in paragraph.split():
            while len(word) > columns:
                if current:
                    lines.append(current)
                    current = ''
                lines.append(word[:columns])
                word = word[columns:]
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= columns:
                current = '%s %s' % (current, word)
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def truncate(self, text: str, width: int) -> str:
        """Cut text to a pixel width, marking that it was cut.

        Used where wrapping is not an option -- a value in a one-line field --
        so the user can see that there is more rather than reading a plausible
        but wrong value.
        """
        columns = self.characters_for(width)
        if len(text) <= columns:
            return text
        if columns <= 0:
            return ''
        if columns == 1:
            return ELLIPSIS
        return text[:columns - 1] + ELLIPSIS


def metrics_for(renderer: Any, line_gap: Optional[int] = None) -> FontMetrics:
    """Measurements for a live :class:`ShaderTextRenderer`.

    The renderer reports zero-sized characters until its atlas is built, and
    laying out against that would collapse every widget, so the caller is
    expected to have initialised it first.

    The scale comes from the cell the atlas actually rendered rather than from
    the size that was asked for: there are nine atlases and a request lands on
    the nearest, so the two are usually not the same number.
    """
    scale = float(renderer.char_height) / float(reference_char_height())
    if line_gap is None:
        line_gap = max(1, int(round(REFERENCE_LINE_GAP * scale)))
    return FontMetrics(renderer.char_width, renderer.char_height,
                       line_gap=line_gap, scale=scale)


def font_size_for(height: int, scale: float = 1.0) -> int:
    """The atlas size an overlay should draw at in a window this tall.

    ``scale`` is the player's own preference, multiplied into the size the
    window height asks for.  Small windows are left at the reference size: text
    scaled down for a 720p display is unreadable rather than merely small, and
    a window that small is more often a test harness than a player's screen.

    The answer is always one of the sizes that exist
    (:func:`OpenGLContext.scenegraph.text.fonts.get_available_sizes`), so a
    slow drag of the window edge cannot build a new atlas per pixel, and the
    largest of them is the ceiling on how big the interface can get.
    """
    automatic = max(1.0, float(height) / float(REFERENCE_HEIGHT))
    return nearest_font_size(REFERENCE_FONT_SIZE * automatic
                             * max(0.1, float(scale)))


def nearest_font_size(size: float) -> int:
    """The available atlas size closest to one that was asked for."""
    return min(_available_sizes(), key=lambda available: abs(available - size))


def reference_char_height() -> int:
    """Cell height of the atlas the skin's pixel measurements are authored for."""
    return _atlas(REFERENCE_FONT_SIZE).char_height


def _available_sizes() -> Sequence[int]:
    from OpenGLContext.scenegraph.text import fonts
    return fonts.get_available_sizes()


def _atlas(size: int) -> Any:
    from OpenGLContext.scenegraph.text import fonts
    _actual, module = fonts.get_closest_atlas(size)
    return module
