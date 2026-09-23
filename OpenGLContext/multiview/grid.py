"""The grid a view is measured against.

An editor's views draw a grid to place things on: one line every so many
units, a heavier one every tenth, in the plane the view looks at. A plan view
and one that turns are ruled across the ground; an elevation is ruled in its
own upright plane, which is where its measurements are.

**How closely it is ruled follows the view's scale.** A grid at a fixed
spacing is a sheet of solid lines when the view is zoomed out and a bare field
when it is zoomed in, so the step is chosen from the ones a ruler is marked in
-- one, two and five in every decade -- as the one that lands nearest a
comfortable number of pixels apart.

The grid is a node the application puts in its scene, and each view is told
whether to draw it: ``grid.show(view, True)``. What it draws is
:func:`lines_for`, which is arithmetic and holds no GL, so what a view is
ruled with can be asked and tested without a window.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.multiview.views import View

__all__ = ['Grid', 'GridLines', 'lines_for', 'spacing_for',
           'DECADE', 'WANTED_PIXELS', 'HEAVY_EVERY']

#: The base the steps are chosen in: one, two and five of every power of ten.
DECADE = 10.0

#: How far apart the lines are aimed to be, in pixels. The step chosen is the
#: one of a ruler's that lands nearest this.
WANTED_PIXELS = 24.0

#: Every so many lines is drawn heavier, so the eye can count along the grid
#: rather than measuring it.
HEAVY_EVERY = 10

#: The steps a ruler is marked in, within one decade.
STEPS = (1.0, 2.0, 5.0)

Point = Tuple[float, float, float]


class GridLines(NamedTuple):
    """What a view's grid is drawn from.

    ``segments`` are the lines as world-space pairs, ``heavy`` the indices of
    those drawn heavier, and ``spacing`` how many units apart they are.
    """

    segments: List[Tuple[Point, Point]]
    heavy: List[int]
    spacing: float


def spacing_for(shown: float, pixels: int) -> float:
    """How many units apart to rule a view showing ``shown`` units in ``pixels``.

    One of :data:`STEPS` in some decade: the one that puts the lines nearest
    :data:`WANTED_PIXELS` apart, so a grid stays readable at any zoom.
    """
    shown = abs(float(shown))
    pixels = abs(int(pixels))
    if shown <= 0.0 or pixels <= 0:
        return 1.0
    wanted = shown * WANTED_PIXELS / pixels
    power = math.floor(math.log10(wanted)) if wanted > 0 else 0
    best, nearest = STEPS[0] * DECADE ** power, None
    for reach in (power, power + 1):
        for step in STEPS:
            candidate = step * DECADE ** reach
            apart = abs(math.log10(candidate / wanted))
            if nearest is None or apart < nearest:
                best, nearest = candidate, apart
    return best


def _plane(view: View) -> Optional[Tuple[np.ndarray, np.ndarray, Point, float]]:
    """The two world directions a view is ruled along, its middle, and its scale.

    An elevation is ruled in its own plane; a plan view and one that turns are
    ruled across the ground, which is the plane things stand on.
    """
    camera = getattr(view.camera, 'view', None)
    if camera is None:
        return None
    across = np.array([1.0, 0.0, 0.0])
    along = np.array([0.0, 0.0, 1.0])
    if hasattr(camera, 'orbit'):                    # a camera that turns
        target = camera.target()
        middle = (float(target[0]), 0.0, float(target[2]))
        shown = 2.0 * camera.distance * math.tan(math.radians(camera.fov) / 2.0)
        return across, along, middle, shown
    centre = tuple(float(value) for value in camera.centre)
    direction = getattr(camera, 'direction', None)
    if direction is None:                           # a plan view of an editor
        return across, along, (centre[0], 0.0, centre[1]), float(camera.span)
    if direction in ('top', 'bottom'):
        middle = (centre[0], 0.0, centre[2])
        return across, along, middle, float(camera.span)
    # An elevation: ruled in the plane it looks at, which is its own axes.
    return (np.asarray(camera.right, 'd'), np.asarray(camera.up, 'd'),
            (centre[0], centre[1], centre[2]), float(camera.span))


def lines_for(view: View, spacing: Optional[float] = None) -> Optional[GridLines]:
    """The lines to rule ``view`` with, or None for a view with no camera.

    The lines stand on the step rather than where the view happens to be, so
    one falls on every round number and the grid reads as a ruler.
    """
    found = _plane(view)
    if found is None:
        return None
    across, along, middle, shown = found
    width, height = view.size
    height = int(height) or 1
    width = int(width) or height
    step = float(spacing) if spacing else spacing_for(shown, height)
    # As much as the view shows, and half again, so a view panned between
    # frames is still ruled to its edges.
    reach = max(shown, shown * width / height) * 0.75
    count = int(math.ceil(reach / step))
    origin = np.asarray(middle, 'd')
    # Where the middle of the view falls on the grid, so the lines are on the
    # step and not on the camera.
    offset_x = round(float(np.dot(origin, across)) / step) * step
    offset_y = round(float(np.dot(origin, along)) / step) * step
    segments: List[Tuple[Point, Point]] = []
    heavy: List[int] = []
    for direction, other, offset, other_offset in (
            (across, along, offset_x, offset_y),
            (along, across, offset_y, offset_x)):
        for index in range(-count, count + 1):
            at = offset + index * step
            reach_to = other_offset + reach
            reach_from = other_offset - reach
            start = direction * at + other * reach_from
            end = direction * at + other * reach_to
            if round(at / step) % HEAVY_EVERY == 0:
                heavy.append(len(segments))
            segments.append((
                (float(start[0]), float(start[1]), float(start[2])),
                (float(end[0]), float(end[1]), float(end[2]))))
    return GridLines(segments, heavy, step)


class Grid:
    """A grid the views of a window can each be told to draw.

    ``spacing`` pins how many units apart the lines are; with none given each
    view is ruled to its own scale. ``colour`` and ``heavyColour`` are what the
    ordinary and the every-tenth lines are drawn in.
    """

    def __init__(self, spacing: Optional[float] = None,
                 colour: Sequence[float] = (0.35, 0.36, 0.38, 1.0),
                 heavyColour: Sequence[float] = (0.5, 0.51, 0.54, 1.0)) -> None:
        self.spacing = spacing
        self.colour = tuple(colour)
        self.heavyColour = tuple(heavyColour)
        #: Which views draw it, by view.
        self._shown: Dict[int, bool] = {}

    def show(self, view: View, shown: bool = True) -> None:
        """Say whether this view draws the grid."""
        self._shown[id(view)] = bool(shown)

    def shownIn(self, view: Any) -> bool:
        """Whether this view draws it; False for a view never told."""
        return bool(self._shown.get(id(view), False))

    def linesFor(self, view: View) -> Optional[GridLines]:
        """What to draw in this view, or None where it draws none."""
        if not self.shownIn(view):
            return None
        return lines_for(view, self.spacing)
