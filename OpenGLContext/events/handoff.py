"""The hand-off between a service's worker and the render thread.

A service (physics, audio) keeps its state on one worker and is driven by
commands from any thread. Two objects carry the traffic:

:class:`Inbox`
    Commands from any thread to the worker. ``post`` is safe from every thread,
    ``drain`` is called by the worker and answers the commands in the order they
    were posted, and ``wait`` blocks the worker until there is something to do.

:class:`Updates`
    Changes the worker makes to the scene, for the render thread. ``set`` on a
    node field keeps the last value written to each (node, field); ``call``
    keeps a function call. The render thread makes them with ``apply``, once a
    frame, before the frame is drawn. Called on the render thread itself, ``set``
    assigns at once, so the code that makes a change is the same wherever it runs.

Neither holds GL or a scenegraph of its own, so a test drives them without a
window.
"""
from __future__ import annotations

import collections
import logging
import threading
from collections.abc import Callable
from typing import Any

__all__ = ['Inbox', 'Updates']

log = logging.getLogger(__name__)


class Inbox:
    """Commands waiting for a worker, posted from any thread.

    ``wake`` is called by the posting thread after each post, for a worker that
    sleeps on something other than :meth:`wait`.
    """

    def __init__(self, wake: Callable[[], Any] | None = None) -> None:
        self._wake = wake
        self._lock = threading.Lock()
        self._commands: collections.deque[Any] = collections.deque()
        self._arrived = threading.Event()

    def __len__(self) -> int:
        with self._lock:
            return len(self._commands)

    def post(self, command: Any) -> None:
        """Queue ``command`` for the worker."""
        with self._lock:
            self._commands.append(command)
            self._arrived.set()
        if self._wake is not None:
            self._wake()

    def drain(self) -> list[Any]:
        """Take every queued command, oldest first."""
        with self._lock:
            commands = list(self._commands)
            self._commands.clear()
            self._arrived.clear()
        return commands

    def wait(self, timeout: float | None = None) -> bool:
        """Block until a command is queued; whether one is."""
        self._arrived.wait(timeout)
        with self._lock:
            return bool(self._commands)


class Updates:
    """Scene changes a worker queues for the render thread.

    ``owner`` is the identity of the render thread; None names the thread that
    makes the object, and :meth:`bind` names another. ``wake`` is called by a
    worker that queues something, to have the loop draw a frame in which
    :meth:`apply` runs.
    """

    def __init__(self, wake: Callable[[], Any] | None = None, owner: int | None = None) -> None:
        self._wake = wake
        self._owner = threading.get_ident() if owner is None else owner
        self._lock = threading.Lock()
        self._sets: dict[tuple[Any, str], Any] = {}
        self._calls: collections.deque[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = (
            collections.deque())

    def bind(self) -> None:
        """Make the calling thread the one that owns the scene."""
        self._owner = threading.get_ident()

    def pending(self) -> int:
        """How many writes and calls wait for :meth:`apply`."""
        with self._lock:
            return len(self._sets) + len(self._calls)

    def set(self, node: Any, **fields: Any) -> None:
        """Assign ``fields`` on ``node``: now on the owning thread, else at the next apply.

        A field written more than once before the apply keeps its last value. The
        node must be hashable, as scenegraph nodes are.
        """
        if threading.get_ident() == self._owner:
            for name, value in fields.items():
                setattr(node, name, value)
            return
        with self._lock:
            for name, value in fields.items():
                self._sets[(node, name)] = value
        self._poke()

    def call(self, function: Callable[..., Any], /, *arguments: Any, **named: Any) -> None:
        """Have ``function(*arguments, **named)`` called at the next apply."""
        with self._lock:
            self._calls.append((function, arguments, named))
        self._poke()

    def apply(self) -> int:
        """Make the held writes, then the held calls in order; how many succeeded.

        Writes made on the owning thread were assigned when they were made and
        are not counted. A write or call that raises is logged and the rest go on.
        """
        with self._lock:
            sets, self._sets = self._sets, {}
            calls = list(self._calls)
            self._calls.clear()
        made = 0
        for (node, name), value in sets.items():
            try:
                setattr(node, name, value)
            except Exception:
                log.exception('could not set %s on %r', name, node)
            else:
                made += 1
        for function, arguments, named in calls:
            try:
                function(*arguments, **named)
            except Exception:
                log.exception('queued call %r failed', function)
            else:
                made += 1
        return made

    def _poke(self) -> None:
        if self._wake is not None:
            self._wake()
