"""Load queue + manager: priority ordering, cancellation, and background loading.

`LoadQueue` is the pure ordering policy (most-urgent-first, cancellable); tested
deterministically. `LoadManager` runs a worker pool over it with an injectable
loader function, so the concurrency is exercised without real glTF payloads.
"""
import threading
import pytest

from OpenGLContext.loaders.tiles3d.loadmanager import LoadQueue, LoadManager


class FakeTile:
    def __init__(self, name):
        self.name = name


# --- LoadQueue (pure) -------------------------------------------------------

def test_queue_pops_most_urgent_first():
    q = LoadQueue()
    a, b, c = FakeTile("a"), FakeTile("b"), FakeTile("c")
    q.push(a, priority=50)
    q.push(b, priority=10)  # nearest / most urgent
    q.push(c, priority=30)
    assert [q.pop().name for _ in range(3)] == ["b", "c", "a"]


def test_queue_equal_priority_is_fifo():
    q = LoadQueue()
    a, b = FakeTile("a"), FakeTile("b")
    q.push(a, 10)
    q.push(b, 10)
    assert [q.pop().name, q.pop().name] == ["a", "b"]


def test_queue_cancel_skips_tile():
    q = LoadQueue()
    a, b = FakeTile("a"), FakeTile("b")
    q.push(a, 10)
    q.push(b, 20)
    q.cancel(a)
    assert q.pop().name == "b"
    assert q.pop() is None


def test_queue_len_counts_pending_uncancelled():
    q = LoadQueue()
    a, b = FakeTile("a"), FakeTile("b")
    q.push(a, 1)
    q.push(b, 2)
    assert len(q) == 2
    q.cancel(a)
    assert len(q) == 1


def test_queue_pop_empty_returns_none():
    assert LoadQueue().pop() is None


# --- LoadManager (threaded) -------------------------------------------------

def test_manager_loads_all_requested():
    calls = []
    lock = threading.Lock()

    def loader(tile):
        with lock:
            calls.append(tile.name)
        return "payload:" + tile.name

    mgr = LoadManager(loader, workers=3)
    try:
        tiles = [FakeTile(n) for n in "abcde"]
        for i, t in enumerate(tiles):
            mgr.request(t, priority=i)
        assert mgr.wait_idle(timeout=5.0)
        ready = dict((t.name, payload) for t, payload in mgr.poll_ready())
        assert ready == {n: "payload:" + n for n in "abcde"}
        assert sorted(calls) == list("abcde")
    finally:
        mgr.shutdown()


def test_manager_cancel_prevents_load():
    started = threading.Event()
    release = threading.Event()
    loaded = []

    def loader(tile):
        if tile.name == "block":
            started.set()
            release.wait(timeout=5.0)
        loaded.append(tile.name)
        return tile.name

    mgr = LoadManager(loader, workers=1)
    try:
        block = FakeTile("block")
        a, b, cancelled = FakeTile("a"), FakeTile("b"), FakeTile("cancel")
        mgr.request(block, priority=0)
        assert started.wait(timeout=5.0)  # worker is busy on `block`
        mgr.request(a, priority=1)
        mgr.request(b, priority=2)
        mgr.request(cancelled, priority=3)
        mgr.cancel(cancelled)
        release.set()
        assert mgr.wait_idle(timeout=5.0)
        assert "cancel" not in loaded
        assert set(loaded) == {"block", "a", "b"}
    finally:
        release.set()
        mgr.shutdown()


def test_manager_processes_in_priority_order_with_one_worker():
    started = threading.Event()
    release = threading.Event()
    order = []

    def loader(tile):
        if tile.name == "block":
            started.set()
            release.wait(timeout=5.0)
        else:
            order.append(tile.name)
        return tile.name

    mgr = LoadManager(loader, workers=1)
    try:
        mgr.request(FakeTile("block"), priority=-1)
        assert started.wait(timeout=5.0)
        # Enqueue out of priority order while the worker is blocked.
        mgr.request(FakeTile("far"), priority=100)
        mgr.request(FakeTile("near"), priority=1)
        mgr.request(FakeTile("mid"), priority=50)
        release.set()
        assert mgr.wait_idle(timeout=5.0)
        assert order == ["near", "mid", "far"]
    finally:
        release.set()
        mgr.shutdown()
