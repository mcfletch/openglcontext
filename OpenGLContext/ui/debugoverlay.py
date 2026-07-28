"""The developer overlay: everything a player should never see, in one place.

**One panel, fed by registered providers.**  A provider is a callable that
returns name/value pairs and knows nothing about drawing; a subsystem appears in
the overlay by registering one, not by anybody editing this module.  That is the
whole reason this is engine machinery rather than a game's own screen: the
renderer, the physics world, the navigation mesh and the application each own
their numbers, and each hands them over the same way::

    context.debugOverlay.register('Map', lambda: [
        ('name', loaded.name), ('family', loaded.family),
    ])

Values are formatted here, so a provider returns whatever it has -- a float, a
flag, a vector, ``None`` -- and never a pre-rendered string.

**It is a HUD layer, not a panel.**  It takes no input, blocks nothing and is
drawn under any screen that is open, so it can be left up while playing.  A
provider that raises turns into an ``error`` row rather than taking the frame
down with it: this is diagnostic equipment, and a diagnostic that breaks the
thing it is measuring is worse than none.

It replaces the frame-rate counter that used to be drawn by
:class:`~OpenGLContext.framecounter.FrameCounter` through fixed-function calls
that mean nothing in a core-profile context.  ``OPENGLCONTEXT_DISABLE_FPS_DISPLAY``
still means what it always did, and now means it here: the overlay starts
hidden, so a captured frame has nothing over it.
"""

from __future__ import annotations

import logging
import os
from typing import (
    Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple,
)

from vrml import field

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.hudwidgets import HUDLayer, HUDWidget
from OpenGLContext.ui.metrics import FontMetrics

log = logging.getLogger(__name__)

__all__ = [
    'DebugOverlay', 'DebugPanel', 'DebugSection', 'LaidOutRow',
    'format_value', 'frame_provider', 'render_provider', 'platform_provider',
    'physics_provider', 'install_default_providers',
]

#: What a provider returns: pairs of name and value, or a mapping of the same.
Rows = Iterable[Tuple[str, Any]]
Provider = Callable[[], Any]


class DebugSection(NamedTuple):
    """One labelled group of rows, as a provider last answered it."""

    title: str
    rows: List[Tuple[str, str]]


class LaidOutRow(NamedTuple):
    """One line of the overlay, placed."""

    rect: Rect
    label: str
    value: str
    heading: bool


def format_value(value: Any) -> str:
    """A provider's value as the one line that will be drawn for it.

    Formatting here rather than in the provider is what keeps the providers
    trivial -- a provider hands over the number it has -- and what keeps the
    overlay's columns reading consistently when a dozen unrelated subsystems
    write into them.
    """
    if value is None:
        return '-'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (tuple, list)) or hasattr(value, '__len__'):
        try:
            return ', '.join(_number(float(component)) for component in value)
        except (TypeError, ValueError):
            pass
    return str(value)


def _number(value: float) -> str:
    """A float with two decimals, and none at all when it is whole.

    Trailing zeros on a frame time are noise, and a position that reads
    ``512.00`` is three characters of nothing on a line where width is scarce.
    """
    text = '%.2f' % (value,)
    if text.endswith('.00'):
        return text[:-3]
    return text.rstrip('0').rstrip('.') if '.' in text else text


class DebugPanel(HUDWidget):
    """The plate the sections are drawn on: two columns, one line per row.

    Its size follows its contents, which change every frame, so it is measured
    and placed each time the overlay is drawn rather than once at layout.
    """

    PROTO = 'DebugPanel'
    anchor = field.newField('anchor', 'SFString', 1, 'top-left')

    def __init__(self, **named: Any) -> None:
        super(DebugPanel, self).__init__(**named)
        #: What the providers last said.  Not a field: it is this frame's
        #: reading, not authored data.
        self.sections: List[DebugSection] = []

    # -- measurement ------------------------------------------------------
    def columnWidths(self, metrics: FontMetrics) -> Tuple[int, int]:
        """Pixels for the name column and for the value column.

        One pair for the whole overlay rather than per section, so the values
        of every subsystem line up in one column and the eye runs down it.
        """
        labels = 0
        values = 0
        for section in self.sections:
            labels = max(labels, metrics.text_width(section.title))
            for name, value in section.rows:
                labels = max(labels, metrics.text_width(name))
                values = max(values, metrics.text_width(value))
        return (labels, values)

    def lineCount(self) -> int:
        """Headings and rows together -- how many lines will be drawn."""
        return sum(1 + len(section.rows) for section in self.sections)

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        lines = self.lineCount()
        if not lines:
            return (0, 0)
        skin = self.activeSkin()
        padding = int(skin.hudPadding)
        labels, values = self.columnWidths(metrics)
        gap = int(skin.hudSpacing) if values else 0
        return (labels + gap + values + padding * 2,
                lines * metrics.line_height + padding * 2)

    def laidOutRows(self, metrics: FontMetrics) -> List[LaidOutRow]:
        """Every heading and row, placed inside this plate, top down.

        The whole of the overlay's layout, and pure arithmetic: hand it a font
        and a set of sections and the rectangles come back, with no window
        anywhere in sight.
        """
        if not self.sections or self.rect.empty:
            return []
        padding = int(self.activeSkin().hudPadding)
        inner = self.rect.inset(padding)
        line_height = metrics.line_height
        cursor = inner.top - metrics.char_height
        laid: List[LaidOutRow] = []
        for section in self.sections:
            laid.append(LaidOutRow(
                Rect(inner.x, cursor, inner.width, metrics.char_height),
                section.title, '', True))
            cursor -= line_height
            for name, value in section.rows:
                laid.append(LaidOutRow(
                    Rect(inner.x, cursor, inner.width, metrics.char_height),
                    name, value, False))
                cursor -= line_height
        return laid

    # -- drawing ----------------------------------------------------------
    def paint(self, renderer: Any) -> None:
        if not self.sections:
            return
        metrics = renderer.metrics
        skin = renderer.skin
        renderer.rect(self.rect, self.tinted(skin.debugFill))
        for row in self.laidOutRows(metrics):
            if row.heading:
                renderer.textIn(row.rect, row.label, skin.debugTitle)
                continue
            renderer.textIn(row.rect, row.label, skin.debugLabel)
            renderer.textIn(row.rect, row.value, skin.debugValue,
                            align='right')


class DebugOverlay(HUDLayer):
    """The overlay itself: a registry of providers and the plate they fill.

    Held by a context (``context.debugOverlay``) and drawn with the rest of its
    HUD.  Registration is by title, so registering the same title twice
    replaces the provider rather than growing a second section with the same
    heading -- which is what a reloaded subsystem would otherwise do.
    """

    PROTO = 'DebugOverlay'
    margin = field.newField('margin', 'SFFloat', 1, 12.0)

    def __init__(self, **named: Any) -> None:
        super(DebugOverlay, self).__init__(**named)
        self.panel = DebugPanel()
        self.children = [self.panel]
        #: Title to (order, provider), in registration order within an order.
        self._providers: Dict[str, Tuple[int, Provider]] = {}
        self._sequence = 0

    # -- the registry -----------------------------------------------------
    def register(self, title: str, provider: Provider,
                 order: int = 50) -> Provider:
        """Add (or replace) a section, and hand the provider back.

        ``order`` sorts the sections: low numbers first, and providers given
        the same order keep the order they registered in, so a subsystem that
        does not care where it lands simply lands after whatever was there.
        """
        self._sequence += 1
        self._providers[title] = (order * 1000 + self._sequence, provider)
        return provider

    def unregister(self, title: str) -> None:
        """Take a section away -- a subsystem that has been shut down."""
        self._providers.pop(title, None)

    def sections(self) -> List[DebugSection]:
        """Ask every provider, in order, for the rows it has right now.

        A provider with nothing to say is left out entirely rather than
        appearing as an empty heading: a physics section on a map with no
        physics is noise on a screen that is short of room.
        """
        found: List[DebugSection] = []
        for title, (_order, provider) in sorted(self._providers.items(),
                                                key=lambda item: item[1][0]):
            rows = self._rowsFrom(title, provider)
            if rows:
                found.append(DebugSection(title, rows))
        return found

    @staticmethod
    def _rowsFrom(title: str, provider: Provider) -> List[Tuple[str, str]]:
        """One provider's rows, formatted, with a failure shown rather than raised."""
        try:
            answer = provider()
        except Exception as error:                  # noqa: BLE001 - diagnostic
            log.debug('debug overlay provider %s failed', title, exc_info=True)
            return [('error', str(error) or type(error).__name__)]
        if hasattr(answer, 'items'):
            answer = list(answer.items())
        return [(str(name), format_value(value)) for name, value in answer]

    # -- the frame --------------------------------------------------------
    def refresh(self) -> None:
        """Read every provider into the plate, ready to be measured and drawn."""
        self.panel.sections = self.sections()

    def tick(self, now: Optional[float] = None) -> None:
        """Refresh from the providers; the numbers are this frame's, not last's."""
        self.refresh()
        super(DebugOverlay, self).tick(now)

    # -- visibility -------------------------------------------------------
    @staticmethod
    def startsVisible() -> bool:
        """Whether a new overlay should be on screen straight away.

        ``OPENGLCONTEXT_DISABLE_FPS_DISPLAY`` is what the capture harness sets
        to get a clean frame, and it has always meant "no numbers over my
        screenshot"; here it means the overlay starts hidden.  A key still
        brings it up, because a capture run is not the only thing that sets it.
        """
        return not os.environ.get('OPENGLCONTEXT_DISABLE_FPS_DISPLAY')

    def toggle(self) -> bool:
        """Show it if it is hidden, hide it if it is up; True if now shown."""
        self.visible = not self.visible
        return bool(self.visible)


# -- the providers shipped with it ----------------------------------------
# Each takes what it needs and returns a callable, so a context registers one
# by naming it rather than by writing a lambda that closes over itself.

def frame_provider(context: Any) -> Provider:
    """Frame rate, frame time and the window this is all being drawn in.

    The rate is the **windowed median**, not the lifetime average: a cumulative
    average bakes in the first frame's shader compile and every synchronous
    load after it, and then reads permanently below what the renderer is
    actually doing.
    """
    def rows() -> Rows:
        counter = getattr(context, 'frameCounter', None)
        width, height = context.getViewPort()
        if counter is None:
            return [('fps', 0), ('viewport', '%dx%d' % (width, height))]
        count, _average, last = counter.summary()
        return [
            ('fps', counter.recentFps()),
            ('frame ms', last * 1000.0),
            ('frames', count),
            ('viewport', '%dx%d' % (width, height)),
        ]
    return rows


def render_provider(context: Any) -> Provider:
    """Which renderer features are on, and what the last frame cost in draws."""
    def rows() -> Rows:
        definition = getattr(context, 'contextDefinition', None)
        found: List[Tuple[str, Any]] = [
            ('profile', 'core' if getattr(context, 'coreProfile', False)
             else 'compatibility'),
        ]
        for name in ('shadows', 'ibl', 'bloom', 'transmission', 'instancing',
                     'vsync'):
            if definition is not None and hasattr(definition, name):
                found.append((name, bool(getattr(definition, name))))
        stats = getattr(context, 'renderStats', None)
        if stats is not None:
            found.extend([
                ('shapes', stats.shapes),
                ('draws', stats.draws),
                ('instanced', '%d in %d groups' % (stats.instances,
                                                   stats.instanceGroups)),
            ])
        return found
    return rows


def platform_provider(context: Any) -> Provider:
    """Where the camera is, and what the character controller under it is doing.

    Everything is read defensively: a context may have no view platform yet, a
    platform may be a plain camera with no controller, and neither is a reason
    for the overlay to stop reporting the rest.
    """
    def rows() -> Rows:
        platform = context.getViewPlatform()
        if platform is None:
            return []
        found: List[Tuple[str, Any]] = [
            ('position', tuple(float(value)
                               for value in platform.position[:3])),
        ]
        controller = getattr(platform, 'controller', None)
        if controller is not None:
            for name, label in (('grounded', 'grounded'),
                                ('velocity', 'velocity'),
                                ('mode', 'mode')):
                if hasattr(controller, name):
                    found.append((label, getattr(controller, name)))
        return found
    return rows


def physics_provider(world: Callable[[], Any]) -> Provider:
    """Body and contact counts from a physics world, fetched when asked for.

    Takes a callable rather than the world itself because a world is built when
    a level loads and replaced when the next one does; a provider holding the
    first would report on it forever.
    """
    def rows() -> Rows:
        found_world = world()
        if found_world is None:
            return []
        found: List[Tuple[str, Any]] = []
        for name, label in (('bodies', 'bodies'), ('contacts', 'contacts')):
            collection = getattr(found_world, name, None)
            if collection is not None:
                found.append((label, len(collection)))
        return found
    return rows


def install_default_providers(overlay: DebugOverlay, context: Any) -> None:
    """Register the sections every context can answer for itself."""
    overlay.register('Frame', frame_provider(context), order=10)
    overlay.register('Render', render_provider(context), order=20)
    overlay.register('View', platform_provider(context), order=30)
