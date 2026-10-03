"""Calls made on the render thread on behalf of other threads.

Work that runs on a background thread -- a download, a decode, a file read --
finishes with a result that has to be used where GL is: a scenegraph built, a
texture uploaded, a widget changed.  The worker does not do that itself.  It
queues the call::

    self.renderQueue.call(self.showModel, scene)

and the context makes it on the render thread, once a frame, before
:meth:`~OpenGLContext.context.Context.OnIdle` and before anything is drawn.
Every :class:`~OpenGLContext.context.Context` holds a queue as
``self.renderQueue`` and the main loop runs it; a program driving its own loop
calls :meth:`RenderQueue.run`.

``call`` is safe from any thread.  ``run`` is for the one thread that owns GL,
and a call is made on whichever thread ran it.  Calls are made in the order
they were queued, and a call that itself queues another has that one made on
the next ``run`` rather than in the same one, so a callback that keeps
re-queueing itself cannot hold up a frame.

A call that is not ready returns :data:`DEFER` and is made again, ahead of
anything queued since, on the next ``run``.
"""
from __future__ import annotations

import collections
import threading
from collections.abc import Callable
from typing import Any, Final

__all__ = ['DEFER', 'RenderQueue']

#: What a queued call returns to be made again on the next :meth:`RenderQueue.run`.
DEFER: Final = object()


class RenderQueue:
    """Calls waiting to be made on the render thread.

    ``wake`` is called, from the thread that queued a call, to get the render
    loop to run it: a context passes what asks its loop for a frame, so an
    otherwise idle window makes the call promptly.
    """

    def __init__(self, wake: Callable[[], Any] | None = None) -> None:
        self._wake = wake
        self._lock = threading.Lock()
        self._calls: collections.deque[tuple[Callable[..., Any], tuple[Any, ...],
                                             dict[str, Any]]] = collections.deque()
        self._before: list[Callable[[], Any]] = []

    def __len__(self) -> int:
        with self._lock:
            return len(self._calls)

    def call(self, function: Callable[..., Any], /, *arguments: Any,
             **named: Any) -> None:
        """Have ``function(*arguments, **named)`` called on the render thread."""
        with self._lock:
            self._calls.append((function, arguments, named))
        if self._wake is not None:
            self._wake()

    def before_run(self, function: Callable[[], Any]) -> None:
        """Have ``function()`` called at the start of every :meth:`run`.

        For work that has to happen on the render thread even when nothing has
        been queued: waiting for a load a recorded session had already finished,
        say.
        """
        self._before.append(function)

    def run(self) -> int:
        """Make the calls queued so far, on this thread; how many were made.

        A call that raises propagates to the caller of ``run`` and the calls
        after it stay queued for the next one.  A call that returns
        :data:`DEFER` is not counted.
        """
        for function in self._before:
            function()
        with self._lock:
            waiting = len(self._calls)
        made = 0
        deferred: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []
        try:
            for _each in range(waiting):
                with self._lock:
                    entry = self._calls.popleft()
                function, arguments, named = entry
                outcome = function(*arguments, **named)
                if outcome is DEFER:
                    deferred.append(entry)
                else:
                    made += 1
        finally:
            if deferred:
                with self._lock:
                    self._calls.extendleft(reversed(deferred))
        return made
