"""A NURBS surface's control points, as a cage a pointer can pick and drag.

A NURBS surface is one shape, so a pick answers with the surface however
carefully it was aimed: there is nothing in the frame that *is* the third
control point. The net supplies one -- a marker standing on every control
point, small enough to see past and large enough to hit -- so a picked marker
is a control point by name, and moving it is an edit to the surface::

    net = ControlNet(shape.geometry)
    group.children = list(group.children) + [net.node]
    ...
    index = net.index_for(event.getObjectPaths())
    if index is not None:
        net.select(index)
        gizmo.attach(net.point(index))

Pair it with :class:`~OpenGLContext.edit.gizmo.TranslationGizmo` for the drag
itself: the net says which point, the gizmo says where it is going, and
:meth:`~ControlNet.move` writes it back.

**The lines matter as much as the markers.** A marker on its own says where one
point is; the row and the column it lies on say which points it is *between*,
and that is what tells a designer what a pull is about to do to the surface --
the cage bends first and the surface follows it. So the net draws a polyline
along every row and every column of the control grid (one polyline through the
lot, for a curve), and moves them with the points. The cage is
``pickable=False``: it is there to be read rather than aimed at, and a line
lying over a marker must not swallow a click meant for the point or the surface
behind it.

The markers share one geometry and one appearance, so a whole net is one
instanced draw rather than a draw per point (see
:mod:`OpenGLContext.passes.instancing`), and the cage is a second. The selected
marker is the exception: it is given its own appearance for as long as it is
selected, which is both what takes it out of the batch and what makes it
visibly the one being worked on.

``controlPoint`` is the field name VRML97 gives both ``NurbsSurface`` and
``NurbsCurve``, so a net serves either. A surface's grid is read the way the
renderer reads it -- ``vDimension`` rows of ``uDimension`` points -- so the
cage's rows are the surface's rows.
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

import numpy as np

from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.coordinate import Coordinate
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.indexedlineset import IndexedLineSet
from OpenGLContext.scenegraph.material import Material
from OpenGLContext.scenegraph.quadrics import Sphere
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform

__all__ = ['ControlNet', 'cage_polylines']

#: How big a marker is, in the surface's own units.
MARKER_SIZE = 0.25

#: The colour of a control point, and of the one being worked on.
MARKER_COLOUR = (0.85, 0.85, 0.88)
SELECTED_COLOUR = (1.00, 0.80, 0.15)

#: How much of its own colour a marker glows with. Control points are controls
#: rather than scenery: they have to read against whatever surface they sit on,
#: including the unlit side of it.
MARKER_GLOW, SELECTED_GLOW = 0.30, 0.55

#: The cage's colour. Dimmer than a marker, because the lines are context for
#: the points rather than things to aim at, and there are a great many more of
#: them. A line carries no lighting, so this is the colour it is drawn.
CAGE_COLOUR = (0.45, 0.48, 0.55)


def cage_polylines(count: int, columns: int = 0) -> List[List[int]]:
    """The rows and columns of a control grid, as lists of point indices.

    ``columns`` is the grid's width -- ``uDimension`` for a surface, since that
    is the stride the renderer reads ``controlPoint`` at. Zero, one, or a width
    the count does not divide by has no grid in it, so the answer is the single
    polyline through every point in order, which is what a curve's cage is.
    """
    if columns < 2 or count < 2 or count % columns:
        return [list(range(count))] if count > 1 else []
    rows = count // columns
    return ([[row * columns + column for column in range(columns)]
             for row in range(rows)]
            + [[row * columns + column for row in range(rows)]
               for column in range(columns)])


class ControlNet:
    """The control points of a NURBS node, drawn as markers and editable.

    ``node`` goes in the scenegraph beside the surface, in the same group, so
    the markers stand where the control points are without anything converting
    between the two. ``markers`` are the marker nodes in control-point order,
    which is the order the ``controlPoint`` field is written in, and ``lines``
    is the cage drawn between them.
    """

    def __init__(self, surface: Any, size: float = MARKER_SIZE,
                 colour: Sequence[float] = MARKER_COLOUR,
                 selected_colour: Sequence[float] = SELECTED_COLOUR,
                 cage_colour: Sequence[float] = CAGE_COLOUR) -> None:
        self.surface = surface
        points = np.asarray(surface.controlPoint, dtype='d')
        #: The one geometry and the one appearance every idle marker shares.
        self.geometry = Sphere(radius=float(size))
        self.appearance = _appearance(colour, MARKER_GLOW)
        self.selected_appearance = _appearance(selected_colour, SELECTED_GLOW)
        self.markers: List[Transform] = [
            Transform(
                translation=tuple(float(value) for value in point),
                children=[Shape(appearance=self.appearance,
                                geometry=self.geometry)],
            )
            for point in points
        ]
        #: The cage's own copy of the points. The markers carry theirs as
        #: translations, so the two are moved together by :meth:`move`.
        self.coordinate = Coordinate(point=points)
        #: The rows and columns, unpickable so a click reaches past them.
        self.lines = Shape(
            appearance=_appearance(cage_colour, 1.0),
            geometry=IndexedLineSet(
                coord=self.coordinate,
                coordIndex=_index_list(cage_polylines(
                    len(points), int(getattr(surface, 'uDimension', 0) or 0))),
            ),
            pickable=False,
        )
        #: The cage first, so the markers a pointer aims at are drawn over it.
        self.node = Group(children=[self.lines] + list(self.markers))
        self._selected: Optional[int] = None

    # -- reading it --------------------------------------------------------
    @property
    def points(self) -> np.ndarray:
        """Every control point, in the order the markers are held in."""
        return np.asarray(self.surface.controlPoint, dtype='d')

    def point(self, index: int) -> np.ndarray:
        """Where one control point stands."""
        return np.asarray(self.surface.controlPoint[index], dtype='d')

    def index_for(self, paths: Any) -> Optional[int]:
        """Which control point a set of picked node paths went through."""
        for path in paths or ():
            for item in path:
                for index, marker in enumerate(self.markers):
                    if item is marker:
                        return index
        return None

    # -- editing it --------------------------------------------------------
    def move(self, index: int, position: Any) -> None:
        """Put a control point somewhere, and its marker and cage with it.

        Both fields are *assigned* rather than written through: the surface's
        tessellation is cached against ``controlPoint`` and the cage's line
        buffer against the coordinate's ``point``, and both caches watch for
        the field being set. An in-place write would leave the old surface on
        screen under a cage drawn where the point used to be.
        """
        points = np.array(self.surface.controlPoint, dtype='f')
        points[index] = np.asarray(position, dtype='f')
        self.surface.controlPoint = points
        self.coordinate.point = points
        self.markers[index].translation = tuple(
            float(value) for value in points[index])

    # -- the one being worked on -------------------------------------------
    @property
    def selected(self) -> Optional[int]:
        """Which control point is being worked on, if any."""
        return self._selected

    def select(self, index: int) -> None:
        """Mark one control point as the one being worked on."""
        marker = self.markers[index]
        self.deselect()
        marker.children[0].appearance = self.selected_appearance
        self._selected = int(index)

    def deselect(self) -> None:
        """Put the marked control point back to an ordinary one."""
        if self._selected is not None:
            self.markers[self._selected].children[0].appearance = \
                self.appearance
            self._selected = None


def _index_list(polylines: Sequence[Sequence[int]]) -> List[int]:
    """Polylines as the ``-1``-separated index list VRML97 wants."""
    indices: List[int] = []
    for polyline in polylines:
        indices.extend(int(index) for index in polyline)
        indices.append(-1)
    return indices


def _appearance(colour: Sequence[float], glow: float) -> Appearance:
    return Appearance(material=Material(
        diffuseColor=tuple(float(channel) for channel in colour),
        emissiveColor=tuple(float(channel) * glow for channel in colour),
    ))
