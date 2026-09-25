"""Holding a memo to every input its answer is made from.

A memo keeps an answer against what it was worked out from, and answers
again from that record while the record matches. An input the record leaves
out is one whose edit the memo does not see: the next frame is drawn from the
stale answer. :func:`check_memo_inputs` is the test for that. It is given a way to
ask the memo and one edit per declared input, applies the edits in turn, and
fails naming every input whose edit left the answer as it was::

    from OpenGLContext.testing.memo import check_memo_inputs

    def test_the_batching_memo_follows_every_input():
        shape = make_shape()
        check_memo_inputs(lambda: batching_answer(shape), {
            'material.reflector': lambda: setattr(material, 'reflector', mirror),
            'reflector.enabled': lambda: setattr(mirror, 'enabled', False),
        }, fresh=lambda: uncached_answer(shape))

Each edit must change what the computation answers; ``fresh``, the answer
worked out with no memo, is how the helper tells an edit the memo missed from
an edit that changed nothing. With ``fresh`` given, the memo's answer is
also compared with it after every edit, so a memo that moves to a wrong
answer fails as well as one that stays put.

The edits are cumulative: each is applied to the state the one before it
left, which is how a scene is edited while it is drawn.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Optional, Union

__all__ = ['MemoMissedInputs', 'check_memo_inputs']

Edit = Callable[[], object]
Edits = Mapping[str, Edit] | Iterable[tuple[str, Edit]]


class MemoMissedInputs(AssertionError):
    """A memo answered as before after an edit to one or more of its inputs."""


_STALE = 'the memo kept its answer after this input changed'
_WRONG = ('the memo answered differently from the computation after this '
          'input changed')
_NOTHING = ('this edit does not change what the computation answers, so it '
            'tests nothing; make it one that does')


def _default_same(a: Any, b: Any) -> bool:
    result = a == b
    if isinstance(result, bool):
        return result
    # An array compares element by element; the answers are the same when
    # every element is.
    return bool(getattr(result, 'all', lambda: result)())


def check_memo_inputs(ask: Callable[[], Any], inputs: Edits, *,
                fresh: Optional[Callable[[], Any]] = None,
                same: Optional[Callable[[Any, Any], bool]] = None) -> None:
    """Edit each of a memo's inputs in turn; raise where its answer did not follow.

    ``ask`` returns the memo's current answer. ``inputs`` names each input
    and gives a callable that edits it, as a mapping or as ``(name, edit)``
    pairs, applied in order. ``fresh`` returns what the computation answers
    with no memo in the way. ``same`` compares two answers, ``==`` by default
    (with arrays compared element by element).

    Raises :class:`MemoMissedInputs` listing every input whose edit the memo
    did not follow, every input after whose edit the memo's answer differs
    from ``fresh``, and every edit that did not change ``fresh`` at all.
    """
    equal = same or _default_same
    pairs = list(inputs.items()) if isinstance(inputs, Mapping) else list(inputs)
    if not pairs:
        raise ValueError('check_memo_inputs was given no inputs to edit')
    found: list[str] = []
    before = ask()
    expected_before = fresh() if fresh is not None else None
    for name, edit in pairs:
        edit()
        after = ask()
        if fresh is not None:
            expected = fresh()
            if equal(expected, expected_before):
                found.append('%s: %s' % (name, _NOTHING))
            elif not equal(after, expected):
                if equal(after, before):
                    found.append('%s: %s' % (name, _STALE))
                else:
                    found.append('%s: %s' % (name, _WRONG))
            expected_before = expected
        elif equal(after, before):
            found.append('%s: %s' % (name, _STALE))
        before = after
    if found:
        raise MemoMissedInputs('\n'.join(found))
