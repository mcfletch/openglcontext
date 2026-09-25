"""Reading the pointer, and moving the camera of the view it is in.

An editor window holds several views of one scene, and the pointer means
something different in each: a right drag pans a plan or an elevation, and
turns a perspective view about what it is looking at. :class:`ViewGestures` finds the
view each event belongs to and asks that view's
:class:`~OpenGLContext.multiview.navigation.ViewNavigation` what the button
raises there -- so which button pans, which turns and which zooms is the
view's own business, and rebinding one changes what the pointer does in that
view alone.

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

:class:`~OpenGLContext.multiview.quad.QuadView` is the four views of an editor
built on this, and :class:`~OpenGLContext.multiview.viewset.ViewSet` is any
arrangement of them.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from OpenGLContext.events.mouseevents import WHEEL_BUTTONS, button_name
from OpenGLContext.multiview.navigation import (
    ZOOM_IN,
    ZOOM_OUT,
    ViewNavigation,
    navigation_for,
)
from OpenGLContext.multiview.views import View, ViewLayout

__all__ = ['ViewGestures']

#: The modifiers an event carries when none is held.
NO_MODIFIERS = (0, 0, 0)


class ViewGestures:
    """The pointer gestures that move a layout's cameras."""

    def __init__(self, layout: ViewLayout,
                 views: Optional[Sequence[View]] = None) -> None:
        #: The layout events are routed through.
        self.layout = layout
        #: The views it drives, or None for every view of the layout.
        self.views = views
        self._held: Optional[View] = None

    def drives(self, view: Optional[View]) -> bool:
        """Whether this view is one it moves the camera of."""
        if view is None or view.camera is None:
            return False
        mine = self.views if self.views is not None else self.layout.views
        return any(view is one for one in mine)

    def navigation(self, view: Optional[View]) -> Optional[ViewNavigation]:
        """The navigation of a view it drives: what the pointer does there."""
        if not self.drives(view):
            return None
        assert view is not None
        return navigation_for(view)

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
        view = self.layout.view_of(event)
        x, y = event.getPickPoint()
        if kind == 'mousemove':
            return self.drag(view, x, y)
        modifiers = tuple(event.getModifiers())
        if event.button in WHEEL_BUTTONS and not event.state:
            # The release of a notch, which the press already answered.
            return self.navigation(view) is not None
        if event.state:
            return self.press(view, x, y, event.button, modifiers)
        return self.release(view, x, y)

    def press(self, view: Optional[View], x: float, y: float, button: int,
              modifiers: Sequence[int] = NO_MODIFIERS) -> bool:
        """A button went down at window pixel ``(x, y)``; True where it raised a gesture.

        What the button does is the view's own: its navigation says which
        command this button and these modifiers raise, and a button nothing is
        bound to is left for whatever else wants it.
        """
        navigation = self.navigation(view)
        if navigation is None:
            return False
        assert view is not None
        command = navigation.command_for(button_name(int(button)), modifiers)
        if command in (ZOOM_IN, ZOOM_OUT):
            return navigation.zoom(1 if command == ZOOM_IN else -1, x, y)
        if command is None or not navigation.begin(command, x, y):
            return False
        self._held = view
        return True

    def drag(self, view: Optional[View], x: float, y: float) -> bool:
        """The pointer moved to ``(x, y)``; True where it moved a camera.

        The gesture stays with the view it began in, wherever the pointer goes.
        """
        if self._held is None:
            return False
        navigation = navigation_for(self._held)
        return navigation is not None and navigation.drag(x, y)

    def release(self, view: Optional[View], x: float, y: float) -> bool:
        """The button came up; True where it ended a gesture."""
        held, self._held = self._held, None
        if held is None:
            return False
        navigation = navigation_for(held)
        return navigation is not None and navigation.release()

    def wheel(self, view: Optional[View], x: float, y: float, notches: int) -> bool:
        """The wheel turned ``notches`` over ``(x, y)``, positive towards the scene."""
        navigation = self.navigation(view)
        if navigation is None:
            return False
        return navigation.zoom(int(notches), x, y)
