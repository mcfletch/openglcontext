"""A viewport that clips its contents, and the bar that scrolls them.

Anything longer than the room it has goes in one of these: a licence notice, a
long settings page, the console's scrollback.  The child is laid out at its
full natural height, the viewport clips to its own rectangle with a scissor
rectangle, and the difference is the scroll range.

Two things follow from clipping with a scissor and are handled here rather than
discovered later:

* **What is clipped away cannot be clicked.**  Hit-testing stops at the
  viewport's rectangle, so a button scrolled out of sight is not secretly
  hittable where it would have been.
* **A focused widget is scrolled into view including its glow margin**, because
  the ring is drawn *outside* the widget and the scissor would otherwise cut it
  in half at the edge of the list.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

from vrml import field

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.widgets import Widget

__all__ = ['ScrollViewport']

#: Lines moved by one notch of the wheel.
WHEEL_LINES = 3


class ScrollViewport(Widget):
    """One child, clipped to this rectangle and scrolled within it."""

    PROTO = 'ScrollViewport'
    children = field.newField('children', 'MFNode', 1, list)
    #: Pixels the content is moved up by; 0 shows the top.
    scroll = field.newField('scroll', 'SFFloat', 1, 0.0)
    #: Hide the bar even when the content overflows, for a console that scrolls
    #: itself.
    showBar = field.newField('showBar', 'SFBool', 1, True)

    interactive = True

    #: Set while the thumb is being dragged: how far down the thumb the pointer
    #: grabbed it, so the content does not jump on the first pixel of motion.
    _thumbGrab: Optional[int] = None
    #: The content's height at the last layout.
    contentHeight: int = 0
    #: The font's line height when this was laid out.  Scrolling is measured in
    #: lines of the text being scrolled, so a notch of the wheel moves the same
    #: amount of *reading* at every interface scale.
    lineHeight: int = 20

    @property
    def focusable(self) -> bool:            # type: ignore[override]
        """Tab stops here only when there is something to scroll."""
        return self.maximumScroll > 0

    def layoutChildren(self) -> Sequence[Widget]:
        return [child for child in self.children
                if getattr(child, 'visible', True)]

    # -- measurement ------------------------------------------------------
    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        width = 0
        height = 0
        inner = None if available is None else max(0, available - self._barGutter())
        for child in self.layoutChildren():
            child_w, child_h = child.natural_size(metrics, inner)
            width = max(width, int(child_w))
            height += int(child_h)
        return (width + self._barGutter(), height)

    def _barWidth(self) -> int:
        return int(self.activeSkin().scrollbarWidth) if self.showBar else 0

    def _barGutter(self) -> int:
        """Width taken from the content: the bar, and a gap before it.

        The gap because the right-hand end of a row is where a slider prints
        its value and where a switch sits, and either of those touching the bar
        reads as an overlap even when it is not one.
        """
        if not self.showBar:
            return 0
        return self._barWidth() + int(self.activeSkin().fieldPadding)

    def _endPadding(self) -> int:
        """Blank kept at the top and bottom of the content.

        One focus-glow margin: the ring is drawn outside the widget, so the
        first and last rows of a scrolling list would otherwise have theirs cut
        off by the scissor with nowhere left to scroll.
        """
        return int(self.activeSkin().focusMargin)

    # -- placement --------------------------------------------------------
    def viewRect(self) -> Rect:
        """The part that shows content, with the bar's width taken off."""
        if not self.needsBar:
            return self.rect
        return Rect(self.rect.x, self.rect.y,
                    max(0, self.rect.width - self._barGutter()), self.rect.height)

    def arrange_content(self, metrics: FontMetrics) -> None:
        children = self.layoutChildren()
        self.lineHeight = metrics.line_height
        if not children:
            self.contentHeight = 0
            return
        # Measured **once**, against the width the content will have if a bar
        # is needed.  Whether one is needed depends on the height, and the
        # height depends on the width, so the narrower of the two is the one
        # that settles: it can only over-estimate, and over-estimating shows a
        # bar that scrolls a little rather than clipping content away.
        # Measuring twice would re-wrap every paragraph on the page for
        # nothing, and against two different widths at that.
        pad = self._endPadding()
        width = max(0, self.rect.width - self._barGutter())
        sizes = [int(child.natural_size(metrics, width)[1])
                 for child in children]
        self.contentHeight = pad * 2 + sum(sizes)
        self.scroll = self._clamp(float(self.scroll))
        view = self.viewRect()
        cursor = view.top - pad + int(self.scroll)
        for child, height in zip(children, sizes, strict=True):
            child.parent = self
            child.arrange(Rect(view.x, cursor - height, view.width, height),
                          metrics)
            cursor -= height

    # -- the scroll range --------------------------------------------------
    @property
    def maximumScroll(self) -> int:
        """How far it can scroll: the content's overhang, or 0."""
        return max(0, self.contentHeight - self.rect.height)

    @property
    def needsBar(self) -> bool:
        """Whether a bar is drawn -- only when there is something to scroll."""
        return bool(self.showBar and self.maximumScroll > 0)

    def _clamp(self, value: float) -> float:
        return max(0.0, min(float(self.maximumScroll), value))

    def scrollTo(self, value: float) -> bool:
        """Move to an absolute offset; True if it actually moved."""
        clamped = self._clamp(value)
        if clamped == self.scroll:
            return False
        moved = clamped - self.scroll
        self.scroll = clamped
        for child in self.layoutChildren():
            _offsetTree(child, 0, int(moved))
        return True

    def scrollBy(self, amount: float) -> bool:
        """Move by a relative amount; True if it actually moved."""
        return self.scrollTo(float(self.scroll) + amount)

    def reveal(self, rect: Rect) -> None:
        """Scroll the least that brings a rectangle fully into view."""
        view = self.viewRect()
        if rect.top > view.top:
            self.scrollBy(-(rect.top - view.top))
        elif rect.y < view.y:
            self.scrollBy(view.y - rect.y)

    # -- the bar ----------------------------------------------------------
    def barRect(self) -> Rect:
        """The scrollbar's track, down the right-hand edge."""
        return Rect(self.rect.right - self._barWidth(), self.rect.y,
                    self._barWidth(), self.rect.height)

    def thumbRect(self) -> Rect:
        """The thumb, sized to the fraction of the content on screen."""
        bar = self.barRect()
        if not self.contentHeight or not self.needsBar:
            return bar
        fraction = min(1.0, self.rect.height / float(self.contentHeight))
        height = max(int(self._barWidth()), int(bar.height * fraction))
        travel = bar.height - height
        offset = int(travel * (float(self.scroll) / self.maximumScroll)) \
            if self.maximumScroll else 0
        return Rect(bar.x, bar.top - height - offset, bar.width, height)

    # -- input -------------------------------------------------------------
    def widget_at(self, x: float, y: float) -> Optional[Widget]:
        """Nothing outside the viewport is hittable, however it was laid out."""
        if not self.visible or not self.rect.contains(x, y):
            return None
        if self.needsBar and self.barRect().contains(x, y):
            return self
        for child in reversed(list(self.layoutChildren())):
            found: Optional[Widget] = child.widget_at(x, y)
            if found is not None and self.viewRect().intersects(found.rect):
                return found
        return self if self.maximumScroll else None

    def press(self, x: float, y: float) -> bool:
        if not self.enabled:
            return False
        self.armed = True
        bar = self.barRect()
        if not (self.needsBar and bar.contains(x, y)):
            self._thumbGrab = None
            return True
        thumb = self.thumbRect()
        if thumb.contains(x, y):
            self._thumbGrab = int(thumb.top - y)
            return True
        # A click on the track pages toward the click, which is what a bar
        # does everywhere else.
        self._thumbGrab = None
        self.scrollBy(self.rect.height if y < thumb.y else -self.rect.height)
        return True

    def drag(self, x: float, y: float) -> None:
        if self._thumbGrab is None:
            return
        bar = self.barRect()
        thumb = self.thumbRect()
        travel = bar.height - thumb.height
        if travel <= 0:
            return
        top = y + self._thumbGrab
        self.scrollTo(self.maximumScroll * (bar.top - top) / float(travel))

    def release(self, x: float, y: float) -> bool:
        was, self.armed = self.armed, False
        self._thumbGrab = None
        return was

    def wheel(self, delta: int, x: float, y: float) -> bool:
        """A notch of the wheel.  False when it changed nothing.

        Not claiming a notch it could not use is what lets a wheel over a page
        that is already at its end reach whatever else might want it.
        """
        if not delta:
            return False
        return self.scrollBy(-delta * WHEEL_LINES * self.lineHeight)

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        # A page keeps one line of what was on screen, so the eye has
        # something to land on rather than starting again from nothing.
        page = max(1, self.rect.height - self.lineHeight)
        if name == '<pagedown>':
            return self.scrollBy(page) or True
        if name == '<pageup>':
            return self.scrollBy(-page) or True
        if name == '<home>':
            return self.scrollTo(0) or True
        if name == '<end>':
            return self.scrollTo(self.maximumScroll) or True
        if name == '<down>':
            return self.scrollBy(self.lineHeight) or True
        if name == '<up>':
            return self.scrollBy(-self.lineHeight) or True
        return False

    # -- drawing ----------------------------------------------------------
    def paint(self, renderer: Any) -> None:
        if not self.needsBar:
            return
        skin = renderer.skin
        renderer.frame(self.barRect(), skin.trackFill,
                       skin.trackImage)
        renderer.frame(self.thumbRect(),
                       skin.buttonHoverFill if self.hovered else skin.thumbFill,
                       skin.thumbImage)

    def paintChildren(self, renderer: Any) -> None:
        """Draw the content clipped to the viewport."""
        previous = renderer.pushScissor(self.viewRect())
        try:
            for child in self.layoutChildren():
                child.paintTree(renderer)
        finally:
            renderer.popScissor(previous)


def _offsetTree(widget: Any, dx: int, dy: int) -> None:
    """Move a laid-out subtree without measuring it again.

    Scrolling changes only where things are, so re-running layout for it would
    be work for nothing -- and would re-wrap every paragraph on every notch of
    the wheel.
    """
    widget.rect = widget.rect.offset(dx, dy)
    for child in widget.layoutChildren():
        _offsetTree(child, dx, dy)
