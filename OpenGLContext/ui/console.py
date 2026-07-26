"""A console over the frame: scrollback, an input line, and commands.

It is the scrolling machinery a licence notice uses with an input line under it,
which is why it comes last: nothing here is new except the command registry and
the logging handler.

The handler is the point of it.  Engine warnings -- a texture that would not
load, a shader that fell back, a driver that refused a format -- go to Python
logging, which in a packaged game goes nowhere a player can see.  Attaching
:class:`ConsoleLogHandler` puts them on screen::

    panel = console.console_panel(registry=game.commands)
    logging.getLogger('OpenGLContext').addHandler(
        console.ConsoleLogHandler(panel))
    context.pushOverlay(panel)
"""

from __future__ import annotations

import logging
from gettext import gettext as _
from typing import Any, Callable, Dict, List, Optional, Tuple

from vrml import field

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.layout import Column, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.scroll import ScrollViewport
from OpenGLContext.ui.widgets import Label, TextField, Widget

__all__ = ['CommandRegistry', 'ConsoleLine', 'ConsoleView', 'ConsolePanel',
           'ConsoleLogHandler', 'console_panel', 'PROMPT']

#: Printed before an echoed command, so what was typed reads apart from output.
PROMPT = '> '
#: How many lines of scrollback are kept by default.
DEFAULT_SCROLLBACK = 500


class ConsoleLine:
    """One line of scrollback and how loud it was."""

    __slots__ = ('text', 'level')

    def __init__(self, text: str, level: int = logging.INFO) -> None:
        self.text = text
        self.level = level


class CommandRegistry:
    """The commands a console knows, and how to run one.

    A game adds to it; ``help`` and ``clear`` are here because a console
    without them is a console nobody can find their way around.
    """

    def __init__(self) -> None:
        self._commands: Dict[str, Tuple[Callable[..., Any], str]] = {}
        self.add('help', self._help, _('list the commands, or describe one'))
        self.add('clear', self._clear, _('empty the scrollback'))

    def add(self, name: str, function: Callable[..., Any],
            help: str = '') -> None:
        """Register a command, called as ``function(panel, *words)``."""
        self._commands[name] = (function, help)

    def names(self) -> List[str]:
        """Every registered command, in the order help lists them."""
        return sorted(self._commands)

    def dispatch(self, panel: Any, line: str) -> Optional[str]:
        """Run a typed line and return what to print, or None for nothing.

        A command that raises reports its exception rather than taking the
        frame down: a console is where things are tried out, and half of what
        is tried is wrong.
        """
        words = line.split()
        if not words:
            return None
        name, arguments = words[0], words[1:]
        entry = self._commands.get(name)
        if entry is None:
            return _('unknown command %r; try "help"') % (name,)
        try:
            result = entry[0](panel, *arguments)
        except Exception as error:              # noqa: BLE001 - reported, not raised
            return '%s: %s' % (type(error).__name__, error)
        return None if result is None else str(result)

    def _help(self, panel: Any, name: str = '') -> str:
        if name:
            entry = self._commands.get(name)
            if entry is None:
                return _('no such command: %s') % (name,)
            return '%s -- %s' % (name, entry[1])
        width = max(len(name) for name in self._commands)
        return '\n'.join('%-*s  %s' % (width, name, self._commands[name][1])
                         for name in self.names())

    @staticmethod
    def _clear(panel: Any) -> None:
        if panel is not None:
            panel.clear()
        return None


class ConsoleView(Widget):
    """The scrollback: a list of lines, drawn one per row.

    Its own widget rather than a :class:`~OpenGLContext.ui.widgets.Label` so
    each line keeps its level and can be coloured by it, and so appending does
    not rebuild one enormous string.
    """

    PROTO = 'ConsoleView'
    #: Lines kept; the oldest are dropped past this.  A console left open for
    #: an hour of warnings would otherwise be a memory leak with a scrollbar.
    maximumLines = field.newField('maximumLines', 'SFInt32', 1,
                                  DEFAULT_SCROLLBACK)

    def __init__(self, **named: Any) -> None:
        super(ConsoleView, self).__init__(**named)
        self.lines: List[ConsoleLine] = []

    def write(self, text: str, level: int = logging.INFO) -> None:
        """Append text, split into lines, dropping the oldest past the limit."""
        for part in str(text).split('\n'):
            self.lines.append(ConsoleLine(part, level))
        limit = int(self.maximumLines)
        if limit and len(self.lines) > limit:
            del self.lines[:len(self.lines) - limit]

    def clear(self) -> None:
        """Forget the scrollback."""
        self.lines = []

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        widest = max([len(line.text) for line in self.lines], default=0)
        return (widest * metrics.char_width,
                len(self.lines) * metrics.line_height)

    def paint(self, renderer: Any) -> None:
        skin = renderer.skin
        top = self.rect.top - renderer.metrics.char_height
        for index, line in enumerate(self.lines):
            row = Rect(self.rect.x, top - index * renderer.metrics.line_height,
                       self.rect.width, renderer.metrics.char_height)
            renderer.textIn(row, line.text, _levelColour(skin, line.level))


def _levelColour(skin: Any, level: int) -> Any:
    if level >= logging.ERROR:
        return skin.consoleError
    if level >= logging.WARNING:
        return skin.consoleWarning
    return skin.consoleText


class ConsolePanel(Panel):
    """A console screen: scrollback above, one line of input below."""

    PROTO = 'ConsolePanel'

    def paint(self, renderer: Any) -> None:
        """Draw the panel with the skin's console fill.

        Darker and less translucent than a settings panel: a console is read
        line by line, and text over a moving world is hard to follow.
        """
        skin = renderer.skin
        renderer.frame(self.rect, skin.consoleFill,
                       skin._image(skin.panelImage))
        renderer.border(self.rect, skin.panelBorder, int(skin.borderWidth))
        if self.title:
            renderer.textIn(self.titleRect(renderer.metrics), self.title,
                            skin.titleText)

    def __init__(self, **named: Any) -> None:
        super(ConsolePanel, self).__init__(**named)
        self.registry: Optional[CommandRegistry] = None
        self.view: Optional[ConsoleView] = None
        self.body: Optional[ScrollViewport] = None
        self.entry: Optional[TextField] = None
        #: Commands typed, most recent last, walked with the arrow keys.
        self.history: List[str] = []
        self._historyAt: Optional[int] = None

    # -- output -----------------------------------------------------------
    def write(self, text: str, level: int = logging.INFO) -> None:
        """Add to the scrollback and follow it down."""
        if self.view is None:
            return
        self.view.write(text, level)
        self._follow()

    def clear(self) -> None:
        """Empty the scrollback -- what the ``clear`` command does."""
        if self.view is not None:
            self.view.clear()

    def _follow(self) -> None:
        """Keep the newest line in sight.

        Only ever downward: a console that yanked the view back while somebody
        was reading older output would be unusable in exactly the moment they
        needed it.
        """
        if self.body is not None:
            self.body.scrollTo(self.body.maximumScroll)

    def arrange_content(self, metrics: Any) -> None:
        super(ConsolePanel, self).arrange_content(metrics)
        self._follow()

    # -- input ------------------------------------------------------------
    def submit(self) -> None:
        """Run what is on the input line."""
        if self.entry is None or self.registry is None:
            return
        line = self.entry.read().strip()
        if not line:
            return
        self.write(PROMPT + line)
        self.history.append(line)
        self._historyAt = None
        self.entry.write('')
        self.entry.caret = 0
        result = self.registry.dispatch(self, line)
        if result:
            self.write(result)

    def recall(self, step: int) -> bool:
        """Walk the history: -1 for older, +1 for newer."""
        if self.entry is None or not self.history:
            return False
        if self._historyAt is None:
            self._historyAt = len(self.history)
        position = min(len(self.history), max(0, self._historyAt + step))
        self._historyAt = position
        self.entry.write(self.history[position]
                         if position < len(self.history) else '')
        self.entry.caret = len(self.entry.read())
        return True

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name == '<return>':
            self.submit()
            return True
        if name == '<up>' and self.focused_widget is self.entry:
            return self.recall(-1)
        if name == '<down>' and self.focused_widget is self.entry:
            return self.recall(1)
        return super(ConsolePanel, self).key(name, modifiers)


class ConsoleLogHandler(logging.Handler):
    """A logging handler that writes into a console panel.

    Held by the handler rather than the panel so a console that has been closed
    simply stops receiving: a game may open and close several over a session,
    and a handler still writing into a dead one is a leak with no symptom.
    """

    def __init__(self, panel: ConsolePanel, level: int = logging.NOTSET) -> None:
        super(ConsoleLogHandler, self).__init__(level)
        self.panel = panel

    def emit(self, record: logging.LogRecord) -> None:
        if self.panel is None or self.panel.closed:
            return
        try:
            self.panel.write(self.format(record), record.levelno)
        except Exception:                       # pragma: no cover - never fail a log
            self.handleError(record)


def console_panel(registry: Optional[CommandRegistry] = None,
                  title: str = '', modal: bool = True,
                  scrollback: int = DEFAULT_SCROLLBACK) -> ConsolePanel:
    """A console ready to be pushed onto a context's overlay stack."""
    view = ConsoleView(name='view', maximumLines=scrollback)
    body = ScrollViewport(name='body', flex=1, children=[view])
    # Flexible so the input line runs the width of the console rather than
    # stopping at whatever a default field measures to.
    entry = TextField(name='entry', flex=1)
    panel = ConsolePanel(
        title=title or _('Console'), name='console', modal=modal, fill=True,
        children=[Column(spacing=4, children=[
            body,
            Row(spacing=4, children=[
                Label(text=PROMPT.strip()), entry]),
        ])])
    panel.registry = registry or CommandRegistry()
    panel.view = view
    panel.body = body
    panel.entry = entry
    panel.focus(entry)
    return panel
