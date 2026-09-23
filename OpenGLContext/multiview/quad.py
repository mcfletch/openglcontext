"""An editor's four views: three orthographic ones around a perspective one.

The top, front and side views show an object's plan and elevations at a
scale, and the perspective view shows how it looks. :class:`QuadView` builds
the :class:`~OpenGLContext.multiview.views.ViewLayout` of the four, frames a box in all
of them, and turns pointer gestures in any view into a move of that view's
camera:

- a drag in an orthographic view pans it, the world following the pointer;
- a drag with the left button in the perspective view orbits it about its
  target, and with any other button pans the target across the view;
- a wheel notch zooms the view under the pointer, an orthographic one about
  the pixel the pointer is on.

The gestures are :class:`~OpenGLContext.multiview.gestures.ViewGestures`, which
a window laying out views of its own uses directly.

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

from typing import Any, Dict, Optional, Sequence, Tuple, Union

import numpy as np

from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform, Point
from OpenGLContext.multiview.navigation import ROTATE_RATE, ZOOM_STEP
from OpenGLContext.multiview.views import View, ViewStyle
from OpenGLContext.multiview.viewset import ViewSet

__all__ = ['QuadView', 'ROTATE_RATE', 'ZOOM_STEP']

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
        #: The four views and their one arrangement.
        self.views = ViewSet(views, arrangements={'quad': views}, mode='quad')
        #: The layout to give the context.
        self.layout = self.views.layout
        #: What turns the pointer into a move of a view's camera.
        self.gestures = self.views.gestures

    def view(self, name: str) -> Optional[View]:
        """The view called ``name``: a direction, or ``'perspective'``."""
        return self.views.view(name)

    # -- framing -----------------------------------------------------------
    def frame(self, minimum: Point, maximum: Point) -> None:
        """Fit the box from ``minimum`` to ``maximum`` into every view.

        Each view is fitted to the size the layout last gave it, so frame after
        the layout has been arranged to see the box fill each view; before,
        each is fitted as a square.
        """
        low = np.asarray(minimum[:3], 'd')
        high = np.asarray(maximum[:3], 'd')
        radius = max(float(np.linalg.norm(high - low)) / 2.0, 1e-6)
        # Near enough to fill the view with a much smaller part of the box,
        # far enough to see a thousand of them.
        self.orbit.nearest = radius * 0.01
        self.orbit.furthest = radius * 1000.0
        self.views.frame(low, high)

    # -- gestures ----------------------------------------------------------
    def handle(self, event: Any) -> bool:
        """Apply a context's ``mousebutton`` or ``mousemove`` event; True where it was taken.

        An event not yet routed is routed through :attr:`layout`, and records
        its view as ``event.view``. A wheel notch arrives as a press and a
        release of :data:`~OpenGLContext.events.mouseevents.WHEEL_UP` or
        ``WHEEL_DOWN``; the press is the notch and the release is taken with
        it.
        """
        return self.gestures.handle(event)

    def press(self, view: Optional[View], x: float, y: float, button: int) -> bool:
        """A button went down at window pixel ``(x, y)``; True where a gesture began."""
        return self.gestures.press(view, x, y, button)

    def drag(self, view: Optional[View], x: float, y: float) -> bool:
        """The pointer moved to ``(x, y)``; True where it moved a camera.

        The gesture stays with the view it began in, wherever the pointer goes.
        """
        return self.gestures.drag(view, x, y)

    def release(self, view: Optional[View], x: float, y: float) -> bool:
        """The button came up; True where it ended a gesture."""
        return self.gestures.release(view, x, y)

    def wheel(self, view: Optional[View], x: float, y: float, notches: int) -> bool:
        """The wheel turned ``notches`` over ``(x, y)``, positive towards the scene."""
        return self.gestures.wheel(view, x, y, notches)
