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
* :class:`DamageIndicator` -- **which way** a hit came from, washed onto the
  screen edge the player would have to turn towards.  How much was lost is
  already on the meter; where it came from is the part a player cannot see and
  can act on.
* :class:`ScreenWash` -- a colour over the whole viewport, for the states
  where the *view* has changed rather than where something has happened in it:
  being dead, being under water, a fade.  It has no direction to give, which
  is exactly what distinguishes it from the one above.

Everything here is arithmetic over a viewport and a font, so a HUD's layout is
testable with no window at all: hand a layer a viewport and read the
rectangles back.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from vrml import field, node

from OpenGLContext.hud import COLUMN, GUIBox
from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.widgets import RootWidget, Widget

__all__ = [
    'HUDLayer', 'HUDWidget', 'HUDGroup', 'Crosshair', 'BarMeter', 'Readout',
    'TextBlock',
    'Message', 'MessageQueue', 'DamageIndicator', 'DamageMark', 'ScreenWash',
    'place', 'hud_text',
    'CROSS', 'DOT', 'CROSS_DOT', 'CIRCLE', 'NONE', 'ANCHORS', 'EDGES',
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
            # The layer's own width is passed on, so a child that *can* fit
            # itself into less room is told how much there is: a bar of five
            # weapons wants its titles on a desktop and its number keys alone
            # in a small window, and neither is a property of the weapons.
            wanted = child.natural_size(metrics, content.width)
            child.arrange(place(content, wanted, str(anchor), offset), metrics)

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
    #: Seconds a :meth:`flash` lasts, and how strong it is at its brightest.
    #: A meter whose number changes silently in the corner is not feedback:
    #: nobody is looking at it, and the flash is what makes the change
    #: something a player notices out of the corner of an eye.
    flashDuration = field.newField('flashDuration', 'SFFloat', 1, 0.35)
    flashStrength = field.newField('flashStrength', 'SFFloat', 1, 0.75)

    #: When the last flash was asked for, on the clock :meth:`tick` is fed,
    #: or None.  Not a field: it is transient and worth neither saving nor
    #: sending.
    _flash_at: Optional[float] = None
    _now: float = 0.0

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

    # -- reacting ---------------------------------------------------------
    def flash(self, now: Optional[float] = None) -> None:
        """Light the whole track briefly: this number just moved.

        Asked for by whoever wrote the value, because *what* is worth
        flashing about is the game's rule and not the meter's: health lost
        matters and health gained from a pickup may not.
        """
        self._flash_at = self._now = (time.monotonic() if now is None else now)

    def tick(self, now: float) -> None:
        self._now = now

    def flashAlpha(self) -> float:
        """How strong the flash is right now, from its strength down to nothing."""
        if self._flash_at is None:
            return 0.0
        duration = float(self.flashDuration)
        if duration <= 0.0:
            return 0.0
        left = 1.0 - (self._now - self._flash_at) / duration
        return float(self.flashStrength) * left if left > 0.0 else 0.0

    def flashColour(self) -> Tuple[float, float, float, float]:
        """White at the flash's current strength."""
        return (1.0, 1.0, 1.0, self.flashAlpha())

    def flashRect(self, metrics: FontMetrics) -> Optional[Rect]:
        """The track while a flash is up, or None.

        The whole track rather than the filled part, so a meter that has just
        been emptied still flashes: the moment health reaches nothing is the
        one a player most needs to see.
        """
        if self.flashAlpha() <= 0.0:
            return None
        return self.barRect(metrics)

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
        lit = self.flashRect(metrics)
        if lit is not None:
            renderer.rect(lit, self.flashColour())
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


class TextBlock(HUDWidget):
    """Several lines of text in a corner: a caption, a legend, a hint.

    The counterpart to :class:`Readout`, which is one line built from a label
    and a value.  This is prose the application composed itself -- what is
    loaded and what the keys do -- and the lines are a field rather than one
    string with newlines in it so a caller can rewrite one of them.

    ``critical`` marks the whole block as saying something has gone wrong; what
    that looks like stays the skin's decision.
    """

    PROTO = 'TextBlock'
    lines = field.newField('lines', 'MFString', 1, list)
    #: Draw it in the skin's critical colour.
    critical = field.newField('critical', 'SFBool', 1, False)
    #: ``left``, ``center`` or ``right`` within whatever room it is given.
    align = field.newField('align', 'SFString', 1, 'left')

    def textColour(self, skin: Any) -> Any:
        """The colour the lines are drawn in."""
        if self.critical:
            return skin.hudCritical
        return self.tinted(skin.hudText)

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        lines = [str(line) for line in self.lines]
        if not lines:
            return (0, 0)
        width = max(metrics.text_width(line) for line in lines)
        # The gap *between* lines, so a one-line block is exactly one line tall
        # and a block is never taller than the text in it.
        height = len(lines) * metrics.line_height - metrics.line_gap
        return (width, height)

    def lineRects(self, metrics: FontMetrics) -> List[Rect]:
        """Where each line goes, first at the top.

        Text reads downwards and this coordinate system counts upwards, so the
        first line is the one nearest ``rect.top``.
        """
        rects = []
        top = self.rect.top
        for _ in self.lines:
            top -= metrics.char_height
            rects.append(Rect(self.rect.x, top, self.rect.width,
                              metrics.char_height))
            top -= metrics.line_gap
        return rects

    def paint(self, renderer: Any) -> None:
        colour = self.textColour(renderer.skin)
        align = str(self.align)
        for rect, line in zip(self.lineRects(renderer.metrics), self.lines,
                              strict=True):
            if line:
                hud_text(renderer, rect, str(line), colour, align=align)


class ScreenWash(HUDWidget):
    """A colour over the whole viewport: the world seen through something.

    The counterpart to :class:`DamageIndicator`, which washes the *edge* a hit
    came from because direction is what a player has to act on.  This one has
    no direction to give, and is for the states where the view itself has
    changed rather than where something has happened in it -- being dead,
    being under water, the moment a screen fades.

    ``strength`` is how solid it is and is the whole of the design decision.
    A wash a player can still read the room through is information; one they
    cannot is a curtain, and the only state that earns a curtain is one where
    there is nothing left to read.
    """

    PROTO = 'ScreenWash'
    anchor = field.newField('anchor', 'SFString', 1, 'center')
    #: What colour, and how solid, 0 to 1.  Visible is a separate field on the
    #: widget itself, so switching one on and off does not disturb its colour.
    colour = field.newField('colour', 'SFColor', 1, (1.0, 0.0, 0.0))
    strength = field.newField('strength', 'SFFloat', 1, 0.0)

    interactive = False

    def wash(self) -> Optional[Tuple[Rect, Tuple[float, float, float, float]]]:
        """The rectangle to fill and its colour, or None when it is invisible.

        None rather than a transparent rectangle, so a wash that is switched
        off costs a comparison rather than a draw -- this is over the whole
        screen and it is up on most frames of most games at zero strength.
        """
        alpha = max(0.0, min(1.0, float(self.strength)))
        if alpha <= 0.0 or self.rect.empty:
            return None
        colour = self.colour
        return (self.rect, (float(colour[0]), float(colour[1]),
                            float(colour[2]), alpha))

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        """The whole layer: a wash is the screen, not a box on it."""
        parent = getattr(self, 'parent', None)
        area = getattr(parent, 'rect', None)
        if area is None:
            return (0, 0)
        return (area.width, area.height)

    def paint(self, renderer: Any) -> None:
        found = self.wash()
        if found is not None:
            renderer.rect(*found)


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


#: The screen edges a :class:`DamageIndicator` washes, and the bearing each
#: one stands for: straight ahead, to the right, behind, to the left.  Behind
#: is the bottom of the screen because that is where a player looks for what
#: they cannot see, and it is the reading every game in the genre has taught.
EDGES: Tuple[Tuple[str, float], ...] = (
    ('top', 0.0),
    ('right', math.pi / 2.0),
    ('bottom', math.pi),
    ('left', -math.pi / 2.0),
)


class DamageMark(object):
    """One hit being shown by a :class:`DamageIndicator`."""

    __slots__ = ('bearing', 'intensity', 'at')

    def __init__(self, bearing: float, intensity: float, at: float) -> None:
        #: Radians from straight ahead, positive to the right, so ``pi`` is
        #: directly behind and ``-pi/2`` is directly to the left.
        self.bearing = float(bearing)
        #: How hard it was, 0 to 1.  What the wash's strength is scaled by.
        self.intensity = float(intensity)
        #: When it landed, on the clock :meth:`DamageIndicator.tick` is fed.
        self.at = float(at)

    def strength(self, now: float, duration: float) -> float:
        """How much of this mark is left, from its intensity down to nothing."""
        if duration <= 0.0:
            return 0.0
        left = 1.0 - (now - self.at) / duration
        return self.intensity * left if left > 0.0 else 0.0

    def spent(self, now: float, duration: float) -> bool:
        return self.strength(now, duration) <= 0.0


class DamageIndicator(HUDWidget):
    """Which way a hit came from, washed onto the edge it came from.

    **The direction is the whole point.**  How much health was lost is already
    on the meter and in the number beside it; what a player cannot see, and
    what they must act on within about a second, is *where the shooter is
    standing*.  So a hit is drawn at the screen edge the player would turn
    towards to face it.

    A bearing is radians from straight ahead, positive to the right, so
    ``+pi/2`` is directly to the right and ``pi`` is directly behind.  Each of
    the four edges takes the share of a hit that faces it, which makes the
    wash slide from one edge to the next as an opponent circles rather than
    snapping between them -- a flicker at the corner would read as a fault in
    the game, not as a shooter moving.

    Several hits are shown at once and each fades on its own clock, so being
    caught in a crossfire looks like being caught in a crossfire.
    """

    PROTO = 'DamageIndicator'
    #: It is drawn over the whole viewport rather than in a corner.
    anchor = field.newField('anchor', 'SFString', 1, 'center')
    #: Seconds one hit takes to fade to nothing.  Long enough to be seen
    #: through the flinch of being shot, short enough that it is not still up
    #: when the player has already turned.
    duration = field.newField('duration', 'SFFloat', 1, 1.1)
    #: How far in from the edge the wash reaches at full strength, in pixels
    #: at the reference font size.
    thickness = field.newField('thickness', 'SFFloat', 1, 48.0)
    #: How solid the wash is at its strongest, 0 to 1.  Well below opaque on
    #: purpose: **it is a warning over a game, not a curtain across it**, and a
    #: wash a player cannot see the room through takes away the very thing they
    #: are being told to look at.
    strength = field.newField('strength', 'SFFloat', 1, 0.34)
    #: How many strips the wash is drawn from.  It is a gradient rather than a
    #: band because a hard-edged block over the world reads as a rendering
    #: fault; four is enough that the step is invisible at speed.
    steps = field.newField('steps', 'SFInt32', 1, 4)
    #: The most that are shown at once.  A firefight can ask for dozens and
    #: the ones underneath contribute nothing a player can see.
    capacity = field.newField('capacity', 'SFInt32', 1, 8)

    #: The clock :meth:`tick` was last given, which is what :meth:`paint`
    #: draws against so a fade is the same on screen as in a test.
    _now: float = 0.0

    def __init__(self, **named: Any) -> None:
        super(DamageIndicator, self).__init__(**named)
        #: What is being shown right now.  Not a field: it is transient and
        #: worth neither saving nor sending.
        self.marks: List[DamageMark] = []

    # -- taking a hit -----------------------------------------------------
    def hurt(self, bearing: float, intensity: float = 1.0,
             now: Optional[float] = None) -> Optional[DamageMark]:
        """Show a hit from ``bearing``, or nothing if it did no damage.

        A hit an armour absorbed entirely is not a hit to flash about, so an
        intensity of zero is dropped here rather than drawn invisibly.
        """
        intensity = max(0.0, min(1.0, float(intensity)))
        if intensity <= 0.0:
            return None
        mark = DamageMark(bearing, intensity,
                          time.monotonic() if now is None else now)
        self.marks.append(mark)
        del self.marks[:-int(self.capacity)]
        return mark

    def clear(self) -> None:
        """Drop everything -- a respawn, a new match."""
        self.marks = []

    def tick(self, now: float) -> None:
        """Take the clock, and let go of whatever has faded out."""
        self._now = now
        duration = float(self.duration)
        self.marks = [mark for mark in self.marks
                      if not mark.spent(now, duration)]

    # -- what is on screen ------------------------------------------------
    def shares(self) -> Dict[str, float]:
        """How strongly each edge is lit, by name, leaving out the dark ones.

        A hit contributes to an edge in proportion to how much it faces it --
        the cosine of the angle between them, and nothing at all behind.  The
        two edges either side of a bearing therefore share it, which is what
        makes an opponent circling the player slide the wash around the screen
        instead of stepping it.
        """
        duration = float(self.duration)
        lit: Dict[str, float] = {}
        for mark in self.marks:
            strength = mark.strength(self._now, duration)
            if strength <= 0.0:
                continue
            for name, facing in EDGES:
                share = math.cos(mark.bearing - facing) * strength
                if share > 1e-6:
                    lit[name] = max(lit.get(name, 0.0), share)
        return lit

    def edges(self, metrics: FontMetrics
              ) -> List[Tuple[str, Rect, Tuple[float, float, float, float]]]:
        """Each lit edge, the band it occupies, and the colour at its outside.

        The band is the whole strip; :meth:`bands` is what actually gets
        drawn, and divides each one into the strips of the gradient.
        """
        if self.rect.empty:
            return []
        reach = min(metrics.pixels(self.thickness),
                    # Never more than a slice of the screen, whatever the
                    # authored thickness and however small the window: four
                    # thick bands on a small viewport meet in the middle.
                    max(1, int(min(self.rect.width, self.rect.height) * 0.22)))
        colour = self.tinted(self.activeSkin().crosshairHit)
        peak = float(colour[3]) * float(self.strength)
        found = []
        for name, share in sorted(self.shares().items()):
            found.append((name, self._band(name, reach),
                          (float(colour[0]), float(colour[1]),
                           float(colour[2]), peak * share)))
        return found

    def bands(self, metrics: FontMetrics
              ) -> List[Tuple[Rect, Tuple[float, float, float, float]]]:
        """The strips to draw and the colour of each, strongest first.

        Every strip sits inside the one before it and is fainter, which is a
        gradient drawn with the flat rectangles the overlay renderer has.
        """
        steps = max(1, int(self.steps))
        drawn = []
        for _name, band, colour in self.edges(metrics):
            for index in range(steps):
                strip = self._strip(band, index, steps)
                if strip.empty:
                    continue
                fade = (steps - index) / float(steps)
                drawn.append((strip, (colour[0], colour[1], colour[2],
                                      colour[3] * fade * fade)))
        return drawn

    def _band(self, name: str, reach: int) -> Rect:
        """The strip of screen one edge's wash occupies."""
        area = self.rect
        if name == 'left':
            return Rect(area.x, area.y, reach, area.height)
        if name == 'right':
            return Rect(area.right - reach, area.y, reach, area.height)
        if name == 'top':
            return Rect(area.x, area.top - reach, area.width, reach)
        return Rect(area.x, area.y, area.width, reach)

    def _strip(self, band: Rect, index: int, steps: int) -> Rect:
        """One slice of a band, counted inwards from the screen edge."""
        if band.width >= band.height:               # a top or bottom band
            height = max(1, band.height // steps)
            outside = band.y if band.y == self.rect.y else band.top - height
            step = height if band.y == self.rect.y else -height
            return Rect(band.x, outside + step * index, band.width, height)
        width = max(1, band.width // steps)
        outside = band.x if band.x == self.rect.x else band.right - width
        step = width if band.x == self.rect.x else -width
        return Rect(outside + step * index, band.y, width, band.height)

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        """The whole layer: a wash is at the edges of the screen, not in a box."""
        parent = getattr(self, 'parent', None)
        area = getattr(parent, 'rect', None)
        if area is None:
            return (0, 0)
        return (area.width, area.height)

    def paint(self, renderer: Any) -> None:
        for strip, colour in self.bands(renderer.metrics):
            renderer.rect(strip, colour)
