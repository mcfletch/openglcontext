"""Choosing one of several things by looking at them.

A drop-down is the right control for a *setting* and the wrong one for a level.
What tells one arena from another is what it looks like, and a list of names
makes a player open each in turn to find out which is which — so
:class:`Carousel` shows a band of pictures with their names underneath, and the
arrows roll it along.

Two widgets, and the smaller one is useful on its own:

:class:`Picture`
    One image in a rectangle, letterboxed to keep its proportions rather than
    stretched — a level shot squeezed into a square slot reads as a bad
    screenshot rather than as a small one.
:class:`Carousel`
    A band of them, one selected, rolled by two arrows, the keyboard or a
    click on any picture you can already see.

**The band is centred on the selection and wraps.** Centred because the point
of showing several is to see what is either side of your choice; wrapping
because a band that stops dead at the last item makes the last item hard to
reach from the first, which is the one journey a player repeats.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from vrml import field

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.widgets import BoundWidget, Widget

log = logging.getLogger(__name__)

__all__ = ['Carousel', 'Item', 'Picture']

#: What a picture's width is to its height when nothing says otherwise.  A
#: level shot is a screenshot, and a screenshot is a landscape.
DEFAULT_ASPECT = 4.0 / 3.0

#: How wide a picture asks to be, in characters.  Characters rather than
#: pixels so a picture grows with the player's interface scale exactly as the
#: text beside it does.
PICTURE_COLUMNS = 16

#: How wide an arrow is, in characters.
ARROW_COLUMNS = 3

#: Space between two pictures in a band, in characters.
SLOT_GAP = 1


@dataclass(frozen=True)
class Item:
    """One thing in a band: what it is, what it is called, what it looks like."""

    option: str
    label: str
    image: str
    selected: bool


class Picture(Widget):
    """One image, letterboxed into whatever rectangle it is given.

    Letterboxed rather than stretched: a screenshot squeezed into the wrong
    proportions reads as a *bad* screenshot rather than as a small one, and the
    whole reason to show art is that a player judges a level by it.

    An image that cannot be read leaves the frame empty rather than taking the
    screen down — a level with no art is a normal thing.
    """

    PROTO = 'UIPicture'
    #: Where the image is: a filesystem path or a ``file:`` URL.
    url = field.newField('url', 'SFString', 1, '')
    #: Width over height, for asking for room before the image is loaded.
    aspect = field.newField('aspect', 'SFFloat', 1, DEFAULT_ASPECT)

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        width = metrics.char_width * PICTURE_COLUMNS
        return (width, max(1, int(width / max(float(self.aspect), 0.1))))

    def paint(self, renderer: Any) -> None:
        paint_image(renderer, self.rect, self.url)


def image_rect(renderer: Any, rect: Rect, url: str) -> Optional[Rect]:
    """Where an image would actually be drawn inside ``rect``, or None.

    Wanted separately from drawing it because a highlight has to go *behind*
    the picture and hug it: a plate the size of the slot reads as a column,
    and the picture is letterboxed somewhere inside that.
    """
    found = renderer.imageTexture(url, blocking=False) if url else None
    if found is None:
        return None
    _texture, width, height = found
    return _letterboxed(rect, width / max(height, 1))


def paint_image(renderer: Any, rect: Rect, url: str,
                fallback: Any = None) -> bool:
    """Draw an image inside ``rect``, keeping its proportions.

    Shared by :class:`Picture` and :class:`Carousel` rather than living on
    either, because a band draws its own pictures directly: one widget per
    visible item would mean building and throwing away a subtree every time an
    arrow was pressed.

    Returns whether an image was drawn.  When none was, ``fallback`` is filled
    instead if it is given, so an empty slot is a plate rather than a hole --
    which is also what a picture still being decoded looks like, since a gallery
    asks without waiting and the plate becomes the picture a frame or two later.
    """
    found = renderer.imageTexture(url, blocking=False) if url else None
    if found is None:
        if fallback is not None:
            renderer.rect(rect, fallback)
        return False
    texture, width, height = found
    renderer.quad(_letterboxed(rect, width / max(height, 1)), (1, 1, 1, 1),
                  texture=texture)
    return True


#: How far the selection plate stands out past the picture it marks, in pixels.
SELECTION_INSET = 3.0


def _grown(rect: Rect, by: float) -> Rect:
    """A rectangle enlarged on every side."""
    return Rect(rect.x - by, rect.y - by, rect.width + by * 2,
                rect.height + by * 2)


def _letterboxed(rect: Rect, aspect: float) -> Rect:
    """The largest rectangle of ``aspect`` that fits inside ``rect``, centred."""
    if rect.width <= 0 or rect.height <= 0 or aspect <= 0:
        return rect
    width = min(rect.width, rect.height * aspect)
    height = width / aspect
    return Rect(rect.x + (rect.width - width) / 2.0,
                rect.y + (rect.height - height) / 2.0, width, height)


class Carousel(BoundWidget):
    """A band of pictures, one of them chosen.

    The value is the chosen option, exactly as :class:`~.widgets.Select`'s is,
    so the two are interchangeable where a screen decides that a list of names
    would do after all.
    """

    PROTO = 'UICarousel'
    #: The values, as they are stored in the bound field.
    options = field.newField('options', 'MFString', 1, list)
    #: What to show under each; falls back to the option itself.
    optionLabels = field.newField('optionLabels', 'MFString', 1, list)
    #: Where each option's picture is; empty for one with no art.
    optionImages = field.newField('optionImages', 'MFString', 1, list)
    value = field.newField('value', 'SFString', 1, '')
    #: How many are on screen at once.  Odd, so there is a middle for the
    #: selection to sit in.
    visibleCount = field.newField('visibleCount', 'SFInt32', 1, 5)

    interactive = True
    focusable = True

    #: What the pointer went down on, so the release acts on the same thing:
    #: -1 and 1 for the arrows, an option for a picture, None for nothing.
    _pressed: Any = None

    def __init__(self, **named: Any) -> None:
        super(Carousel, self).__init__(**named)
        options = list(self.options)
        if options and self.read() not in options:
            # A value nobody offers is settled *now* rather than being resolved
            # on every read: a remembered level that has since been deleted
            # would otherwise report itself as still chosen while showing the
            # first one, and whoever asked would start the wrong map.
            self.write(options[0])

    # -- what is chosen ---------------------------------------------------
    @property
    def index(self) -> int:
        """Where the current value sits in ``options``.

        A value that is not one of them reads as the first: a remembered level
        that has since been deleted should show *something*, and the first is
        what the screen was authored to default to.
        """
        try:
            return list(self.options).index(self.read())
        except ValueError:
            return 0

    def label_for(self, index: int) -> str:
        labels = list(self.optionLabels)
        if index < len(labels):
            return str(labels[index])
        options = list(self.options)
        return str(options[index]) if index < len(options) else ''

    def image_for(self, index: int) -> str:
        images = list(self.optionImages)
        return str(images[index]) if index < len(images) else ''

    def visible(self) -> List[Item]:
        """The band as it is shown: the selection in the middle, wrapping.

        Wrapping so a band of five over a list of fifty always shows five —
        a band that ran short at the ends would shift the selection out of the
        middle just as a player reached the part of the list they were heading
        for.
        """
        options = list(self.options)
        if not options:
            return []
        span = min(max(1, int(self.visibleCount)), len(options))
        first = self.index - span // 2
        return [self._item(options, (first + offset) % len(options))
                for offset in range(span)]

    def _item(self, options: List[str], index: int) -> Item:
        return Item(option=str(options[index]), label=self.label_for(index),
                    image=self.image_for(index), selected=index == self.index)

    # -- moving -----------------------------------------------------------
    def step(self, direction: int) -> bool:
        """Move by one, wrapping at either end."""
        options = list(self.options)
        if not options:
            return False
        return self.write(options[(self.index + direction) % len(options)])

    def next(self) -> bool:
        return self.step(1)

    def previous(self) -> bool:
        return self.step(-1)

    def select(self, option: str) -> bool:
        """Choose a named option; False if there is no such thing."""
        if option not in list(self.options):
            return False
        return self.write(option)

    # -- where everything lands -------------------------------------------
    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        span = min(max(1, int(self.visibleCount)), max(1, len(self.options)))
        slot = metrics.char_width * PICTURE_COLUMNS
        arrows = metrics.char_width * ARROW_COLUMNS * 2
        gaps = metrics.char_width * SLOT_GAP * (span - 1)
        picture = int(slot / DEFAULT_ASPECT)
        # The caption sits under the picture, and gets a line of its own plus
        # the gap that separates it, so a name never crowds the art.
        # Two text lines under the art: the cut name on each tile, and the
        # chosen one's full name across the band.
        return (arrows + slot * span + gaps,
                picture + (metrics.char_height + metrics.line_gap) * 2)

    def arrowRects(self) -> Tuple[Rect, Rect]:
        """The two arrows, at either end of the band."""
        width = min(self.rect.width / 2.0, max(1.0, self.rect.height / 3.0))
        return (Rect(self.rect.x, self.rect.y, width, self.rect.height),
                Rect(self.rect.right - width, self.rect.y, width,
                     self.rect.height))

    def slotRects(self, metrics: FontMetrics) -> List[Rect]:
        """Where each visible item goes, left to right, between the arrows."""
        items = self.visible()
        if not items:
            return []
        # Remembered, so a click can be resolved against the same layout the
        # player is looking at without the caller passing metrics twice.
        self._metrics = metrics
        left, right = self.arrowRects()
        room = max(0.0, right.x - left.right)
        gap = metrics.char_width * SLOT_GAP
        width = max(0.0, (room - gap * (len(items) - 1)) / len(items))
        return [Rect(left.right + (width + gap) * index, self.rect.y,
                     width, self.rect.height)
                for index in range(len(items))]

    def captionRect(self, slot: Rect, metrics: FontMetrics) -> Rect:
        """The strip under one picture where its (cut) name goes.

        Above the chosen-name line, which has the band's whole width.
        """
        return Rect(slot.x, slot.y + metrics.char_height + metrics.line_gap,
                    slot.width, metrics.char_height)

    def pictureRect(self, slot: Rect, metrics: FontMetrics) -> Rect:
        """The part of a slot the art occupies: above both caption lines."""
        used = (metrics.char_height + metrics.line_gap) * 2
        return Rect(slot.x, slot.y + used, slot.width,
                    max(0.0, slot.height - used))

    # -- input -------------------------------------------------------------
    def press(self, x: float, y: float) -> bool:
        if not super(Carousel, self).press(x, y):
            self._pressed = None
            return False
        left, right = self.arrowRects()
        if left.contains(x, y):
            self._pressed = -1
        elif right.contains(x, y):
            self._pressed = 1
        else:
            self._pressed = self._optionAt(x, y)
        return True

    def release(self, x: float, y: float) -> bool:
        armed, self.armed = self.armed, False
        pressed, self._pressed = self._pressed, None
        if not (armed and self.enabled and self.rect.contains(x, y)):
            return False
        if pressed in (-1, 1):
            # An arrow *looks*; it does not choose.  A caller that opens what
            # was chosen -- which is what a band of pictures is for -- would
            # otherwise open something every time somebody pressed an arrow to
            # see the next one.  ``step`` still reports the value moving, so
            # anything following the selection keeps up.
            self.step(pressed)
            return True
        if isinstance(pressed, str):
            # Clicking a picture you can already see is faster than arrowing
            # to it, and is what a band of pictures invites.
            self.select(pressed)
        self.activate()
        return True

    def _optionAt(self, x: float, y: float) -> Optional[str]:
        """Which visible option is under a point, if any."""
        metrics = self._metrics
        if metrics is None:
            return None
        for slot, item in zip(self.slotRects(metrics), self.visible(),
                              strict=False):
            if slot.contains(x, y):
                return item.option
        return None

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name in ('<right>', '<down>'):
            self.step(1)
            return True
        if name in ('<left>', '<up>'):
            self.step(-1)
            return True
        return False

    def wheel(self, delta: int, x: float, y: float) -> bool:
        if delta and self.wheelAdjusts():
            self.step(1 if delta > 0 else -1)
            return True
        return False

    #: The metrics the band was last drawn with, so a click can be resolved
    #: against the same layout the player is looking at.  Not a field: it is
    #: the state of one frame, not something to save.
    _metrics: Optional[FontMetrics] = None

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        metrics = renderer.metrics
        self._metrics = metrics
        renderer.frame(self.rect, skin.fieldFill, skin.fieldImage)
        items = self.visible()
        for slot, item in zip(self.slotRects(metrics), items, strict=False):
            self._paintItem(renderer, slot, item, metrics)
        self._paintArrows(renderer, skin)
        self._paintChosen(renderer, skin, metrics, items)

    def _paintItem(self, renderer: Any, slot: Rect, item: Item,
                   metrics: FontMetrics) -> None:
        """One picture and its name, marked if it is the chosen one."""
        skin = renderer.skin
        picture = self.pictureRect(slot, metrics)
        if item.selected:
            # A plate *behind the picture and hugging it*: a border on a
            # photograph is hard to see against whatever the photograph happens
            # to be, and a plate the size of the slot reads as a column rather
            # than as a highlight, since the art is letterboxed inside it.
            drawn = image_rect(renderer, picture, item.image) or picture
            renderer.rect(_grown(drawn, SELECTION_INSET), skin.focusGlow)
        paint_image(renderer, picture, item.image, fallback=skin.panelFill)
        renderer.textIn(self.captionRect(slot, metrics),
                        # Cut to the slot rather than overflowing: five
                        # overlapping level names are less readable than five
                        # shortened ones.
                        metrics.truncate(item.label, int(slot.width)),
                        skin.titleText if item.selected else skin.labelText,
                        align='center')

    def _paintChosen(self, renderer: Any, skin: Any, metrics: FontMetrics,
                     items: List[Item]) -> None:
        """The chosen item's name in full, across the whole band.

        A tile is too narrow for a name of any length, so the captions under
        the pictures are cut and this is where the answer to "what is that one
        called" actually lives.  It has the width of the band to itself.
        """
        chosen = [item for item in items if item.selected]
        if not chosen:
            return
        line = Rect(self.rect.x, self.rect.y, self.rect.width,
                    metrics.char_height)
        renderer.textIn(line, metrics.truncate(chosen[0].label,
                                               int(self.rect.width)),
                        skin.titleText, align='center')

    def _paintArrows(self, renderer: Any, skin: Any) -> None:
        left, right = self.arrowRects()
        colour = skin.labelText if self.enabled else skin.disabledText
        renderer.textIn(left, '<', colour, align='center')
        renderer.textIn(right, '>', colour, align='center')
