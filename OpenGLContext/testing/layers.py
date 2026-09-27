"""Driving an optional frame layer that always fails.

Reflections, zone probe captures and bloom add to a frame that is complete
without them. When one fails -- a driver refusing a framebuffer format, a
value no layer can draw with -- the frame is drawn without it, the failure is
reported once, and the layer is not tried again: a layer that fails in one
frame fails in the next, and one retried every frame costs, logs and asks for
frames for ever (:class:`~OpenGLContext.passes.layerguard.LayerGuard`).

:func:`check_failing_layer` holds a layer to that. It replaces the layer's
method with one that raises, draws ``frames`` frames, and fails where the
layer was entered more than ``attempts`` times, where the failure was reported
other than ``reports`` times, or where the layer asked for more than
``most_asked`` frames after it first failed::

    from OpenGLContext.testing.layers import check_failing_layer
    from OpenGLContext.testing.scenes import scene_context

    with scene_context([mirror, floor]) as context:
        context.OnDraw(force=1)
        check_failing_layer(lambda: context.OnDraw(force=1),
                            type(context.renderPass), '_renderReflections',
                            context=context)

A report is a log record at ``ERROR`` or above carrying the exception raised;
a frame asked for is a call of ``context.triggerRedraw``.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from collections.abc import Callable, Iterator
from typing import Any, Optional

__all__ = ['LayerFailure', 'LayerRun', 'LayerNotIsolated', 'check_failing_layer',
           'drive_failing_layer']


class LayerFailure(RuntimeError):
    """What the replaced layer raises."""


class LayerNotIsolated(AssertionError):
    """A failing layer was retried, reported more than once, or kept asking for frames."""


@dataclass(frozen=True)
class LayerRun:
    """What ``frames`` frames with the layer failing came to.

    ``attempts`` is how many times the layer was entered, ``reports`` how
    many log records reported its failure, ``asked`` how many frames it asked
    for from the first failure on, and ``drawn`` how many frames completed.
    """

    frames: int
    attempts: int
    reports: int
    asked: int
    drawn: int


class _Reports(logging.Handler):
    """Log records carrying a :class:`LayerFailure`."""

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.found: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and isinstance(record.exc_info[1], LayerFailure):
            self.found.append(record)


@contextlib.contextmanager
def _reports() -> Iterator[_Reports]:
    handler = _Reports()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)


def drive_failing_layer(frame: Callable[[], object], owner: Any, name: str, *,
                        frames: int = 10, context: Any = None) -> LayerRun:
    """Draw ``frames`` frames with ``owner.name`` raising, and count what followed.

    ``frame`` draws one frame; ``owner`` is the class (or object) whose
    attribute ``name`` is the layer, replaced for the frames and put back
    afterwards. ``context``, where given, has its ``triggerRedraw`` counted.
    An exception out of ``frame`` itself is not caught: a layer whose failure
    stops the frame fails the test there.
    """
    attempts = [0]
    asked = [0]
    failed = [False]

    def failing(*_args: Any, **_named: Any) -> Any:
        attempts[0] += 1
        failed[0] = True
        raise LayerFailure('%s fails, as check_failing_layer makes it' % (name,))

    restore_trigger: Optional[Callable[[], None]] = None
    if context is not None:
        trigger = context.triggerRedraw

        def counting(*args: Any, **named: Any) -> Any:
            if failed[0]:
                asked[0] += 1
            return trigger(*args, **named)
        # An override the context already had is put back; otherwise the
        # counting one is removed, uncovering the class's own.
        own_trigger = vars(context).get('triggerRedraw')
        context.triggerRedraw = counting

        def restore_trigger() -> None:
            if own_trigger is not None:
                context.triggerRedraw = own_trigger
            else:
                del context.triggerRedraw

    # Put back where it was found: an attribute ``owner`` holds itself is
    # restored, and one it inherits (or an instance's class provides) is
    # uncovered again by removing the replacement.
    held = vars(owner).get(name) if hasattr(owner, '__dict__') else None
    setattr(owner, name, failing)
    drawn = 0
    try:
        with _reports() as reports:
            for _ in range(frames):
                frame()
                drawn += 1
    finally:
        if held is not None:
            setattr(owner, name, held)
        else:
            delattr(owner, name)
        if restore_trigger is not None:
            restore_trigger()
    return LayerRun(frames, attempts[0], len(reports.found), asked[0], drawn)


def check_failing_layer(frame: Callable[[], object], owner: Any, name: str, *,
                        frames: int = 10, context: Any = None, attempts: int = 1,
                        reports: int = 1, most_asked: int = 0) -> LayerRun:
    """The :class:`LayerRun` of a failing layer; raise where it was not isolated.

    Raises :class:`LayerNotIsolated` where the layer was entered other than
    ``attempts`` times, reported other than ``reports`` times, or asked for
    more than ``most_asked`` frames after its first failure.
    """
    run = drive_failing_layer(frame, owner, name, frames=frames, context=context)
    found = []
    if run.attempts != attempts:
        found.append('the layer was entered %d times in %d frames; it should be '
                     '%d, and then switched off' % (run.attempts, frames, attempts))
    if run.reports != reports:
        found.append('its failure was reported %d times; it should be %d'
                     % (run.reports, reports))
    if run.asked > most_asked:
        found.append('it asked for %d frames after it failed; the bound is %d'
                     % (run.asked, most_asked))
    if found:
        raise LayerNotIsolated('%s: %s' % (name, '; '.join(found)))
    return run
