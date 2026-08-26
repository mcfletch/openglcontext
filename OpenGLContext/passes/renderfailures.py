"""What failed to draw, counted per cause and reported once.

A render pass catches every exception a node raises, so one bad node cannot take
the rest of the frame with it.  The cost of that is a scene which draws nothing
while the process exits successfully: a node that fails on every frame produces
one log line per frame at a level nobody is watching, and the only visible
symptom is a black window.

This is the bookkeeping that makes such a run say so.  A failure is logged in
full the first time its *cause* is seen -- the pass it happened in, the kind of
node, and the exception -- and after that only counted, so a node failing sixty
times a second costs one line rather than sixty.  At teardown the whole set is
reported together, which is the line that names an otherwise silent black frame.

It holds no GL and no scenegraph, only what it was told, so what counts as "the
same failure" is tested directly; see ``tests/unit/test_render_failures.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

__all__ = ['RenderFailure', 'RenderFailureLog']

#: Stands in for anything the log asked a node or an exception for and did not
#: get.  A failing node is by definition misbehaving, and a report that raised
#: while describing one would lose the report and the failure with it.
UNKNOWN = '?'


def _describe(value: Any, attribute: str) -> str:
    """``value``'s ``attribute``, or :data:`UNKNOWN` if it will not give one."""
    try:
        answer = getattr(value, attribute, None)
        return str(answer) if answer else UNKNOWN
    except Exception:
        return UNKNOWN


def _message(err: BaseException) -> str:
    """The first line of ``err``'s message.

    One line, because a ``GLError`` prints its whole failing call over a dozen
    of them -- the arguments, the C signature, the description -- and only the
    first distinguishes one cause from another.  The rest differ per node and
    would make every node its own "cause".
    """
    try:
        text = str(err).strip()
    except Exception:
        return UNKNOWN
    return text.splitlines()[0] if text else UNKNOWN


class RenderFailure:
    """One cause of failure, and how many times it has happened."""

    __slots__ = ('where', 'description', 'count')

    def __init__(self, where: str, description: str) -> None:
        #: Which part of the frame it happened in -- 'opaque', 'transparent'.
        self.where = where
        #: The node kind and the exception, as it will be reported.
        self.description = description
        self.count = 0

    def __repr__(self) -> str:
        return 'RenderFailure(%r, %r, count=%d)' % (
            self.where, self.description, self.count)


class RenderFailureLog:
    """The failures one session's rendering has produced.

    One per render pass, living as long as the pass does, so the counts describe
    the run rather than the frame.
    """

    def __init__(self) -> None:
        self._failures: Dict[Tuple[str, str, str, str], RenderFailure] = {}
        self._reported = False

    def record(self, where: str, node: Any, err: BaseException) -> bool:
        """Note that ``node`` failed to render in ``where``.

        Returns whether this cause has not been seen before, which is the
        caller's cue to log the traceback: the first occurrence carries the
        stack that explains it and the rest carry the same one again.
        """
        key = (where, type(node).__name__, type(err).__name__, _message(err))
        failure = self._failures.get(key)
        first = failure is None
        if failure is None:
            failure = self._failures[key] = RenderFailure(
                where, '%s %s: %s: %s' % (
                    key[1], _describe(node, 'DEF'), key[2], key[3]))
            # A cause seen after the summary was given is news again, so the
            # session can still account for itself if it renders on.
            self._reported = False
        failure.count += 1
        return first

    def summary(self) -> List[RenderFailure]:
        """Every cause recorded, the most frequent first."""
        return sorted(self._failures.values(), key=lambda f: -f.count)

    def report(self, logger: Optional[logging.Logger] = None) -> None:
        """Say what never drew, once for the run.

        At warning level and against the whole run rather than a frame: a scene
        that drew nothing is the thing a person looking at a black window needs
        told, and it is worth one paragraph at the end however long they watched.
        """
        if self._reported:
            return
        failures = self.summary()
        if not failures:
            return
        self._reported = True
        logger = logger if logger is not None else log
        logger.warning(
            'Rendering finished with %d node%s that never drew:\n%s',
            len(failures), '' if len(failures) == 1 else 's',
            '\n'.join('    %s (%d time%s, %s pass)' % (
                failure.description, failure.count,
                '' if failure.count == 1 else 's', failure.where)
                for failure in failures))

    def reset(self) -> None:
        """Forget everything, as for a new scene."""
        self._failures.clear()
        self._reported = False

    def __bool__(self) -> bool:
        return bool(self._failures)

    def __len__(self) -> int:
        return len(self._failures)
