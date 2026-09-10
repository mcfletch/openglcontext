"""Semantics for fractional and absolute dragging"""
from typing import Tuple


class DragWatcher(object):
    """Class providing semantics for fractional and absolute dragging

    With this class you can track the start position of a drag action
    and query for both absolute distance dragged, and distance as a
    fraction of the distance to the edges of the window.
    """
    def __init__(self, startX: float, startY: float,
                 totalX: float, totalY: float) -> None:
        """Initialise the DragWatcher

        startX, startY -- initial coordinates for the drag
        totalX, totalY -- overall dimensions of the context
        """
        self.start = startX, startY
        self.total = totalX, totalY
    def uniformFractions(self, newX: float, newY: float) -> Tuple[float, float]:
        """Calculate fractional delta measured against the whole window

        newX, newY -- new selection point from which to calculate

        The **symmetric** measure: the same movement gives the same fraction
        wherever the drag began and whichever way it goes.  What
        :meth:`fractions` gives instead is the distance travelled toward the
        edge the pointer is heading for, which is a different scale on each
        side of the start point -- so a drag beginning near an edge is
        hypersensitive in that direction.  Anything mapping movement to an
        angle wants this one; see
        :class:`OpenGLContext.move.orbit.TurntableOrbit`.
        """
        totalX, totalY = self.total
        return (
            (newX - self.start[0]) / float(totalX) if totalX else 0.0,
            (newY - self.start[1]) / float(totalY) if totalY else 0.0,
        )
    def fractions(self, newX: float, newY: float) -> Tuple[float, float]:
        """Calculate fractional delta from the start point toward the edge

        newX, newY -- new selection point from which to calculate

        One at the edge of the window and zero where the drag began, on each
        side independently: the two directions are measured against different
        distances, so this says "how far toward the edge" rather than "how
        far".  For a movement that has to mean the same amount either way, use
        :meth:`uniformFractions`.

        A drag begun on an edge has no distance to travel toward that edge, and
        the fraction is then zero however far the pointer goes that way.
        """
        if (newX, newY) == self.start:
            return 0.0, 0.0
        values = []
        for index, item in ((0, newX), (1, newY)):
            delta = float(item - self.start[index])
            span = self.start[index] if delta < 0 else self.total[index] - self.start[index]
            values.append(delta / span if span else 0.0)
        return values[0], values[1]

    def distances(self, newX: float, newY: float) -> Tuple[float, float]:
        """Calculate absolute distances from start point

        newX, newY -- new selection point from which to calculate
        """
        return newX - self.start[0], newY - self.start[1]
        