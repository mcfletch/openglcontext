"""Screen-space layout for overlay GUI nodes.

This is the layout half of a widget: how big it wants to be, how much of the
space left over it claims, and the margin around it.  The drawing half, the
input half and the concrete widgets are in :mod:`OpenGLContext.ui`; keeping the
geometry here means a container can lay out anything that answers these
questions, widget or not.

Sizes are **pixels**, and the origin is the bottom-left of the window -- the
same origin a mouse event's pick point arrives in.  A :class:`GUINode` reports
a natural size, a container hands it a rectangle, and that is the whole
protocol; there is no constraint solver and no second pass.

    ``width``/``height``  an explicit size in pixels; 0 means "measure me"
    ``flex``              share of the leftover main-axis space; 0 means fixed
    ``left``/``right``/``top``/``bottom``   margin outside the widget
    ``maximumWidth``      a ceiling on the width, whatever is offered; 0 for none
    ``alignSelf``         where to sit when narrower than what was offered

Pixel sizes here are **pixels at the reference font size** and are multiplied
by the interface scale, exactly as the skin's are -- see
:mod:`OpenGLContext.ui.metrics`.
"""

from typing import Any, Iterator, List, Optional, Sequence, Tuple

from vrml import field, node

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import REFERENCE_METRICS, FontMetrics

#: Main-axis directions a :class:`GUIBox` understands.
ROW = 'row'
COLUMN = 'column'


def distribute(children: Sequence[Any], mains: List[int], spare: int) -> List[int]:
    """Share out (or claw back) main-axis space among the flexible children.

    Space left over goes to the children that asked for it, in proportion to
    their ``flex``.  A **shortfall** comes out of the same children, clamped so
    none goes negative: a flexible child is the one that volunteered to be
    whatever size is left, which includes being smaller.  Fixed children are
    never squeezed -- a box too small for them overflows instead, because the
    overflow is visible while a crushed layout silently lies.

    ``mains`` is read, never written: the answer comes back as a new list, so a
    caller that keeps the sizes it measured still has them.
    """
    total_flex = sum(float(child.flex) for child in children)
    if not spare or total_flex <= 0:
        return list(mains)
    mains = list(mains)
    claimants = [index for index, child in enumerate(children) if child.flex]
    given = 0
    for position, index in enumerate(claimants):
        if position == len(claimants) - 1:
            share = spare - given           # the last one absorbs rounding
        else:
            share = int(spare * float(children[index].flex) / total_flex)
        mains[index] = max(0, mains[index] + share)
        given += share
    return mains


class GUINode(object):
    """Mix-in giving a node a natural size and a rectangle on screen."""

    #: Share of the leftover main-axis space this claims; 0 keeps it at its
    #: natural size.
    flex = field.newField("flex", "SFFloat", 1, 0.0)
    #: Explicit size in pixels; 0 means measure the content instead.
    width = field.newField("width", "SFFloat", 1, 0.0)
    height = field.newField("height", "SFFloat", 1, 0.0)
    #: Margin outside the widget, in pixels.
    left = field.newField("left", "SFFloat", 1, 0.0)
    right = field.newField("right", "SFFloat", 1, 0.0)
    top = field.newField("top", "SFFloat", 1, 0.0)
    bottom = field.newField("bottom", "SFFloat", 1, 0.0)
    #: A ceiling on how wide this may be drawn, whatever rectangle it is given;
    #: 0 for none.  What stops a slider running the width of a 4K display when
    #: the column it is in happens to be that wide.
    maximumWidth = field.newField("maximumWidth", "SFFloat", 1, 0.0)
    #: Where to sit inside the rectangle when narrower than it: ``stretch``
    #: (the default, take it all), ``start``, ``center`` or ``end``.  Anything
    #: but ``stretch`` also shrinks the widget to its measured width, which is
    #: how a switch ends up against the right margin instead of adrift in the
    #: middle of a wide column.
    alignSelf = field.newField("alignSelf", "SFString", 1, "stretch")

    #: Where this ended up, set by :meth:`arrange`.  Empty until then, so a
    #: click that arrives before the first layout hits nothing rather than
    #: guessing.
    rect = Rect(0, 0, 0, 0)
    #: The container this is inside, set when it is arranged.
    parent: Any = None
    #: The measurements :attr:`rect` was made from, kept by :meth:`arrange`.
    _metrics: Optional[FontMetrics] = None
    #: Whether this reports a different height for a different width -- text
    #: that wraps.  A row measures those a second time once it knows what
    #: width each child ended up with; everything else is measured once.
    wrapsToWidth: bool = False

    @property
    def metrics(self) -> FontMetrics:
        """The measurements this was last laid out with.

        Geometry derived from :attr:`rect` -- a slider's track, a text field's
        caret column -- has to use the same numbers the rectangle was made
        from.  Threading them back in through every caller is how the two come
        apart: one path passes them, another does not, and the widget then
        responds to the pointer somewhere other than where it drew itself.
        """
        return REFERENCE_METRICS if self._metrics is None else self._metrics

    # -- measurement ------------------------------------------------------
    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        """Size of what is inside, ignoring margins.  Overridden by widgets.

        ``available`` is the width the caller can offer, or None when it does
        not know yet.  It is what lets wrapped text report the height it will
        actually need instead of one very long line.
        """
        return (0, 0)

    def natural_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        """Size this asks for, including its margins.

        An explicit ``width``/``height`` wins over the measurement, which is
        how a game pins a column of controls to one width so their labels line
        up instead of stepping in and out with the text in them.
        """
        margin_x = metrics.pixels(self.left) + metrics.pixels(self.right)
        margin_y = metrics.pixels(self.top) + metrics.pixels(self.bottom)
        inner = None if available is None else max(0, int(available) - margin_x)
        content_w, content_h = self.content_size(metrics, inner)
        if self.width:
            content_w = int(self.width)
        if self.height:
            content_h = int(self.height)
        return (int(content_w) + margin_x, int(content_h) + margin_y)

    def natural_width(self, metrics: FontMetrics,
                      available: Optional[int] = None) -> int:
        """The width this asks for, margins included."""
        return self.natural_size(metrics, available)[0]

    def natural_height(self, metrics: FontMetrics,
                       available: Optional[int] = None) -> int:
        """The height this asks for, margins included."""
        return self.natural_size(metrics, available)[1]

    # -- placement --------------------------------------------------------
    def arrange(self, rect: Rect, metrics: FontMetrics) -> None:
        """Take a rectangle, keep the part inside the margins, fill it in."""
        self._metrics = metrics
        self.rect = self._fitWidth(
            rect.inset(metrics.pixels(self.left), metrics.pixels(self.top),
                       metrics.pixels(self.right), metrics.pixels(self.bottom)),
            metrics)
        self.arrange_content(metrics)

    def _fitWidth(self, rect: Rect, metrics: FontMetrics) -> Rect:
        """Narrow a rectangle to the cap and the alignment, if either asks.

        Only ever narrower: a widget is offered a rectangle by its container
        and may decline part of it, but taking more would draw over a sibling.
        """
        align = str(self.alignSelf)
        limit = int(self.maximumWidth)
        if align == 'stretch' and not limit:
            return rect
        width = rect.width
        if align != 'stretch':
            content = int(self.width) or int(
                self.content_size(metrics, rect.width)[0])
            width = min(width, content)
        if limit:
            width = min(width, metrics.pixels(limit))
        if width >= rect.width:
            return rect
        if align == 'end':
            return Rect(rect.right - width, rect.y, width, rect.height)
        if align == 'center':
            return Rect(rect.x + (rect.width - width) // 2, rect.y, width,
                        rect.height)
        return Rect(rect.x, rect.y, width, rect.height)

    def arrange_content(self, metrics: FontMetrics) -> None:
        """Place whatever is inside :attr:`rect`.  Overridden by containers."""

    # -- the tree ---------------------------------------------------------
    def layoutChildren(self) -> Sequence[Any]:
        """Children that take part in layout, in drawing order.

        Typed loosely because the protocol is what matters: a container lays
        out anything that reports a natural size and takes a rectangle, widget
        or not.
        """
        return ()

    def walk(self) -> Iterator['GUINode']:
        """This node and every descendant, parents before children."""
        yield self
        for child in self.layoutChildren():
            yield from child.walk()

    def root(self) -> 'GUINode':
        """The outermost node of this tree -- normally the panel."""
        current: GUINode = self
        while current.parent is not None:
            current = current.parent
        return current


class GUISpacer(GUINode, node.Node):
    """Blank space.  Flexible by default, which is what pushes a row apart."""

    PROTO = "GUISpacer"
    flex = field.newField("flex", "SFFloat", 1, 1.0)


class PaintedImage(GUINode, node.Node):
    """An image laid out at its own pixel size."""

    PROTO = "PaintedImage"
    image = field.newField("image", "SFImage", 1, None)

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        if self.image is not None:
            return (int(self.image.width), int(self.image.height))
        return (0, 0)


class GUIBox(GUINode, node.Node):
    """Children in a line, along ``direction``, sharing the leftover space.

    One pass: fixed children take their natural size, ``flex`` children divide
    what is left in proportion to their flex.  ``flexJustify`` says what to do
    when there is space left over and nothing flexible to absorb it, and
    ``align`` places each child across the other axis.
    """

    PROTO = "GUIBox"
    children = field.newField("children", "MFNode", 1, list)
    #: ``row`` or ``column``.  A column stacks downward from the top, because
    #: that is the order the text in it reads.
    direction = field.newField("direction", "SFString", 1, ROW)
    #: Pixels between one child and the next.
    spacing = field.newField("spacing", "SFFloat", 1, 0.0)
    #: Pixels between the box's edge and its children.
    padding = field.newField("padding", "SFFloat", 1, 0.0)
    #: ``start``, ``end``, ``center``, ``stretch`` or ``space-between``:
    #: what to do with main-axis space no child claimed.
    flexJustify = field.newField("flexJustify", "SFString", 1, "start")
    #: ``start``, ``end``, ``center`` or ``stretch``: how a child is placed
    #: across the other axis.
    align = field.newField("align", "SFString", 1, "stretch")

    @property
    def horizontal(self) -> bool:
        """Whether children run left to right rather than top to bottom."""
        return bool(self.direction != COLUMN)

    def layoutChildren(self) -> Sequence[Any]:
        return [child for child in self.children
                if getattr(child, 'visible', True)]

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        children = self.layoutChildren()
        sizes = [child.natural_size(metrics,
                                    self._childAvailable(available, metrics))
                 for child in children]
        gaps = metrics.pixels(self.spacing) * max(0, len(children) - 1)
        pad = metrics.pixels(self.padding) * 2
        if self.horizontal and available is not None:
            # Same two passes as arranging, so a row reports a height that
            # accounts for its wrapped text rather than for one long line.
            room = max(0, int(available) - pad - gaps)
            mains = self._distribute(
                children, sizes, room - sum(size[0] for size in sizes))
            sizes, _mains = self._remeasure(children, sizes, mains, metrics,
                                            room)
        if self.horizontal:
            main = sum(size[0] for size in sizes) + gaps
            cross = max([size[1] for size in sizes], default=0)
        else:
            main = sum(size[1] for size in sizes) + gaps
            cross = max([size[0] for size in sizes], default=0)
        if self.horizontal:
            return (main + pad, cross + pad)
        return (cross + pad, main + pad)

    def _childAvailable(self, available: Optional[int],
                        metrics: FontMetrics) -> Optional[int]:
        """The width a child may measure against, for the *first* pass.

        A column hands its own width straight down.  A row cannot, because its
        children have not yet been given their shares of it -- so a row
        measures once to settle the shares and then asks anything whose height
        depends on its width again, against the width it actually got.  See
        :meth:`_remeasure`.
        """
        if available is None or self.horizontal:
            return None
        return max(0, int(available) - int(metrics.pixels(self.padding)) * 2)

    @staticmethod
    def _remeasure(children: Sequence[Any], sizes: List[Tuple[int, int]],
                   mains: List[int], metrics: FontMetrics, room: int
                   ) -> Tuple[List[Tuple[int, int]], List[int]]:
        """Second pass along a row, for children whose height follows a width.

        Two things happen, and only to the children that say they wrap.  Each
        is held to the room its siblings left it -- text that wraps has no
        natural width worth the name, only a longest line -- and is then asked
        again for the height it needs at that width.

        Everything else is left alone: it already measured against the width it
        was going to get, and asking twice would be a second text-wrapping pass
        over every label on the page.
        """
        settled = list(sizes)
        widths = list(mains)
        for index, child in enumerate(children):
            if not getattr(child, 'wrapsToWidth', False):
                continue
            others = sum(widths) - widths[index]
            widths[index] = max(0, min(widths[index], room - others))
            settled[index] = child.natural_size(metrics, widths[index])
        return (settled, widths)

    def arrange_content(self, metrics: FontMetrics) -> None:
        children = self.layoutChildren()
        for child in children:
            child.parent = self
        if not children:
            return
        inner = self.rect.inset(metrics.pixels(self.padding))
        available = None if self.horizontal else inner.width
        sizes = [child.natural_size(metrics, available) for child in children]
        spacing = metrics.pixels(self.spacing)
        available = (inner.width if self.horizontal else inner.height)
        used = sum((size[0] if self.horizontal else size[1]) for size in sizes)
        used += spacing * (len(children) - 1)
        mains = self._distribute(children, sizes, available - used)
        if self.horizontal:
            # The shares are settled, so anything whose height follows its
            # width can now be held to the room left and asked again.
            sizes, mains = self._remeasure(
                children, sizes, mains, metrics,
                available - spacing * (len(children) - 1))
        offset, gap = self._justify(available - sum(mains)
                                    - spacing * (len(children) - 1),
                                    len(children))
        cursor = offset
        for child, size, main in zip(children, sizes, mains, strict=True):
            child.arrange(self._childRect(inner, cursor, main, size), metrics)
            cursor += main + spacing + gap

    def _distribute(self, children: Sequence[GUINode],
                    sizes: Sequence[Tuple[int, int]], spare: int) -> List[int]:
        """Main-axis size for each child: natural, plus its share of ``spare``."""
        mains = [int(size[0] if self.horizontal else size[1]) for size in sizes]
        return distribute(children, mains, spare)

    def _justify(self, spare: int, count: int) -> Tuple[int, int]:
        """Where the run of children starts, and any gap added between them."""
        if spare <= 0:
            return (0, 0)
        justify = self.flexJustify
        if justify == 'end':
            return (spare, 0)
        if justify == 'center':
            return (spare // 2, 0)
        if justify == 'space-between' and count > 1:
            return (0, spare // (count - 1))
        return (0, 0)

    def _childRect(self, inner: Rect, cursor: int, main: int,
                   size: Tuple[int, int]) -> Rect:
        """One child's rectangle, from its main-axis run and the cross axis."""
        if self.horizontal:
            cross, extent = self._cross(inner.height, size[1])
            return Rect(inner.x + cursor, inner.y + cross, main, extent)
        # A column reads downward, so the first child sits at the top.
        cross, extent = self._cross(inner.width, size[0])
        return Rect(inner.x + cross, inner.top - cursor - main, extent, main)

    def _cross(self, available: int, natural: int) -> Tuple[int, int]:
        """Offset and size across the axis the box does not run along."""
        align = self.align
        if align == 'stretch':
            return (0, available)
        extent = min(natural, available)
        if align == 'center':
            return ((available - extent) // 2, extent)
        if align == 'end':
            return (available - extent, extent)
        return (0, extent)
