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
    """

    PROTO = 'Grid'
    children = field.newField('children', 'MFNode', 1, list)
    columns = field.newField('columns', 'SFInt32', 1, 2)
    #: Pixels between one row and the next.
    spacing = field.newField('spacing', 'SFFloat', 1, 4.0)
    #: Pixels between one column and the next.
    columnSpacing = field.newField('columnSpacing', 'SFFloat', 1, 8.0)
    #: Share of the leftover width per column.  Empty gives it all to the last.
    columnFlex = field.newField('columnFlex', 'MFFloat', 1, list)

    def layoutChildren(self) -> Sequence[Any]:
        return [child for child in self.children
                if getattr(child, 'visible', True)]

    # -- measurement ------------------------------------------------------
    def _rows(self) -> List[List[Any]]:
        """The children grouped into rows; the last row may be short."""
        count = max(1, int(self.columns))
        children = list(self.layoutChildren())
        return [children[start:start + count]
                for start in range(0, len(children), count)]

    def _measure(self, metrics: Any) -> Tuple[List[int], List[int]]:
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

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        if not self.layoutChildren():
            return (0, 0)
        widths, heights = self._measure(metrics)
        return (sum(widths) + int(self.columnSpacing) * (len(widths) - 1),
                sum(heights) + int(self.spacing) * (len(heights) - 1))

    # -- placement --------------------------------------------------------
    def _columnWidths(self, metrics: Any, available: int) -> List[int]:
        widths, _heights = self._measure(metrics)
        gaps = int(self.columnSpacing) * (len(widths) - 1)
        spare = available - sum(widths) - gaps
        if spare <= 0:
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

    def arrange_content(self, metrics: Any) -> None:
        rows = self._rows()
        if not rows:
            return
        widths = self._columnWidths(metrics, self.rect.width)
        _columns, heights = self._measure(metrics)
        spacing = int(self.spacing)
        column_spacing = int(self.columnSpacing)
        cursor_y = self.rect.top
        for row, height in zip(rows, heights, strict=True):
            cursor_x = self.rect.x
            for index, child in enumerate(row):
                child.parent = self
                child.arrange(Rect(cursor_x, cursor_y - height,
                                   widths[index], height), metrics)
                cursor_x += widths[index] + column_spacing
            cursor_y -= height + spacing
