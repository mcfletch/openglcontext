"""Several arrangements of one set of views, shown by name.

A window that offers more than one way to look at a scene -- the plan alone,
the plan beside a perspective view, all four at once -- keeps one set of
cameras and changes which of them are on screen. :class:`ViewSet` holds the
views, the :class:`~OpenGLContext.multiview.views.ViewLayout` of each
arrangement, the pointer gestures and the framing::

    views = ViewSet([plan, front, left, angled], mode='quad')
    context.viewLayout = views.layout
    views.arrange(*context.getViewPort())
    views.frame(minimum, maximum)
    ...
    def ProcessEvent(self, event):
        if views.handle(event):
            self.triggerRedraw(1)
            return None
        return super().ProcessEvent(event)

``show(name)`` changes the arrangement; the cameras are shared, so what was
being looked at is what the new arrangement shows. ``driven`` names the views
whose cameras the pointer moves, for a window that drives one of them itself --
an editor whose plan view is where its tools draw keeps that one.

It holds no GL: the views, the rectangles they are drawn in, and which view an
event belongs to.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from OpenGLContext.multiview.gestures import ViewGestures
from OpenGLContext.multiview.views import View, ViewLayout

__all__ = ['ViewSet', 'fit_view']

#: How many views each named arrangement places.
ARRANGEMENT_FOR = {1: 'single', 2: 'split', 4: 'quad'}

#: A corner of a box: three numbers, however they are held.
Box = Union[Sequence[float], np.ndarray]


class ViewSet:
    """The views a window can show, and the arrangements of them.

    ``views`` are the views, in the order a quad places them: top left, top
    right, bottom left, bottom right. ``arrangements`` maps each name to the
    views it shows, by name or by view; with none given, every view is offered
    on its own under its own name, the first two together as ``'split'`` and
    all four as ``'quad'``. ``mode`` is the arrangement to open on, and
    ``driven`` the views the pointer moves the cameras of.
    """

    def __init__(self, views: Sequence[View],
                 arrangements: Optional[Mapping[str, Iterable[Any]]] = None,
                 mode: Optional[str] = None,
                 driven: Optional[Iterable[Any]] = None,
                 split_at: Tuple[float, float] = (0.5, 0.5)) -> None:
        self.views: List[View] = list(views)
        if not self.views:
            raise ValueError('a view set holds at least one view')
        chosen = (arrangements if arrangements is not None
                  else self._offered())
        self._layouts: Dict[str, ViewLayout] = {
            name: self._layout(name, shown, split_at)
            for name, shown in chosen.items()}
        #: Which arrangement is up.
        self.mode = mode if mode is not None else next(iter(self._layouts))
        if self.mode not in self._layouts:
            raise ValueError('there is no %r arrangement; the ones there are: %s'
                             % (self.mode, ', '.join(self._layouts)))
        #: The views the pointer moves the cameras of.
        self.driven = ([self.named(view) for view in driven]
                       if driven is not None else list(self.views))
        #: The window the views were last placed in, for measuring a view the
        #: arrangement is not showing.
        self.window = (1, 1)
        self.gestures = ViewGestures(self._layouts[self.mode])
        self.show(self.mode)

    def _offered(self) -> Dict[str, Tuple[View, ...]]:
        """Each view alone, the first two side by side, and four in a quad."""
        offered: Dict[str, Tuple[View, ...]] = {
            view.name or 'view %d' % index: (view,)
            for index, view in enumerate(self.views)}
        if len(self.views) >= 2:
            offered['split'] = (self.views[0], self.views[1])
        if len(self.views) >= 4:
            offered['quad'] = tuple(self.views[:4])
        return offered

    def named(self, view: Any) -> View:
        """The view ``name`` names, or the view itself; a usage error for neither.

        :meth:`view` answers None for a name this set has not got, which is
        what a caller asking whether it has one wants; this is for a caller
        that knows it has, and would rather say so than carry a None.
        """
        if isinstance(view, View):
            for mine in self.views:
                if view is mine:
                    return view
            raise ValueError('%r is not a view of this set' % (view,))
        for mine in self.views:
            if mine.name == view:
                return mine
        raise ValueError('this set has no view called %r; the ones it has are %s'
                         % (view, ', '.join(mine.name for mine in self.views)))

    def _layout(self, name: str, shown: Iterable[Any],
                split_at: Tuple[float, float]) -> ViewLayout:
        chosen = [self.named(view) for view in shown]
        arrangement = ARRANGEMENT_FOR.get(len(chosen))
        if arrangement is None:
            raise ValueError(
                'a named arrangement places one, two or four views; %r names %d'
                % (name, len(chosen)))
        return ViewLayout(chosen, arrangement, split_at)

    # -- the arrangements --------------------------------------------------
    @property
    def arrangements(self) -> Dict[str, ViewLayout]:
        """The arrangements on offer, by name, in the order they were given."""
        return dict(self._layouts)

    @property
    def layout(self) -> ViewLayout:
        """The layout the context should draw."""
        return self._layouts[self.mode]

    def show(self, name: str) -> ViewLayout:
        """Show the arrangement ``name``, and answer its layout."""
        if name not in self._layouts:
            raise ValueError('there is no %r arrangement; the ones there are: %s'
                             % (name, ', '.join(self._layouts)))
        self.mode = name
        layout = self._layouts[name]
        layout.arrange(*self.window)
        self.gestures.layout = layout
        self.gestures.views = [view for view in layout.views
                               if any(view is mine for mine in self.driven)]
        return layout

    def view(self, name: str) -> Optional[View]:
        """The view called ``name``, or None."""
        for view in self.views:
            if view.name == name:
                return view
        return None

    def showing(self, view: View) -> bool:
        """Whether this view is one the current arrangement draws."""
        return any(view is shown and shown.visible for shown in self.layout.views)

    def maximise(self, view: Optional[View] = None) -> None:
        """Give one view the whole window, or give the arrangement back."""
        self.layout.maximise(view)

    # -- placing them ------------------------------------------------------
    def arrange(self, width: int, height: int) -> List[View]:
        """Place the views in a window this size; the ones to draw, in order."""
        self.window = (int(width) or 1, int(height) or 1)
        return self.layout.arrange(*self.window)

    def size(self, view: View) -> Tuple[int, int]:
        """A view's own size, or the window's where the arrangement hides it.

        A view that is about to be shown is measured by the window, so framing
        a box in it before it is placed puts the box somewhere sensible rather
        than in a one-pixel square.
        """
        return view.size if view.visible else self.window

    def local(self, view: View, x: float, y: float) -> Tuple[float, float]:
        """Window pixel ``(x, y)`` in ``view``'s own pixels."""
        return view.local(x, y)

    # -- framing -----------------------------------------------------------
    def frame(self, minimum: Box, maximum: Box) -> None:
        """Fit the box from ``minimum`` to ``maximum`` into every view."""
        for view in self.views:
            fit_view(view, minimum, maximum, self.size(view))

    # -- the pointer -------------------------------------------------------
    def view_for(self, event: Any) -> Optional[View]:
        """The view an event belongs to: the context's answer, or the layout's.

        See :meth:`~OpenGLContext.multiview.views.ViewLayout.view_of`.
        """
        return self.layout.view_of(event)

    def handle(self, event: Any) -> bool:
        """Move a camera if the event asks one to; True where it was taken.

        An event in a view the application drives is never taken.
        """
        return self.gestures.handle(event)


def fit_view(view: View, minimum: Box, maximum: Box,
             size: Tuple[int, int]) -> bool:
    """Fit a box into one view; False for a view with no camera to fit it in.

    Each camera is framed as its kind is: an orthographic view and one that
    turns take the box, and a plan view takes the ground it stands on.
    """
    camera = getattr(view.camera, 'view', None)
    if camera is None:
        return False
    low = np.asarray(minimum[:3], 'd')
    high = np.asarray(maximum[:3], 'd')
    box = getattr(camera, 'frame_box', None)
    if box is not None:
        box(low, high, size)
    elif getattr(camera, 'direction', None) is not None:
        camera.frame(low, high, size)
    else:
        camera.frame((low[0], low[2]), (high[0], high[2]), size)
    return True
