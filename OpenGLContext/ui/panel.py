"""One overlay screen: where it sits, what has focus, what the keyboard does.

A panel is the unit an overlay stack pushes and pops.  It owns the things that
are per-screen rather than per-widget -- the focus, the accelerators, the Enter
default, the command table -- and it says whether it is **modal**, which is what
decides how much of the world hears anything while it is up.

**A modal panel sinks all input.**  Not the events it handles: *all* of them,
including the ones it ignores.  It is a lid, not a filter.  The alternative --
a per-event "consumed" flag -- makes every new widget answer "which events do I
want" honestly, forever, and it is the answer nobody gets right.  What that
means for the world underneath is in :mod:`OpenGLContext.ui.overlay`; here it
is one field.

**Two things a panel can be beyond modal.**  ``capturing`` suspends every
UI-level key -- accelerators, Tab, the Enter default -- so a key-rebinding
dialog sees Tab, Enter and the mouse buttons verbatim.  Escape is reserved as
the way out of one, and is therefore the one key that cannot be bound.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from vrml import field, node

from OpenGLContext.hud import distribute
from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.skin import DEFAULT_SKIN, PRIMARY
from OpenGLContext.ui.widgets import Widget

__all__ = ['Panel']


class Panel(Widget):
    """A screen drawn over the frame, with its own focus and modality."""

    PROTO = 'Panel'
    #: Drawn along the top of the panel; empty for none.
    title = field.newField('title', 'SFString', 1, '')
    children = field.newField('children', 'MFNode', 1, list)
    #: While up, nothing below this panel hears anything -- not the world, not
    #: a parent panel.
    modal = field.newField('modal', 'SFBool', 1, True)
    #: Every event goes verbatim to the focused widget: no accelerators, no
    #: focus traversal, no Enter default.  For key rebinding.
    capturing = field.newField('capturing', 'SFBool', 1, False)
    #: Escape closes; a panel that must be answered turns this off.
    closeOnEscape = field.newField('closeOnEscape', 'SFBool', 1, True)
    #: Dim the frame behind, so the eye goes to the question.
    scrim = field.newField('scrim', 'SFBool', 1, False)
    #: Take the whole window height rather than sitting at the natural size.
    #: The *width* is still capped by ``preferredColumns``.
    fill = field.newField('fill', 'SFBool', 1, False)
    #: Pixels kept clear between the panel and the window edge.
    margin = field.newField('margin', 'SFFloat', 1, 24.0)
    #: Content width **in characters**, 0 for none.  This is both the width a
    #: dialog's text is measured against and the **maximum width** the panel
    #: will take, which is what keeps a settings screen a centred column on a
    #: 4K display rather than a line of controls a metre apart.  In characters
    #: rather than pixels so it holds at every interface scale.
    preferredColumns = field.newField('preferredColumns', 'SFInt32', 1, 0)
    #: The artwork and colours this screen paints with; the default flat skin
    #: when NULL.
    skin = field.newField('skin', 'SFNode', 1, node.NULL)

    interactive = True

    #: Whether the panel has been dismissed, and with what.
    closed: bool = False
    result: Any = None
    #: Called with the panel once it closes.
    on_close: Optional[Callable[['Panel'], None]] = None
    #: Whether any bound value has been edited since the panel opened.  What
    #: lights an Apply button for a change made two dialogs deep.
    dirty: bool = False
    #: Whether the focus ring is drawn.  Keyboard focus and text entry earn it;
    #: clicking a button does not, because a button that keeps a ring
    #: afterwards looks stuck.
    focusVisible: bool = False
    #: Room the title takes, settled at layout time; 0 for an untitled panel.
    _title_height: int = 0
    #: This panel's skin at the current interface scale, and what it was made
    #: from, so it is rebuilt only when one of the two changes.
    _scaledSkin: Optional[Any] = None
    _scaledFrom: Optional[Any] = None
    _scaledBy: float = 1.0
    _focused: Optional[Widget] = None
    _armed: Optional[Widget] = None
    _hovered: Optional[Widget] = None
    #: The widget to put focus back on when a child dialog closes.
    _resume_focus: Optional[Widget] = None

    def __init__(self, **named: Any) -> None:
        super(Panel, self).__init__(**named)
        #: Named actions a widget can trigger.  Each is called with the panel
        #: and the widget, so one command can serve several buttons.
        self.commands: Dict[str, Callable[['Panel', Widget], None]] = {
            'close': lambda panel, widget: panel.close(widget.value or None),
        }
        #: Keys that act without a control of their own -- a second spelling
        #: of an answer, a shortcut to a page.  Each is called with the panel.
        self.accelerators: Dict[str, Callable[['Panel'], None]] = {}
        #: Notified when the panel closes.  Separate from ``on_close`` so an
        #: overlay stack can pop the panel without taking the one callback the
        #: caller wanted for the answer.
        self.closeListeners: List[Callable[['Panel'], None]] = []

    # -- layout -----------------------------------------------------------
    def layoutChildren(self) -> Sequence[Any]:
        return [child for child in self.children
                if getattr(child, 'visible', True)]

    def activeSkin(self) -> Any:
        """The skin every widget on this screen paints with.

        Scaled for the window the panel was last laid out in, so a measurement
        read from it is in real pixels and no widget has to know the scale
        exists.
        """
        if self._scaledSkin is not None:
            return self._scaledSkin
        return self.skin if self.skin else DEFAULT_SKIN

    def scaleSkin(self, metrics: Any) -> Any:
        """Settle the skin for one interface scale, and hand it back."""
        base = self.skin if self.skin else DEFAULT_SKIN
        factor = float(getattr(metrics, 'scale', 1.0))
        if self._scaledFrom is not base or self._scaledBy != factor:
            self._scaledFrom = base
            self._scaledBy = factor
            self._scaledSkin = base.scaled(factor)
        return self._scaledSkin

    def contentRect(self) -> Rect:
        """Where the children go: inside the padding, below any title."""
        skin = self.activeSkin()
        inner = self.rect.inset(int(skin.panelPadding))
        if self.title:
            return Rect(inner.x, inner.y, inner.width,
                        max(0, inner.height - self._title_height))
        return inner

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        skin = self.activeSkin()
        widest = 0
        total = 0
        for child in self.layoutChildren():
            width, height = child.natural_size(metrics, available)
            widest = max(widest, int(width))
            total += int(height)
        if self.title:
            widest = max(widest, metrics.text_width(self.title))
            total += metrics.line_height + int(skin.rowSpacing)
        pad = int(skin.panelPadding) * 2
        return (widest + pad, total + pad)

    def layout(self, viewport: Tuple[int, int], metrics: Any) -> None:
        """Place the panel in a window of this size and arrange its contents.

        Run when something changes rather than every frame: a settings page is
        a few dozen widgets, and re-measuring text for all of them at 144Hz is
        work nobody asked for.
        """
        self.link()
        view_width, view_height = (int(viewport[0]), int(viewport[1]))
        self.viewport = Rect(0, 0, view_width, view_height)
        margin = metrics.pixels(self.margin)
        skin = self.scaleSkin(metrics)
        self._title_height = (metrics.line_height + int(skin.rowSpacing)
                              if self.title else 0)
        limit = max(0, view_width - margin * 2)
        if self.fill:
            width = min(limit, self._maximumWidth(metrics) or limit)
            height = max(0, view_height - margin * 2)
        else:
            width, height = self.natural_size(
                metrics, self._preferredWidth(metrics, limit))
            width = min(int(self.width) or width, limit)
            height = min(int(self.height) or height,
                         max(0, view_height - margin * 2))
        self.rect = Rect((view_width - width) // 2,
                         (view_height - height) // 2, width, height)
        self.arrange_content(metrics)

    def _maximumWidth(self, metrics: Any) -> int:
        """The widest this panel may be drawn, or 0 for no limit."""
        if not self.preferredColumns:
            return 0
        return (int(self.preferredColumns) * metrics.char_width
                + int(self.activeSkin().panelPadding) * 2)

    def link(self) -> None:
        """Point every widget in the tree at its container, top down.

        Before measuring rather than while arranging, because a widget finds
        its skin -- and therefore its padding, its switch size, everything it
        measures against -- by walking up to the panel.  Measurement runs
        before anything is placed, so a tree linked only as it is arranged
        would size its first pass against the unscaled default and paint the
        result at the real scale.
        """
        stack: List[Any] = [self]
        while stack:
            current = stack.pop()
            for child in current.layoutChildren():
                child.parent = current
                stack.append(child)

    def _preferredWidth(self, metrics: Any,
                        limit: int) -> Optional[int]:
        """The content width to measure against, or None to let it be natural."""
        maximum = self._maximumWidth(metrics)
        if not maximum:
            return None
        padding = int(self.activeSkin().panelPadding) * 2
        return max(0, min(maximum - padding, limit - padding))

    def arrange_content(self, metrics: Any) -> None:
        content = self.contentRect()
        children = self.layoutChildren()
        if not children:
            return
        skin = self.activeSkin()
        spacing = int(skin.rowSpacing)
        # Several children stack; the usual case is one Column that has already
        # arranged everything inside it.
        sizes = [child.natural_size(metrics, content.width)
                 for child in children]
        heights = [int(size[1]) for size in sizes]
        spare = content.height - sum(heights) - spacing * (len(children) - 1)
        if len(children) == 1:
            # A lone child gets exactly the room the panel has, more or less
            # than it asked for.  A screen is a fixed size and what is in it
            # has to fit; the child's own flexible parts -- a scroll viewport --
            # take up the difference, which is what keeps a settings page's
            # buttons on screen however long the list above them grows.
            heights[0] = content.height
        elif any(child.flex for child in children):
            heights = distribute(children, heights, spare)
        cursor = content.top
        for child, height in zip(children, heights, strict=True):
            child.parent = self
            child.arrange(Rect(content.x, cursor - height,
                               content.width, height), metrics)
            cursor -= height + spacing

    def titleRect(self, metrics: Any) -> Rect:
        """Where the title is drawn, along the top inside the padding."""
        inner = self.rect.inset(int(self.activeSkin().panelPadding))
        return Rect(inner.x, inner.top - metrics.line_height, inner.width,
                    metrics.line_height)

    # -- drawing ----------------------------------------------------------
    def paint(self, renderer: Any) -> None:
        skin = renderer.skin
        renderer.frame(self.rect, skin.panelFill, skin._image(skin.panelImage))
        renderer.border(self.rect, skin.panelBorder, int(skin.borderWidth))
        if self.title:
            renderer.textIn(self.titleRect(renderer.metrics), self.title,
                            skin.titleText)

    # -- focus ------------------------------------------------------------
    @property
    def focused_widget(self) -> Optional[Widget]:
        """Where the keyboard is, or None."""
        return self._focused

    def focusables(self) -> List[Widget]:
        """Every widget Tab can stop on, in the order they are laid out."""
        return [widget for widget in self.walk()
                if widget is not self and widget.focusable
                and widget.enabled and widget.visible]

    def focus(self, widget: Optional[Widget], visible: bool = True) -> None:
        """Give the keyboard to a widget, or to nothing."""
        if self._focused is widget:
            self.focusVisible = self.focusVisible or visible
            return
        if self._focused is not None:
            self._focused.focus_lost()
        self._focused = widget
        if widget is not None:
            widget.focus_gained()
            self._scrollIntoView(widget)
        self.focusVisible = visible and widget is not None

    def focusNext(self, step: int = 1) -> bool:
        """Move focus along the Tab order, wrapping at the ends."""
        order = self.focusables()
        if not order:
            self.focus(None)
            return False
        try:
            index = order.index(self._focused)     # type: ignore[arg-type]
        except ValueError:
            index = -1 if step > 0 else 0
        self.focus(order[(index + step) % len(order)])
        return True

    def _scrollIntoView(self, widget: Widget) -> None:
        """Ask any enclosing viewport to bring a newly focused widget into view.

        Including its glow margin: a viewport clips with a scissor rectangle,
        so a widget flush against the edge would otherwise have its focus ring
        cut in half.
        """
        current = widget.parent
        while current is not None:
            reveal = getattr(current, 'reveal', None)
            if reveal is not None:
                reveal(widget.rect.expand(int(self.activeSkin().focusMargin)))
            current = current.parent

    # -- pointer ----------------------------------------------------------
    def pointer_moved(self, x: float, y: float) -> bool:
        """Track hover and continue any drag.  True if the frame should redraw."""
        if self._armed is not None:
            self._armed.drag(x, y)
            return True
        found = self.widget_at(x, y)
        if found is self._hovered:
            return False
        if self._hovered is not None:
            self._hovered.hovered = False
        self._hovered = found
        if found is not None:
            found.hovered = True
        return True

    def pointer_pressed(self, x: float, y: float, button: int = 0) -> bool:
        """Arm whatever is under the pointer.  True if something took it."""
        if self.capturing and self._focused is not None:
            claim = getattr(self._focused, 'button', None)
            if claim is not None:
                claim(button)
                return True
        found = self.widget_at(x, y)
        if found is None or found is self:
            self.focus(None)
            self._armed = None
            return False
        self._armed = found if found.press(x, y) else None
        # A click earns a focus ring only where the keyboard is about to be
        # used: typing into a field with no ring leaves you guessing where the
        # characters are going.
        self.focus(found if found.focusable else None,
                   visible=bool(found.acceptsText))
        return self._armed is not None

    def pointer_released(self, x: float, y: float, button: int = 0) -> bool:
        armed, self._armed = self._armed, None
        if armed is None:
            return False
        return armed.release(x, y)

    def wheel(self, delta: int, x: float, y: float) -> bool:
        """Offer a wheel notch to the widget under the pointer, then its parents."""
        current: Optional[Any] = self.widget_at(x, y)
        while current is not None:
            if current.wheel(delta, x, y):
                return True
            current = current.parent
        return False

    # -- keyboard ---------------------------------------------------------
    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        """Offer a key to the panel.  True if it acted on it.

        The return says whether anything changed, for redraw; it is *not* what
        decides whether the world sees the key.  A modal panel sinks every
        event whatever this says.
        """
        if name == '<escape>':
            if self.closeOnEscape:
                self.close(None)
                return True
            return False
        if self.capturing:
            return bool(self._focused is not None
                        and self._focused.key(name, modifiers))
        if self._focused is not None and self._focused.key(name, modifiers):
            return True
        if name == '<tab>':
            return self.focusNext(-1 if modifiers[0] else 1)
        if name == '<return>':
            primary = self.primary()
            if primary is not None and primary.enabled:
                primary.activate()
                return True
            return False
        return self.accelerate(name)

    def character(self, text: str) -> bool:
        """A typed character, for whichever widget wants text."""
        if self._focused is not None and self._focused.acceptsText:
            return self._focused.character(text)
        return False

    def accelerate(self, name: str) -> bool:
        handler = self.accelerators.get(name)
        if handler is not None:
            handler(self)
            return True
        for widget in self.walk():
            if widget is not self and widget.accelerate(name):
                return True
        return False

    def primary(self) -> Optional[Widget]:
        """The panel's default action: its first visible ``primary`` button.

        Disabled or not: which action Enter means is a property of the screen,
        while whether it can be taken right now is a separate question, asked
        where Enter is handled.  An Apply that is the default only once it is
        lit would leave Enter meaning nothing at all on a fresh page.
        """
        for widget in self.walk():
            if (widget is not self and getattr(widget, 'role', None) == PRIMARY
                    and widget.visible):
                return widget
        return None

    # -- acting -----------------------------------------------------------
    def dispatch(self, widget: Widget) -> None:
        """Run the command a widget names, if this panel has one by that name."""
        action = getattr(widget, 'action', '')
        command = self.commands.get(action) if action else None
        if command is not None:
            command(self, widget)

    def valueChanged(self, widget: Widget) -> None:
        """A bound widget wrote a value: the panel now has unsaved edits."""
        self.dirty = True

    def close(self, result: Any = None) -> None:
        """Dismiss the panel, carrying a result back to whoever opened it."""
        if self.closed:
            return
        self.closed = True
        self.result = result
        if self._armed is not None:
            self._armed.cancel()
            self._armed = None
        if self.on_close is not None:
            self.on_close(self)
        for listener in list(self.closeListeners):
            listener(self)

    def suspend(self) -> None:
        """A panel opened over this one; drop transient pointer state.

        Nothing under a modal hears anything, so a button left armed here would
        fire on a release it never saw the press for.
        """
        if self._armed is not None:
            self._armed.cancel()
            self._armed = None
        if self._hovered is not None:
            self._hovered.hovered = False
            self._hovered = None
        self._resume_focus = self._focused

    def resume(self) -> None:
        """The panel over this one closed; take focus back where it was.

        Without this, Tab order restarts at the top of the page every time a
        dialog closes.
        """
        if self._resume_focus is not None and self._resume_focus.enabled:
            self.focus(self._resume_focus, visible=self.focusVisible)
