"""An editor's four views: three orthographic ones around a perspective one.

The top, front and side views show an object's plan and elevations at a
scale, and the perspective view shows how it looks. :class:`QuadView` builds
the :class:`~OpenGLContext.multiview.views.ViewLayout` of the four, frames a box in all
of them, and turns pointer gestures in any view into a move of that view's
camera:

- a drag with the right or middle button in an orthographic view pans it, the
  world following the pointer;
- a drag with the right button in the perspective view orbits it about its
  target, and with the middle button pans the target across the view;
- the left button is left unbound, for whatever the window uses the primary
  click for;
- a wheel notch zooms the view under the pointer, an orthographic one about
  the pixel the pointer is on.

The perspective view opens thirty degrees round from the front, above the
model, so it shows a side the three elevations do not. A scene that carries
cameras -- VRML97 ``Viewpoint`` nodes, or a glTF file's cameras -- is opened
through the first of them instead; :meth:`QuadView.cameras_found` is told
them, and ``choose_camera`` picks another or none::

    quad = QuadView(choose_camera=lambda cameras: cameras[-1])
    ...
    def OnViewpointsChanged(self, paths):
        quad.cameras_found(scene_cameras(self.sg))

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

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform, Point
from OpenGLContext.multiview.viewpoints import (
    CameraChooser, SceneCamera, first_camera, look_through,
)
from OpenGLContext.multiview.views import View, ViewStyle
from OpenGLContext.multiview.viewset import ViewSet

__all__ = ['QuadView', 'ELEVATIONS', 'FLAT_BACKGROUND', 'OPENING_HEADING']

#: Which way the three orthographic views look, placed top left, top right and
#: bottom left; the perspective view is bottom right.
ELEVATIONS = ('top', 'front', 'left')

#: What an orthographic view clears to, in place of the scene's sky.
FLAT_BACKGROUND = (0.32, 0.33, 0.35)

#: The heading the perspective view opens on, in degrees: thirty round from
#: the front towards the right, so it shows the side the left elevation does
#: not.
OPENING_HEADING = 330.0

Colour = Union[Tuple[float, float, float], Tuple[float, float, float, float]]


class QuadView:
    """The four views of an editor window and the gestures that move them.

    ``directions`` names the three orthographic views, placed top left, top
    right and bottom left; the perspective view is bottom right. The default
    is the plan, the front elevation and the view from the left. The
    orthographic views clear to ``background``; the perspective view draws the
    scene's own ``Background``.

    ``choose_camera`` picks which of the scene's cameras the perspective view
    opens on, given them in the order the scene declares them; it answers
    None to keep the view it opened on. The first, unless given.
    """

    def __init__(self, directions: Sequence[str] = ELEVATIONS,
                 background: Colour = FLAT_BACKGROUND,
                 choose_camera: CameraChooser = first_camera) -> None:
        if len(directions) != 3:
            raise ValueError('a quad view has three orthographic views, not %d'
                             % len(directions))
        #: The orthographic views' cameras, by direction.
        self.orthographic: Dict[str, OrthoView] = {
            direction: OrthoView(direction) for direction in directions}
        #: The perspective view's camera. It may go below the model as well as
        #: above it: an object, unlike the land, has an underside to look at.
        self.orbit = OrbitView(heading=OPENING_HEADING,
                               lowest=-OrbitView.HIGHEST)
        #: Which of the scene's cameras to open on.
        self.choose_camera = choose_camera
        #: The scene's cameras, as :meth:`cameras_found` was last told them.
        self.cameras: List[SceneCamera] = []
        #: The box last framed, which is how far ahead a camera looked
        #: through is orbited about.
        self._framed: Optional[Tuple[np.ndarray, np.ndarray]] = None
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
        self.orbit.fit_limits(float(np.linalg.norm(high - low)) / 2.0)
        self._framed = (low, high)
        self.views.frame(low, high)

    # -- the scene's cameras -----------------------------------------------
    def cameras_found(self, cameras: Sequence[SceneCamera]) -> Optional[SceneCamera]:
        """The scene's cameras are these; the one the perspective view now looks through.

        The first time a scene has any, the perspective view is pointed
        through the one ``choose_camera`` picks. After that the list is only
        kept, for a menu to offer, and the view stays where it has been
        moved to. None where nothing was looked through.
        """
        opening = not self.cameras
        self.cameras = list(cameras)
        if not (opening and self.cameras):
            return None
        chosen = self.choose_camera(self.cameras)
        if chosen is None or not self.look_through(chosen):
            return None
        return chosen

    def look_through(self, camera: SceneCamera) -> bool:
        """Point the perspective view through ``camera``.

        It orbits the point ahead of the camera nearest the middle of the box
        last framed, so an orbit afterwards turns about the model.
        """
        view = self.view('perspective')
        if view is None:
            return False
        return look_through(view, camera, distance=self._ahead(camera))

    def _ahead(self, camera: SceneCamera) -> Optional[float]:
        """How far ahead of ``camera`` the middle of the framed box is, or None."""
        if self._framed is None:
            return None
        low, high = self._framed
        middle = (low + high) / 2.0
        along = float((middle - np.asarray(camera.position, 'd'))
                      @ np.asarray(camera.forward, 'd'))
        radius = float(np.linalg.norm(high - low)) / 2.0
        return max(along, radius * 0.1, 1e-6)

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
