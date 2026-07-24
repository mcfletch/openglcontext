"""Background loading of tile payloads.

`LoadQueue` is the ordering policy: a min-heap keyed on priority (smaller = more
urgent, e.g. nearer / higher screen-space error), with FIFO tie-breaking and
cancellation. `LoadManager` runs a worker pool that drains the queue, calling an
injectable `loader_fn(tile)` off the render thread and delivering results through a
ready queue. Keeping the loader injectable lets the glTF payload path (and its
decode) be swapped in without entangling the streaming logic.
"""
import heapq
import itertools
import queue
import threading
from collections.abc import Callable
from typing import Any


class LoadQueue:
    """Priority queue of pending tile loads (smaller priority = more urgent)."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, int, Any]] = []
        self._counter = itertools.count()
        self._present: set[int] = set()
        self._cancelled: set[int] = set()

    def push(self, tile: Any, priority: float) -> None:
        tid = id(tile)
        if tid in self._present:
            return
        self._present.add(tid)
        self._cancelled.discard(tid)
        heapq.heappush(self._heap, (priority, next(self._counter), tid, tile))

    def cancel(self, tile: Any) -> None:
        self._cancelled.add(id(tile))

    def pop(self) -> Any:
        while self._heap:
            _, _, tid, tile = heapq.heappop(self._heap)
            self._present.discard(tid)
            if tid in self._cancelled:
                self._cancelled.discard(tid)
                continue
            return tile
        return None

    def __len__(self) -> int:
        return sum(1 for tid in self._present if tid not in self._cancelled)


class LoadManager:
    """Worker pool that loads tiles off the render thread via `loader_fn`."""

    def __init__(self, loader_fn: Callable[[Any], Any], workers: int = 2) -> None:
        self.loader_fn = loader_fn
        self._queue = LoadQueue()
        self._ready: queue.Queue[tuple[Any, Any]] = queue.Queue()
        self._cond = threading.Condition()
        self._inflight = 0
        self._stop = False
        self._threads = [
            threading.Thread(target=self._worker, daemon=True)
            for _ in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    def request(self, tile: Any, priority: float) -> None:
        with self._cond:
            self._queue.push(tile, priority)
            self._cond.notify()

    def cancel(self, tile: Any) -> None:
        with self._cond:
            self._queue.cancel(tile)

    def poll_ready(self) -> list[tuple[Any, Any]]:
        """Drain completed loads as (tile, payload) pairs. Payload is the loader's
        return value, or the raised exception if it failed."""
        out: list[tuple[Any, Any]] = []
        while True:
            try:
                out.append(self._ready.get_nowait())
            except queue.Empty:
                return out

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Block until the queue is empty and no load is in flight."""
        with self._cond:
            return self._cond.wait_for(
                lambda: len(self._queue) == 0 and self._inflight == 0, timeout
            )

    def shutdown(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        for thread in self._threads:
            thread.join(timeout=2.0)

    def _worker(self) -> None:
        while True:
            with self._cond:
                while not self._stop and len(self._queue) == 0:
                    self._cond.wait()
                if self._stop:
                    return
                tile = self._queue.pop()
                if tile is None:  # pragma: no cover - pop() under the lock after a
                    continue      # positive len() always returns a present tile
                self._inflight += 1
            try:
                payload = self.loader_fn(tile)
                self._ready.put((tile, payload))
            except Exception as err:  # deliver failures instead of dying silently
                self._ready.put((tile, err))
            finally:
                with self._cond:
                    self._inflight -= 1
                    self._cond.notify_all()
