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

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

import logging

from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel

log = logging.getLogger(__name__)

__all__ = ['OverlayStack', 'OverlayMixin', 'WHEEL_UP', 'WHEEL_DOWN']

#: What identifies one held input: its kind, and the key name or button number.
_Claim = tuple[str, Any]


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
        self.panels: list[Panel] = []
        #: Called with the stack whenever a panel is pushed or popped.
        self.on_change: Optional[Callable[['OverlayStack'], None]] = None
        #: The viewport the panels were last laid out for.
        self.laidOutFor: Optional[tuple[int, int]] = None

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

    def push(self, panel: Panel, viewport: Optional[tuple[int, int]] = None,
             metrics: Any = None) -> Panel:
        """Put a panel on top, suspending whatever was there.

        With a ``viewport`` and ``metrics`` it is laid out at once; without,
        the whole stack is laid out again on the next frame, since the panels
        under it being laid out for this window says nothing about the new
        one.

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
        # A panel that opens panels of its own -- a menu's submenus -- opens
        # them where it was put, unless it was told somewhere else.
        if panel.stack is None:
            panel.stack = self
        if viewport is not None and metrics is not None:
            panel.layout(viewport, metrics)
            self.laidOutFor = viewport
        else:
            self.invalidate()
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

    def tick(self, now: float) -> None:
        """Advance whatever the panels do over time to ``now``.

        A menu that has had something chosen goes away here once it has
        lingered; a panel with nothing that moves is left alone.
        """
        for panel in list(self.panels):
            tick = getattr(panel, 'tick', None)
            if tick is not None:
                tick(now)

    # -- layout -----------------------------------------------------------
    def layout(self, viewport: tuple[int, int], metrics: Any) -> None:
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

    # -- input, down the layers -------------------------------------------
    # Each of these offers the event to the panels topmost first and returns
    # whether any acted; what the *world* hears is decided by sinks(), not by
    # these.
    def layers(self) -> list[Panel]:
        """The panels an event is offered to, topmost first.

        Down to and including the first modal one, because a modal panel is a
        lid and nothing under it hears anything.  Above one, several modeless
        panels -- a menu bar and a tool palette -- are layers of a single
        interface, and each gets a look at what the layer over it left.
        """
        offered: list[Panel] = []
        for panel in reversed(self.panels):
            offered.append(panel)
            if panel.modal:
                break
        return offered

    def _first(self, action: Callable[[Panel], bool]) -> bool:
        """Offer down the layers until one takes it."""
        for panel in self.layers():
            if action(panel):
                return True
        return False

    def _each(self, action: Callable[[Panel], bool]) -> bool:
        """Offer to every layer, whoever acts.

        For the pointer's *position*, which is not something one layer takes
        from another: a pointer that leaves the bar for the strip over it has
        to stop the bar drawing itself hovered, and it never would if the strip
        ended the walk by acting on the same move.
        """
        acted = False
        for panel in self.layers():
            acted = bool(action(panel)) or acted
        return acted

    def key(self, name: str, modifiers: tuple[int, int, int]) -> bool:
        return self._first(lambda panel: panel.key(name, modifiers))

    def character(self, text: str) -> bool:
        return self._first(lambda panel: panel.character(text))

    def pointer_moved(self, x: float, y: float) -> bool:
        return self._each(lambda panel: panel.pointer_moved(x, y))

    def hovered(self) -> Optional[Any]:
        """The widget the pointer is over, of the topmost panel that has one."""
        for panel in self.layers():
            found = panel.hovered_widget
            if found is not None:
                return found
        return None

    def pointer_pressed(self, x: float, y: float, button: int = 0) -> bool:
        return self._first(lambda panel: panel.pointer_pressed(x, y, button))

    def pointer_released(self, x: float, y: float, button: int = 0) -> bool:
        return self._first(lambda panel: panel.pointer_released(x, y, button))

    def wheel(self, delta: int, x: float, y: float) -> bool:
        return self._first(lambda panel: panel.wheel(delta, x, y))


if TYPE_CHECKING:
    class _Host:
        """What :class:`OverlayMixin` needs of the class beside it.

        Declared for a checker and aliased to ``object`` at run time: the
        context and :class:`~OpenGLContext.ui.screen.ScreenMixin` are what
        actually provide these, and a real base of either name here would put a
        second copy in the MRO.  Each signature matches the real one.
        """

        getInputState: Any
        suspendPointerCapture: Any

        def getViewPort(self) -> tuple[int, int]: ...
        def triggerRedraw(self, force: int = 0) -> Any: ...
        def redrawAt(self, when: float) -> None: ...
        def overlayMetrics(self) -> Optional[FontMetrics]: ...
        def setPointerShape(self, name: str) -> bool: ...
        def screenTrees(self, metrics: FontMetrics,
                        now: Optional[float] = None) -> list[Any]: ...
        def ProcessEvent(self, event: Any) -> Any: ...
        def hasMouseMoveHandlers(self) -> bool: ...
else:
    _Host = object


class OverlayMixin(_Host):
    """Gives a context an overlay stack, its input routing and its drawing.

    The HUD half -- the layers under these panels, and the drawing both go
    through -- is :class:`~OpenGLContext.ui.screen.ScreenMixin`, which every
    context has.  This is the half that takes input.

    This mixin expects to be combined with a class that already inherits from
    :class:`~OpenGLContext.ui.screen.ScreenMixin` (every ``Context`` does), so
    it does not inherit from ``ScreenMixin`` itself.
    """

    _overlays: Optional[OverlayStack] = None
    _overlayActive: bool = False
    _holdingInputs: Optional[dict['_Claim', bool]] = None
    #: The input the world is being told about right now, or None. See
    #: :meth:`letGoOfHeldInput`.
    _dispatching: Optional['_Claim'] = None

    #: Where the pointer was last seen, and when it stopped there, for a tip
    #: that waits for it to rest.
    _pointerAt: Optional[tuple[float, float]] = None
    _pointerSince: float = 0.0
    _tooltip: Any = None
    #: The shape the pointer is in, so it is set when it changes and not on
    #: every movement; None where the backend has changed it since.
    _cursorShown: Optional[str] = ''
    #: Whether the pointer is grabbed for mouse-look, which hides it.
    _pointerHeld: bool = False

    @property
    def _holding(self) -> dict['_Claim', bool]:
        """Which side is holding each down/up input, made on first use.

        True where the overlay took the press, False where it went past. Read
        and cleared by the release -- see :meth:`overlaySinks`.
        """
        if self._holdingInputs is None:
            self._holdingInputs = {}
        return self._holdingInputs

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
            if active:
                self.letGoOfHeldInput()
            self.getInputState().clear()
            if not active:
                self.releaseOverlayPictures()
        self.triggerRedraw(1)

    def letGoOfHeldInput(self) -> None:
        """Tell the world every key it is holding has come up.

        A panel takes the input, so the release of a key held while it opens
        never arrives -- and an application that tracks held keys itself, as a
        movement mode and a game's steering both do, has no other way to learn
        the key is no longer down.  Left alone that is a throttle stuck open
        and a wheel stuck at full lock behind the menu that stopped them being
        let go of.  Clearing
        :class:`~OpenGLContext.events.inputstate.InputState` covers the
        sampler; this covers everyone else, by saying it in the only language
        an input handler speaks.

        The keystroke that *opened* the panel is not among them: it is being
        delivered right now, and handing the world its release as well would
        run whatever else is bound to that key coming up -- which for Escape,
        the key that opens a panel in most applications, is the handler that
        quits.

        The same idea as
        :meth:`OpenGLContext.events.glfwevents.EventHandlerMixin.clearHeldKeys`,
        which does it for a window that loses focus mid-key.
        """
        from OpenGLContext.events import synthetic
        held = getattr(self.getInputState(), 'held_keys', None)
        if held is None:                       # pragma: no cover - no sampler
            return
        for name in sorted(held()):
            if self._dispatching == ('keyboard', name):
                continue
            event = synthetic.build({'type': 'keyboard', 'key': name,
                                     'state': 0})
            if event is None:                  # pragma: no cover - a known type
                continue
            event.context = self
            self._holding.pop(('keyboard', name), None)
            super(OverlayMixin, self).ProcessEvent(event)

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
        # Which input the world is being told about right now, so that a panel
        # opened by this very keystroke does not immediately hand the world its
        # release (:meth:`letGoOfHeldInput`).
        previous, self._dispatching = self._dispatching, _claimKey(event)
        try:
            return super(OverlayMixin, self).ProcessEvent(event)
        finally:
            self._dispatching = previous

    def overlaySinks(self, event: Any) -> bool:
        """Give an event to the overlay; True if nothing else should see it.

        A modal overlay sinks everything, handled or not.  A modeless one --
        a HUD, a console left open while play continues -- sinks only what it
        actually used.

        **An input goes whole to whichever side took its press.**  Anything
        that arrives as a down and an up -- a key, a mouse button -- is held by
        whoever read the down, and only the matching up lets go of it, so the
        two halves must not be split by a panel opening or closing in between:

        * A press the overlay took takes its release with it.  Without that the
          last panel on the stack is a trap: Escape's key-down closes it, the
          stack empties, and the key-up lands on the world's own Escape
          handler, which in every OpenGLContext application quits it.  The same
          goes for the click that dismisses a dialog, whose release would
          otherwise pick whatever was behind it.
        * A press that went *past* the overlay keeps its release, however
          modal a panel that has opened since.  The far side is holding that
          key down and has no other way to learn it came up: swallowing the
          release leaves a throttle open, a wheel at full lock, or a drag with
          no end.  Software key-repeat (``glfwevents.pumpKeyRepeats``) makes
          this the ordinary case rather than a corner: a key held while a panel
          opens goes on delivering presses, and those belong to the panel while
          the key itself does not.
        """
        claim = _claimKey(event)
        stack = self._overlays
        if stack is None or not stack.visible:
            sunk = False
        else:
            acted = self._routeToOverlay(stack, event)
            if acted:
                self.triggerRedraw(1)
            sunk = bool(stack.sinks() or acted)
        if claim is None:
            return sunk
        if _isPress(event):
            # Whichever side takes the press holds the input until its release.
            # A repeat of a key the far side already holds still goes to the
            # panel, but it does not change hands: the key is not the panel's
            # to let go of.
            self._holding.setdefault(claim, sunk)
            return sunk
        # A press the overlay took takes its release with it, wherever the
        # stack has got to by now; anything else follows what is on screen.
        return bool(self._holding.pop(claim, None)) or sunk

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
            if not point:
                return False
            moved = stack.pointer_moved(point[0], point[1])
            # Noted whether or not a panel wanted it: a tip waits for the
            # pointer to rest, and the cursor follows what it is over, in the
            # gaps between controls as much as on them.
            self.pointerRested(point[0], point[1])
            self.showCursor()
            return bool(moved)
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
        return bool(super(OverlayMixin, self).hasMouseMoveHandlers())

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
                    now: Optional[float] = None) -> list[Any]:
        """The HUD layers, the open panels, and any tip over the lot.

        The panels are advanced to ``now`` first, so one whose time is up is
        gone before it is drawn.
        """
        trees = super(OverlayMixin, self).screenTrees(metrics, now)
        stack = self._overlays
        if stack is not None and stack.visible:
            from OpenGLContext.events import systemtime
            stack.tick(systemtime.systemTime() if now is None else float(now))
        if stack is not None and stack.visible and self.layoutOverlays():
            trees.extend(stack.panels)
            tip = self.tooltipTree(now)
            if tip is not None:
                size = self.getViewPort()
                tip.layout((int(size[0]), int(size[1])), metrics)
                trees.append(tip)
        return trees

    # -- what the pointer is told ------------------------------------------
    def pointerRested(self, x: float, y: float,
                      now: Optional[float] = None) -> None:
        """The pointer moved to ``(x, y)``: note where, and when it stopped.

        The pause a tip waits for is measured from the last movement, so a
        pointer crossing a window shows nothing and one that comes to rest on
        a control is answered. ``now`` is the session's clock, which is what
        :meth:`tooltipTree` measures against.
        """
        from OpenGLContext.events import systemtime
        from OpenGLContext.ui.tooltip import TOOLTIP_PAUSE
        self._pointerAt = (float(x), float(y))
        self._pointerSince = (systemtime.systemTime() if now is None
                              else float(now))
        self._tooltip = None
        stack = self._overlays
        hovered = stack.hovered() if stack is not None and stack.visible else None
        if str(getattr(hovered, 'tooltip', '') or ''):
            # A window that draws on demand draws nothing more once the
            # pointer is still, so the frame the tip appears in is asked for.
            self.redrawAt(self._pointerSince + TOOLTIP_PAUSE)

    def setPointerCapture(self, capture: bool) -> bool:
        """Grab or release the pointer as the backend does; False where it cannot.

        A grabbed pointer is hidden, and no shape is asked for while it is, so
        a hover cannot show it again. Releasing it leaves the backend's
        ordinary pointer, so the shape the control under it wants is asked for
        again at once.
        """
        backend = getattr(super(OverlayMixin, self), 'setPointerCapture', None)
        if backend is None:
            return False
        done = bool(backend(capture))
        if done:
            self._pointerHeld = bool(capture)
            self._cursorShown = None
            if not capture:
                self.showCursor()
        return done

    def showCursor(self) -> bool:
        """Put the pointer into the shape the widget under it asks for.

        Called as the pointer crosses the window. A backend with no cursors
        answers False and the pointer stays as it is, as it does while
        mouse-look holds the pointer hidden.
        """
        if self._pointerHeld:
            return False
        wanted = self.cursorWanted()
        if wanted == self._cursorShown:
            return True
        shown = bool(self.setPointerShape(wanted))
        if shown:
            self._cursorShown = wanted
        return shown

    def cursorWanted(self) -> str:
        """What the widget under the pointer asks the cursor to be, or ``''``."""
        stack = self._overlays
        if stack is None or not stack.visible:
            return ''
        found = stack.hovered()
        return str(getattr(found, 'cursor', '') or '')

    def tooltipTree(self, now: Optional[float] = None) -> Optional[Any]:
        """The tip to draw over the frame, or None while there is none.

        None until the pointer has rested on a control with something to say
        for :data:`~OpenGLContext.ui.tooltip.TOOLTIP_PAUSE`.
        """
        from OpenGLContext.events import systemtime
        from OpenGLContext.ui.tooltip import TOOLTIP_PAUSE, Tooltip
        stack = self._overlays
        if stack is None or not stack.visible or self._pointerAt is None:
            return None
        found = stack.hovered()
        text = str(getattr(found, 'tooltip', '') or '')
        if not text:
            self._tooltip = None
            return None
        now = systemtime.systemTime() if now is None else float(now)
        if now - self._pointerSince < TOOLTIP_PAUSE:
            return None
        tip = self._tooltip
        if tip is None or str(tip.text) != text:
            tip = Tooltip(text=text, anchor=self._pointerAt)
            self._tooltip = tip
        return tip
