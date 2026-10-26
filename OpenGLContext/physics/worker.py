"""The workers that step a physics runtime.

A worker owns a :class:`~OpenGLContext.physics.runtime.WorldRuntime` and decides
which thread steps it. Both forms take commands from any thread through an
:class:`~OpenGLContext.events.handoff.Inbox` and hand the render thread a
:class:`Outbox` of the latest snapshot and the events made since the last one.

:class:`InlineWorker`
    Steps the world in :meth:`~InlineWorker.collect`, on the thread that calls it.
    A command made while it is stepping (from a step hook or a physics callback)
    is applied at once; any other is applied at the start of the next call.
:class:`ThreadWorker`
    Steps the world on a daemon thread at the definition's rate.

Neither steps a world that is not
:meth:`~OpenGLContext.physics.runtime.WorldRuntime.busy` when no command has
arrived: the thread blocks and the inline worker returns at once, so a resting
scene costs no steps. A registered step handler or a driven body keeps the world
busy.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, NamedTuple, Protocol

from omi_physics.threaded import pace

from OpenGLContext.events.handoff import Inbox
from OpenGLContext.physics.records import Command, PhysicsEvent, Snapshot
from OpenGLContext.physics.runtime import WorldRuntime
from OpenGLContext.physics.settings import PhysicsDefinition

__all__ = ['InlineWorker', 'Outbox', 'ThreadWorker', 'Worker']

log = logging.getLogger(__name__)

#: Tick times kept for :meth:`ThreadWorker.rate`: about a second of a healthy worker.
RATE_WINDOW = 120
_NOTHING = Command('noop', 0)


class Outbox(NamedTuple):
    """What a worker hands the render thread: a snapshot if a new one was published, and events."""
    snapshot: Snapshot | None
    events: list[PhysicsEvent]


class Worker(Protocol):
    """What the physics service needs of a worker."""

    runtime: WorldRuntime
    inbox: Inbox
    #: The exception that stopped the worker's thread, or None.
    error: Exception | None

    def on_worker_thread(self) -> bool:
        """Whether the calling thread is the one stepping the world right now."""

    def flush(self) -> None:
        """Apply waiting commands now on the calling thread, where no thread of the worker's runs."""

    def submit(self, command: Command) -> None:
        """Make ``command`` from any thread."""

    def collect(self, dt: float) -> Outbox:
        """Take what the worker has published; an inline worker steps ``dt`` seconds first."""

    def step(self, dt: float) -> None:
        """Advance by ``dt`` seconds by hand."""

    def start(self) -> None:
        """Begin stepping, where the worker has a thread."""

    def stop(self) -> None:
        """Stop stepping and release the thread."""


class InlineWorker:
    """Steps the world in :meth:`collect`, on the calling thread."""

    def __init__(self, definition: PhysicsDefinition, runtime: WorldRuntime | None = None) -> None:
        self.runtime = runtime if runtime is not None else WorldRuntime(definition)
        self.inbox = Inbox()
        #: Always None: a step that raises here raises in :meth:`collect`, on the caller's thread.
        self.error: Exception | None = None
        self._stepping = False
        #: How many commands the runtime had applied at the last published snapshot; -1 before the first.
        self._published_count = -1

    def submit(self, command: Command) -> None:
        """Apply ``command`` now if the world is mid-step, else at the next :meth:`collect`."""
        if self._stepping:
            self.runtime.apply(command)
        else:
            self.inbox.post(command)

    def collect(self, dt: float) -> Outbox:
        """Apply the waiting commands, run the steps ``dt`` seconds hold and publish the result.

        A frame with no command applied since the last snapshot, in a world that
        is not :meth:`~OpenGLContext.physics.runtime.WorldRuntime.busy`, steps
        nothing and publishes nothing: the last snapshot still stands, as on a
        :class:`ThreadWorker` that has gone idle, and the frame's time is not
        carried toward the next step.
        """
        runtime = self.runtime
        commands = self.inbox.drain()
        if (not commands and self._published_count == runtime.applied_count
                and self._published_count >= 0 and not runtime.busy()):
            return Outbox(None, runtime.take_events())
        self._advance(dt, commands)
        self._published_count = runtime.applied_count
        return Outbox(runtime.snapshot(runtime.alpha), runtime.take_events())

    def step(self, dt: float) -> None:
        """Advance by ``dt`` seconds and leave the result for the next :meth:`collect`."""
        self._advance(dt, self.inbox.drain())

    def _advance(self, dt: float, commands: list[Command]) -> None:
        self._stepping = True
        try:
            self.runtime.bind_thread()
            for command in commands:
                self.runtime.apply(command)
            self.runtime.step_frame(dt)
        finally:
            self._stepping = False

    def start(self) -> None:
        """An inline worker has no thread to start."""

    def stop(self) -> None:
        """An inline worker has no thread to stop."""

    def on_worker_thread(self) -> bool:
        """Whether a step is under way, so the caller is a hook inside it."""
        return self._stepping

    def flush(self) -> None:
        """Apply the waiting commands without stepping.

        A flush made from a hook inside a step leaves that step in charge.
        """
        was, self._stepping = self._stepping, True
        try:
            self.runtime.bind_thread()
            for command in self.inbox.drain():
                self.runtime.apply(command)
        finally:
            self._stepping = was


class ThreadWorker:
    """Steps the world on a daemon thread, one fixed step per tick."""

    def __init__(self, definition: PhysicsDefinition, wake: Callable[[], Any] | None = None,
                 runtime: WorldRuntime | None = None) -> None:
        self.runtime = runtime if runtime is not None else WorldRuntime(definition)
        self._wake = wake
        self.inbox = Inbox()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._published: Snapshot | None = None
        self._collected = 0
        self._events: list[PhysicsEvent] = []
        self._ticks: collections.deque[float] = collections.deque(maxlen=RATE_WINDOW)
        self._tick_count = threading.Condition()
        self._steps = 0
        self._dropped = 0
        #: Whether the thread is blocked with nothing to do.
        self.idle = False
        #: The exception that ended the thread, or None while it has not failed.
        self.error: Exception | None = None

    @property
    def sim_hz(self) -> float:
        """The tick rate asked for, in steps a second."""
        return 1.0 / self.runtime.step_dt

    def on_worker_thread(self) -> bool:
        """Whether the calling thread is the stepping thread."""
        return self._thread is not None and threading.get_ident() == self._thread.ident

    def flush(self) -> None:
        """Apply the waiting commands on the calling thread, when no thread is running."""
        self._flush()

    def _flush(self) -> bool:
        with self._lock:
            if self._thread is not None:
                return False
        self.runtime.bind_thread()
        commands = self.inbox.drain()
        for command in commands:
            self.runtime.apply(command)
        return bool(commands)

    # -- lifecycle ------------------------------------------------------
    @property
    def thread_id(self) -> int | None:
        """The identity of the stepping thread; None while it is not running."""
        return None if self._thread is None else self._thread.ident

    def start(self) -> None:
        """Begin stepping on a daemon thread; a second call, or one after the thread failed, does nothing."""
        with self._lock:
            if self._thread is not None or self.error is not None:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name='physics', daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the thread and wait for it to end."""
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is None:
            return
        self._stop.set()
        self.inbox.post(_NOTHING)
        thread.join(timeout=5.0)

    # -- the render thread's side ---------------------------------------
    def submit(self, command: Command) -> None:
        """Queue ``command``, or apply it at once from a callback on the stepping thread.

        A worker whose thread has failed answers ``run`` and ``settle`` at once
        with its :attr:`error` and drops the rest.
        """
        if self.error is not None:
            self._refuse(command)
        elif self.on_worker_thread():
            self.runtime.apply(command)
        else:
            self.inbox.post(command)
            if self.error is not None:      # the thread failed between the check and the post
                self._fail_waiting()

    def collect(self, dt: float) -> Outbox:  # noqa: ARG002 the thread steps by its own clock
        """The newest snapshot if it has not been collected, and the events since the last call."""
        if self._thread is None and self.error is None:
            self._publish_without_thread()
        with self._lock:
            snapshot = self._published
            if snapshot is not None and snapshot.version == self._collected:
                snapshot = None
            if snapshot is not None:
                self._collected = snapshot.version
            events, self._events = self._events, []
        return Outbox(snapshot, events)

    def _publish_without_thread(self) -> None:
        """Apply what is waiting and publish the world as it stands, with no thread running."""
        if self._flush() or self._published is None:
            self._publish()

    def step(self, dt: float) -> None:
        """Advance by ``dt`` seconds on the calling thread, for a worker that is not running."""
        if self._thread is not None:
            raise RuntimeError('step() is for a worker whose thread is stopped')
        self.runtime.bind_thread()
        for command in self.inbox.drain():
            self.runtime.apply(command)
        self.runtime.step_frame(dt)
        self._publish()

    def settle(self, timeout: float = 5.0) -> bool:
        """Wait until every command posted so far has been applied and published."""
        marker = threading.Event()
        self.submit(Command('settle', 0, (marker,)))
        return marker.wait(timeout) and self.error is None

    def wait_ticks(self, count: int, timeout: float = 5.0) -> bool:
        """Wait for ``count`` more ticks; False if they do not come in ``timeout`` seconds."""
        deadline = time.monotonic() + timeout
        with self._tick_count:
            target = self._steps + count
            while self._steps < target:
                left = deadline - time.monotonic()
                if left <= 0.0:
                    return False
                self._tick_count.wait(left)
        return True

    # -- accounting -----------------------------------------------------
    @property
    def steps(self) -> int:
        """Ticks run since the thread started."""
        return self._steps

    @property
    def dropped(self) -> int:
        """Ticks given up because the one before overran its budget."""
        return self._dropped

    def rate(self) -> float:
        """Ticks a second the thread is achieving over the recent past; 0 before two ticks."""
        ticks = list(self._ticks)
        if len(ticks) < 2 or ticks[-1] <= ticks[0]:
            return 0.0
        return (len(ticks) - 1) / (ticks[-1] - ticks[0])

    # -- the thread -----------------------------------------------------
    def _loop(self) -> None:
        try:
            self._run()
        except Exception as error:  # noqa: BLE001 kept as the worker's error and raised by Physics.frame
            log.exception('the physics worker stopped')
            self.error = error
            self._fail_waiting()

    def _fail_waiting(self) -> None:
        """End every wait on this worker: fail each waiting ``run`` future with :attr:`error`
        and set each ``settle`` marker, whose :meth:`settle` then answers False."""
        markers, self.runtime.markers = self.runtime.markers, []
        for command in self.inbox.drain():
            self._refuse(command)
        for marker in markers:
            marker.set()

    def _refuse(self, command: Command) -> None:
        """Answer ``command`` as a worker that has failed does: a ``run`` future fails with
        :attr:`error` and a ``settle`` marker is set; anything else is dropped."""
        if command.op == 'run':
            future = command.args[1]
            if future.set_running_or_notify_cancel():
                future.set_exception(self.error)
        elif command.op == 'settle':
            command.args[0].set()

    def _run(self) -> None:
        runtime = self.runtime
        runtime.bind_thread()
        next_due = time.perf_counter()
        while not self._stop.is_set():
            applied = self._apply_waiting()
            if not applied and not runtime.busy():
                self._publish()
                self.idle = True
                self.inbox.wait(None)
                self.idle = False
                next_due = time.perf_counter()
                continue
            runtime.step_once()
            self._publish()
            self._tick(time.perf_counter())
            delay, next_due, overran = pace(next_due, time.perf_counter(), runtime.step_dt)
            if overran:
                self._dropped += 1
            if delay > 0.0:
                self._stop.wait(delay)

    def _apply_waiting(self) -> bool:
        commands = self.inbox.drain()
        for command in commands:
            self.runtime.apply(command)
        return bool(commands)

    def _publish(self) -> None:
        snapshot = self.runtime.snapshot()
        events = self.runtime.take_events()
        with self._lock:
            waiting = self._published
            if waiting is not None and waiting.version != self._collected:
                snapshot = snapshot.following(waiting)
            self._published = snapshot
            self._events.extend(events)
        markers, self.runtime.markers = self.runtime.markers, []
        for marker in markers:
            marker.set()
        if self._wake is not None and snapshot.version and self.runtime.busy():
            self._wake()

    def _tick(self, now: float) -> None:
        self._ticks.append(now)
        with self._tick_count:
            self._steps += 1
            self._tick_count.notify_all()
