"""A world seen along one axis, at a scale rather than at a distance.

The top, front and side views of an editor. The projection is orthographic,
so a unit is the same number of pixels wherever it is in the view, and a point
under the pointer is a point in the view's own plane: a drag in the front view
moves something in x and y and leaves its z alone.

:class:`OrthoView` is the arithmetic: which way it looks, the point in the
middle of the view, how many units fit down it, and the conversions between a
pixel and a world point. :class:`OrthoViewPlatform` presents it to the render
pass as an ordinary camera, and is what a :class:`~OpenGLContext.multiview.views.View`
is given::

    front = OrthoView('front', centre=(0.0, 1.0, 0.0), span=4.0)
    layout = ViewLayout.split(View(OrthoViewPlatform(front)), View())
    ...
    front.pan(dx, dy, view.rect[2:])           # a drag, in view pixels
    front.zoom(0.8, at=view.local(x, y), viewport=view.rect[2:])

:class:`~OpenGLContext.edit.mapview.MapView` is the ``'top'`` view of a
terrain editor, with its centre given as a map's ``(x, z)``.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, Tuple, Union

import numpy as np

from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.passes.shadowmath import ortho_matrix

__all__ = ['DIRECTIONS', 'OrthoView', 'OrthoViewPlatform', 'Point']

Vector = Tuple[float, float, float]
#: A point given as a sequence of numbers or as an array.
Point = Union[Sequence[float], np.ndarray]

#: For each direction a view can look along, the world directions of the
#: view's right, its up, and the way back towards the camera. The camera stands
#: on the side the name gives -- ``'front'`` stands at +z looking down -z,
#: which is the view a VRML or glTF scene opens on -- and ``'top'`` puts -z up
#: the screen, as a map puts north.
DIRECTIONS: Dict[str, Tuple[Vector, Vector, Vector]] = {
    'front': ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    'back': ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),
    'right': ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
    'left': ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
    'top': ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    'bottom': ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
}


def _size(viewport: Sequence[float]) -> Tuple[int, int]:
    """A viewport's width and height, neither of them zero."""
    return (int(viewport[0]) or 1), (int(viewport[1]) or 1)


class OrthoView:
    """Where an orthographic view is looking, and how much of the world it holds.

    ``direction`` is a key of :data:`DIRECTIONS`. ``centre`` is the world point
    in the middle of the view, and ``span`` how many units fit down its
    *height* -- down rather than across, so a wider view shows more of the
    world rather than the same world stretched. ``depth`` is how far along the
    axis the view reaches, half in front of the centre and half behind it.
    ``smallest`` and ``largest`` are the limits a zoom holds the span to.
    """

    def __init__(self, direction: str = 'front',
                 centre: Sequence[float] = (0.0, 0.0, 0.0), span: float = 10.0,
                 depth: float = 1000.0, smallest: float = 1e-4,
                 largest: float = 1e7) -> None:
        self.centre = tuple(float(value) for value in centre[:3])
        self.direction = direction
        self.depth = float(depth)
        self.smallest = float(smallest)
        self.largest = float(largest)
        self.span = float(span)

    @property
    def direction(self) -> str:
        """Which way the view looks: a key of :data:`DIRECTIONS`.

        Assigning another turns the camera to it and keeps where it is looking
        and how much it shows, so a view swapped from the front to the side is
        the same scene from another quarter rather than somewhere else.
        """
        return self._direction

    @direction.setter
    def direction(self, value: str) -> None:
        if value not in DIRECTIONS:
            raise ValueError('%r is not one of %s'
                             % (value, ', '.join(DIRECTIONS)))
        self._direction = value
        right, up, back = DIRECTIONS[value]
        self._right = np.array(right, dtype='d')
        self._up = np.array(up, dtype='d')
        self._back = np.array(back, dtype='d')

    @property
    def right(self) -> np.ndarray:
        """The world direction to the right of the view."""
        return self._right.copy()

    @property
    def up(self) -> np.ndarray:
        """The world direction up the view."""
        return self._up.copy()

    @property
    def back(self) -> np.ndarray:
        """The world direction from the scene towards the camera."""
        return self._back.copy()

    @property
    def span(self) -> float:
        """How many units fit down the height of the view."""
        return self._span

    @span.setter
    def span(self, value: float) -> None:
        self._span = float(min(max(float(value), self.smallest), self.largest))

    def units_per_pixel(self, viewport: Sequence[float]) -> float:
        """The scale the view is drawn at."""
        return self.span / _size(viewport)[1]

    # -- the camera --------------------------------------------------------
    def eye(self) -> np.ndarray:
        """Where the camera stands: back along the axis, at the near edge of the depth."""
        position: np.ndarray = np.asarray(self.centre, 'd') + self._back * (self.depth / 2.0)
        return position

    def matrices(self, viewport: Sequence[float]) -> Tuple[np.ndarray, np.ndarray]:
        """``(model-view, projection)`` for this view, row-vector."""
        model = np.zeros((4, 4), dtype='d')
        model[:3, 0] = self._right
        model[:3, 1] = self._up
        model[:3, 2] = self._back
        model[3, 3] = 1.0
        model[3, :3] = -(self.eye() @ model[:3, :3])
        width, height = _size(viewport)
        half_height = self.span / 2.0
        half_width = half_height * width / height
        projection = ortho_matrix(-half_width, half_width,
                                  -half_height, half_height, 0.0, self.depth)
        return model, np.asarray(projection, dtype='d')

    # -- reading the pointer ----------------------------------------------
    def world_from_screen(self, x: float, y: float,
                          viewport: Sequence[float]) -> np.ndarray:
        """The world point under a view pixel, in the plane through the centre.

        Pixels count from the bottom left of the view, as
        :meth:`~OpenGLContext.multiview.views.View.local` gives them.
        """
        scale = self.units_per_pixel(viewport)
        width, height = _size(viewport)
        point: np.ndarray = (np.asarray(self.centre, 'd')
                             + self._right * (float(x) - width / 2.0) * scale
                             + self._up * (float(y) - height / 2.0) * scale)
        return point

    def screen_from_world(self, point: Point,
                          viewport: Sequence[float]) -> Tuple[float, float]:
        """The view pixel a world point is drawn at; its depth moves nothing."""
        offset = np.asarray(point[:3], 'd') - np.asarray(self.centre, 'd')
        scale = self.units_per_pixel(viewport) or 1e-12
        width, height = _size(viewport)
        return (width / 2.0 + float(offset @ self._right) / scale,
                height / 2.0 + float(offset @ self._up) / scale)

    # -- moving about ------------------------------------------------------
    def pan(self, dx: float, dy: float, viewport: Sequence[float]) -> None:
        """Drag the view by a pointer movement in pixels.

        The world goes with the pointer, so what was under it stays under it.
        """
        scale = self.units_per_pixel(viewport)
        moved = (np.asarray(self.centre, 'd')
                 - self._right * float(dx) * scale - self._up * float(dy) * scale)
        self.centre = tuple(float(value) for value in moved)

    def zoom(self, factor: float, at: Optional[Sequence[float]] = None,
             viewport: Optional[Sequence[float]] = None) -> None:
        """Scale the view. Below 1 comes closer; above 1 draws back.

        ``at`` is a view pixel to zoom about, usually the pointer; the world
        point under it stays where it is.
        """
        if at is None or viewport is None:
            self.span = self.span * float(factor)
            return
        anchor = self.world_from_screen(at[0], at[1], viewport)
        self.span = self.span * float(factor)
        moved = self.world_from_screen(at[0], at[1], viewport)
        shifted = np.asarray(self.centre, 'd') + anchor - moved
        self.centre = tuple(float(value) for value in shifted)

    def frame(self, minimum: Point, maximum: Point,
              viewport: Sequence[float]) -> None:
        """Put a box on screen: centred, wholly inside the view, and within its depth."""
        low = np.asarray(minimum[:3], 'd')
        high = np.asarray(maximum[:3], 'd')
        self.centre = tuple(float(value) for value in (low + high) / 2.0)
        size = np.abs(high - low)
        across = float(size @ np.abs(self._right))
        down = float(size @ np.abs(self._up))
        width, height = _size(viewport)
        # Whichever direction needs the smaller scale decides, or the other
        # runs off the edge.
        self.span = max(down, across * height / width, self.smallest)
        self.depth = max(self.depth, 2.0 * float(size @ np.abs(self._back)))


class OrthoViewPlatform(ViewPlatform):
    """An :class:`OrthoView` presented to the render pass as a camera.

    Reads the view rather than copying it, so panning or zooming the view is
    what moves the camera.
    """

    def __init__(self, view: OrthoView, viewport: Sequence[float] = (1, 1)) -> None:
        # Before the base class, because setting a position on this platform
        # is how the view is told where to look, and the base sets one.
        self.view = view
        self.viewport = _size(viewport)
        super().__init__(position=tuple(view.eye()))

    def setViewport(self, x: float, y: float) -> None:
        self.viewport = _size((x, y))

    @property
    def position(self) -> np.ndarray:
        """Where the camera stands, back along the view's axis."""
        return np.append(self.view.eye(), 1.0)

    @position.setter
    def position(self, value: Any) -> None:
        """Move the view in its own plane to face a position handed to the platform."""
        view = self.view
        centre = np.asarray(view.centre, 'd')
        offset = np.asarray(value, 'd').ravel()[:3] - centre
        right, up = view.right, view.up
        moved = centre + right * float(offset @ right) + up * float(offset @ up)
        view.centre = tuple(float(v) for v in moved)

    def setPosition(self, position: Any) -> None:
        self.position = position

    def viewMatrix(self, trimDepth: Any = None, inverse: bool = False) -> np.ndarray:
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


#: A view drawn through a camera that turns, with distance making things
#: smaller.
PERSPECTIVE = 'perspective'

#: The same camera drawn flat, so two things of a size measure the same
#: wherever they stand.
ORTHOGRAPHIC = 'ortho'

#: Every kind a view can be pointed at: the six axes, and the two ways a
#: turning camera is drawn. What a view-name menu offers.
VIEW_KINDS: Tuple[str, ...] = tuple(DIRECTIONS) + (PERSPECTIVE, ORTHOGRAPHIC)


def view_kind(view: Any) -> Optional[str]:
    """Which of :data:`VIEW_KINDS` this view is looking through, or None."""
    camera = getattr(view.camera, 'view', None)
    if camera is None:
        return None
    direction = getattr(camera, 'direction', None)
    if direction is not None:
        return str(direction)
    if hasattr(camera, 'orbit'):
        return ORTHOGRAPHIC if getattr(camera, 'orthographic', False) else PERSPECTIVE
    # A plan view of an editor: the top view, told its centre as a map's.
    return 'top'


def shown_by(camera: Any) -> Tuple[Tuple[float, float, float], float]:
    """Where a camera is looking and how much it shows, whatever kind it is.

    ``(centre, span)`` in world units: the point in the middle of the view,
    and how much of the world fits down it. What a switch from one kind to
    another is seeded with, so the new camera shows the same subject at the
    same size.
    """
    if hasattr(camera, 'orbit'):
        target = camera.target()
        shown = 2.0 * camera.distance * math.tan(math.radians(camera.fov) / 2.0)
        return ((float(target[0]), float(target[1]), float(target[2])),
                float(shown))
    centre = tuple(float(value) for value in camera.centre)
    span = float(camera.span)
    if len(centre) == 2:              # a plan view's centre is a map's (x, z)
        return ((centre[0], 0.0, centre[1]), span)
    return ((centre[0], centre[1], centre[2]), span)


def point_view(view: Any, kind: str, **named: Any) -> bool:
    """Point ``view`` at ``kind``; False for a view with no camera to point.

    An axis name gives the view an orthographic camera looking along it;
    ``'perspective'`` and ``'ortho'`` give it one that turns, drawn with and
    without perspective. Where the camera it has is already of that family it
    is turned in place, so whatever else holds that camera goes on working;
    otherwise the view is given a new one, looking at what the old one looked
    at, showing as much as it showed.
    """
    if kind not in VIEW_KINDS:
        raise ValueError('%r is not one of %s' % (kind, ', '.join(VIEW_KINDS)))
    camera = getattr(view.camera, 'view', None)
    if camera is None:
        return False
    viewport = getattr(view.camera, 'viewport', (1, 1))
    centre, span = shown_by(camera)
    if kind in DIRECTIONS:
        if isinstance(camera, OrthoView):
            camera.direction = kind
            return True
        view.camera = OrthoViewPlatform(
            OrthoView(kind, centre=centre, span=span, **named), viewport)
        return True
    from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
    flat = kind == ORTHOGRAPHIC
    if isinstance(camera, OrbitView):
        camera.orthographic = flat
        return True
    orbit = OrbitView(centre=(centre[0], centre[2]), ground=centre[1],
                      orthographic=flat, **named)
    # As much of the world as the view was showing, so the switch keeps the
    # subject the size it was.
    orbit.distance = max(span / 2.0 / math.tan(math.radians(orbit.fov) / 2.0),
                         orbit.nearest)
    view.camera = OrbitViewPlatform(orbit, viewport)
    return True
