"""Semantics for fractional and absolute dragging"""

class DragWatcher(object):
    """Class providing semantics for fractional and absolute dragging

    With this class you can track the start position of a drag action
    and query for both absolute distance dragged, and distance as a
    fraction of the distance to the edges of the window.
    """
    def __init__ (self, startX, startY, totalX, totalY ):
        """Initialise the DragWatcher

        startX, startY -- initial coordinates for the drag
        totalX, totalY -- overall dimensions of the context
        """
        self.start = startX, startY
        self.total = totalX, totalY
    def fractions (self, newX, newY ):
        """Calculate fractional delta from the start point

        newX, newY -- new selection point from which to calculate
        """
        if (newX, newY) == self.start:
            return 0.0,0.0
        values = []
        for index, item in ((0, newX), (1, newY)):
            if item < self.start[index]:
                value = float(item-self.start[index])/ self.start[index]
            else:
                value = float(item-self.start[index])/ (self.total[index]-self.start[index])
            values.append (value)
        return values
    def distances (self, newX, newY ):
        """Calculate absolute distances from start point

        newX, newY -- new selection point from which to calculate
        """
        if (newX, newY) == self.start:
            return 0,0
        else:
            return newX-self.start[0], newY-self.start[1]
        