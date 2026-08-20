"""Attaching a session recorder to a running context, and taking it off again.

A recording has to see **what the platform delivered**, before anything in the
engine has had a chance to sink it: an event an overlay swallowed is still an
event the player produced, and a replay that never delivers it does not
reproduce the session.  The entry points -- ``ProcessEvent``, ``addPickEvent``,
``recordPointerMotion``, ``OnResize``, ``OnDraw`` -- are each overridden by a
mixin somewhere in a context's ancestry, so "before anything in the engine" is
*above the whole class hierarchy*, which is what an attribute on the instance
is.  That is what a :class:`Tap` installs, and it installs nothing at all unless
telemetry is switched on, so a game that is not recording pays nothing.

Frames are timed from the same tap: one ``OnDraw`` is one frame on every
backend, and timing the interval between the end of one and the end of the next
counts everything a frame costs -- polling the platform, the application's idle
work, the wait for a redraw and the draw itself -- rather than only the part
inside the renderer.  Where the backend also divides its loop into phases (see
:mod:`OpenGLContext.looptrace`) that breakdown is summed into the block.
"""

from __future__ import annotations

import functools
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from OpenGLContext import entropy
from OpenGLContext.events import synthetic
from OpenGLContext.telemetry.journal import (DEFAULT_MAX_BYTES, SessionJournal,
                                             default_path)
from OpenGLContext.telemetry.recorder import SessionRecorder
from OpenGLContext.telemetry.replay import Recording, Replay

log = logging.getLogger(__name__)

__all__ = ['MAX_MB_ENV', 'REPLAY_ENV', 'ReplaySession', 'SessionRecording',
           'TELEMETRY_ENV', 'Tap', 'install', 'start', 'start_replay']

#: Record this session to the named file. ``1`` or ``auto`` writes to a dated
#: file under the user's application-data directory.
TELEMETRY_ENV = 'OPENGLCONTEXT_TELEMETRY'

#: Replay the named journal into this session instead of taking live input.
REPLAY_ENV = 'OPENGLCONTEXT_TELEMETRY_REPLAY'

#: The journal's ceiling, in megabytes.
MAX_MB_ENV = 'OPENGLCONTEXT_TELEMETRY_MAX_MB'

#: Log records from here are never put into the journal: a journal that cannot
#: be written says so through the logging relay, and recording that would be
#: the write that just failed.
OWN_LOGGERS = __name__.rsplit('.', 1)[0]

#: Values of :data:`TELEMETRY_ENV` that mean "somewhere sensible" rather than a
#: path.
AUTOMATIC = ('1', 'auto', 'yes', 'on', 'true')


class Tap:
    """Sees a bound method's calls without changing what it does.

    Installed as an attribute of the *instance*, which puts it above every
    class in the ancestry -- so it sees a call before any override in the
    hierarchy has had the chance to answer it instead of passing it on.

    before -- called with the same arguments, before the method runs.
    after -- called with the exception that escaped, or ``None``, once it has.

    Neither hook can affect the call: one that raises is a debug line and
    nothing more, because a tap is diagnostic equipment and does not get to be
    the thing that breaks the frame.
    """

    def __init__(self, target: Any, name: str,
                 before: Optional[Callable[..., Any]] = None,
                 after: Optional[Callable[[Optional[BaseException]], Any]] = None
                 ) -> None:
        self.target = target
        self.name = name
        self.installed = False
        original = getattr(target, name, None)
        if not callable(original):
            log.debug('nothing to tap: %r has no %s', type(target).__name__, name)
            return
        self.original = original

        @functools.wraps(original)
        def wrapper(*arguments: Any, **named: Any) -> Any:
            if before is not None:
                _guard(before, *arguments, **named)
            error: Optional[BaseException] = None
            try:
                return original(*arguments, **named)
            except BaseException as caught:
                error = caught
                raise
            finally:
                if after is not None:
                    _guard(after, error)

        setattr(target, name, wrapper)
        self.installed = True

    def remove(self) -> None:
        """Take the tap off, leaving the method the class defines."""
        if not self.installed:
            return
        self.installed = False
        try:
            delattr(self.target, self.name)
        except AttributeError:
            setattr(self.target, self.name, self.original)


def _guard(hook: Callable[..., Any], *arguments: Any, **named: Any) -> None:
    try:
        hook(*arguments, **named)
    except Exception:
        log.debug('a telemetry hook failed', exc_info=True)


class _LogRelay(logging.Handler):
    """Puts warnings, errors and logged exceptions into the journal.

    Most of what a game knows about a failure it has already survived is in its
    log, and a log that scrolled past in a terminal nobody kept is not evidence.
    Anything the telemetry package logs itself is left out: a journal that could
    not be written says so through this handler, and recording that would be
    the write that fails.
    """

    def __init__(self, recorder: SessionRecorder, level: int = logging.WARNING):
        super().__init__(level)
        self.recorder = recorder

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(OWN_LOGGERS):
            return
        try:
            if record.exc_info and record.exc_info[1] is not None:
                self.recorder.exception(record.exc_info[1],
                                        thread=record.threadName)
                return
            self.recorder.message(record.levelno, record.name,
                                  record.getMessage())
        except Exception:                       # noqa: BLE001 - diagnostic
            self.handleError(record)


class SessionRecording:
    """One context, recorded: the taps, the hooks and the journal together.

    A game reaches this as ``context.telemetry`` and uses it to say what the
    engine cannot know::

        context.telemetry.mark('level-loaded', map='ztn3dm1', bots=4)
    """

    def __init__(self, context: Any, journal: SessionJournal,
                 recorder: SessionRecorder,
                 clock: Any = time.perf_counter) -> None:
        self.context = context
        self.journal = journal
        self.recorder = recorder
        self._clock = clock
        self._taps: List[Tap] = []
        self._handler: Optional[logging.Handler] = None
        self._hooks: Dict[str, Any] = {}
        self._drawStarted = 0.0
        self._previousEnd: Optional[float] = None
        #: The last exception written, so the same one reaching this by two
        #: routes -- escaping the draw and then unwinding the main loop -- is
        #: one record rather than two.
        self._recorded: Optional[BaseException] = None
        self.closed = False
        self._install()

    # -- what the game says -----------------------------------------------
    def mark(self, name: str, **fields: Any) -> None:
        """Note something the application knows and the engine cannot."""
        self.recorder.mark(name, **fields)

    @property
    def path(self) -> Any:
        """The file being written."""
        return self.journal.path

    # -- wiring -----------------------------------------------------------
    def _install(self) -> None:
        context = self.context
        self._taps = [
            Tap(context, 'OnDraw', before=self._beginFrame, after=self._endFrame),
            Tap(context, 'ProcessEvent', before=self._event),
            Tap(context, 'addPickEvent', before=self._pickEvent),
            Tap(context, 'recordPointerMotion', before=self._pointer),
            Tap(context, 'forgetPointerOrigin', before=self._pointerOrigin),
            Tap(context, 'OnResize', before=self._resize),
        ]
        self._handler = _LogRelay(self.recorder)
        logging.getLogger().addHandler(self._handler)
        self._hooks = {
            'excepthook': sys.excepthook,
            'threading': threading.excepthook,
        }
        sys.excepthook = self._systemExcepthook
        threading.excepthook = self._threadExcepthook

    def close(self, reason: str = 'quit') -> None:
        """Stop recording, write the ending and let the context go.

        Safe to call twice, and safe to call from a shutdown path that will not
        run a ``finally`` block afterwards -- which is where it is called from,
        because a session killed in the middle of its failure is the one whose
        record is worth having.
        """
        if self.closed:
            return
        # Before anything is torn down: a session closed from a ``finally``
        # while an exception is still propagating is a session that ended
        # *because* of it, and the hooks that would otherwise catch it run
        # after every ``finally`` has already emptied the journal.
        in_flight = sys.exc_info()[1]
        if in_flight is not None:
            self.exception(in_flight, fatal=True)
            reason = 'exception'
        self.closed = True
        for tap in self._taps:
            tap.remove()
        self._taps = []
        if self._handler is not None:
            logging.getLogger().removeHandler(self._handler)
            self._handler = None
        if self._hooks:
            sys.excepthook = self._hooks['excepthook']
            threading.excepthook = self._hooks['threading']
            self._hooks = {}
        self.recorder.close(reason)
        self.journal.close()
        if getattr(self.context, 'telemetry', None) is self:
            self.context.telemetry = None

    # -- what went wrong --------------------------------------------------
    def exception(self, error: BaseException, thread: Optional[str] = None,
                  fatal: bool = False) -> None:
        """Record an exception, unless it is the one just recorded.

        One failure reaches this by more than one route -- it escapes the draw,
        then unwinds the main loop, then meets the exception hook -- and each
        route is worth having for the failures the others miss.  Identity is
        what separates a second route from a second failure.
        """
        if error is self._recorded:
            return
        self._recorded = error
        self.recorder.exception(error, thread=thread, fatal=fatal)

    # -- the frame --------------------------------------------------------
    def _beginFrame(self, *arguments: Any, **named: Any) -> None:
        self._drawStarted = self._clock()

    def _endFrame(self, error: Optional[BaseException]) -> None:
        now = self._clock()
        if error is not None and isinstance(error, Exception):
            self.exception(error, fatal=True)
        duration = (None if self._previousEnd is None
                    else now - self._previousEnd)
        self._previousEnd = now
        trace = getattr(self.context, 'loopTrace', None)
        # The most recently *completed* iteration: this frame is inside the
        # open one, whose phases have not been charged yet. A block sums sixty
        # frames of them, where being one frame out does not show.
        last = getattr(trace, 'last', None)
        phases = last[1] if last else None
        self.recorder.frame(duration, draw=now - self._drawStarted,
                            phases=phases,
                            stalled=bool(duration
                                         and duration >= self._stallSeconds()))

    def _stallSeconds(self) -> float:
        """What counts as a stall here.

        The loop trace's threshold, which the environment can set, and its
        default for a backend that measures no loop of its own -- a stall is a
        stall whether or not anything was timing the iteration it happened in.
        """
        trace = getattr(self.context, 'loopTrace', None)
        seconds = getattr(trace, 'stall_seconds', None)
        if seconds:
            return float(seconds)
        from OpenGLContext.looptrace import LoopTrace
        return LoopTrace.DEFAULT_STALL_MS / 1000.0

    # -- the input --------------------------------------------------------
    def _event(self, event: Any, *arguments: Any, **named: Any) -> None:
        record = synthetic.describe(event)
        if record is not None:
            self.recorder.input(record)

    def _pickEvent(self, event: Any, *arguments: Any, **named: Any) -> None:
        record = synthetic.describe(event)
        if record is not None:
            # It went to the selection pass, and a replay must send it the same
            # way: that is the route that resolves what was under the cursor.
            record['pick'] = True
            self.recorder.input(record)

    def _pointer(self, x: Any, y: Any, *arguments: Any, **named: Any) -> None:
        self.recorder.input({'type': 'pointer', 'x': x, 'y': y})

    def _pointerOrigin(self, *arguments: Any, **named: Any) -> None:
        self.recorder.input({'type': 'pointer-origin'})

    def _resize(self, width: Any = 0, height: Any = 0,
                *arguments: Any, **named: Any) -> None:
        self.recorder.input({'type': 'resize',
                             'width': int(width), 'height': int(height)})

    # -- the exceptions ---------------------------------------------------
    def _systemExcepthook(self, kind: Any, error: Any, traceback: Any) -> None:
        _guard(self.exception, error, fatal=True)
        _guard(self.journal.close)
        self._hooks.get('excepthook', sys.__excepthook__)(kind, error, traceback)

    def _threadExcepthook(self, arguments: Any) -> None:
        error = getattr(arguments, 'exc_value', None)
        thread = getattr(getattr(arguments, 'thread', None), 'name', None)
        if error is not None:
            _guard(self.exception, error, thread=thread, fatal=True)
        self._hooks.get('threading', threading.__excepthook__)(arguments)


class ReplaySession:
    """One context, driven by a recording instead of by a player."""

    def __init__(self, context: Any, replay: Replay, path: Any = None) -> None:
        self.context = context
        self.replay = replay
        #: The journal being replayed, for anything reporting what is running.
        self.path = Path(path) if path is not None else None
        self._announced = False
        self._tap = Tap(context, 'OnDraw', before=self._beginFrame)
        replay.install()

    def _beginFrame(self, *arguments: Any, **named: Any) -> None:
        self.replay.frame()
        if self.replay.finished and not self._announced:
            self._announced = True
            log.warning('the recording has been replayed in full (%d frames); '
                        'the session continues live from here',
                        self.replay.frames)

    def close(self, reason: str = 'stopped') -> None:
        """Stop replaying and give the engine's clock back. Safe to call twice.

        ``reason`` is accepted and ignored, so a context can finish whichever
        kind of session it has without asking which kind it is: a replay writes
        nothing, so it has nowhere to put one.
        """
        self._tap.remove()
        self.replay.remove()
        if getattr(self.context, 'telemetry', None) is self:
            self.context.telemetry = None


# -- switching it on --------------------------------------------------------

def start(context: Any, path: Any = None,
          max_bytes: Optional[int] = None) -> SessionRecording:
    """Record ``context`` to ``path``, answering the recording.

    A path that cannot be written is a warning and a journal that writes
    nothing, never a reason a game will not start: the taps are installed
    either way, so switching recording on can never change how a session
    behaves.
    """
    from OpenGLContext import stalltrace
    # Captured before the journal exists, so the state written down is the one
    # the session goes on to draw from rather than one a few numbers later.
    randomness = entropy.capture()
    journal = SessionJournal(
        path if path is not None else default_path(),
        header=_header(context, randomness),
        max_bytes=DEFAULT_MAX_BYTES if max_bytes is None else max_bytes)
    recorder = SessionRecorder(journal, state=stalltrace.overlay_context(context))
    recorder.entropy(randomness)
    session = SessionRecording(context, journal, recorder)
    context.telemetry = session
    if not journal.disabled:
        log.warning('recording this session to %s', journal.path)
    return session


def start_replay(context: Any, path: Any) -> Optional[ReplaySession]:
    """Replay the journal at ``path`` into ``context``.

    Answers ``None`` when the file holds no session, so a mistyped path is a
    warning and a game that runs normally rather than one that appears to have
    lost its input.
    """
    recording = Recording.read(path)
    if not recording.inputs and not recording.blocks:
        log.warning('%s holds no recorded session; nothing to replay', path)
        return None
    # Before anything is built: a game generates its world in OnInit, and a
    # world generated from different numbers is a different world for the
    # recorded input to arrive in.
    entropy.restore(recording.entropy)
    replay = Replay(recording,
                    lambda record: synthetic.dispatch(context, record))
    session = ReplaySession(context, replay, path)
    context.telemetry = session
    log.warning('replaying %s: %d frames, %d inputs',
                path, recording.frames, len(recording.inputs))
    return session


def install(context: Any) -> Optional[Any]:
    """Whatever the environment asked for, or ``None`` if it asked for nothing.

    Called by every context as it is built (``Context.setupTelemetry``), so a
    game switches recording on from outside itself with no code at all.
    """
    replaying = os.environ.get(REPLAY_ENV)
    if replaying:
        return start_replay(context, replaying)
    asked = os.environ.get(TELEMETRY_ENV)
    if not asked:
        return None
    path = None if asked.lower() in AUTOMATIC else asked
    return start(context, path, max_bytes=_configured_ceiling())


def _configured_ceiling() -> Optional[int]:
    """The journal's ceiling in bytes, as the environment asks for it.

    A value that is not a number is a warning and the default, never a failure
    to start: a mistyped diagnostic switch must not be the reason a game will
    not run.
    """
    asked = os.environ.get(MAX_MB_ENV)
    if not asked:
        return DEFAULT_MAX_BYTES
    try:
        return int(float(asked) * 1024 * 1024)
    except ValueError:
        log.warning('%s=%r is not a number of megabytes; using %d',
                    MAX_MB_ENV, asked, DEFAULT_MAX_BYTES)
        return DEFAULT_MAX_BYTES


def _describeDefinition(definition: Any) -> Dict[str, Any]:
    """The window this session asked for, as data.

    Read defensively field by field: a context definition is a VRML node whose
    fields are arrays and enumerations rather than the numbers and strings a
    journal can hold, and one that will not convert must cost that line of the
    header rather than the recording.
    """
    found: Dict[str, Any] = {}
    try:
        found['size'] = [int(value) for value in getattr(definition, 'size', ())]
    except (TypeError, ValueError):
        pass
    for name in ('profile', 'title'):
        value = getattr(definition, name, None)
        if value:
            found[name] = str(value)
    return found


def _header(context: Any, randomness: Optional[Dict[str, Any]] = None
            ) -> Dict[str, Any]:
    """What is known about this session before it has drawn anything.

    The rest of the description of the application arrives in the ``state``
    records, from the developer overlay, once there is something to describe.
    The seed is here as well as in its own record, because it is one number
    and the first line is where a reader looks for it.
    """
    header: Dict[str, Any] = {'context': type(context).__name__}
    if randomness and 'seed' in randomness:
        header['seed'] = randomness['seed']
    try:
        from OpenGLContext import __version__
        header['engine'] = str(__version__)
    except Exception:                           # noqa: BLE001 - diagnostic
        pass
    definition = getattr(context, 'contextDefinition', None)
    if definition is not None:
        header['definition'] = _describeDefinition(definition)
    from OpenGLContext import renderoptions
    settings = {name: os.environ[name] for name in renderoptions.ENVIRONMENT
                if name in os.environ}
    if settings:
        header['environment'] = settings
    return header
