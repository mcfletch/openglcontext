"""A session journal read back, and run again.

A recording that can only be *read* leaves the developer trying to reproduce a
failure by hand from a description of it.  The point of recording every input
against the frame that acted on it is that the session can be **re-run**: the
same keys, the same clicks in the same places, on the same frames, against a
clock driven by the frame times that were recorded rather than by however fast
this machine happens to be.

Four pieces:

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

:class:`MarkComparison`
    What the game says about itself this time, against what it said when the
    session was recorded -- which is how a replay answers the only question it
    raises: did it play out the same way, and if not, where did the two part?

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

__all__ = ['MarkComparison', 'Recording', 'RecordedClock', 'Replay',
           'read_records']

#: How far two recorded numbers may differ and still be the same number. A
#: replay runs the same arithmetic on the same machine, so this is about the
#: last bit of a float rather than about tolerance for a different answer.
CLOSE_ENOUGH = 1e-9


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
    where :class:`Replay` calls it -- as that frame *ends*, which is where the
    recording's own clock moved (:class:`OpenGLContext.telemetry.record.RecordingClock`).

    Time is counted from the first recorded frame rather than from the start of
    the file, so installing this does not jump the world forward by however long
    the session spent starting up before it drew anything.
    """

    def __init__(self, times: Iterable[float], start: Optional[float] = None) -> None:
        self.times = [float(value) for value in times]
        self.start = systemtime.systemTime() if start is None else float(start)
        #: When the first recorded frame began, which this clock reads as
        #: ``start``.
        self.origin = self.times[0] if self.times else 0.0
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
        self._now = self.start + elapsed - self.origin
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
        #: The last frame whose input has gone out, so a frame's input is
        #: delivered once however many times it is asked for.
        self._delivered = -1
        self.last = max([recording.frames - 1] + list(self._inputs), default=-1)

    @property
    def finished(self) -> bool:
        """Whether every recorded frame and input has been replayed."""
        return self.frames > self.last

    def deliverFrame(self, index: int) -> bool:
        """Deliver the input recorded against frame ``index``, once.

        Answers whether this was the delivery: asked for a frame already
        delivered it does nothing, which is what lets the input go out at the
        moment the platform would have delivered it and the frame that draws it
        ask again without seeing it twice.
        """
        if index <= self._delivered:
            return False
        self._delivered = index
        for record in self._inputs.get(index, ()):
            try:
                self.deliver(record)
            except Exception:
                # One input that will not go back is a gap in the replay, not
                # the end of it: whatever follows may still reach the failure.
                log.debug('could not replay %r', record, exc_info=True)
        return True

    def frame(self) -> int:
        """Begin the frame about to be drawn, with its input delivered.

        Ordinarily :meth:`finish` has already delivered it, as the frame before
        this one ended; this is what delivers the first frame's, and any that
        a backend which never finishes a frame would otherwise never see.

        The clock is not moved here; see :meth:`finish`.
        """
        index = self.frames
        self.deliverFrame(index)
        self.frames += 1
        return index

    def finish(self) -> float:
        """The frame has ended: move the clock on, and offer the next input.

        Both at the *end* of the frame, because that is where the session being
        replayed had them.  The clock moved there
        (:class:`OpenGLContext.telemetry.record.RecordingClock`), so what the
        next frame reads here is what the next frame read then.  And the
        platform delivered input *between* frames -- it is polled, and then the
        application does the frame's work on what was found -- so input
        delivered at the top of the draw instead arrives after that work and is
        acted on a frame late, which is a shot, a weapon change and a jump each
        landing a frame after it did.
        """
        now = self.clock.frame(self.frames)
        self.deliverFrame(self.frames)
        return now

    # -- the clock --------------------------------------------------------
    def install(self) -> 'Replay':
        """Take the engine's time source over with the recorded one."""
        self.clock.install()
        return self

    def remove(self) -> None:
        """Give the engine's time source back."""
        self.clock.restore()


class MarkComparison:
    """The marks a replay makes, against the ones its recording holds.

    A replay is worth exactly what it reproduces, and the engine cannot tell
    whether it did: it delivered the same input against the same clock, and
    what came of that is the game's business.  The game's own marks are the
    game's account of what came of it, so matching them in order -- same mark,
    same fields, same frame -- is the session answering for itself.

    marks -- the ``mark`` records the journal holds, in the order they were
        written.

    Position rather than search: a replay is claimed to have done the same
    things in the same order, so the *n*-th mark answers the *n*-th mark, and
    anything else is a divergence.  Only the first one is described, because
    everything after it is that one's consequence.
    """

    def __init__(self, marks: Iterable[Dict[str, Any]]) -> None:
        self.expected = list(marks)
        #: Marks the replay has made, and how they went.
        self.made = 0
        self.matched = 0
        self.diverged = 0
        #: Where the two first parted, as a line a person reads, or None.
        self.first: Optional[str] = None

    # -- taking them in ---------------------------------------------------
    def mark(self, frame: int, name: str, fields: Dict[str, Any]) -> bool:
        """Answer the next recorded mark with this one; True if they agree."""
        expected = (self.expected[self.made] if self.made < len(self.expected)
                    else None)
        self.made += 1
        difference = _difference(expected, frame, name, fields)
        if difference is None:
            self.matched += 1
            return True
        self.diverged += 1
        if self.first is None:
            self.first = difference
        return False

    def reached(self, name: str, frame: int) -> bool:
        """Whether ``frame`` has caught up with the next recorded ``name``.

        What lets a replay put back something that did *not* come from the
        player: a level mounted when a worker thread finished with it, a
        download that landed.  Those arrive on whatever frame the disk decides,
        and a session where the level appeared three frames early is one where
        every recorded input after it was given to a world that had already
        started.

        True when the recording holds no such mark still to be answered, so a
        replay never waits for something that never happened.
        """
        when = self.expected_frame(name)
        return True if when is None else int(frame) >= when

    def overdue(self, name: str, frame: int) -> bool:
        """Whether the recording had made ``name`` by ``frame`` and this has not.

        The other half of :meth:`reached`, and the half that says *hurry*: a
        load can finish late as easily as early, and a replay that mounts a
        level nine frames after the recording did is as far out of step as one
        that mounted it nine frames before.  False when the recording holds no
        such mark, so nothing ever waits for something that never happened.
        """
        when = self.expected_frame(name)
        return when is not None and int(frame) >= when

    def expected_frame(self, name: str) -> Optional[int]:
        """The frame the next unanswered recorded ``name`` was made on."""
        for expected in self.expected[self.made:]:
            if str(expected.get('name', '')) == name:
                return int(expected.get('frame', 0))
        return None

    # -- what came of it --------------------------------------------------
    @property
    def missing(self) -> List[Dict[str, Any]]:
        """Recorded marks the replay has not reached: what it never did."""
        return self.expected[self.made:]

    def summary(self) -> Dict[str, Any]:
        """The comparison as numbers, for an overlay or a report."""
        return {'recorded': len(self.expected), 'made': self.made,
                'matched': self.matched, 'diverged': self.diverged,
                'missing': len(self.missing), 'first': self.first}

    def verdict(self) -> str:
        """One line saying whether this replay reproduced its recording."""
        if not self.expected and not self.made:
            return 'no marks to compare: the game marked nothing'
        if self.first is not None:
            return '%d of %d marks as recorded, then %s' % (
                self.matched, len(self.expected), self.first)
        if self.missing:
            return ('%s as recorded; %d the recording holds were never made'
                    % (_count(self.matched, 'mark'), len(self.missing)))
        if self.matched == 1:
            return '1 mark, as recorded'
        return '%d marks, all as recorded' % (self.matched,)

    def __repr__(self) -> str:
        return '<%s %s>' % (self.__class__.__name__, self.verdict())


def _count(number: int, thing: str) -> str:
    """``3 marks``, and ``1 mark``."""
    return '%d %s%s' % (number, thing, '' if number == 1 else 's')


def _difference(expected: Optional[Dict[str, Any]], frame: int, name: str,
                fields: Dict[str, Any]) -> Optional[str]:
    """How a mark differs from the one it should have answered, or None."""
    if expected is None:
        return 'a mark the recording does not hold: %s' % (
            _describe(name, fields),)
    if str(expected.get('name', '')) != name:
        return '%s where the recording has %s' % (
            _describe(name, fields),
            _describe(str(expected.get('name', '')),
                      expected.get('fields') or {}))
    written = _as_data(fields)
    if not _same(expected.get('fields') or {}, written):
        return '%s where the recording has %s' % (
            _describe(name, written),
            _describe(name, expected.get('fields') or {}))
    if int(expected.get('frame', -1)) != int(frame):
        return '%s on frame %d where the recording has frame %d' % (
            _describe(name, written), frame, int(expected.get('frame', -1)))
    return None


def _describe(name: str, fields: Dict[str, Any]) -> str:
    """A mark as a reader wants to see it: its name and what it carried."""
    if not fields:
        return name
    return '%s %s' % (name, ' '.join(
        '%s=%s' % (key, value) for key, value in sorted(fields.items())))


def _as_data(fields: Dict[str, Any]) -> Dict[str, Any]:
    """A live mark's fields as the data a journal would have written for them.

    Through the journal's own serialiser, so what is compared is what would
    have been recorded: a tuple and the list it is written as are the same
    mark, and so are an array and its numbers.
    """
    from OpenGLContext.telemetry.journal import as_data
    try:
        return dict(json.loads(json.dumps(fields, default=as_data)))
    except (TypeError, ValueError):
        return dict(fields)


def _same(expected: Any, found: Any) -> bool:
    """Whether two recorded values say the same thing.

    Numbers within :data:`CLOSE_ENOUGH`, because the same arithmetic run twice
    on one machine agrees to the last bit or two and a replay is not being
    asked about the last bit.
    """
    if isinstance(expected, dict) and isinstance(found, dict):
        return (set(expected) == set(found)
                and all(_same(expected[key], found[key]) for key in expected))
    if isinstance(expected, (list, tuple)) and isinstance(found, (list, tuple)):
        return (len(expected) == len(found)
                and all(_same(one, other)
                        for one, other in zip(expected, found,
                                              strict=False)))
    if isinstance(expected, bool) or isinstance(found, bool):
        return expected is found
    if isinstance(expected, (int, float)) and isinstance(found, (int, float)):
        return abs(float(expected) - float(found)) <= max(
            CLOSE_ENOUGH, CLOSE_ENOUGH * abs(float(expected)))
    return bool(expected == found)
