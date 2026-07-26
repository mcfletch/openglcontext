"""Containers: a row, a column and a grid of label/control pairs.

All three are one top-down pass with no constraint solver: a child reports the
size it wants, the container hands back a rectangle, and that is the end of it.
:class:`~OpenGLContext.hud.GUIBox` does the work for the two boxes; the grid
adds the one thing a box cannot express, which is a column of labels that lines
up across unrelated rows.
"""

from typing import Any, List, Optional, Sequence, Tuple

from vrml import field

from OpenGLContext.hud import COLUMN, GUIBox, ROW
from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.widgets import Widget

__all__ = ['Box', 'Row', 'Column', 'Grid']


class Box(Widget, GUIBox):
    """A run of children along one axis, and a widget like any other.

    The layout is :class:`~OpenGLContext.hud.GUIBox`'s; what this adds is the
    widget half -- hit-testing through to the children, hover, the press it
    passes on.
    """

    PROTO = 'Box'


class Row(Box):
    """Children side by side, sharing the width left over."""

    PROTO = 'Row'
    direction = field.newField('direction', 'SFString', 1, ROW)


class Column(Box):
    """Children stacked downward from the top, sharing the height left over."""

    PROTO = 'Column'
    direction = field.newField('direction', 'SFString', 1, COLUMN)


class Grid(Widget):
    """Cells in a fixed number of columns, filled left to right, top to bottom.

    Every cell in a column gets that column's width, so the controls of a
    settings page line up however long each label happens to be -- the reason
    this is not just a column of rows.  Space left over goes to the columns
    named in ``columnFlex``, or to the last column, which is where the controls
    are.

    **A row is a thing, not two things side by side.**  ``rowPadding`` gives
    each one room above and below, a hairline is drawn in the gap between one
    row and the next, and the row the pointer is on or the keyboard is in is
    washed with a faint fill.  Together they are what lets the eye run from a
    label on the left to the control on the right without losing the line, and
    what makes the whole row a target rather than the control alone.

    Pixel sizes here are at the reference font size and are multiplied by the
    interface scale; the colours come from the panel's skin.
    """

    PROTO = 'Grid'
    children = field.newField('children', 'MFNode', 1, list)
    columns = field.newField('columns', 'SFInt32', 1, 2)
    #: Pixels between one row and the next.
    spacing = field.newField('spacing', 'SFFloat', 1, 4.0)
    #: Pixels between one column and the next.
    columnSpacing = field.newField('columnSpacing', 'SFFloat', 1, 8.0)
    #: Pixels of clear space above and below each row's contents.
    rowPadding = field.newField('rowPadding', 'SFFloat', 1, 0.0)
    #: Share of the leftover width per column.  Empty gives it all to the last.
    columnFlex = field.newField('columnFlex', 'MFFloat', 1, list)

    #: ``rowPadding`` in real pixels, settled at layout time.
    _laidOutPadding: int = 0

    def layoutChildren(self) -> Sequence[Widget]:
        return [child for child in self.children
                if getattr(child, 'visible', True)]

    # -- measurement ------------------------------------------------------
    def _rows(self) -> List[List[Any]]:
        """The children grouped into rows; the last row may be short."""
        count = max(1, int(self.columns))
        children = list(self.layoutChildren())
        return [children[start:start + count]
                for start in range(0, len(children), count)]

    def _measure(self, metrics: FontMetrics) -> Tuple[List[int], List[int]]:
        """Natural width of each column and height of each row."""
        rows = self._rows()
        widths = [0] * max(1, int(self.columns))
        heights = []
        for row in rows:
            tallest = 0
            for index, child in enumerate(row):
                width, height = child.natural_size(metrics)
                widths[index] = max(widths[index], int(width))
                tallest = max(tallest, int(height))
            heights.append(tallest)
        return (widths, heights)

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        if not self.layoutChildren():
            return (0, 0)
        widths, heights = self._measure(metrics)
        padding = metrics.pixels(self.rowPadding) * 2
        return (sum(widths)
                + metrics.pixels(self.columnSpacing) * (len(widths) - 1),
                sum(heights) + padding * len(heights)
                + metrics.pixels(self.spacing) * (len(heights) - 1))

    # -- placement --------------------------------------------------------
    #: Characters a column is never squeezed below.  Narrower than this and a
    #: label is not shortened, it is destroyed.
    MINIMUM_COLUMN_CHARS = 4

    def _columnWidths(self, metrics: FontMetrics, available: int) -> List[int]:
        widths, _heights = self._measure(metrics)
        gaps = metrics.pixels(self.columnSpacing) * (len(widths) - 1)
        spare = available - sum(widths) - gaps
        if spare < 0:
            return self._squeeze(widths, -spare, metrics)
        if spare == 0:
            return widths
        flex = [float(value) for value in self.columnFlex]
        if len(flex) != len(widths) or sum(flex) <= 0:
            flex = [0.0] * len(widths)
            flex[-1] = 1.0
        total = sum(flex)
        given = 0
        claimants = [index for index, value in enumerate(flex) if value]
        for position, index in enumerate(claimants):
            share = (spare - given if position == len(claimants) - 1
                     else int(spare * flex[index] / total))
            widths[index] += share
            given += share
        return widths

    def _squeeze(self, widths: List[int], shortfall: int,
                 metrics: FontMetrics) -> List[int]:
        """Take a shortfall out of the widest columns, never below a floor.

        Unlike a box, a grid has an obvious place to find the room: the label
        column is the one with slack, and text that is shortened -- with an
        ellipsis, by whatever draws it -- still reads.  Overflowing instead
        would put a control over the scrollbar or off the panel, where it can
        be clicked but not seen.
        """
        floor = self.MINIMUM_COLUMN_CHARS * metrics.char_width
        widths = list(widths)
        while shortfall > 0:
            widest = max(range(len(widths)), key=lambda index: widths[index])
            if widths[widest] <= floor:
                break                   # nothing left to give
            take = min(shortfall, widths[widest] - floor)
            widths[widest] -= take
            shortfall -= take
        return widths

    def arrange_content(self, metrics: FontMetrics) -> None:
        rows = self._rows()
        if not rows:
            return
        widths = self._columnWidths(metrics, self.rect.width)
        _columns, heights = self._measure(metrics)
        spacing = metrics.pixels(self.spacing)
        column_spacing = metrics.pixels(self.columnSpacing)
        padding = self._laidOutPadding = metrics.pixels(self.rowPadding)
        cursor_y = self.rect.top - padding
        for row, height in zip(rows, heights, strict=True):
            cursor_x = self.rect.x
            for index, child in enumerate(row):
                child.parent = self
                child.arrange(Rect(cursor_x, cursor_y - height,
                                   widths[index], height), metrics)
                cursor_x += widths[index] + column_spacing
            cursor_y -= height + padding * 2 + spacing

    # -- rows as a whole ---------------------------------------------------
    def rowRects(self) -> List[Rect]:
        """One rectangle per row, spanning the grid and taking in the padding.

        Derived from where the cells actually are rather than remembered from
        layout, so a row drawn inside a scrolling viewport moves with its
        contents instead of staying where the page started.
        """
        count = max(1, int(self.columns))
        children = list(self.layoutChildren())
        padding = self._rowPaddingPixels()
        rects = []
        for start in range(0, len(children), count):
            row = children[start:start + count]
            top = max(child.rect.top for child in row)
            bottom = min(child.rect.y for child in row)
            rects.append(Rect(self.rect.x, bottom - padding, self.rect.width,
                              (top - bottom) + padding * 2))
        return rects

    def _rowPaddingPixels(self) -> int:
        """The row padding in real pixels, settled when the grid was arranged.

        A size rather than a position, so unlike the cells' rectangles it does
        not move when the page is scrolled.
        """
        return self._laidOutPadding

    def rowOf(self, widget: Any) -> Optional[int]:
        """Which row a widget sits in, or None if it is not in this grid.

        A control nested inside a cell still belongs to the cell's row, so the
        search is upward from the widget rather than downward from the grid --
        which is also what makes it cheap enough to do when the pointer moves
        instead of when the frame draws.
        """
        count = max(1, int(self.columns))
        cells = list(self.layoutChildren())
        current: Optional[Any] = widget
        while current is not None:
            for index, cell in enumerate(cells):
                if cell is current:
                    return index // count
            current = current.parent
        return None

    def activeRows(self) -> Tuple[Optional[int], Optional[int]]:
        """Which row the pointer is on, and which the keyboard is in.

        Read from what the panel already knows rather than searched for: hover
        and focus each change at exactly one place, and recomputing them by
        walking every widget in every cell on every frame is work the layout
        deliberately does only on a change.
        """
        panel = self.root()
        hovered = self.rowOf(getattr(panel, 'hovered_widget', None))
        focused = None
        if getattr(panel, 'focusVisible', False):
            focused = self.rowOf(getattr(panel, 'focused_widget', None))
        return (hovered, focused)

    def paint(self, renderer: Any) -> None:
        skin = renderer.skin
        hovered, focused = self.activeRows()
        rects = self.rowRects()
        for index, rect in enumerate(rects):
            if index == focused:
                renderer.rect(rect, skin.rowFocus)
            elif index == hovered:
                renderer.rect(rect, skin.rowHover)
            if index and float(skin.rowRule[3]):
                # In the gap above the row, where it separates rather than
                # underlines: a rule against a row's own edge reads as a box.
                # A whole pixel at every scale, or it is a line nobody can see.
                previous = rects[index - 1]
                thickness = max(1, renderer.metrics.pixels(1))
                renderer.rect(Rect(rect.x, (rect.top + previous.y) // 2,
                                   rect.width, thickness), skin.rowRule)
