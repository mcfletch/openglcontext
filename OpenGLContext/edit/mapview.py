"""A world seen from straight above, at a scale rather than at a distance.

An editor's plan view. The camera looks down and the projection is
orthographic, so a metre is the same number of pixels wherever it is on the
screen: what is drawn is a *map*, and a route drawn on it with the pointer is
the route the world gets. A perspective view cannot promise that -- the far end
of a straight is half the size of the near end, and a click there means
something different.

:class:`MapView` is the arithmetic: where the middle of the screen is, how many
metres fit down it, and the two conversions an editor lives on --
:meth:`~MapView.world_from_screen` for where the pointer is, and
:meth:`~MapView.screen_from_world` for where to draw a marker.
:class:`MapViewPlatform` presents it to the render pass as an ordinary camera.

::

    view = MapView(centre=(0.0, 0.0), span=1200.0)
    context.platform = MapViewPlatform(view)
    ...
    x, z = view.world_from_screen(event.getPickPoint()[0],
                                  event.getPickPoint()[1], viewport)
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

import numpy as np

from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.passes.shadowmath import ortho_matrix

__all__ = ['MapView', 'MapViewPlatform']

#: How far above the highest ground the camera sits. The projection is
#: orthographic, so this changes nothing about what is drawn; it is there so a
#: frustum test and a near plane both have somewhere to measure from.
STAND_OFF = 10.0


class MapView:
    """Where a plan view is looking, and how much of the world it holds.

    ``centre`` is the world ``(x, z)`` in the middle of the window and ``span``
    is how many metres fit down its *height* -- down rather than across, so a
    wider window shows more world rather than the same world stretched.

    ``floor`` and ``ceiling`` are the heights the view clips at: everything the
    world is expected to occupy, since a plan view that clipped a hilltop away
    would be a map with a hole in it.
    """

    def __init__(self, centre: Tuple[float, float] = (0.0, 0.0),
                 span: float = 1000.0, floor: float = -1000.0,
                 ceiling: float = 2000.0, smallest: float = 10.0,
                 largest: float = 100000.0) -> None:
        self.centre = (float(centre[0]), float(centre[1]))
        self.floor = float(floor)
        self.ceiling = float(ceiling)
        #: The closest and widest the view may be zoomed to.
        self.smallest = float(smallest)
        self.largest = float(largest)
        self.span = float(span)

    @property
    def span(self) -> float:
        """How many metres fit down the height of the window."""
        return self._span

    @span.setter
    def span(self, value: float) -> None:
        self._span = float(min(max(float(value), self.smallest), self.largest))

    # -- the camera --------------------------------------------------------
    def metres_per_pixel(self, viewport: Tuple[int, int]) -> float:
        """The scale the map is drawn at."""
        height = int(viewport[1]) or 1
        return self.span / height

    def matrices(self, viewport: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
        """``(model-view, projection)`` for this view, row-vector.

        The model-view turns the world so that looking down ``-y`` becomes
        looking down ``-z``, which is what a camera does, and puts the map's
        centre at the origin. North (``-z`` in the world) ends up *up* the
        screen, which is what a map does with north.
        """
        model = np.zeros((4, 4), dtype='d')
        model[0, 0] = 1.0       # world +x is screen right
        model[2, 1] = -1.0      # world -z is screen up
        model[1, 2] = 1.0       # world +y is towards the eye, which is +z
        model[3, 3] = 1.0
        eye = np.array([self.centre[0], self.ceiling + STAND_OFF,
                        self.centre[1]], dtype='d')
        model[3, :3] = -(eye @ model[:3, :3])
        half_height = self.span / 2.0
        aspect = (int(viewport[0]) or 1) / (int(viewport[1]) or 1)
        half_width = half_height * aspect
        depth = (self.ceiling + STAND_OFF) - self.floor
        projection = ortho_matrix(-half_width, half_width,
                                  -half_height, half_height, 0.0, depth)
        return model, np.asarray(projection, dtype='d')

    # -- reading the pointer ----------------------------------------------
    def world_from_screen(self, x: float, y: float,
                          viewport: Tuple[int, int]) -> Tuple[float, float]:
        """The world ``(x, z)`` under a window pixel.

        Window pixels count from the bottom left, as GL and the pick point do.
        """
        scale = self.metres_per_pixel(viewport)
        width, height = (int(viewport[0]) or 1), (int(viewport[1]) or 1)
        return (self.centre[0] + (float(x) - width / 2.0) * scale,
                self.centre[1] - (float(y) - height / 2.0) * scale)

    def screen_from_world(self, point: Any,
                          viewport: Tuple[int, int]) -> Tuple[float, float]:
        """Where a world point is drawn, in window pixels.

        Takes ``(x, z)`` or a full ``(x, y, z)``; the height is ignored,
        because in a plan view it does not move anything.
        """
        values = np.asarray(point, dtype='d')
        x, z = (float(values[0]), float(values[-1]))
        scale = self.metres_per_pixel(viewport) or 1e-9
        width, height = (int(viewport[0]) or 1), (int(viewport[1]) or 1)
        return (width / 2.0 + (x - self.centre[0]) / scale,
                height / 2.0 - (z - self.centre[1]) / scale)

    # -- moving about ------------------------------------------------------
    def pan(self, dx: float, dy: float, viewport: Tuple[int, int]) -> None:
        """Drag the map by a pointer movement in pixels.

        The world goes with the pointer, so what was under it stays under it.
        """
        scale = self.metres_per_pixel(viewport)
        self.centre = (self.centre[0] - float(dx) * scale,
                       self.centre[1] + float(dy) * scale)

    def zoom(self, factor: float, at: Optional[Tuple[float, float]] = None,
             viewport: Optional[Tuple[int, int]] = None) -> None:
        """Scale the view. Below 1 comes closer; above 1 draws back.

        ``at`` is a window pixel to zoom about -- the pointer, usually. The
        world point under it is the one that stays put, because a map that
        slides out from under the pointer while it is being zoomed cannot be
        aimed.
        """
        if at is None or viewport is None:
            self.span = self.span * float(factor)
            return
        anchor = self.world_from_screen(at[0], at[1], viewport)
        self.span = self.span * float(factor)
        moved = self.world_from_screen(at[0], at[1], viewport)
        self.centre = (self.centre[0] + anchor[0] - moved[0],
                       self.centre[1] + anchor[1] - moved[1])

    def frame(self, minimum: Tuple[float, float], maximum: Tuple[float, float],
              viewport: Tuple[int, int]) -> None:
        """Put a region on screen: centred, and wholly inside the window."""
        self.centre = ((float(minimum[0]) + float(maximum[0])) / 2.0,
                       (float(minimum[1]) + float(maximum[1])) / 2.0)
        width, height = (int(viewport[0]) or 1), (int(viewport[1]) or 1)
        across = abs(float(maximum[0]) - float(minimum[0]))
        down = abs(float(maximum[1]) - float(minimum[1]))
        # Whichever direction needs the smaller scale decides, or the other one
        # runs off the edge.
        self.span = max(down, across * height / width, self.smallest)


class MapViewPlatform(ViewPlatform):
    """A :class:`MapView` presented to the render pass as a camera.

    Reads the view rather than copying it, so panning or zooming the map is
    what moves the camera; there is no second copy of where the editor is
    looking to fall out of step with the first.
    """

    def __init__(self, view: MapView, viewport: Tuple[int, int] = (1, 1)) -> None:
        # Before the base class, because setting a position on this platform
        # is how the map is told where to look, and the base sets one.
        self.view = view
        self.viewport = (int(viewport[0]), int(viewport[1]))
        super(MapViewPlatform, self).__init__(
            position=(view.centre[0], view.ceiling + STAND_OFF, view.centre[1]))

    def setViewport(self, x: int, y: int) -> None:
        self.viewport = (int(x), int(y))

    @property
    def position(self) -> np.ndarray:
        """Where the camera is: above the middle of the map, looking down."""
        return np.array([self.view.centre[0], self.view.ceiling + STAND_OFF,
                         self.view.centre[1], 1.0], dtype='d')

    @position.setter
    def position(self, value: Any) -> None:
        """Move the map to sit under a position handed to the platform."""
        values = np.asarray(value, dtype='d')
        self.view.centre = (float(values[0]), float(values[2]))

    def setPosition(self, position: Any) -> None:
        self.position = position

    def viewMatrix(self, trimDepth: Any = None,
                   inverse: bool = False) -> np.ndarray:
        projection = self.view.matrices(self.viewport)[1]
        if inverse:
            return np.linalg.inv(projection).astype('f')
        return projection.astype('f')

    def modelMatrix(self, inverse: bool = False) -> np.ndarray:
        model = self.view.matrices(self.viewport)[0]
        if inverse:
            return np.linalg.inv(model).astype('f')
        return model.astype('f')

    def matrix(self, inverse: bool = False) -> np.ndarray:
        model, projection = self.view.matrices(self.viewport)
        if inverse:
            return np.linalg.inv(model @ projection).astype('f')
        combined: np.ndarray = model @ projection
        return combined.astype('f')
