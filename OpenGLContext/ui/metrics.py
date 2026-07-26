"""Measuring text for the overlay UI.

Every widget's natural size comes from measured text rather than a guess, which
is what keeps a label inside its own button.  The shader font
(:mod:`OpenGLContext.scenegraph.text.shadertext`) is a fixed-size monospaced
bitmap atlas, so a character width and height describe it completely and the
measurement is exact arithmetic -- testable with no GL context.

:func:`metrics_for` adapts a live text renderer; construct a
:class:`FontMetrics` directly to lay out or test without one.
"""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple

#: Appended to text that was cut to fit.
ELLIPSIS = '…'


class FontMetrics:
    """Character measurements for one monospaced font size."""

    def __init__(self, char_width: int, char_height: int,
                 line_gap: int = 2) -> None:
        self.char_width = int(char_width)
        self.char_height = int(char_height)
        #: Blank pixels between one line's cell and the next.
        self.line_gap = int(line_gap)

    @property
    def line_height(self) -> int:
        """Baseline-to-baseline distance: a character cell plus the gap."""
        return self.char_height + self.line_gap

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


def metrics_for(renderer: Any, line_gap: int = 2) -> FontMetrics:
    """Measurements for a live :class:`ShaderTextRenderer`.

    The renderer reports zero-sized characters until its atlas is built, and
    laying out against that would collapse every widget, so the caller is
    expected to have initialised it first.
    """
    return FontMetrics(renderer.char_width, renderer.char_height,
                       line_gap=line_gap)
