"""What a session is worth writing down, and when.

Every rule about a recording lives here, and nothing else does: no GL, no
window, no file.  A :class:`SessionRecorder` is handed a ``write`` callable and
a clock, which is what lets the frame an input is stamped with, the way a
frame's records are grouped and the point at which a block of frame times is
closed all be pinned against exact numbers rather than sampled ones.  The file
is :mod:`OpenGLContext.telemetry.journal`'s business and the taps that feed this
are :mod:`OpenGLContext.telemetry.record`'s.

**Input belongs to the frame that will act on it.**  A key pressed while the
platform is being polled is read by the update that follows, so it is stamped
with the frame that has not been drawn yet -- and a replay hands it over as the
frame *before* that one ends, which is where the platform handed it over, so
the frame's own work finds it exactly as it did.  That correspondence is as much
a part of the format as the fields are.

**A frame's records are held until the frame ends**, which is what lets a
hundred pointer positions inside one frame collapse to the one position anything
could observe.  A mark or an exception is written the moment it is made
instead: it may be the last thing the process manages to say.
"""

from __future__ import annotations

import logging
import time
import traceback as traceback_module
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

__all__ = ['SessionRecorder', 'milliseconds']

#: Input whose successive reports inside one frame say the same thing: only
#: where the pointer ended up is observable by the time the frame runs, so the
#: earlier positions are a hundred lines a second saying nothing.
COLLAPSING = ('pointer', 'mousemove')

Record = Dict[str, Any]


class SessionRecorder:
    """One session's worth of input, frame times, exceptions and marks.

    write -- called with each record, a JSON-safe mapping. A write that raises
        costs that record and never the game.
    clock -- seconds from any origin; the recorded ``t`` is measured from the
        first reading.
    block -- how many frames share one ``frames`` record.
    state_seconds -- how often the application's own description is sampled.
    state -- a callable answering that description, normally the developer
        overlay's sections (see
        :func:`OpenGLContext.stalltrace.overlay_context`), so a game's map,
        player and counters reach the file without a second description that
        can drift from the first.
    """

    #: Frames to a block.  About a second of a healthy loop: enough that the
    #: file is a hundredth the size of one line per frame, short enough that
    #: a session killed outright loses only the last second of timings.
    BLOCK = 60

    #: How often the application describes itself. Often enough to say where
    #: the player was when it went wrong, rarely enough to be free.
    STATE_SECONDS = 5.0

    def __init__(self, write: Callable[[Record], None],
                 clock: Any = time.perf_counter,
                 block: int = BLOCK,
                 state_seconds: float = STATE_SECONDS,
                 state: Optional[Callable[[], Dict[str, Any]]] = None) -> None:
        self._write = write
        self._clock = clock
        self.block = int(block)
        self.state_seconds = float(state_seconds)
        self._state = state
        self.started = clock()
        #: Frames finished.  The frame *in progress* is therefore this number,
        #: which is what an input arriving now will be stamped with.
        self.frames = 0
        self.closed = False
        self._pending: List[Record] = []
        self._times: List[float] = []
        self._draws: List[Optional[float]] = []
        self._phases: Dict[str, float] = {}
        self._stalls = 0
        self._block_started: Optional[float] = None
        #: Seconds of frames written down so far, added up as the file holds
        #: them; see :meth:`frame`.
        self._timeline = 0.0
        self._state_at = float('-inf')

    # -- the clock --------------------------------------------------------
    @property
    def elapsed(self) -> float:
        """Seconds since the recording began."""
        return float(self._clock() - self.started)

    # -- taking it in -----------------------------------------------------
    def input(self, record: Record) -> None:
        """Record one input, exactly as the platform delivered it.

        Held until the frame it belongs to ends, so a run of pointer positions
        can collapse to the last of them -- but only a run: an input of any
        other kind between two of them keeps them apart, because where the
        pointer was when a button went down is the whole of some bugs.
        """
        if self.closed:
            return
        entry = dict(record)
        entry['kind'] = 'input'
        if (entry.get('type') in COLLAPSING and self._pending
                and self._pending[-1].get('type') == entry.get('type')):
            self._stamp(entry)
            self._pending[-1] = entry
            return
        self._hold(entry)

    def frame(self, duration: Optional[float], draw: Optional[float] = None,
              phases: Optional[Dict[str, float]] = None,
              stalled: bool = False) -> float:
        """Finish one frame, writing out everything it collected.

        duration -- seconds from the previous frame's start to this one's: the
            period the player feels, which includes polling the platform and
            whatever the application does when the loop is idle. ``None`` for
            the first frame, which has no predecessor to be measured against
            and is worth only the time inside its own draw.
        draw -- seconds inside ``OnDraw``.
        phases -- the loop's own breakdown of the iteration, where the backend
            measures one (see :mod:`OpenGLContext.looptrace`).

        Answers what this frame is **worth on the recorded timeline** -- the
        duration as the file will hold it, to a hundredth of a millisecond --
        which is what the world's clock moves by while recording, so that a
        replay adding the file's own numbers up arrives at the same instants.
        """
        if self.closed:
            return 0.0
        if duration is None:
            duration = draw or 0.0
        step = milliseconds(duration) / 1000.0
        if self._block_started is None:
            # The timeline this session is written down against, which is the
            # sum of the frames written down rather than a second measurement
            # of the same thing: a replay has only the file to add up, and two
            # accounts of when a frame happened is one of them being wrong.
            self._block_started = self._timeline
        self._timeline += step
        self._times.append(duration)
        self._draws.append(draw)
        if phases:
            for name, seconds in phases.items():
                self._phases[name] = self._phases.get(name, 0.0) + seconds
        if stalled:
            self._stalls += 1
        self._sampleState()
        self._flush()
        self.frames += 1
        if len(self._times) >= self.block:
            self._closeBlock()
        return step

    def mark(self, name: str, /, **fields: Any) -> None:
        """Note something the application knows and the engine cannot.

        ``recorder.mark('level-loaded', map='ztn3dm1', bots=4)`` -- the line a
        reader looks for first when a file is four minutes long and the failure
        is at the end of it.
        """
        self._emit({'kind': 'mark', 'name': name, 'fields': fields})

    def entropy(self, state: Dict[str, Any]) -> None:
        """Where this session's randomness starts.

        Its own record rather than a line of the header: the seed is one
        number a person can read, and the generator states beside it are a few
        thousand, which would make the one line a reader looks at first
        unreadable. See :mod:`OpenGLContext.entropy`.
        """
        record = dict(state)
        record['kind'] = 'entropy'
        self._emit(record)

    def exception(self, error: BaseException, thread: Optional[str] = None,
                  fatal: bool = False) -> None:
        """Record an exception and the stack it came from.

        fatal -- it ended the session rather than being handled.
        """
        record: Record = {
            'kind': 'exception',
            'type': type(error).__name__,
            'message': str(error),
            'traceback': _traceback(error),
            'fatal': bool(fatal),
        }
        if thread:
            record['thread'] = thread
        self._emit(record)

    def message(self, level: int, logger: str, message: str,
                traceback: Optional[List[str]] = None) -> None:
        """Record a warning or an error somebody logged."""
        record: Record = {
            'kind': 'log',
            'level': logging.getLevelName(level),
            'logger': logger,
            'message': message,
        }
        if traceback:
            record['traceback'] = traceback
        self._emit(record)

    def close(self, reason: str = 'end') -> None:
        """Write everything still held, and the ending. Safe to call twice."""
        if self.closed:
            return
        self._flush()
        self._closeBlock()
        self.closed = True
        # Straight to the writer: `closed` is already set, so `_emit` would
        # drop it, and this is the one record that says the file is whole.
        self._deliver({'kind': 'end', 't': round(self.elapsed, 4),
                       'frame': self.frames, 'frames': self.frames,
                       'reason': reason})

    # -- writing it out ---------------------------------------------------
    def _stamp(self, record: Record) -> Record:
        record['t'] = round(self.elapsed, 4)
        record['frame'] = self.frames
        return record

    def _hold(self, record: Record) -> None:
        """Keep a record until the frame it belongs to ends."""
        self._pending.append(self._stamp(record))

    def _emit(self, record: Record) -> None:
        """Write a record now, after anything the frame is already holding.

        For what may be the last thing said: an exception, a mark, the ending.
        Ordering is kept by flushing first, so the file reads in the order
        things happened.
        """
        if self.closed:
            return
        self._flush()
        self._deliver(self._stamp(record))

    def _flush(self) -> None:
        pending, self._pending = self._pending, []
        for record in pending:
            self._deliver(record)

    def _deliver(self, record: Record) -> None:
        try:
            self._write(record)
        except Exception:
            # A recording is diagnostic equipment; it does not get to be the
            # thing that ends the session it is recording.
            log.debug('could not write a telemetry record', exc_info=True)

    def _closeBlock(self) -> None:
        """Write the frame times collected so far, if there are any."""
        if not self._times:
            return
        count = len(self._times)
        # Stamped here rather than through ``_stamp``: a block is *about* the
        # frames it holds, so its ``frame`` is the first of them rather than
        # wherever the session has since got to.
        record: Record = {
            'kind': 'frames',
            'frame': self.frames - count,
            't': round(self._block_started or 0.0, 4),
            'ms': [milliseconds(seconds) for seconds in self._times],
        }
        if any(draw is not None for draw in self._draws):
            record['draw_ms'] = [None if draw is None else milliseconds(draw)
                                 for draw in self._draws]
        if self._phases:
            record['phases_ms'] = {name: round(seconds * 1000.0, 2)
                                   for name, seconds in self._phases.items()}
        if self._stalls:
            record['stalls'] = self._stalls
        self._times = []
        self._draws = []
        self._phases = {}
        self._stalls = 0
        self._block_started = None
        self._deliver(record)

    def _sampleState(self) -> None:
        """Ask the application to describe itself, at most every so often."""
        if self._state is None:
            return
        now = self.elapsed
        if now - self._state_at < self.state_seconds:
            return
        self._state_at = now
        try:
            sections = self._state()
        except Exception:
            log.debug('the telemetry state provider failed', exc_info=True)
            return
        if sections:
            self._hold({'kind': 'state', 'sections': sections})


def milliseconds(seconds: float) -> float:
    """Seconds as the milliseconds a journal holds for them.

    A hundredth of a millisecond, which is finer than anything a frame can be
    measured to and coarse enough that a file is not mostly digits.  One place
    for it because the recorded timeline is the sum of these: what is written
    down and what the world's clock moves by have to be the same number.
    """
    return round(seconds * 1000.0, 2)


def _traceback(error: BaseException) -> List[str]:
    """An exception's traceback as the lines a reader wants, newlines removed."""
    formatted = traceback_module.format_exception(
        type(error), error, error.__traceback__)
    return [line for chunk in formatted for line in chunk.rstrip().split('\n')]
