"""The views a context shows, built from its definition's ``navigation.views``.

:class:`MultiViewMixin` is one of :class:`~OpenGLContext.context.Context`'s
bases.  A context whose navigation declares a
:class:`~OpenGLContext.move.navigationdefinition.Views` gets a
:class:`~OpenGLContext.multiview.viewset.ViewSet` built from it as the context
completes: the views, their arrangements, the keys that switch them and the
furniture in each view, as the declaration's ``switching`` asks::

    class Editor(Context):
        contextDefinition = ContextDefinition(navigation=Navigation(
            modes=['examine'],
            views=Views(
                views=[ViewDefinition(name='top', camera='top', gestures=['plan']),
                       ViewDefinition(name='perspective')],
                switching=['keys', 'controls'])))

With ``views`` NULL, which is the default, it builds nothing and a frame draws
the window's one view.  :meth:`MultiViewMixin.startViews` makes the plan, two
elevations and the window's own view at run time, and writes that declaration
into the definition.

A perspective view with no gestures draws through whatever
``getViewPlatform()`` answers, so the movement modes, a bound ``Viewpoint``
and any camera the application swaps in drive it as they drive a window of
one view.  The other views have cameras of their own (:func:`viewSetFor`).

The overlay stack sits ahead of this mix-in in ``Context``'s bases, so it is
offered each event first -- the furniture has to have the click meant for a
button standing in front of a view -- and what the furniture leaves reaches
the views.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Optional

from OpenGLContext.move.navigationdefinition import (
    ORTHOGRAPHIC, Arrangement, Navigation, ViewDefinition, Views, viewGestures)
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
from OpenGLContext.multiview.navigation import ViewNavigationMode, navigation_for
from OpenGLContext.multiview.quad import ELEVATIONS, FLAT_BACKGROUND
from OpenGLContext.multiview.viewpoints import (
    SceneCamera, first_camera, look_through, scene_cameras)
from OpenGLContext.multiview.views import View, ViewLayout, ViewStyle
from OpenGLContext.multiview.viewset import ViewSet

__all__ = ['MultiViewMixin', 'ARRANGEMENTS', 'quadViews', 'viewSetFor']

#: The arrangements :meth:`MultiViewMixin.startViews` declares: the window's
#: own view alone, and the four.
ARRANGEMENTS = ('single', 'quad')


def quadViews(elevations: Sequence[str] = ELEVATIONS, arrangement: str = 'single',
              switching: Sequence[str] = ()) -> Views:
    """The plan, two elevations and the window's own view, declared.

    ``elevations`` names the orthographic views, each looking along the axis
    of the same name, and a ``perspective`` view draws through the window's
    own camera.  They are arranged as :data:`ARRANGEMENTS`: ``single`` (the
    perspective view alone) and ``quad``.
    """
    shown = [str(direction) for direction in elevations]
    return Views(
        views=[ViewDefinition(name=direction, camera=direction) for direction in shown]
        + [ViewDefinition(name='perspective')],
        arrangements=[Arrangement(name='single', views=['perspective']),
                      Arrangement(name='quad', views=[*shown, 'perspective'])],
        arrangement=arrangement,
        switching=list(switching))


def _gestures(names: Sequence[str]) -> Optional[ViewNavigationMode]:
    """The registered gesture sets ``names`` names, as one; None for none.

    Combined in the order named, so where two sets bind one button the first
    set's gesture is the one the button raises.
    """
    if not names:
        return None
    sets: list[ViewNavigationMode] = [viewGestures(str(name)) for name in names]
    if len(sets) == 1:
        return sets[0]
    return ViewNavigationMode(
        name='+'.join(str(chosen.name) for chosen in sets),
        label=' + '.join(str(chosen.label) for chosen in sets),
        bindings=[binding for chosen in sets for binding in chosen.bindings])


def _viewFor(declared: ViewDefinition) -> View:
    """One declared view, with the camera and the gestures it names.

    An orthographic view looks along its axis.  A ``scene`` view, and a
    perspective one given gestures of its own, get a camera that orbits, since
    the gestures move a camera and the window's own belongs to the movement
    modes.  A perspective view without gestures has no camera, and draws
    through the window's.
    """
    from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform

    style = (ViewStyle(background=FLAT_BACKGROUND, grid=True) if declared.flat()
             else ViewStyle(background=True))
    camera: Any = None
    if declared.camera in ORTHOGRAPHIC:
        camera = OrthoViewPlatform(OrthoView(str(declared.camera)))
    elif declared.camera == 'scene' or declared.gestures:
        camera = OrbitViewPlatform(OrbitView(nearest=1e-6, lowest=-OrbitView.HIGHEST))
    view = View(camera, name=str(declared.name), style=style)
    mode = _gestures(declared.gestures)
    if camera is not None and mode is not None:
        navigation_for(view, mode)
    return view


def viewSetFor(declaration: Views) -> ViewSet:
    """The :class:`ViewSet` a :class:`Views` declaration describes.

    The views in the order declared, the declared arrangements (or those
    :meth:`Views.arrangementViews` offers where none are), opening on
    ``arrangement`` or the first.  The pointer moves every view with a camera
    of its own; the window's own view is moved by the movement modes.
    """
    views = [_viewFor(declared) for declared in declaration.views]
    return ViewSet(
        views,
        arrangements=declaration.arrangementViews(),
        mode=str(declaration.arrangement) or None,
        driven=[view for view in views if view.camera is not None])


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
        def completeInit(self) -> bool: ...
        def setupDefaultEventCallbacks(self) -> None: ...
        def addEventHandler(self, eventType: Any, *arguments: Any,
                            **named: Any) -> Any: ...
else:
    _Host = object


class MultiViewMixin(_Host):
    """The views the definition declares, over whatever camera the window had."""

    #: Which arrangement :meth:`startViews` opens in.
    multiViewArrangement: str = 'single'
    #: The key that steps to the next arrangement, where the views' ``switching``
    #: holds ``keys``; '' binds none.
    viewsCycleKey: str = 'v'
    #: The key that gives the view under the last click the whole window, and
    #: gives it back, where ``switching`` holds ``keys``; '' binds none.
    viewMaximiseKey: str = 'x'

    #: The views, once they are built.
    views: Optional[ViewSet] = None
    #: The furniture drawn in them, where the views offer controls.
    viewChrome: Any = None

    _viewBounds: Optional[Callable[[], Optional[tuple[Any, Any]]]] = None
    #: The views that look through the scene's first camera.
    _sceneViews: tuple[str, ...] = ()

    # -- the declaration ---------------------------------------------------
    def declaredViews(self) -> Optional[Views]:
        """The definition's :class:`Views`, or None where it declares none."""
        definition = getattr(self, 'contextDefinition', None)
        navigation = definition.navigation if definition is not None else None
        return (navigation.views or None) if navigation else None

    def setupDefaultEventCallbacks(self) -> None:
        """Bind the arrangement and maximise keys, where the views offer them."""
        super().setupDefaultEventCallbacks()
        declared = self.declaredViews()
        if declared is None:
            return
        if 'keys' in declared.switching:
            for key, function in ((self.viewsCycleKey, self.toggleViews),
                                  (self.viewMaximiseKey, self.maximiseView)):
                if key:
                    self.addEventHandler('keyboard', name=key, state=0,
                                         function=function)

    def completeInit(self) -> bool:
        """Complete the context, then build the views it declares."""
        completed = bool(super().completeInit())
        declared = self.declaredViews()
        if completed and declared is not None and self.views is None:
            self.buildViews(declared)
        return completed

    # -- building ----------------------------------------------------------
    def buildViews(self, declaration: Views, bounds: Optional[Any] = None) -> ViewSet:
        """Build the views ``declaration`` describes, place and frame them; the set.

        ``bounds`` is what there is to see, as ``(minimum, maximum)`` or a
        callable answering that, which frames the views with cameras of their
        own and is what a view's *zoom to fit* fits.  With none given the
        window's own :meth:`~OpenGLContext.context.Context.sceneBounds` is
        asked.  The furniture goes up where ``switching`` holds ``controls``.
        """
        self.views = viewSetFor(declaration)
        self._sceneViews = tuple(str(declared.name) for declared in declaration.views
                                 if declared.camera == 'scene')
        self._viewBounds = (bounds if callable(bounds)
                            else (lambda bounds=bounds: bounds)
                            if bounds is not None else self.boundsOfScene)
        self.views.arrange(*self.getViewPort())
        self.frameViews()
        if 'controls' in declaration.switching:
            self._startViewChrome()
        return self.views

    def startViews(self, bounds: Optional[Any] = None,
                   arrangement: Optional[str] = None,
                   elevations: Sequence[str] = ELEVATIONS,
                   chrome: bool = True) -> ViewSet:
        """Show the plan, two elevations and the window's own view; the set.

        For a context that turns several views on at run time.  Writes
        :func:`quadViews` into the definition's ``navigation.views`` and
        builds it (:meth:`buildViews`).  ``arrangement`` is what to open in,
        :attr:`multiViewArrangement` unless given; ``chrome`` puts the
        furniture up, where the context has an overlay stack.
        """
        declaration = quadViews(
            elevations, str(arrangement or self.multiViewArrangement),
            ['controls'] if chrome else [])
        definition = getattr(self, 'contextDefinition', None)
        if definition is not None:
            if definition.navigation:
                definition.navigation.views = declaration
            else:
                definition.navigation = Navigation(views=declaration)
        return self.buildViews(declaration, bounds)

    def _startViewChrome(self) -> None:
        """Put the views' furniture on the overlay stack, where there is one."""
        stack = getattr(self, 'overlays', None)
        if stack is None or self.views is None:
            return
        from OpenGLContext.ui.viewchrome import ViewChrome
        self.viewChrome = ViewChrome(
            layout=self.views.layout, stack=stack,
            on_arrange=self.viewsArranged, bounds=self._viewBounds,
            cameras=self.sceneCameras,
            menu_items=self.viewMenuItems)
        stack.push(self.viewChrome)

    def viewMenuItems(self, view: Any) -> list[Any]:
        """The application's own rows for ``view``'s menu; none unless overridden.

        Asked each time a view's name is clicked, so what it answers can follow
        the scene.  Return :class:`~OpenGLContext.ui.menu.MenuItem` rows; they
        go below a separator at the foot of the menu.  An override calls up to
        this and adds to what it answers, so mix-ins can each add their own.
        """
        return []

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
        """Fit what there is to see into every view; False with nothing to fit.

        A ``scene`` view then stands where the scene's first camera stands,
        where the scene has one.
        """
        if self.views is None or self._viewBounds is None:
            return False
        found = self._viewBounds()
        if found:
            minimum, maximum = found
            self.views.frame(minimum, maximum)
        camera = first_camera(self.sceneCameras()) if self._sceneViews else None
        if camera is not None:
            for name in self._sceneViews:
                look_through(self.views.named(name), camera)
        return bool(found)

    # -- switching ---------------------------------------------------------
    def showViews(self, name: str) -> None:
        """Show the arrangement ``name``, whatever the views' ``switching`` says."""
        if self.views is None:
            return
        self.views.show(name)
        if self.viewChrome is not None:
            self.viewChrome.layout_of = self.views.layout
        self.viewsArranged()

    def toggleViews(self, event: Any = None) -> None:
        """Take the arrangements in the order declared, so one key reaches them all."""
        if self.views is None:
            return
        names = list(self.views.arrangements)
        index = names.index(self.views.mode) if self.views.mode in names else -1
        self.showViews(names[(index + 1) % len(names)])

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
