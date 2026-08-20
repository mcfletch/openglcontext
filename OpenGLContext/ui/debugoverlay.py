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

This is where the frame rate is drawn.
:class:`~OpenGLContext.framecounter.FrameCounter` measures it and does not draw
it: doing that would mean fixed-function calls, which mean nothing in a
core-profile context.  ``OPENGLCONTEXT_DISABLE_FPS_DISPLAY`` starts the overlay
hidden, so a captured frame has nothing over it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import (
    Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple,
)

from vrml import field

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.hudwidgets import HUDLayer, HUDWidget
from OpenGLContext.ui.metrics import FontMetrics

log = logging.getLogger(__name__)

__all__ = [
    'DebugOverlay', 'DebugPanel', 'DebugSection', 'Fixed', 'LaidOutRow',
    'audio_provider', 'format_value', 'frame_provider', 'loop_provider',
    'render_provider', 'platform_provider', 'physics_provider',
    'simulation_provider', 'telemetry_provider', 'install_default_providers',
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


@dataclass(frozen=True)
class Fixed:
    """A number that keeps its decimals however round it happens to be.

    For the rows that change every frame.  :func:`_number` drops trailing
    zeros, which is right for a position — ``512.00`` is three characters of
    nothing on a crowded line — and wrong for a frame rate: 60, 59.97 and 60.1
    are three different widths in three consecutive frames, and a number that
    changes width sixty times a second is a number nobody can read.
    """

    value: float
    decimals: int = 2

    def __str__(self) -> str:
        return '%.*f' % (self.decimals, self.value)


def format_value(value: Any) -> str:
    """A provider's value as the one line that will be drawn for it.

    Formatting here rather than in the provider is what keeps the providers
    trivial -- a provider hands over the number it has -- and what keeps the
    overlay's columns reading consistently when a dozen unrelated subsystems
    write into them.
    """
    if value is None:
        return '-'
    if isinstance(value, Fixed):
        return str(value)
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
            # Fixed decimals: these two change every frame, and a value that
            # changes *width* every frame twitches on the screen.
            ('fps', Fixed(counter.recentFps())),
            ('frame ms', Fixed(last * 1000.0)),
            ('frames', count),
            ('viewport', '%dx%d' % (width, height)),
        ]
    return rows


def loop_provider(context: Any) -> Provider:
    """What the whole main loop costs, and which part of it costs that.

    The section to read when the Frame section looks healthy and the game does
    not.  ``fps`` above measures the inside of ``OnDraw`` and only for frames
    that changed something; ``loop fps`` here measures iterations of wall
    clock, which is the rate a player's hands feel.  The two disagreeing is the
    diagnosis: the renderer is keeping up and something outside it is not.

    ``loop ms`` beside ``worst ms`` says the same thing about a single hitch
    that a median cannot -- a healthy median next to a worst ten times larger
    is a loop that stutters -- and the phase rows below say where the worst one
    went.  Phases divide the iteration rather than overlapping it, so they add
    up to ``loop ms`` and the largest is the culprit by construction.

    Left out entirely by a backend that runs its own loop and never opens an
    iteration: rows of zeroes would read as a loop doing nothing at all, which
    is a worse answer than no rows.
    """
    def rows() -> Rows:
        trace = getattr(context, 'loopTrace', None)
        if trace is None:
            return []
        summary = trace.summary()
        if not summary['iterations']:
            return []
        found: List[Tuple[str, Any]] = [
            ('loop fps', Fixed(summary['rate'])),
            ('loop ms', Fixed(summary['median_ms'])),
            ('worst ms', Fixed(summary['worst_ms'])),
            ('stalls', summary['stalls']),
        ]
        culprit = trace.worst_phase()
        if culprit is not None:
            found.append(('last stall', '%s %.0fms' % culprit))
        # Worst first, which `phases_ms` already orders them by: a panel that
        # reads top-down as most-to-least expensive answers "where did it go"
        # without the reader comparing every row against every other.
        found.extend((name, Fixed(milliseconds))
                     for name, milliseconds in trace.phases_ms().items())
        return found
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


def simulation_provider(simulation: Callable[[], Any]) -> Provider:
    """Whether a background physics thread is getting the turns it asked for.

    The companion to :func:`physics_provider`, which reports on the *world*;
    this reports on the thread stepping it.  A simulation that falls behind
    resets its schedule rather than running the missed ticks back to back --
    the only alternative is a spiral -- so being starved costs simulated time
    silently, and everything in the world moves slowly.  That is
    indistinguishable from wrong gravity, wrong units or a wrong timestep until
    ``sim hz`` is on the panel beside the rate that was asked for.

    Takes a callable for the same reason :func:`physics_provider` does: a
    simulation is built when a level loads and replaced when the next one does.
    """
    def rows() -> Rows:
        found_sim = simulation()
        if found_sim is None:
            return []
        found: List[Tuple[str, Any]] = [
            ('sim hz', Fixed(found_sim.rate())),
            ('asked', Fixed(found_sim.sim_hz)),
            ('steps', found_sim.steps),
        ]
        # Zero is the healthy answer and a healthy row is a row not worth the
        # space; a non-zero one is the whole reason the section exists.
        dropped = found_sim.dropped
        if dropped:
            found.append(('dropped', dropped))
        return found
    return rows


def audio_provider(context: Any) -> Provider:
    """What this context's sound is doing, and whether it is doing it at all.

    The one subsystem whose state cannot be seen, which is exactly why it wants
    a place on the overlay: a sound that is not audible may be off, may have no
    device, may have lost its voice to a louder one, or may simply be too far
    away, and no amount of listening tells those four apart.

    Reported even when there is no engine, because "audio: idle" -- nothing in
    this scene has asked to make a noise -- is itself the answer to the most
    common question.
    """
    def rows() -> Rows:
        from OpenGLContext.audio import scene as audioscene
        if getattr(context, 'contextDefinition', None) is None:
            return []
        return list(audioscene.describe(context).items())
    return rows


def telemetry_provider(context: Any) -> Provider:
    """Whether this session is being recorded or replayed, and how far in.

    A player asked to "switch recording on and reproduce it" needs to see that
    it is on, and somebody watching a replay needs to know how much of the
    recording is left -- past its end a replay is an ordinary live session
    again, and nothing else on the screen would say so.

    Nothing at all when neither is happening, which is the usual case: an empty
    provider is a section the overlay leaves out.
    """
    def rows() -> Rows:
        session = getattr(context, 'telemetry', None)
        if session is None:
            return []
        recorder = getattr(session, 'recorder', None)
        if recorder is not None:
            journal = session.journal
            from OpenGLContext import entropy
            found = [('recording', journal.path.name),
                     ('seed', entropy.seed()),
                     ('frames', recorder.frames),
                     ('records', journal.written),
                     ('size', '%.1fkB' % (journal.bytes / 1024.0,))]
            if journal.disabled:
                found.append(('state', 'stopped: could not write'))
            elif journal.saturated:
                found.append(('state', 'at its ceiling'))
            return found
        replay = getattr(session, 'replay', None)
        if replay is None:
            return []
        path = getattr(session, 'path', None)
        return [('replaying', path.name if path is not None else 'a recording'),
                ('frame', '%d/%d' % (replay.frames, replay.recording.frames)),
                ('state', 'finished' if replay.finished else 'running')]
    return rows


def install_default_providers(overlay: DebugOverlay, context: Any) -> None:
    """Register the sections every context can answer for itself."""
    overlay.register('Frame', frame_provider(context), order=10)
    # Directly under Frame, because the two are read against each other: a
    # healthy `fps` over a poor `loop fps` is the whole diagnosis, and a reader
    # who has to hunt down the panel for the second number will not compare it.
    overlay.register('Loop', loop_provider(context), order=15)
    # Beside Loop, because both are about the session rather than the scene,
    # and because a recording is a thing you want to see is running.
    overlay.register('Session', telemetry_provider(context), order=16)
    overlay.register('Render', render_provider(context), order=20)
    overlay.register('View', platform_provider(context), order=30)
    overlay.register('Audio', audio_provider(context), order=35)
