"""Moving the camera of whichever view the pointer is in.

An editor window holds several views of one scene, and the pointer means
something different in each: a drag pans a plan or an elevation, and turns a
perspective view about what it is looking at. :class:`ViewGestures` reads a
context's pointer events, finds the view each belongs to, and moves that
view's camera:

- a drag in an orthographic or plan view pans it, the world following the
  pointer;
- a drag with the left button in a perspective view orbits it about its
  target, and with any other button carries the target across the view;
- a wheel notch zooms the view under the pointer, an orthographic one about
  the pixel the pointer is on.

It holds no GL. A context hands it each pointer event, and it takes the ones
that move a camera::

    gestures = ViewGestures(layout)
    ...
    def ProcessEvent(self, event):
        if gestures.handle(event):
            self.triggerRedraw(1)
            return None
        return super().ProcessEvent(event)

``views`` names the views it drives, for a window that moves one of them
itself -- an editor whose plan view is where the drawing tools work gives it
the other views and keeps that one. ``layout`` can be replaced, so a window
that rearranges its views hands over the new layout.

:class:`~OpenGLContext.edit.quadview.QuadView` is the four views of an editor
built on this.
"""
from __future__ import annotations

import math
from typing import Any, Optional, Sequence, Tuple

from OpenGLContext.edit.mapview import MapViewPlatform
from OpenGLContext.edit.orbitview import OrbitViewPlatform
from OpenGLContext.edit.orthoview import OrthoViewPlatform
from OpenGLContext.events.mouseevents import WHEEL_BUTTONS, WHEEL_UP
from OpenGLContext.views import View, ViewLayout

__all__ = ['ViewGestures', 'ORBIT_RATE', 'ZOOM_STEP']

#: Degrees a perspective view orbits for each pixel the pointer is dragged.
ORBIT_RATE = 0.4

#: What one wheel notch towards the scene multiplies a view's span or
#: distance by.
ZOOM_STEP = 0.8

#: The cameras that pan and zoom in their own plane: an orthographic view along
#: an axis, and the plan view an editor draws its map on.
PLANAR = (OrthoViewPlatform, MapViewPlatform)


class ViewGestures:
    """The pointer gestures that move a layout's cameras."""

    def __init__(self, layout: ViewLayout, views: Optional[Sequence[View]] = None,
                 orbit_rate: float = ORBIT_RATE,
                 zoom_step: float = ZOOM_STEP) -> None:
        #: The layout events are routed through.
        self.layout = layout
        #: The views it drives, or None for every view of the layout.
        self.views = views
        self.orbit_rate = float(orbit_rate)
        self.zoom_step = float(zoom_step)
        self._held: Optional[Tuple[View, int, float, float]] = None

    def drives(self, view: Optional[View]) -> bool:
        """Whether this view is one it moves the camera of."""
        if view is None or view.camera is None:
            return False
        mine = self.views if self.views is not None else self.layout.views
        return any(view is one for one in mine)

    # -- gestures ----------------------------------------------------------
    def handle(self, event: Any) -> bool:
        """Apply a context's ``mousebutton`` or ``mousemove`` event; True where it was taken.

        An event not yet routed is routed through :attr:`layout`, and records
        its view as ``event.view``. A wheel notch arrives as a press and a
        release of :data:`~OpenGLContext.events.mouseevents.WHEEL_UP` or
        ``WHEEL_DOWN``; the press is the notch and the release is taken with
        it.
        """
        kind = getattr(event, 'type', None)
        if kind not in ('mousebutton', 'mousemove'):
            return False
        if event.view is None:
            event.view = self.layout.route(event)
        x, y = event.getPickPoint()
        if kind == 'mousemove':
            return self.drag(event.view, x, y)
        if event.button in WHEEL_BUTTONS:
            if not event.state:
                return self.drives(event.view)
            notches = 1 if event.button == WHEEL_UP else -1
            return self.wheel(event.view, x, y, notches)
        if event.state:
            return self.press(event.view, x, y, event.button)
        return self.release(event.view, x, y)

    def press(self, view: Optional[View], x: float, y: float, button: int) -> bool:
        """A button went down at window pixel ``(x, y)``; True where a gesture began."""
        if not self.drives(view):
            return False
        assert view is not None
        self._held = (view, int(button), float(x), float(y))
        return True

    def drag(self, view: Optional[View], x: float, y: float) -> bool:
        """The pointer moved to ``(x, y)``; True where it moved a camera.

        The gesture stays with the view it began in, wherever the pointer goes.
        """
        if self._held is None:
            return False
        held, button, last_x, last_y = self._held
        dx, dy = float(x) - last_x, float(y) - last_y
        self._held = (held, button, float(x), float(y))
        camera = held.camera
        if isinstance(camera, PLANAR):
            camera.view.pan(dx, dy, _size(held))
        elif button == 0:
            camera.view.orbit(-dx * self.orbit_rate, -dy * self.orbit_rate)
        else:
            self._pan_orbit(camera.view, dx, dy, _size(held))
        return True

    def release(self, view: Optional[View], x: float, y: float) -> bool:
        """The button came up; True where it ended a gesture."""
        held = self._held is not None
        self._held = None
        return held

    def wheel(self, view: Optional[View], x: float, y: float, notches: int) -> bool:
        """The wheel turned ``notches`` over ``(x, y)``, positive towards the scene."""
        if not self.drives(view):
            return False
        assert view is not None
        factor = self.zoom_step ** int(notches)
        camera = view.camera
        if isinstance(camera, PLANAR):
            camera.view.zoom(factor, at=view.local(x, y), viewport=_size(view))
        else:
            camera.view.dolly(factor)
        return True

    # -- helpers -----------------------------------------------------------
    def _pan_orbit(self, camera: Any, dx: float, dy: float,
                   viewport: Tuple[int, int]) -> None:
        """Carry a perspective view's target with the pointer, at the target's depth."""
        model, _projection = camera.matrices(viewport)
        right, up = model[:3, 0], model[:3, 1]
        scale = (2.0 * camera.distance * math.tan(math.radians(camera.fov) / 2.0)
                 / viewport[1])
        target = camera.target() - (right * dx + up * dy) * scale
        camera.look_at((float(target[0]), float(target[2])), float(target[1]))


def _size(view: View) -> Tuple[int, int]:
    """A view's size, or a square where the layout has not placed it yet."""
    width, height = view.size
    if width <= 0 or height <= 0:
        return (1, 1)
    return (int(width), int(height))
