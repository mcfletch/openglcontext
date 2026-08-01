"""A trace written to disk while the loop is slow, and the report that reads it.

:mod:`OpenGLContext.looptrace` divides a slow frame among named phases, which
answers *which subsystem* owned it.  It cannot answer which code inside that
subsystem, and it never will: by the time an iteration closes, the stack that
would have said has already unwound.  The overlay has the same limit from the
other end -- it shows the present, and a stutter is something you want to look
at *afterwards*, from the recording, not something you can catch by watching a
panel while playing.

So this module records.  A watcher thread samples the main thread's Python
stack **only while an iteration is already overrunning**, and consecutive slow
iterations are gathered into one *episode*, written to a JSON-lines file as it
ends.  An episode is the unit because it is the unit the complaint is in: "the
game went unplayable for four seconds" is one thing that happened, not two
hundred stalled frames, and a file with one line per frame is a log rather than
a diagnosis.

Each episode carries when it began, how long it lasted, its worst and mean
iteration, what the loop had been managing *before* it went wrong, the phase
breakdown, whatever state the application wanted recorded, and the stacks that
dominated the samples -- ranked, with the share of samples each held.  That
last is what turns ``match 54ms`` into a function and a line number.

**Sampling is gated on the stall itself.** A profiler that runs during the
frames that are fine is spending the one currency the question is about, so
:meth:`~OpenGLContext.looptrace.LoopTrace.overrunning` is asked before every
sample and a healthy loop is never sampled at all.  The cost when nothing is
wrong is one predicate per interval on a thread that is otherwise asleep.

Switched on by naming a file::

    OPENGLCONTEXT_STALL_TRACE=/tmp/stalls.jsonl python -m twitchoglc

and read back with::

    python -m OpenGLContext.stalltrace /tmp/stalls.jsonl

Nothing is written unless the variable is set, and a path that cannot be
written is a warning and a disabled journal -- never a reason a game will not
start.
"""

from __future__ import annotations

import collections
import datetime
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import (Any, Callable, Deque, Dict, Iterable, List, Optional,
                    Sequence, Tuple)

log = logging.getLogger(__name__)

__all__ = ['StackSampler', 'StallJournal', 'TRACE_ENV', 'describe_episode',
           'hot_stacks', 'install', 'overlay_context', 'read_episodes',
           'stack_of']

TRACE_ENV = 'OPENGLCONTEXT_STALL_TRACE'

#: One level of a sampled stack: file, line, function.
Level = Tuple[str, int, str]
Stack = Tuple[Level, ...]
Sample = Tuple[float, Stack]

#: How deep a sampled stack is kept. Deep enough to cross the engine into the
#: application, short enough that a runaway recursion cannot put ten thousand
#: frames in one record.
STACK_DEPTH = 30


def stack_of(frame: Any, depth: int = STACK_DEPTH) -> Stack:
    """The call stack above ``frame``, innermost first.

    Walked by hand rather than through :mod:`traceback` because this runs on a
    sampler's clock: the frames are wanted as three cheap values each, not as
    formatted lines with the source read off disk for every one of them.

    ``None`` -- a thread that has already gone -- is an empty stack, because a
    sampler that raced a shutdown must not be an error.
    """
    found: List[Level] = []
    while frame is not None and len(found) < depth:
        code = frame.f_code
        found.append((code.co_filename, frame.f_lineno, code.co_name))
        frame = frame.f_back
    return tuple(found)


def hot_stacks(stacks: Iterable[Stack], keep: int = 5) -> List[Dict[str, Any]]:
    """The stacks that held the most samples, worst first.

    Grouped by the *whole* stack rather than by the innermost function: two
    routes into the same helper are two different problems, and a leaf-only
    tally reports them as one.
    """
    counted = collections.Counter(stacks)
    total = sum(counted.values())
    if not total:
        return []
    return [
        {
            'count': count,
            'percent': round(100.0 * count / total, 1),
            'stack': ['%s:%d %s' % (os.path.basename(name), line, function)
                      for name, line, function in stack],
        }
        for stack, count in counted.most_common(keep)
    ]


def _function_key(level: Level) -> str:
    """A sampled level as the function it is in, without the line.

    Lines split a function across every statement inside it, which is exactly
    the fragmentation this tally exists to undo.
    """
    name, _line, function = level
    return '%s %s' % (os.path.basename(name), function)


def hot_functions(stacks: Iterable[Stack],
                  keep: int = 8) -> List[Dict[str, Any]]:
    """Where the samples were, per **function**, worst first.

    The tally that survives a function being reached a dozen ways.  Grouping by
    the whole stack -- which :func:`hot_stacks` does, and should -- splits one
    expensive function across every call site and every line that reaches it,
    so a function holding sixty per cent of a stall can read as a dozen entries
    at five per cent each and the trace looks like it found nothing.

    Two numbers per function, as any profiler gives:

    ``self_percent``
        Share of samples where this function was the one *running*.  Where the
        time is actually being spent.
    ``cumulative_percent``
        Share of samples where it was anywhere on the stack.  What the cost was
        *inside of*, which is how the expensive leaf gets attributed to the
        subsystem that chose to call it.

    A function that recurses counts once per sample, not once per frame, so a
    recursive descent cannot report more than the whole.
    """
    own: 'collections.Counter[str]' = collections.Counter()
    inside: 'collections.Counter[str]' = collections.Counter()
    total = 0
    for stack in stacks:
        if not stack:
            continue
        total += 1
        own[_function_key(stack[0])] += 1
        inside.update({_function_key(level) for level in stack})
    if not total:
        return []
    ranked = sorted(own.keys() | inside.keys(),
                    key=lambda name: (-own[name], -inside[name], name))
    return [
        {
            'name': name,
            'self': own[name],
            'self_percent': round(100.0 * own[name] / total, 1),
            'cumulative': inside[name],
            'cumulative_percent': round(100.0 * inside[name] / total, 1),
        }
        for name in ranked[:keep]
    ]


class StackSampler:
    """Samples one thread's Python stack, but only when told it is worth it.

    ``when`` is asked before every sample and is normally
    :meth:`LoopTrace.overrunning`, so the sampler sleeps through every healthy
    frame and wakes into the slow ones.  That is what makes it affordable to
    leave switched on: profiling the frames that are fine would spend exactly
    the thing being measured.
    """

    #: Samples held. At the default interval this is a bit over a minute of
    #: *stalled* time -- far longer than any episode worth reading, because
    #: nothing accumulates while the loop is healthy.
    KEEP = 8000

    def __init__(self, when: Callable[[], bool],
                 interval: float = 0.005,
                 keep: int = KEEP,
                 thread_id: Optional[int] = None,
                 clock: Any = time.perf_counter) -> None:
        self.when = when
        self.interval = interval
        # -1 rather than None for a main thread with no identity, which cannot
        # happen in a running interpreter: it keeps the lookup a plain int one
        # and makes "no such thread" the same harmless miss either way.
        if thread_id is None:
            thread_id = threading.main_thread().ident
        self.thread_id: int = -1 if thread_id is None else thread_id
        self._clock = clock
        self._samples: Deque[Sample] = collections.deque(maxlen=keep)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        #: Samples taken since the sampler started, including dropped ones.
        self.count = 0

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        """Begin sampling on a daemon thread (idempotent)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='stall-sampler',
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop sampling and wait for the thread to go (idempotent)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self.interval)

    # -- sampling ---------------------------------------------------------
    def sample(self) -> None:
        """Take one sample, if the loop is currently overrunning."""
        try:
            if not self.when():
                return
            frame = sys._current_frames().get(self.thread_id)
            if frame is None:
                return
            stack = stack_of(frame)
        except Exception:
            # The sampler races the interpreter by design; it must never be the
            # thing that ends the process it is watching.
            log.debug('stack sample failed', exc_info=True)
            return
        with self._lock:
            self._samples.append((self._clock(), stack))
            self.count += 1

    # -- reading ----------------------------------------------------------
    @property
    def held(self) -> int:
        """How many samples are currently retained."""
        with self._lock:
            return len(self._samples)

    def between(self, start: float, end: float) -> List[Sample]:
        """Every retained sample stamped within ``[start, end]``."""
        with self._lock:
            return [sample for sample in self._samples
                    if start <= sample[0] <= end]

    def complete_since(self, when: float) -> bool:
        """Whether nothing has been dropped from ``when`` onwards.

        An episode whose opening samples fell out of the buffer must say so:
        a truncated record that does not admit it reads as the whole story,
        and the hottest stack in the part that survived is not necessarily the
        hottest stack in the part that mattered.
        """
        with self._lock:
            if not self._samples:
                return True
            return self._samples[0][0] <= when


class _Episode:
    """One slow period being accumulated, before it is written out."""

    def __init__(self, started: float, wall: float, baseline_ms: float,
                 context: Dict[str, Any], continues: bool = False) -> None:
        self.started = started
        self.wall = wall
        self.baseline_ms = baseline_ms
        self.context = context
        self.continues = continues
        self.ended = started
        self.durations: List[float] = []
        self.stalled = 0
        self.phases: Dict[str, float] = {}

    def add(self, duration: float, phases: Dict[str, float], stalled: bool,
            now: float) -> None:
        self.durations.append(duration)
        self.ended = now
        if stalled:
            self.stalled += 1
        for name, seconds in phases.items():
            self.phases[name] = self.phases.get(name, 0.0) + seconds


class StallJournal:
    """Writes one JSON line per slow period, with the stacks that caused it.

    Subscribed to a :class:`~OpenGLContext.looptrace.LoopTrace` -- it is called
    with ``(duration, phases, stalled)`` after every iteration -- and holds an
    episode open across a run of slow ones, closing it when the loop has been
    healthy for ``gap`` iterations in a row.  That tolerance is why a slow
    period with the odd good frame in it stays one episode: a player
    experiences it as one, and so should the file.
    """

    def __init__(self, path: Any,
                 sampler: Any = None,
                 context: Optional[Callable[[], Dict[str, Any]]] = None,
                 gap: int = 4,
                 hot: int = 5,
                 max_seconds: float = 5.0,
                 stall_ms: Optional[float] = None,
                 baseline: Optional[Callable[[], float]] = None,
                 clock: Any = time.perf_counter,
                 now: Any = time.time) -> None:
        self.path = Path(path)
        self.sampler = sampler
        self.context = context
        self.gap = gap
        self.hot = hot
        self.max_seconds = max_seconds
        self._baseline = baseline
        self._clock = clock
        self._now = now
        self._episode: Optional[_Episode] = None
        self._good = 0
        self._written = 0
        self._recent: Deque[float] = collections.deque(maxlen=60)
        #: True once a write has failed; nothing is attempted afterwards.
        self.disabled = False
        self._open(stall_ms)

    # -- the file ---------------------------------------------------------
    def _open(self, stall_ms: Optional[float]) -> None:
        """Create the file and write the header naming this run."""
        header = {
            'kind': 'header',
            'version': 1,
            'started': _isoformat(self._now()),
            'stall_ms': stall_ms,
            'argv': list(sys.argv),
            'pid': os.getpid(),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('w') as handle:
                handle.write(json.dumps(header) + '\n')
        except OSError as error:
            log.warning('cannot write the stall trace to %s (%s); '
                        'no trace will be recorded', self.path, error)
            self.disabled = True

    def _write(self, record: Dict[str, Any]) -> None:
        """Append one record, flushed, so a kill -9 keeps what came before."""
        if self.disabled:
            return
        try:
            with self.path.open('a') as handle:
                handle.write(json.dumps(record) + '\n')
        except OSError as error:
            log.warning('cannot append to the stall trace %s (%s); '
                        'no more will be recorded', self.path, error)
            self.disabled = True

    # -- the listener -----------------------------------------------------
    def __call__(self, duration: float, phases: Dict[str, float],
                 stalled: bool) -> None:
        """Take one iteration from the loop trace."""
        now = self._clock()
        if stalled:
            if self._episode is None:
                self._episode = _Episode(now - duration, self._now(),
                                         self._baseline_ms(), self._context())
            self._good = 0
        elif self._episode is None:
            self._recent.append(duration)
            return
        else:
            self._good += 1
        self._episode.add(duration, phases, stalled, now)
        if self._good > self.gap:
            self._close_episode()
        elif now - self._episode.started >= self.max_seconds:
            # Cut it and carry on in a new part. A slow period that outlives
            # the session would otherwise be the one thing the file never
            # records -- and a session that ends while it is struggling is the
            # commonest way for one to end.
            self._close_episode()
            self._episode = _Episode(now, self._now(), self._baseline_ms(),
                                     self._context(), continues=True)

    def _baseline_ms(self) -> float:
        """What the loop had been managing before this went wrong.

        Without it, "slow" has nothing to be slow compared to: 200ms a frame is
        a catastrophe in a game that was running at 16 and unremarkable in one
        that was already at 180.
        """
        if self._baseline is not None:
            return self._baseline()
        if not self._recent:
            return 0.0
        ordered = sorted(self._recent)
        return ordered[len(ordered) // 2] * 1000.0

    def _context(self) -> Dict[str, Any]:
        """Whatever the application wants recorded alongside the stacks."""
        if self.context is None:
            return {}
        try:
            return self.context()
        except Exception:
            log.debug('stall trace context failed', exc_info=True)
            return {}

    # -- writing an episode ----------------------------------------------
    def _close_episode(self) -> None:
        episode, self._episode, self._good = self._episode, None, 0
        if episode is None:
            return
        self._written += 1
        self._write(self._describe(episode))

    def _describe(self, episode: _Episode) -> Dict[str, Any]:
        durations = episode.durations
        count = len(durations) or 1
        seconds = episode.ended - episode.started
        record: Dict[str, Any] = {
            'kind': 'episode',
            'episode': self._written,
            'at': _isoformat(episode.wall),
            'seconds': round(seconds, 3),
            'iterations': len(durations),
            'stalled': episode.stalled,
            'continues': episode.continues,
            'worst_ms': round(max(durations, default=0.0) * 1000.0, 1),
            'mean_ms': round(sum(durations) * 1000.0 / count, 1),
            'baseline_ms': round(episode.baseline_ms, 1),
            'phases_ms': {name: round(total * 1000.0 / count, 1)
                          for name, total
                          in sorted(episode.phases.items(),
                                    key=lambda pair: -pair[1])},
            'context': episode.context,
        }
        record.update(self._stacks(episode))
        return record

    def _stacks(self, episode: _Episode) -> Dict[str, Any]:
        """The hot stacks of this episode, and honesty about the sampling."""
        if self.sampler is None:
            return {'functions': [], 'hot': [],
                    'samples': {'taken': 0, 'incomplete': False}}
        samples = self.sampler.between(episode.started, episode.ended)
        stacks = [stack for _stamp, stack in samples]
        return {
            # Both, because they answer different questions: `functions` says
            # where the time went, `hot` says which route it took to get there.
            'functions': hot_functions(stacks),
            'hot': hot_stacks(stacks, self.hot),
            'samples': {
                'taken': len(samples),
                'incomplete': not self.sampler.complete_since(episode.started),
            },
        }

    def close(self) -> None:
        """Write any episode still open (idempotent).

        A run killed in the middle of a stall is exactly the run whose record
        is worth having, so shutting down is not a reason to discard one.
        """
        self._close_episode()


def _isoformat(when: float) -> str:
    """A wall-clock stamp readable next to anything else's log."""
    return datetime.datetime.fromtimestamp(
        when, tz=datetime.timezone.utc).isoformat()


def overlay_context(context: Any) -> Callable[[], Dict[str, Any]]:
    """Every section of the developer overlay, as the episode's context.

    The overlay already knows how to describe this application -- the map, the
    player, the renderer's counts, whatever the game registered -- so a trace
    gets all of it without anyone writing a second description that can drift
    from the first.  Read once when an episode opens, which is after the frame
    it belongs to has already been lost.
    """
    def rows() -> Dict[str, Any]:
        overlay = getattr(context, 'debugOverlay', None)
        if overlay is None:
            return {}
        return {section.title: dict(section.rows)
                for section in overlay.sections()}
    return rows


def install(trace: Any, path: Optional[str] = None,
            context: Any = None) -> Optional[StallJournal]:
    """Attach a journal and sampler to ``trace`` if a trace file was asked for.

    Answers the journal, or ``None`` when :data:`TRACE_ENV` is unset -- which
    is the usual case, and costs nothing at all.
    """
    asked = path if path is not None else os.environ.get(TRACE_ENV)
    if not asked:
        return None
    sampler = StackSampler(when=trace.overrunning)
    journal = StallJournal(
        asked, sampler=sampler,
        context=overlay_context(context) if context is not None else None,
        stall_ms=round(trace.stall_seconds * 1000.0, 3),
        baseline=lambda: float(trace.summary()['median_ms']))
    sampler.start()
    trace.subscribe(journal)
    log.warning('recording main-loop stalls to %s', journal.path)
    return journal


# -- reading it back --------------------------------------------------------

def read_episodes(path: Any) -> List[Dict[str, Any]]:
    """Every episode in a trace file, skipping the header.

    A line that will not parse is skipped rather than fatal: a run that was
    killed mid-write leaves a partial last line, and every episode before it is
    still worth having.
    """
    found: List[Dict[str, Any]] = []
    try:
        text = Path(path).read_text()
    except OSError as error:
        log.warning('cannot read the stall trace %s (%s)', path, error)
        return found
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            log.warning('skipping an unreadable line in %s', path)
            continue
        if record.get('kind') == 'episode':
            found.append(record)
    return found


def describe_episode(episode: Dict[str, Any], hot: int = 3) -> str:
    """One episode as text, for a terminal."""
    lines = [
        '%s  %.1fs, %d iterations (%d slow)' % (
            episode.get('at', '-'), episode.get('seconds', 0.0),
            episode.get('iterations', 0), episode.get('stalled', 0)),
        '  worst %sms, mean %sms, was running at %sms' % (
            episode.get('worst_ms'), episode.get('mean_ms'),
            episode.get('baseline_ms')),
    ]
    phases = episode.get('phases_ms') or {}
    if phases:
        lines.append('  phases: ' + ', '.join(
            '%s %sms' % (name, value) for name, value in phases.items()))
    samples = episode.get('samples') or {}
    if samples.get('incomplete'):
        lines.append('  NOTE: samples incomplete -- the start of this episode '
                     'fell out of the sampler buffer')
    # Functions first: this is the answer, and the stacks below are the
    # evidence for it. Reading a dozen near-identical stacks to work out which
    # function they have in common is work the report should have done.
    functions = episode.get('functions') or []
    if functions:
        lines.append('  where %d samples were, by function:' % (
            samples.get('taken', 0),))
        lines.append('      %6s %6s  %s' % ('self', 'cum', 'function'))
        for entry in functions:
            lines.append('      %5.1f%% %5.1f%%  %s' % (
                entry.get('self_percent', 0.0),
                entry.get('cumulative_percent', 0.0), entry.get('name', '?')))
    for entry in (episode.get('hot') or [])[:hot]:
        lines.append('  a route there, %.1f%% of samples:'
                     % (entry.get('percent', 0.0),))
        for level in entry.get('stack', [])[:12]:
            lines.append('      %s' % (level,))
    context = episode.get('context') or {}
    for title, rows in context.items():
        lines.append('  %s: %s' % (title, ', '.join(
            '%s=%s' % pair for pair in rows.items())))
    return '\n'.join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Print a trace file as a report, worst episode first."""
    import argparse

    parser = argparse.ArgumentParser(
        prog='python -m OpenGLContext.stalltrace',
        description='Report the slow periods recorded in a stall trace.')
    parser.add_argument('path', help='a file written by OPENGLCONTEXT_STALL_TRACE')
    parser.add_argument('--by', choices=('time', 'worst', 'length'),
                        default='worst',
                        help='order the episodes (default: worst first)')
    parser.add_argument('--limit', type=int, default=10,
                        help='how many episodes to show (default: 10)')
    options = parser.parse_args(argv)

    episodes = read_episodes(options.path)
    if not episodes:
        sys.stdout.write('no slow periods recorded in %s\n' % (options.path,))
        return 0
    order = {
        'time': lambda item: item.get('at', ''),
        'worst': lambda item: -(item.get('worst_ms') or 0.0),
        'length': lambda item: -(item.get('seconds') or 0.0),
    }[options.by]
    ranked = sorted(episodes, key=order)
    lost = sum(episode.get('seconds') or 0.0 for episode in episodes)
    sys.stdout.write('%d slow periods, %.1fs of them\n\n' % (len(episodes), lost))
    for episode in ranked[:options.limit]:
        sys.stdout.write(describe_episode(episode) + '\n\n')
    if len(ranked) > options.limit:
        sys.stdout.write('... and %d more (--limit)\n'
                         % (len(ranked) - options.limit,))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
