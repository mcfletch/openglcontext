"""Four views of the scene in any window that wants them.

A window that shows a scene can show it four ways at once -- the plan, two
elevations and the view it already had -- without knowing anything about
layouts. :class:`MultiViewMixin` gives it that: the arrangements, the
furniture in each view, and a key that switches between one view and four::

    class Viewer(OverlayMixin, MultiViewMixin, BaseContext):
        def OnInit(self):
            self.startViews(bounds=(scene.minimum, scene.maximum))

The perspective view draws through whatever ``getViewPlatform()`` answers, so
the navigation, a bound ``Viewpoint`` and any camera the application swaps in
drive it as they drive a window of one view. The three orthographic views are
the mixin's, and are framed on the bounds it is given.

It goes *after* ``OverlayMixin`` in the bases, so the overlay is offered each
event first -- the furniture has to have the click meant for a button standing
in front of a view -- and what the furniture leaves reaches the views.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Optional

from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
from OpenGLContext.multiview.quad import ELEVATIONS, FLAT_BACKGROUND
from OpenGLContext.multiview.viewpoints import SceneCamera, scene_cameras
from OpenGLContext.multiview.views import View, ViewLayout, ViewStyle
from OpenGLContext.multiview.viewset import ViewSet

__all__ = ['MultiViewMixin', 'ARRANGEMENTS']

#: The arrangements the mixin offers, in the order its key takes them: the
#: window's own view alone, and the four.
ARRANGEMENTS = ('single', 'quad')


if TYPE_CHECKING:
    class _Host:
        """What this mix-in needs of the context beside it.

        Declared for a checker and aliased to ``object`` at run time, as the
        overlay's own host protocol is: the mix-in is put over a real context
        and reaches these through the MRO rather than owning them.
        """

        def getViewPort(self) -> tuple[int, int]: ...
        def getViewLayout(self) -> Any: ...
        def triggerRedraw(self, force: int = 0) -> Any: ...
        def hasMouseMoveHandlers(self) -> bool: ...
        def ProcessEvent(self, event: Any) -> Any: ...
        def ViewPort(self, width: int, height: int) -> None: ...
else:
    _Host = object


class MultiViewMixin(_Host):
    """One view or four, over whatever camera the window already had."""

    #: Which arrangement a window opens in.
    multiViewArrangement: str = 'single'

    #: The views, once :meth:`startViews` has made them.
    views: Optional[ViewSet] = None
    #: The furniture drawn in them, where this window has an overlay stack.
    viewChrome: Any = None

    _viewBounds: Optional[Callable[[], Optional[tuple[Any, Any]]]] = None

    # -- building ----------------------------------------------------------
    def startViews(self, bounds: Optional[Any] = None,
                   arrangement: Optional[str] = None,
                   elevations: Sequence[str] = ELEVATIONS,
                   chrome: bool = True) -> ViewSet:
        """Make the views and put the furniture up; the set.

        ``bounds`` is what there is to see, as ``(minimum, maximum)`` or a
        callable answering that, which frames the orthographic views and is
        what a view's *zoom to fit* fits. With none given the window's own
        :meth:`~OpenGLContext.context.Context.sceneBounds` is asked, so a
        window that has a scenegraph needs to say nothing at all.
        ``arrangement`` is what to open in, ``'single'`` unless the class says
        otherwise.
        """
        flat = ViewStyle(background=FLAT_BACKGROUND, grid=True)
        views = [View(OrthoViewPlatform(OrthoView(direction)), name=direction,
                      style=flat)
                 for direction in elevations]
        # The window's own camera: a view with none draws through whatever
        # `getViewPlatform` answers, which is what leaves the navigation, the
        # bound Viewpoint and any camera the application swaps in driving it.
        views.append(View(name='perspective', style=ViewStyle(background=True)))
        self.views = ViewSet(
            views,
            arrangements={'single': ('perspective',),
                          'quad': tuple(view.name for view in views)},
            mode=str(arrangement or self.multiViewArrangement),
            driven=tuple(elevations))
        self._viewBounds = (bounds if callable(bounds)
                            else (lambda bounds=bounds: bounds)
                            if bounds is not None else self.boundsOfScene)
        self.views.arrange(*self.getViewPort())
        self.frameViews()
        if chrome:
            self._startViewChrome()
        return self.views

    def _startViewChrome(self) -> None:
        """Put the views' furniture on the overlay stack, where there is one."""
        stack = getattr(self, 'overlays', None)
        if stack is None or self.views is None:
            return
        from OpenGLContext.ui.viewchrome import ViewChrome
        self.viewChrome = ViewChrome(
            layout=self.views.layout, stack=stack,
            on_arrange=self.viewsArranged, bounds=self._viewBounds,
            cameras=self.sceneCameras)
        stack.push(self.viewChrome)

    # -- what the window draws ---------------------------------------------
    def getViewLayout(self) -> Any:
        """The layout this frame draws: the views', or the window's own."""
        if self.views is not None:
            return self.views.layout
        return super().getViewLayout()

    def viewsArranged(self) -> None:
        """Place the views again: something changed what is on screen."""
        if self.views is None:
            return
        self.views.arrange(*self.getViewPort())
        stack = getattr(self, 'overlays', None)
        if stack is not None:
            stack.invalidate()
        self.triggerRedraw(1)

    def sceneCameras(self) -> list[SceneCamera]:
        """The cameras the window's scene carries, as each view's menu offers them.

        Choosing one in the window's own view binds its ``Viewpoint``; in an
        elevation it gives that view a perspective camera standing there.
        """
        graph = getattr(self, 'getSceneGraph', None)
        return scene_cameras(graph() if graph is not None else None)

    def boundsOfScene(self) -> Optional[tuple[Any, Any]]:
        """The box round what the window is showing, or None where it shows nothing.

        From the context's own ``sceneBounds``, which answers a centre and a
        radius: the box round that sphere is what the views are fitted to,
        which is the same thing the single-view framing already works in.
        """
        found = getattr(self, 'sceneBounds', None)
        around = found() if found is not None else None
        if not around:
            return None
        centre, radius = around
        radius = float(radius) or 1.0
        return (tuple(float(value) - radius for value in centre[:3]),
                tuple(float(value) + radius for value in centre[:3]))

    def frameViews(self) -> bool:
        """Fit what there is to see into every view; False with nothing to fit."""
        if self.views is None or self._viewBounds is None:
            return False
        found = self._viewBounds()
        if not found:
            return False
        minimum, maximum = found
        self.views.frame(minimum, maximum)
        return True

    # -- switching ---------------------------------------------------------
    def showViews(self, name: str) -> None:
        """Show the arrangement ``name`` -- ``'single'`` or ``'quad'``."""
        if self.views is None:
            return
        self.views.show(name)
        if self.viewChrome is not None:
            self.viewChrome.layout_of = self.views.layout
        self.viewsArranged()

    def toggleViews(self, event: Any = None) -> None:
        """Take the arrangements in turn, so one key reaches them all."""
        if self.views is None:
            return
        index = ARRANGEMENTS.index(self.views.mode) if \
            self.views.mode in ARRANGEMENTS else -1
        self.showViews(ARRANGEMENTS[(index + 1) % len(ARRANGEMENTS)])

    def maximiseView(self, event: Any = None) -> None:
        """Give the view under the last click the window, or give it back."""
        if self.views is None:
            return
        self.views.maximise()
        self.viewsArranged()

    # -- the pointer -------------------------------------------------------
    def ProcessEvent(self, event: Any) -> Any:
        """Offer the pointer to the views before the window's own navigation.

        The furniture has already had it, since this sits under the overlay in
        the bases; a drag the views take never reaches the navigation, so
        panning an elevation does not also walk the camera.
        """
        if self.views is not None and self.views.handle(event):
            self.triggerRedraw(1)
            return None
        return super().ProcessEvent(event)

    def hasMouseMoveHandlers(self) -> bool:
        """True while a view is being dragged, which the handler registry does not see."""
        if self.views is not None and self.views.gestures.dragging:
            return True
        return bool(super().hasMouseMoveHandlers())

    def clearHeldKeys(self) -> None:
        """Let go of what is held as the window loses focus: a view's drag, and the keys."""
        if self.views is not None:
            self.views.release_all()
        clear = getattr(super(), 'clearHeldKeys', None)
        if clear is not None:
            clear()

    def ViewPort(self, width: int, height: int) -> None:
        """The window changed size: each view is told the size of its tile."""
        super().ViewPort(width, height)
        if self.views is not None:
            self.views.arrange(int(width), int(height) or 1)
