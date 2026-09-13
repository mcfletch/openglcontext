"""Resource loads that run off the thread that asked for them.

A texture, a shader, a panorama or an inlined scene is fetched and decoded
while the world goes on being drawn, and the node it belongs to is filled in
when the work finishes.  A field setter hands that work over with
:func:`load_in_background`; :func:`wait_for_idle` is how a test or a tool waits
for a scene to be complete before it looks at it.

Two properties of the pool are what make it safe to hand a whole world's
resources to:

**A fixed number of workers.**  One thread per URL is one thread per face of a
cubemap and one per texture in a scene, so a world of a few hundred images
would spend more of itself starting threads than loading.  :data:`WORKERS`
threads do the same work at a bounded cost, and start only as work arrives.

**No first-use imports on a worker.**  A module being imported for the first
time is imported under CPython's import lock, which is held with the GIL
released and which no Python signal handler can interrupt: a thread waiting for
that lock is a thread no ``KeyboardInterrupt``, no ``SIGTERM`` and no test
runner's timeout can reach.  So the imports a load needs are made by the thread
that submits it -- that is what ``prepare`` is for -- where they are ordinary,
interruptible work and an ``ImportError`` is raised where a caller can see it.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

__all__ = ['WORKERS', 'LoadPool', 'load_in_background', 'pending',
           'wait_for_idle']

#: How many loads run at once.  Enough to keep a disk and a network busy while
#: a frame is being drawn, few enough that a scene naming a thousand textures
#: does not answer with a thousand threads.
WORKERS = 4

#: What a worker takes off the queue: what to call the resource if the work
#: raises, the callable, and its arguments.
_Work = tuple[str, Callable[..., Any], tuple]


class LoadPool:
    """A bounded set of daemon threads running submitted loads.

    The engine has one, which :func:`load_in_background` submits to.  A caller
    wanting loads that do not queue behind the scenegraph's can build another.
    """

    def __init__(self, workers: int = WORKERS, name: str = 'oglc-load') -> None:
        self.workers = workers
        self.name = name
        self._queue: queue.Queue[Optional[_Work]] = queue.Queue()
        self._state = threading.Condition()
        self._threads: list[threading.Thread] = []
        self._prepared: set[Callable[[], None]] = set()
        self._pending = 0

    def submit(self, description: str, work: Callable[..., Any], *args: Any,
               prepare: Optional[Callable[[], None]] = None) -> None:
        """Run ``work(*args)`` on a worker; answer at once.

        ``description`` names the resource in the log if the work raises.
        ``prepare`` runs first, **on the calling thread**, and at most once per
        pool for a given callable: it is where a load's imports are made.  It
        has to be safe to call twice, since two threads submitting at the same
        moment may both reach it.
        """
        if prepare is not None and prepare not in self._prepared:
            # Deliberately not under the lock: `prepare` imports, and holding a
            # lock across an import is the shape of deadlock this pool exists
            # to keep out of the engine.
            prepare()
            with self._state:
                self._prepared.add(prepare)
        started = []
        with self._state:
            self._pending += 1
            while len(self._threads) < min(self.workers, self._pending):
                thread = threading.Thread(
                    target=self._work, daemon=True,
                    name='%s-%d' % (self.name, len(self._threads) + 1))
                self._threads.append(thread)
                started.append(thread)
        self._queue.put((description, work, args))
        for thread in started:
            thread.start()

    def pending(self) -> int:
        """How many submitted loads have yet to finish."""
        with self._state:
            return self._pending

    def wait_for_idle(self, timeout: Optional[float] = None) -> bool:
        """Wait until every load submitted so far has finished.

        Answers whether they did, so a caller that gave a timeout can tell a
        finished load from an expired wait.  Work submitted *while* waiting is
        waited for too, which is what a scene whose first file names the rest
        of them needs.
        """
        with self._state:
            return self._state.wait_for(lambda: self._pending == 0, timeout)

    def shutdown(self, timeout: Optional[float] = None) -> bool:
        """Stop this pool's workers once the queue is empty.

        Answers whether they all went within ``timeout``.  For a caller that
        built a pool of its own; the engine's own pool lives as long as the
        process does, and its workers are daemons so an exit never waits.
        """
        with self._state:
            threads, self._threads = self._threads, []
        for _thread in threads:
            self._queue.put(None)
        deadline = None if timeout is None else time.monotonic() + timeout
        for thread in threads:
            thread.join(None if deadline is None
                        else max(0.0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in threads)

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:                        # shutdown's sentinel
                return
            description, work, args = item
            try:
                work(*args)
            except Exception:
                log.warning('Background load of %s failed', description,
                            exc_info=True)
            finally:
                with self._state:
                    self._pending -= 1
                    if not self._pending:
                        self._state.notify_all()


_pool = LoadPool()


def load_in_background(description: str, work: Callable[..., Any], *args: Any,
                       prepare: Optional[Callable[[], None]] = None) -> None:
    """Run ``work(*args)`` on the engine's loader pool; answer at once.

    See :meth:`LoadPool.submit` for what ``prepare`` is for and why it runs on
    the calling thread.
    """
    _pool.submit(description, work, *args, prepare=prepare)


def pending() -> int:
    """How many background loads have yet to finish."""
    return _pool.pending()


def wait_for_idle(timeout: Optional[float] = None) -> bool:
    """Wait for every background load to finish; answer whether they did."""
    return _pool.wait_for_idle(timeout)
