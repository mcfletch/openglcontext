"""A session journal read back, and run again.

A recording that can only be *read* leaves the developer trying to reproduce a
failure by hand from a description of it.  The point of recording every input
against the frame that acted on it is that the session can be **re-run**: the
same keys, the same clicks in the same places, on the same frames, against a
clock driven by the frame times that were recorded rather than by however fast
this machine happens to be.

Three pieces:

:class:`Recording`
    The file as data -- its header, its input grouped by frame, when each frame
    happened, and the exceptions and marks a report wants.

:class:`RecordedClock`
    The engine's time source (:mod:`OpenGLContext.events.systemtime`), reading
    the time the recording had reached at the frame being replayed.  Everything
    time-driven follows it, so a scene animates and a simulation steps by
    exactly the amounts they did.

:class:`Replay`
    Delivers each frame's input before that frame is drawn, and moves the clock
    on.

What replays exactly is what the session was a function of: its input and its
clock.  A game that reads ``time.time()`` for itself, seeds from the system
random source, or depends on how a thread happened to be scheduled will replay
approximately rather than exactly -- close enough to walk into the same wall,
which is usually the whole of what is wanted.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from OpenGLContext.events import systemtime

log = logging.getLogger(__name__)

__all__ = ['Recording', 'RecordedClock', 'Replay', 'read_records']


def read_records(path: Any) -> List[Dict[str, Any]]:
    """Every record in a journal file.

    A line that will not parse is skipped rather than fatal: a session killed
    mid-write leaves a partial last line, and it is the session that was killed
    whose records are worth having.
    """
    found: List[Dict[str, Any]] = []
    try:
        text = Path(path).read_text()
    except OSError as error:
        log.warning('cannot read the telemetry journal %s (%s)', path, error)
        return found
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            found.append(json.loads(line))
        except ValueError:
            log.debug('skipping an unreadable line in %s', path)
    return found


class Recording:
    """One session as data."""

    #: Which list each repeated kind of record collects into.
    BUCKETS = {
        'input': 'inputs', 'frames': 'blocks', 'exception': 'exceptions',
        'log': 'messages', 'mark': 'marks', 'state': 'states',
    }

    def __init__(self, records: Iterable[Dict[str, Any]]) -> None:
        self.records = list(records)
        self.header: Dict[str, Any] = {}
        self.inputs: List[Dict[str, Any]] = []
        self.blocks: List[Dict[str, Any]] = []
        self.exceptions: List[Dict[str, Any]] = []
        self.messages: List[Dict[str, Any]] = []
        self.marks: List[Dict[str, Any]] = []
        self.states: List[Dict[str, Any]] = []
        self.end: Dict[str, Any] = {}
        #: Where this session's randomness started; see
        #: :mod:`OpenGLContext.entropy`. Empty for a journal that recorded
        #: none -- an older one, or one cut off before it was written.
        self.entropy: Dict[str, Any] = {}
        self.truncated = False
        for record in self.records:
            kind = str(record.get('kind', ''))
            bucket = self.BUCKETS.get(kind)
            if bucket is not None:
                getattr(self, bucket).append(record)
            elif kind == 'header':
                self.header = record
            elif kind == 'end':
                self.end = record
            elif kind == 'entropy':
                self.entropy = record
            elif kind == 'truncated':
                self.truncated = True

    @classmethod
    def read(cls, path: Any) -> 'Recording':
        """The recording in a journal file."""
        return cls(read_records(path))

    # -- what is in it ----------------------------------------------------
    def inputs_by_frame(self) -> Dict[int, List[Dict[str, Any]]]:
        """Each frame's input, in the order it arrived, keyed by frame."""
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for record in self.inputs:
            grouped.setdefault(int(record.get('frame', 0)), []).append(record)
        return grouped

    def frame_times(self) -> List[float]:
        """When each frame started, in seconds from the start of the session.

        Recovered from the blocks rather than stored per frame: a block says
        when its first frame began and how long each frame in it took, and each
        frame's time is where those add up to.
        """
        times: List[float] = []
        for block in self.blocks:
            when = float(block.get('t', 0.0))
            for milliseconds in block.get('ms', ()):
                times.append(when)
                when += float(milliseconds) / 1000.0
        return times

    @property
    def frames(self) -> int:
        """How many frames the session lasted."""
        return sum(len(block.get('ms', ())) for block in self.blocks)

    def summary(self) -> Dict[str, Any]:
        """The session in one mapping, for a report or an overlay."""
        milliseconds = sorted(float(value) for block in self.blocks
                              for value in block.get('ms', ()))
        total = sum(milliseconds) / 1000.0
        return {
            'started': self.header.get('started'),
            'argv': self.header.get('argv', []),
            'frames': len(milliseconds),
            'seconds': round(total, 2),
            'fps': round(len(milliseconds) / total, 1) if total else 0.0,
            'median_ms': milliseconds[len(milliseconds) // 2] if milliseconds else 0.0,
            'worst_ms': milliseconds[-1] if milliseconds else 0.0,
            'stalls': sum(int(block.get('stalls', 0)) for block in self.blocks),
            'inputs': len(self.inputs),
            'exceptions': len(self.exceptions),
            'marks': len(self.marks),
            'truncated': self.truncated,
            'reason': self.end.get('reason'),
        }


class RecordedClock:
    """The engine's time source, reading what the recording had reached.

    times -- when each frame started, in seconds from the start of the session,
        as :meth:`Recording.frame_times` answers.
    start -- the world time the first frame happens at. By default the clock
        this one replaces is asked, so a replay continues the world's time
        rather than restarting it.

    Nothing advances it: :meth:`frame` says which frame is being drawn, which is
    where :class:`Replay` calls it.
    """

    def __init__(self, times: Iterable[float], start: Optional[float] = None) -> None:
        self.times = [float(value) for value in times]
        self.start = systemtime.systemTime() if start is None else float(start)
        self.frames = 0
        self._now = self.start
        self._previous: Any = None
        self._installed = False

    def frame(self, index: int) -> float:
        """Move to the time frame ``index`` was recorded at.

        A frame past the end of the recording holds the last recorded time: a
        replay that outlives its recording must not travel backwards, which a
        timer handed a time earlier than the last one it saw reports as
        negative progress.
        """
        self.frames = int(index)
        if self.times:
            elapsed = self.times[min(int(index), len(self.times) - 1)]
        else:
            elapsed = 0.0
        self._now = self.start + elapsed
        return self._now

    def __call__(self) -> float:
        return self._now

    # -- installing -------------------------------------------------------
    def install(self) -> 'RecordedClock':
        """Take over as the engine's time source."""
        if not self._installed:
            self._previous = systemtime.setTimeSource(self)
            self._installed = True
        return self

    def restore(self) -> None:
        """Give the previous time source back. Safe to call twice."""
        if self._installed:
            systemtime.setTimeSource(self._previous)
            self._installed = False
            self._previous = None

    def __enter__(self) -> 'RecordedClock':
        return self.install()

    def __exit__(self, *exception: Any) -> None:
        self.restore()

    def __repr__(self) -> str:
        return '<%s frame %d of %d, t=%.3f>' % (
            self.__class__.__name__, self.frames, len(self.times), self._now)


class Replay:
    """Delivers a recording's input, a frame at a time.

    recording -- a :class:`Recording`.
    deliver -- called with each input record; normally
        ``lambda record: synthetic.dispatch(context, record)``.
    start -- the world time the first frame happens at; see
        :class:`RecordedClock`.
    """

    def __init__(self, recording: Recording,
                 deliver: Callable[[Dict[str, Any]], Any],
                 start: Optional[float] = None) -> None:
        self.recording = recording
        self.deliver = deliver
        self._inputs = recording.inputs_by_frame()
        self.clock = RecordedClock(recording.frame_times(), start=start)
        #: Frames replayed so far, which is the frame about to be drawn.
        self.frames = 0
        self.last = max([recording.frames - 1] + list(self._inputs), default=-1)

    @property
    def finished(self) -> bool:
        """Whether every recorded frame and input has been replayed."""
        return self.frames > self.last

    def frame(self) -> int:
        """Deliver the input recorded against the frame about to be drawn.

        Called at the top of the frame, because that is where the input the
        recording stamped with this frame had arrived: the platform is polled,
        then the frame acts on what it found.
        """
        index = self.frames
        self.clock.frame(index)
        for record in self._inputs.get(index, ()):
            try:
                self.deliver(record)
            except Exception:
                # One input that will not go back is a gap in the replay, not
                # the end of it: whatever follows may still reach the failure.
                log.debug('could not replay %r', record, exc_info=True)
        self.frames += 1
        return index

    # -- the clock --------------------------------------------------------
    def install(self) -> 'Replay':
        """Take the engine's time source over with the recorded one."""
        self.clock.install()
        return self

    def remove(self) -> None:
        """Give the engine's time source back."""
        self.clock.restore()
