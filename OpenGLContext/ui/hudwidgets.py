"""Screen furniture drawn over a live world: reticule, meters, messages.

**A HUD is not an overlay panel.**  The overlay stack in
:mod:`OpenGLContext.ui.overlay` is modal -- while a panel is up, nothing under
it hears anything -- which is right for a settings screen and wrong for a
health bar.  So a HUD is a :class:`HUDLayer`: a tree of widgets laid out over
the whole viewport, drawn *under* the overlay stack through the same batched
renderer, and never offered a single event.  Nothing in one is interactive,
nothing in one takes focus, and a click passes straight through it to the
world.

**Placement is by anchor, not by flow.**  Health goes in one corner, ammunition
in another and the reticule in the middle, and no row-and-column arithmetic
describes that as well as naming the corner does.  So each child carries an
``anchor`` and an ``offset`` and :func:`place` puts it there; a child with no
anchor -- an ordinary :class:`~OpenGLContext.ui.layout.Column`, say -- is given
the whole layer and lays itself out as it always would.

Sizes here are **pixels at the reference font size** and are multiplied by the
interface scale, exactly as the skin's are, so a reticule authored on a 1080p
display is the same size in the eye on a 4K one.  See
:mod:`OpenGLContext.ui.metrics`.

What the widgets are for:

* :class:`Crosshair` -- the aiming reticule.  Its shape, gap, arm length and
  thickness are fields, so **a weapon names its own reticule** rather than the
  game having one; ``spread`` widens the gap, which is how a weapon whose
  accuracy falls off while firing shows it.
* :class:`BarMeter` -- health, armour, a charge.  Its colour comes from where
  the value sits against two thresholds, because a player reads a state and not
  a number.
* :class:`Readout` -- an icon and a number: ammunition, a count, a timer.
* :class:`MessageQueue` -- pickups, frags and warnings, newest first, each
  fading out on its own clock.

Everything here is arithmetic over a viewport and a font, so a HUD's layout is
testable with no window at all: hand a layer a viewport and read the
rectangles back.
"""

from __future__ import annotations

import time
from typing import Any, List, Optional, Sequence, Tuple

from vrml import field, node

from OpenGLContext.hud import COLUMN, GUIBox
from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.widgets import RootWidget, Widget

__all__ = [
    'HUDLayer', 'HUDWidget', 'HUDGroup', 'Crosshair', 'BarMeter', 'Readout',
    'Message', 'MessageQueue', 'place', 'hud_text',
    'CROSS', 'DOT', 'CROSS_DOT', 'CIRCLE', 'NONE', 'ANCHORS',
]

#: Reticule shapes.  ``cross`` is four arms around a gap, ``dot`` a single
#: square, ``cross-dot`` both, ``circle`` four arcs, ``none`` nothing at all --
#: which is a real choice, not an omission: some weapons aim down their own
#: sights and some players want the middle of the screen clear.
CROSS, DOT, CROSS_DOT, CIRCLE, NONE = 'cross', 'dot', 'cross-dot', 'circle', 'none'

#: Where an anchored child sits in its layer.  Anything else is read as
#: ``center``, so a typo puts the element somewhere visible rather than
#: nowhere.
ANCHORS = (
    'top-left', 'top', 'top-right',
    'left', 'center', 'right',
    'bottom-left', 'bottom', 'bottom-right',
)


def place(container: Rect, size: Tuple[int, int], anchor: str,
          offset: Tuple[int, int]) -> Rect:
    """Where a box of ``size`` sits in ``container``, by name and then nudged.

    ``offset`` is in pixels with **+y up**, the origin this whole coordinate
    system uses, and it moves the box the way it reads: an offset of (5, 7) on
    a bottom-left element moves it right and up, away from the corner it is
    anchored to, whichever corner that is.
    """
    width, height = int(size[0]), int(size[1])
    anchor = anchor if anchor in ANCHORS else 'center'
    if anchor.endswith('left'):
        x = container.x
    elif anchor.endswith('right'):
        x = container.right - width
    else:
        x = container.x + (container.width - width) // 2
    if anchor.startswith('top'):
        y = container.top - height
    elif anchor.startswith('bottom'):
        y = container.y
    else:
        y = container.y + (container.height - height) // 2
    return Rect(x + int(offset[0]), y + int(offset[1]), width, height)


def hud_text(renderer: Any, rect: Rect, text: str, colour: Any,
             align: str = 'left') -> None:
    """One line of HUD text, over a shadow of itself.

    A HUD is drawn over a world whose colours nobody controls -- pale text on a
    white wall is text nobody can read, and sizing the colours for the world is
    impossible when the world is a map somebody else made.  A one-pixel shadow
    behind every glyph fixes it at every brightness, and it costs one more quad
    per character in a batch that is already one draw call.

    ``skin.hudShadow`` with an alpha of zero turns it off, for a game that
    would rather draw a plate.
    """
    shadow = renderer.skin.hudShadow
    if float(shadow[3]) > 0:
        renderer.textIn(rect.offset(1, -1), text, shadow, align=align)
    renderer.textIn(rect, text, colour, align=align)


class Anchored(object):
    """Fields that say where in a HUD layer something goes.

    A mix-in rather than a base class because both a leaf widget and a
    container want it, and the two have different bases already.
    """

    #: One of :data:`ANCHORS`.
    anchor = field.newField('anchor', 'SFString', 1, 'center')
    #: Pixels away from that anchor, +x right and +y up, at the reference font
    #: size.
    offset = field.newField('offset', 'SFVec2f', 1, (0.0, 0.0))

    def anchorOffset(self, metrics: FontMetrics) -> Tuple[int, int]:
        """This element's offset in real pixels."""
        return (metrics.pixels(self.offset[0]), metrics.pixels(self.offset[1]))


class HUDWidget(Anchored, Widget):
    """Base for a HUD element: anchored, never interactive, optionally tinted.

    ``color`` overrides whatever the skin would have chosen; an alpha of zero
    means "use the skin", which is what lets a game recolour one element
    without authoring a whole skin for it.
    """

    PROTO = 'HUDWidget'
    color = field.newField('color', 'SFVec4f', 1, (0, 0, 0, 0))

    interactive = False
    focusable = False

    def tinted(self, fallback: Any) -> Any:
        """This element's colour: its own if it has one, else the skin's."""
        if float(self.color[3]):
            return self.color
        return fallback


class HUDGroup(Anchored, Widget, GUIBox):
    """Several HUD elements travelling to one corner together.

    A column by default, because that is how a stack of meters reads.  It is
    the ordinary box layout with an anchor on the front of it, so what is
    inside can be anything -- meters, readouts, a nested row.
    """

    PROTO = 'HUDGroup'
    direction = field.newField('direction', 'SFString', 1, COLUMN)
    anchor = field.newField('anchor', 'SFString', 1, 'top-left')

    interactive = False


class HUDLayer(RootWidget):
    """A screen's worth of HUD: every child placed by its own anchor.

    Laid out for a viewport rather than centred in one like a panel, and drawn
    beneath every panel, so a dialog opened over a game covers its HUD rather
    than fighting with it.
    """

    PROTO = 'HUDLayer'
    #: Pixels kept clear between the layer's contents and the window edge, at
    #: the reference font size.
    margin = field.newField('margin', 'SFFloat', 1, 16.0)

    interactive = False

    def widget_at(self, x: float, y: float) -> Optional[Widget]:
        """Nothing: a HUD is a picture and the pointer goes through it."""
        return None

    # -- layout -----------------------------------------------------------
    def layout(self, viewport: Tuple[int, int], metrics: FontMetrics) -> None:
        """Take the whole window and place every child in it."""
        self.link()
        self._metrics = metrics
        self.scaleSkin(metrics)
        self.rect = Rect(0, 0, int(viewport[0]), int(viewport[1]))
        self.arrange_content(metrics)

    def contentRect(self, metrics: FontMetrics) -> Rect:
        """The rectangle children are placed in: the window inside the margin."""
        return self.rect.inset(metrics.pixels(self.margin))

    def arrange_content(self, metrics: FontMetrics) -> None:
        content = self.contentRect(metrics)
        for child in self.layoutChildren():
            child.parent = self
            anchor = getattr(child, 'anchor', None)
            if anchor is None:
                # Not a HUD element: an ordinary container, which knows how to
                # fill a rectangle on its own.
                child.arrange(content, metrics)
                continue
            offset = child.anchorOffset(metrics)
            child.arrange(place(content, child.natural_size(metrics),
                                str(anchor), offset), metrics)

    # -- the clock --------------------------------------------------------
    def tick(self, now: Optional[float] = None) -> None:
        """Advance everything in the layer that fades, expires or flashes.

        Called once a frame, before the layer is drawn.  Passing the time in
        rather than reading a clock here is what makes the behaviour testable
        and what lets a game drive its HUD from its own simulation clock.
        """
        if now is None:
            now = time.monotonic()
        for widget in self.walk():
            if widget is self:
                continue
            advance = getattr(widget, 'tick', None)
            if advance is not None:
                advance(now)

    # -- drawing ----------------------------------------------------------
    def paint(self, renderer: Any) -> None:
        """A layer has no body of its own; its children are the HUD."""


class Crosshair(HUDWidget):
    """The aiming reticule, and the mark that says a shot connected.

    Everything about it is a field, because **the reticule belongs to the
    weapon**: a table of weapons names one of these each, and switching weapon
    is switching this node rather than branching in the drawing code.

    ``spread`` is extra gap, in reference pixels, and is what a weapon whose
    accuracy falls off while firing writes into as it fires.  It widens the
    reticule rather than moving it, so what the player sees is the size of the
    area a shot might land in.
    """

    PROTO = 'Crosshair'
    #: One of :data:`CROSS`, :data:`DOT`, :data:`CROSS_DOT`, :data:`CIRCLE`,
    #: :data:`NONE`.
    shape = field.newField('shape', 'SFString', 1, CROSS)
    anchor = field.newField('anchor', 'SFString', 1, 'center')
    #: Clear pixels between the middle and the near end of each arm.  The gap
    #: is the point of a crosshair: it leaves what is being aimed at visible.
    gap = field.newField('gap', 'SFFloat', 1, 5.0)
    #: Length and thickness of one arm.
    length = field.newField('length', 'SFFloat', 1, 7.0)
    thickness = field.newField('thickness', 'SFFloat', 1, 2.0)
    #: Side of the centre dot, for the shapes that have one.
    dotSize = field.newField('dotSize', 'SFFloat', 1, 2.0)
    #: Extra gap from the current weapon's accuracy, in reference pixels.
    spread = field.newField('spread', 'SFFloat', 1, 0.0)
    #: How long the hit mark stays up, and how big it is.
    hitDuration = field.newField('hitDuration', 'SFFloat', 1, 0.35)
    hitSize = field.newField('hitSize', 'SFFloat', 1, 4.0)
    #: Draw the reticule over a darker copy of itself, so it reads against a
    #: pale wall as well as a dark one.
    outline = field.newField('outline', 'SFBool', 1, True)

    #: When the last confirmed hit was, on the clock :meth:`tick` is fed, or
    #: None.  Not a field: it is transient and worth neither saving nor
    #: sending.
    _hit_at: Optional[float] = None
    _now: float = 0.0

    # -- geometry ---------------------------------------------------------
    def reach(self, metrics: FontMetrics) -> int:
        """Pixels from the middle to the far end of an arm."""
        if str(self.shape) == NONE:
            return 0
        if str(self.shape) == DOT:
            return max(1, metrics.pixels(self.dotSize)) // 2
        return (metrics.pixels(float(self.gap) + float(self.spread))
                + metrics.pixels(self.length))

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        extent = self.reach(metrics) * 2
        return (extent, extent)

    def segments(self, metrics: FontMetrics) -> List[Rect]:
        """The rectangles the reticule is drawn from, in its laid-out place.

        Rectangles rather than lines because that is what the overlay renderer
        draws, and a circle is four arcs approximated the same way -- at the
        few pixels a reticule occupies, the difference is invisible and the
        batch stays one draw.
        """
        shape = str(self.shape)
        if shape == NONE or self.rect.empty:
            return []
        x, y = self.rect.centre
        dot = max(1, metrics.pixels(self.dotSize))
        if shape == DOT:
            return [Rect(x - dot // 2, y - dot // 2, dot, dot)]
        gap = metrics.pixels(float(self.gap) + float(self.spread))
        thickness = max(1, metrics.pixels(self.thickness))
        half = thickness // 2
        if shape == CIRCLE:
            # Four arcs: the top and bottom of a ring, and its two sides.
            span = gap * 2
            return [
                Rect(x - gap, y + gap - half, span, thickness),
                Rect(x - gap, y - gap - half, span, thickness),
                Rect(x - gap - half, y - gap, thickness, span),
                Rect(x + gap - half, y - gap, thickness, span),
            ]
        arm = max(1, metrics.pixels(self.length))
        segments = [
            Rect(x - gap - arm, y - half, arm, thickness),
            Rect(x + gap, y - half, arm, thickness),
            Rect(x - half, y - gap - arm, thickness, arm),
            Rect(x - half, y + gap, thickness, arm),
        ]
        if shape == CROSS_DOT:
            segments.append(Rect(x - dot // 2, y - dot // 2, dot, dot))
        return segments

    def outlineSegments(self, metrics: FontMetrics) -> List[Rect]:
        """The reticule's shape, one pixel larger on every side.

        Drawn first and in the shadow colour, which is what stops a light
        crosshair disappearing into a light wall.  Empty when ``outline`` is
        off.
        """
        if not self.outline:
            return []
        return [segment.expand(1) for segment in self.segments(metrics)]

    def hitMarks(self, metrics: FontMetrics) -> List[Rect]:
        """Four ticks around the middle while a hit is being acknowledged.

        Empty once :attr:`hitDuration` has passed, so the caller draws it
        unconditionally and the clock decides whether anything appears.
        """
        if self._hit_at is None or self.rect.empty:
            return []
        if self._now - self._hit_at > float(self.hitDuration):
            return []
        x, y = self.rect.centre
        size = max(2, metrics.pixels(self.hitSize))
        thickness = max(1, metrics.pixels(self.thickness))
        out = metrics.pixels(float(self.gap) + float(self.spread)) + size
        return [
            Rect(x - out, y - out, size, thickness),
            Rect(x + out - size, y - out, size, thickness),
            Rect(x - out, y + out - thickness, size, thickness),
            Rect(x + out - size, y + out - thickness, size, thickness),
        ]

    # -- events -----------------------------------------------------------
    def hit(self, now: Optional[float] = None) -> None:
        """Acknowledge a confirmed hit, so the player sees that it landed."""
        self._hit_at = self._now = (time.monotonic() if now is None else now)

    def tick(self, now: float) -> None:
        self._now = now

    # -- drawing ----------------------------------------------------------
    def paint(self, renderer: Any) -> None:
        metrics = renderer.metrics
        colour = self.tinted(renderer.skin.crosshair)
        for outline in self.outlineSegments(metrics):
            renderer.rect(outline, renderer.skin.hudShadow)
        for segment in self.segments(metrics):
            renderer.rect(segment, colour)
        for mark in self.hitMarks(metrics):
            renderer.rect(mark, renderer.skin.crosshairHit)


class BarMeter(HUDWidget):
    """A value against a maximum, drawn as a bar that changes colour.

    Three colours rather than a gradient, because what a player reads off a
    meter at speed is a state -- fine, low, about to matter -- and a continuous
    ramp says none of those clearly.  Where the thresholds sit is the game's
    decision, so they are fields.
    """

    PROTO = 'BarMeter'
    value = field.newField('value', 'SFFloat', 1, 0.0)
    maximum = field.newField('maximum', 'SFFloat', 1, 100.0)
    #: Drawn to the left of the bar; empty for none.
    label = field.newField('label', 'SFString', 1, '')
    #: Whether the number itself is drawn over the bar.
    showValue = field.newField('showValue', 'SFBool', 1, True)
    #: Bar size in pixels at the reference font size.
    barWidth = field.newField('barWidth', 'SFFloat', 1, 140.0)
    barHeight = field.newField('barHeight', 'SFFloat', 1, 14.0)
    #: Fractions of the maximum below which the meter reads low, then critical.
    warnFraction = field.newField('warnFraction', 'SFFloat', 1, 0.5)
    criticalFraction = field.newField('criticalFraction', 'SFFloat', 1, 0.25)

    @property
    def fraction(self) -> float:
        """How full the bar is, from 0 to 1.

        A maximum of zero is a meter of nothing rather than an error: a game
        showing armour before any has been picked up has exactly that.
        """
        maximum = float(self.maximum)
        if maximum <= 0:
            return 0.0
        return max(0.0, min(1.0, float(self.value) / maximum))

    def stateColour(self, skin: Any) -> Any:
        """The bar's colour for where its value sits against the thresholds."""
        own = self.tinted(None)
        if own is not None:
            return own
        fraction = self.fraction
        if fraction <= float(self.criticalFraction):
            return skin.hudCritical
        if fraction <= float(self.warnFraction):
            return skin.hudWarn
        return skin.hudGood

    # -- geometry ---------------------------------------------------------
    def labelWidth(self, metrics: FontMetrics) -> int:
        if not self.label:
            return 0
        return (metrics.text_width(str(self.label))
                + int(self.activeSkin().hudSpacing))

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        return (self.labelWidth(metrics) + metrics.pixels(self.barWidth),
                max(metrics.pixels(self.barHeight), metrics.char_height))

    def barRect(self, metrics: FontMetrics) -> Rect:
        """The whole track, label allowed for."""
        height = metrics.pixels(self.barHeight)
        left = self.rect.x + self.labelWidth(metrics)
        return Rect(left, self.rect.y + (self.rect.height - height) // 2,
                    max(0, self.rect.right - left), height)

    def fillRect(self, metrics: FontMetrics) -> Rect:
        """The filled part of the track."""
        track = self.barRect(metrics)
        return Rect(track.x, track.y, int(track.width * self.fraction),
                    track.height)

    # -- drawing ----------------------------------------------------------
    def paint(self, renderer: Any) -> None:
        metrics = renderer.metrics
        skin = renderer.skin
        if self.label:
            hud_text(renderer, Rect(self.rect.x, self.rect.y,
                                    self.labelWidth(metrics), self.rect.height),
                     str(self.label), skin.hudText)
        track = self.barRect(metrics)
        renderer.rect(track, skin.hudTrack)
        renderer.rect(self.fillRect(metrics), self.stateColour(skin))
        if self.showValue:
            hud_text(renderer, track, '%d' % (int(self.value),), skin.hudText,
                     align='center')


class Readout(HUDWidget):
    """An optional icon, an optional label and a value: ammunition, a count.

    ``critical`` is the game saying "this one matters now" -- the last few
    rounds, the last seconds -- and it is a flag rather than a colour so the
    skin still decides what that looks like.
    """

    PROTO = 'Readout'
    label = field.newField('label', 'SFString', 1, '')
    value = field.newField('value', 'SFString', 1, '')
    #: A nine-slice drawn to the left of the text; NULL for none.
    icon = field.newField('icon', 'SFNode', 1, node.NULL)
    #: Side of that icon in pixels at the reference font size.
    iconSize = field.newField('iconSize', 'SFFloat', 1, 20.0)
    #: Draw the value in the skin's critical colour.
    critical = field.newField('critical', 'SFBool', 1, False)
    #: ``left``, ``center`` or ``right`` within whatever room it is given.
    align = field.newField('align', 'SFString', 1, 'left')

    def valueColour(self, skin: Any) -> Any:
        """The colour the number is drawn in."""
        if self.critical:
            return skin.hudCritical
        return self.tinted(skin.hudText)

    def text(self) -> str:
        """Label and value as one line, with either half optional."""
        return ' '.join(part for part in (str(self.label), str(self.value))
                        if part)

    def iconWidth(self, metrics: FontMetrics) -> int:
        if not self.icon:
            return 0
        return metrics.pixels(self.iconSize) + int(self.activeSkin().hudSpacing)

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        text = self.text()
        width = self.iconWidth(metrics) + metrics.text_width(text)
        height = max(metrics.char_height,
                     metrics.pixels(self.iconSize) if self.icon else 0)
        return (width, height)

    def iconRect(self, metrics: FontMetrics) -> Rect:
        side = metrics.pixels(self.iconSize)
        return Rect(self.rect.x, self.rect.y + (self.rect.height - side) // 2,
                    side, side)

    def paint(self, renderer: Any) -> None:
        metrics = renderer.metrics
        skin = renderer.skin
        if self.icon:
            renderer.ninepatch(self.iconRect(metrics), self.icon)
        text = self.text()
        if not text:
            return
        left = self.rect.x + self.iconWidth(metrics)
        hud_text(renderer, Rect(left, self.rect.y,
                                max(0, self.rect.right - left),
                                self.rect.height),
                 text, self.valueColour(skin), align=str(self.align))


class Message(object):
    """One line in a :class:`MessageQueue`, and when it stops being shown."""

    __slots__ = ('text', 'posted', 'duration', 'color')

    def __init__(self, text: str, posted: float, duration: float,
                 color: Optional[Sequence[float]] = None) -> None:
        self.text = text
        self.posted = posted
        self.duration = duration
        self.color = color

    def expired(self, now: float) -> bool:
        return now - self.posted >= self.duration

    def alpha(self, now: float, fade: float) -> float:
        """How solid this message is: 1 until the fade begins, then down to 0."""
        remaining = self.duration - (now - self.posted)
        if remaining <= 0:
            return 0.0
        if fade <= 0 or remaining >= fade:
            return 1.0
        return max(0.0, remaining / fade)


class MessageQueue(HUDWidget):
    """Transient lines -- a pickup, a frag, a warning -- newest first.

    Each carries its own clock rather than the queue holding one deadline, so a
    warning posted with a long life is not cut short by a pickup posted after
    it.  ``capacity`` is what is *shown*: older messages are dropped when a new
    one arrives, because a HUD that scrolls is a HUD nobody reads.
    """

    PROTO = 'MessageQueue'
    anchor = field.newField('anchor', 'SFString', 1, 'top')
    #: Seconds a message is shown for, and how much of the end of that is
    #: spent fading.
    duration = field.newField('duration', 'SFFloat', 1, 4.0)
    fade = field.newField('fade', 'SFFloat', 1, 1.0)
    #: The most that are shown at once.
    capacity = field.newField('capacity', 'SFInt32', 1, 5)
    align = field.newField('align', 'SFString', 1, 'center')

    #: The clock :meth:`tick` was last given, which is what :meth:`paint`
    #: draws against so a fade is the same on screen as in a test.
    _now: float = 0.0

    def __init__(self, **named: Any) -> None:
        super(MessageQueue, self).__init__(**named)
        #: What is up right now, newest first.  Not a field: it is transient.
        self.messages: List[Message] = []

    # -- posting ----------------------------------------------------------
    def post(self, text: str, now: Optional[float] = None,
             duration: Optional[float] = None,
             color: Optional[Sequence[float]] = None) -> Message:
        """Show a line, and hand back the message so a caller can hold it."""
        if now is None:
            now = time.monotonic()
        message = Message(text, now,
                          float(self.duration if duration is None else duration),
                          color)
        self.messages.insert(0, message)
        del self.messages[int(self.capacity):]
        return message

    def clear(self) -> None:
        """Drop everything -- a new match, a new level."""
        self.messages = []

    def tick(self, now: float) -> None:
        """Take the clock, and let go of whatever has run out."""
        self._now = now
        self.messages = [message for message in self.messages
                         if not message.expired(now)]

    # -- what is on screen ------------------------------------------------
    def entries(self, now: float) -> List[Tuple[str, Tuple[float, float, float, float]]]:
        """The lines to draw and the colour each is drawn in, newest first.

        The colour carries the fade in its alpha, so the caller draws what it
        is given and nothing else has to know about time.
        """
        skin = self.activeSkin()
        base = self.tinted(skin.hudText)
        found = []
        for message in self.messages:
            if message.expired(now):
                continue
            colour = message.color if message.color is not None else base
            alpha = float(colour[3]) * message.alpha(now, float(self.fade))
            found.append((message.text,
                          (float(colour[0]), float(colour[1]),
                           float(colour[2]), alpha)))
        return found

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        if not self.messages:
            return (0, 0)
        widest = max(metrics.text_width(message.text)
                     for message in self.messages)
        return (widest, len(self.messages) * metrics.line_height)

    def paint(self, renderer: Any) -> None:
        metrics = renderer.metrics
        top = self.rect.top - metrics.char_height
        for index, (text, colour) in enumerate(self.entries(self._now)):
            hud_text(renderer,
                     Rect(self.rect.x, top - index * metrics.line_height,
                          self.rect.width, metrics.char_height),
                     text, colour, align=str(self.align))
