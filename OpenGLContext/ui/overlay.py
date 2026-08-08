"""The stack of overlay panels, and the context mix-in that feeds it.

Overlays form a stack, and **the topmost modal panel receives input while
everything under it receives nothing** -- the world, and any parent panel.  A
confirmation raised over a settings screen leaves that screen as deaf as the
scene behind it.

That rule has one consequence the wiring has to carry, and it is why this is a
mix-in rather than a pair of event handlers.  ``ViewPlatformMixin.ProcessEvent``
feeds :class:`~OpenGLContext.events.inputstate.InputState` *before* it
dispatches, so gating the handlers alone would leave a key the overlay consumed
already recorded as held -- a player walking into a wall while typing into a
text field.  So while a modal overlay is up the sampler is not fed at all,
opening one clears it, and closing one starts from nothing held, which is what
the player's fingers report on the next key event anyway.

Mix it in **ahead of** the navigation mix-in, so its ``ProcessEvent`` runs
first::

    class Game(OverlayMixin, GLFWInteractiveContext):
        ...
    game.pushOverlay(dialogs.confirm('Quit?', on_answer=game.quitting))
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Set, Tuple

import logging

from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel

log = logging.getLogger(__name__)

__all__ = ['OverlayStack', 'OverlayMixin', 'WHEEL_UP', 'WHEEL_DOWN']

#: What identifies one held input: its kind, and the key name or button number.
_Claim = Tuple[str, Any]


def _claimKey(event: Any) -> Optional['_Claim']:
    """What identifies one held input, or None if the event is not one half.

    Only the events that come in a down/up pair are claimable.  A ``keypress``
    is a whole keystroke on its own and a mouse move is neither half of
    anything.
    """
    kind = getattr(event, 'type', None)
    if kind == 'keyboard':
        return ('keyboard', getattr(event, 'name', ''))
    if kind == 'mousebutton':
        return ('mousebutton', int(getattr(event, 'button', 0)))
    return None


def _isPress(event: Any) -> bool:
    return bool(getattr(event, 'state', 0))


class OverlayStack:
    """Panels over the frame, newest on top, only the top one hearing anything."""

    def __init__(self) -> None:
        self.panels: List[Panel] = []
        #: Called with the stack whenever a panel is pushed or popped.
        self.on_change: Optional[Callable[['OverlayStack'], None]] = None
        #: The viewport the panels were last laid out for.
        self.laidOutFor: Optional[Tuple[int, int]] = None

    # -- the stack --------------------------------------------------------
    @property
    def visible(self) -> bool:
        """Whether anything is on screen."""
        return bool(self.panels)

    @property
    def top(self) -> Optional[Panel]:
        """The panel that hears the input, or None."""
        return self.panels[-1] if self.panels else None

    def named(self, name: str) -> Optional[Panel]:
        """The panel already on the stack under that name, or None.

        What lets a second press of the settings key raise the screen that is
        already up rather than stacking another copy of it over itself.
        """
        for panel in self.panels:
            if panel.name == name:
                return panel
        return None

    def sinks(self) -> bool:
        """Whether the world should hear nothing at all right now."""
        return any(panel.modal for panel in self.panels)

    def capturing(self) -> bool:
        """Whether the top panel wants every event verbatim."""
        top = self.top
        return bool(top is not None and top.capturing)

    def push(self, panel: Panel, viewport: Optional[Tuple[int, int]] = None,
             metrics: Any = None) -> Panel:
        """Put a panel on top, suspending whatever was there.

        A panel that has already been closed is refused rather than accepted
        and then quietly ignored: it would never fire the listener that takes
        it back off, so it would sit on the stack sinking every event for the
        rest of the session.
        """
        if panel.closed:
            raise ValueError(
                "cannot push a panel that has already been closed")
        if self.panels:
            self.panels[-1].suspend()
        self.panels.append(panel)
        panel.closeListeners.append(self._panelClosed)
        if viewport is not None and metrics is not None:
            panel.layout(viewport, metrics)
            self.laidOutFor = viewport
        self._changed()
        return panel

    def pop(self, result: Any = None) -> Optional[Panel]:
        """Close the top panel, as if its Cancel had been pressed."""
        top = self.top
        if top is not None:
            top.close(result)
        return top

    def remove(self, panel: Panel) -> None:
        """Take a panel out of the stack and resume whatever was under it."""
        if panel not in self.panels:
            return
        self.panels.remove(panel)
        try:
            panel.closeListeners.remove(self._panelClosed)
        except ValueError:
            pass
        if self.panels:
            self.panels[-1].resume()
        self._changed()

    def clear(self) -> None:
        """Close every panel, innermost first.

        Over a snapshot rather than "until the stack is empty", so the loop is
        bounded by the number of panels rather than by every one of them
        reporting its own removal.  A panel closed behind the stack's back has
        nothing left to notify anyone with, and a loop that waited for it would
        never end.
        """
        for panel in list(reversed(self.panels)):
            panel.close(None)
            self.remove(panel)

    def _panelClosed(self, panel: Panel) -> None:
        self.remove(panel)

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change(self)

    # -- layout -----------------------------------------------------------
    def layout(self, viewport: Tuple[int, int], metrics: Any) -> None:
        """Lay every panel out for a window size.

        Every panel rather than only the top one: a parent screen is still
        drawn behind its child dialog, and a stale layout would show it in the
        wrong place the moment the window resized.
        """
        for panel in self.panels:
            panel.layout(viewport, metrics)
        self.laidOutFor = (int(viewport[0]), int(viewport[1]))

    def invalidate(self) -> None:
        """Force the next frame to lay out again."""
        self.laidOutFor = None

    # -- input, all of it for the top panel only --------------------------
    # Each of these offers the event to the top panel and returns whether it
    # acted; what the *world* hears is decided by sinks(), not by these.
    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        top = self.top
        return bool(top is not None and top.key(name, modifiers))

    def character(self, text: str) -> bool:
        top = self.top
        return bool(top is not None and top.character(text))

    def pointer_moved(self, x: float, y: float) -> bool:
        top = self.top
        return bool(top is not None and top.pointer_moved(x, y))

    def pointer_pressed(self, x: float, y: float, button: int = 0) -> bool:
        top = self.top
        return bool(top is not None and top.pointer_pressed(x, y, button))

    def pointer_released(self, x: float, y: float, button: int = 0) -> bool:
        top = self.top
        return bool(top is not None and top.pointer_released(x, y, button))

    def wheel(self, delta: int, x: float, y: float) -> bool:
        top = self.top
        return bool(top is not None and top.wheel(delta, x, y))


class OverlayMixin:
    """Gives a context an overlay stack, its input routing and its drawing.

    The HUD half -- the layers under these panels, and the drawing both go
    through -- is :class:`~OpenGLContext.ui.screen.ScreenMixin`, which every
    context has.  This is the half that takes input.

    This mixin expects to be combined with a class that already inherits from
    :class:`~OpenGLContext.ui.screen.ScreenMixin` (every ``Context`` does), so
    it does not inherit from ``ScreenMixin`` itself.
    """

    # Supplied by the context this is mixed into (annotations only, so the
    # real methods are still found at run time).
    getInputState: Any
    suspendPointerCapture: Any
    _overlays: Optional[OverlayStack] = None
    _overlayActive: bool = False
    #: Inputs whose press the overlay took, so their release is taken too.
    #: See :meth:`overlaySinks`.
    _claimed: Optional[Set['_Claim']] = None

    @property
    def overlays(self) -> OverlayStack:
        """This context's overlay stack, made on first use."""
        if self._overlays is None:
            stack = OverlayStack()
            stack.on_change = self._overlaysChanged
            self._overlays = stack
        return self._overlays

    # -- opening and closing ----------------------------------------------
    def pushOverlay(self, panel: Panel) -> Panel:
        """Put a panel on screen and give it the input."""
        return self.overlays.push(panel, viewport=self.getViewPort(),
                                  metrics=self.overlayMetrics())

    def popOverlay(self, result: Any = None) -> Optional[Panel]:
        """Dismiss the top panel."""
        return self.overlays.pop(result)

    def _overlaysChanged(self, stack: OverlayStack) -> None:
        """Take or hand back the things a panel needs while it is up.

        The pointer, because an overlay is clicked with the same pointer a
        mouse-look mode has grabbed; the input sampler, because whatever was
        held at the moment the panel opened would otherwise stay held for as
        long as it is up; and the pictures, once nothing is on screen to want
        them.
        """
        active = stack.visible
        if active != self._overlayActive:
            self._overlayActive = active
            self.suspendPointerCapture(active)
            self.getInputState().clear()
            if not active:
                self.releaseOverlayPictures()
        self.triggerRedraw(1)

    def releaseOverlayPictures(self) -> None:
        """Give the overlay's picture textures back to the card.

        Called when the last panel closes.  A gallery of a few hundred models
        is a few hundred screenshots, and the cache's budget is only enforced
        while *more* are arriving -- so with no panel left to load any, whatever
        was browsed would stay resident for the rest of the session.

        What goes is the decoded texture, not the file: an ``http(s)`` picture
        stays in the on-disk resolver cache and a local one was never anywhere
        else, so reopening decodes from disk rather than fetching again.  The
        worker pool is left running, which is what separates this from
        :meth:`~OpenGLContext.ui.pictures.PictureCache.close`; the cache is
        ready for the next panel.

        Runs on whichever thread closed the panel, which is the thread that
        handles events and therefore the one holding the GL context -- the same
        assumption every other overlay teardown here makes.
        """
        renderer = getattr(self, '_overlayRenderer', None)
        if renderer is not None:
            renderer.pictures.clear()

    # -- input -------------------------------------------------------------
    def ProcessEvent(self, event: Any) -> Any:
        """Offer the event to the overlay first; pass it on only if it survives."""
        if self.overlaySinks(event):
            return None
        return super(OverlayMixin, self).ProcessEvent(event)   # type: ignore[misc]

    def overlaySinks(self, event: Any) -> bool:
        """Give an event to the overlay; True if nothing else should see it.

        A modal overlay sinks everything, handled or not.  A modeless one --
        a HUD, a console left open while play continues -- sinks only what it
        actually used.

        **A press the overlay took takes its release with it**, whether or not
        an overlay is still up by the time the release arrives.  Without that
        ledger the last panel on the stack is a trap: Escape's key-down closes
        it, the stack empties, and the key-up lands on the world's own Escape
        handler, which in every OpenGLContext application quits it.  The same
        goes for the click that dismisses a dialog, whose release would
        otherwise pick whatever was behind it.
        """
        claim = _claimKey(event)
        stack = self._overlays
        if stack is None or not stack.visible:
            return self._releaseClaim(claim, event)
        acted = self._routeToOverlay(stack, event)
        if acted:
            self.triggerRedraw(1)
        sunk = bool(stack.sinks() or acted)
        if claim is not None and sunk:
            self._holdClaim(claim, event)
        elif claim is not None:
            self._releaseClaim(claim, event)
        return sunk

    def _holdClaim(self, claim: '_Claim', event: Any) -> None:
        """Remember a press the overlay took, or forget it on its release."""
        if self._claimed is None:
            self._claimed = set()
        if _isPress(event):
            self._claimed.add(claim)
        else:
            self._claimed.discard(claim)

    def _releaseClaim(self, claim: Optional['_Claim'], event: Any) -> bool:
        """Whether this release finishes an input the overlay already took."""
        if claim is None or _isPress(event) or not self._claimed:
            return False
        if claim not in self._claimed:
            return False
        self._claimed.discard(claim)
        return True

    def _routeToOverlay(self, stack: OverlayStack, event: Any) -> bool:
        kind = getattr(event, 'type', None)
        if kind == 'keyboard':
            if getattr(event, 'state', 0):
                return stack.key(event.name, tuple(event.getModifiers()))
            return False
        if kind == 'keypress':
            return stack.character(event.name)
        if kind == 'mousebutton':
            return self._routeButton(stack, event)
        if kind == 'mousemove':
            point = event.getPickPoint()
            return bool(point) and stack.pointer_moved(point[0], point[1])
        return False

    @staticmethod
    def _routeButton(stack: OverlayStack, event: Any) -> bool:
        point = event.getPickPoint()
        if not point:
            return False
        button = int(getattr(event, 'button', 0))
        down = bool(getattr(event, 'state', 0))
        # The wheel arrives as a pair of buttons; a capturing panel wants them
        # verbatim, since a wheel notch is a bindable input.
        if button in (WHEEL_UP, WHEEL_DOWN) and not stack.capturing():
            if not down:
                return False
            return stack.wheel(1 if button == WHEEL_UP else -1,
                               point[0], point[1])
        if down:
            return stack.pointer_pressed(point[0], point[1], button)
        return stack.pointer_released(point[0], point[1], button)

    def hasMouseMoveHandlers(self) -> bool:
        """An overlay wants moves for hover, whatever the scenegraph wants.

        The pick optimiser drops move events when nothing is listening, and a
        button that does not light under the pointer reads as scenery.
        """
        if self._overlays is not None and self._overlays.visible:
            return True
        return bool(super(OverlayMixin, self).hasMouseMoveHandlers())   # type: ignore[misc]

    # -- layout and drawing -----------------------------------------------
    def layoutOverlays(self, force: bool = False) -> bool:
        """Lay the panels out for the current window; False if not yet possible.

        Layout runs when something changes -- a push, a resize -- rather than
        every frame.
        """
        stack = self._overlays
        if stack is None or not stack.visible:
            return False
        size = self.getViewPort()
        viewport = (int(size[0]), int(size[1]))
        if not force and stack.laidOutFor == viewport:
            return True
        metrics = self.overlayMetrics()
        if metrics is None:
            return False
        stack.layout(viewport, metrics)
        return True

    def screenTrees(self, metrics: FontMetrics,
                    now: Optional[float] = None) -> List[Any]:
        """The HUD layers, and then the open panels on top of them."""
        trees = super(OverlayMixin, self).screenTrees(metrics, now)
        stack = self._overlays
        if stack is not None and stack.visible and self.layoutOverlays():
            trees.extend(stack.panels)
        return trees
