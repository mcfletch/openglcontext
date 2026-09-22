"""An editor's four views: three orthographic ones around a perspective one.

The top, front and side views show an object's plan and elevations at a
scale, and the perspective view shows how it looks. :class:`QuadView` builds
the :class:`~OpenGLContext.views.ViewLayout` of the four, frames a box in all
of them, and turns pointer gestures in any view into a move of that view's
camera:

- a drag in an orthographic view pans it, the world following the pointer;
- a drag with the left button in the perspective view orbits it about its
  target, and with any other button pans the target across the view;
- a wheel notch zooms the view under the pointer, an orthographic one about
  the pixel the pointer is on.

It holds no GL. A context hands it each pointer event, and it takes the
ones that move a camera::

    quad = QuadView()
    context.viewLayout = quad.layout
    quad.frame(minimum, maximum)
    ...
    def ProcessEvent(self, event):
        if quad.handle(event):
            self.triggerRedraw(1)
            return None
        return super().ProcessEvent(event)

:meth:`QuadView.press`, :meth:`~QuadView.drag`, :meth:`~QuadView.release`
and :meth:`~QuadView.wheel` are the same gestures for an application that
reads its pointer some other way.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, Tuple, Union

import numpy as np

from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.edit.orthoview import OrthoView, OrthoViewPlatform, Point
from OpenGLContext.events.mouseevents import WHEEL_BUTTONS, WHEEL_UP
from OpenGLContext.views import View, ViewLayout, ViewStyle

__all__ = ['QuadView', 'ORBIT_RATE', 'ZOOM_STEP']

#: Degrees a perspective view orbits for each pixel the pointer is dragged.
ORBIT_RATE = 0.4

#: What one wheel notch towards the scene multiplies a view's span or
#: distance by.
ZOOM_STEP = 0.8

Colour = Union[Tuple[float, float, float], Tuple[float, float, float, float]]


class QuadView:
    """The four views of an editor window and the gestures that move them.

    ``directions`` names the three orthographic views, placed top left, top
    right and bottom left; the perspective view is bottom right. The default
    is the plan, the front elevation and the view from the left. The
    orthographic views clear to ``background``; the perspective view draws the
    scene's own ``Background``.
    """

    def __init__(self, directions: Sequence[str] = ('top', 'front', 'left'),
                 background: Colour = (0.32, 0.33, 0.35)) -> None:
        if len(directions) != 3:
            raise ValueError('a quad view has three orthographic views, not %d'
                             % len(directions))
        #: The orthographic views' cameras, by direction.
        self.orthographic: Dict[str, OrthoView] = {
            direction: OrthoView(direction) for direction in directions}
        #: The perspective view's camera.
        self.orbit = OrbitView()
        flat = ViewStyle(background=background)
        views = [View(OrthoViewPlatform(camera), name=direction, style=flat)
                 for direction, camera in self.orthographic.items()]
        views.append(View(OrbitViewPlatform(self.orbit), name='perspective',
                          style=ViewStyle(background=True)))
        #: The layout to give the context.
        self.layout = ViewLayout.quad(views[0], views[1], views[2], views[3])
        self._held: Optional[Tuple[View, int, float, float]] = None

    def view(self, name: str) -> Optional[View]:
        """The view called ``name``: a direction, or ``'perspective'``."""
        for view in self.layout.views:
            if view.name == name:
                return view
        return None

    # -- framing -----------------------------------------------------------
    def frame(self, minimum: Point, maximum: Point) -> None:
        """Fit the box from ``minimum`` to ``maximum`` into every view.

        Each view is fitted to the size the layout last gave it, so frame after
        the layout has been arranged to see the box fill each view; before,
        each is fitted as a square.
        """
        low = np.asarray(minimum[:3], 'd')
        high = np.asarray(maximum[:3], 'd')
        for view in self.layout.views:
            size = _size(view)
            if isinstance(view.camera, OrthoViewPlatform):
                view.camera.view.frame(low, high, size)
        radius = max(float(np.linalg.norm(high - low)) / 2.0, 1e-6)
        # Near enough to fill the view with a much smaller part of the box,
        # far enough to see a thousand of them.
        self.orbit.nearest = radius * 0.01
        self.orbit.furthest = radius * 1000.0
        perspective = self.view('perspective')
        assert perspective is not None
        self.orbit.frame_box(low, high, _size(perspective))

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
                return self._owns(event.view)
            notches = 1 if event.button == WHEEL_UP else -1
            return self.wheel(event.view, x, y, notches)
        if event.state:
            return self.press(event.view, x, y, event.button)
        return self.release(event.view, x, y)

    def press(self, view: Optional[View], x: float, y: float, button: int) -> bool:
        """A button went down at window pixel ``(x, y)``; True where a gesture began."""
        if not self._owns(view):
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
        if isinstance(camera, OrthoViewPlatform):
            camera.view.pan(dx, dy, _size(held))
        elif button == 0:
            self.orbit.orbit(-dx * ORBIT_RATE, -dy * ORBIT_RATE)
        else:
            self._pan_orbit(dx, dy, _size(held))
        return True

    def release(self, view: Optional[View], x: float, y: float) -> bool:
        """The button came up; True where it ended a gesture."""
        held = self._held is not None
        self._held = None
        return held

    def wheel(self, view: Optional[View], x: float, y: float, notches: int) -> bool:
        """The wheel turned ``notches`` over ``(x, y)``, positive towards the scene."""
        if not self._owns(view):
            return False
        assert view is not None
        factor = ZOOM_STEP ** int(notches)
        if isinstance(view.camera, OrthoViewPlatform):
            view.camera.view.zoom(factor, at=view.local(x, y), viewport=_size(view))
        else:
            self.orbit.dolly(factor)
        return True

    # -- helpers -----------------------------------------------------------
    def _owns(self, view: Optional[View]) -> bool:
        return view is not None and any(view is mine for mine in self.layout.views)

    def _pan_orbit(self, dx: float, dy: float, viewport: Tuple[int, int]) -> None:
        """Carry the perspective view's target with the pointer, at the target's depth."""
        model, _projection = self.orbit.matrices(viewport)
        right, up = model[:3, 0], model[:3, 1]
        scale = (2.0 * self.orbit.distance * math.tan(math.radians(self.orbit.fov) / 2.0)
                 / viewport[1])
        target = self.orbit.target() - (right * dx + up * dy) * scale
        self.orbit.look_at((float(target[0]), float(target[2])), float(target[1]))


def _size(view: View) -> Tuple[int, int]:
    """A view's size, or a square where the layout has not placed it yet."""
    width, height = view.size
    if width <= 0 or height <= 0:
        return (1, 1)
    return (int(width), int(height))
