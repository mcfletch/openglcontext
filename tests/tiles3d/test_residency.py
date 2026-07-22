"""Residency: tile lifecycle, memory accounting, and LRU eviction under a budget.

Tracks each tile's state (UNLOADED -> LOADING -> READY -> RENDERABLE), the resident
byte total, and evicts the least-recently-wanted renderable tiles when the budget is
exceeded, never evicting a tile that is still wanted or pinned as a parent fallback.
"""
import pytest

from OpenGLContext.loaders.tiles3d.residency import Residency, TileState


class FakeTile:
    def __init__(self, name):
        self.name = name


def test_unknown_tile_is_unloaded():
    r = Residency(memory_budget=1000)
    assert r.get_state(FakeTile("a")) == TileState.UNLOADED


def test_lifecycle_transitions():
    r = Residency(memory_budget=1000)
    t = FakeTile("a")
    r.begin_load(t)
    assert r.get_state(t) == TileState.LOADING
    r.set_ready(t)
    assert r.get_state(t) == TileState.READY
    r.set_renderable(t, nbytes=100)
    assert r.get_state(t) == TileState.RENDERABLE


def test_resident_bytes_accounts_renderable():
    r = Residency(memory_budget=1000)
    a, b = FakeTile("a"), FakeTile("b")
    r.set_renderable(a, 100)
    r.set_renderable(b, 250)
    assert r.resident_bytes == 350


def test_wanted_to_load_returns_only_unloaded():
    r = Residency(memory_budget=1000)
    a, b, c = FakeTile("a"), FakeTile("b"), FakeTile("c")
    r.begin_load(b)
    r.set_renderable(c, 100)
    assert r.wanted_to_load([a, b, c]) == [a]


def test_enforce_budget_evicts_least_recently_wanted_first():
    r = Residency(memory_budget=250)
    a, b, c = FakeTile("a"), FakeTile("b"), FakeTile("c")
    for t in (a, b, c):
        r.set_renderable(t, 100)
    # Mark wanted in order a, b, c so a is least-recently-wanted.
    r.note_wanted([a])
    r.note_wanted([b])
    r.note_wanted([c])
    evicted = r.enforce_budget(keep=[])
    assert [t.name for t in evicted] == ["a"]
    assert r.get_state(a) == TileState.UNLOADED
    assert r.resident_bytes == 200


def test_enforce_budget_never_evicts_kept_tiles():
    r = Residency(memory_budget=150)
    a, b = FakeTile("a"), FakeTile("b")
    r.set_renderable(a, 100)
    r.set_renderable(b, 100)
    r.note_wanted([a])
    r.note_wanted([b])
    evicted = r.enforce_budget(keep=[b])  # a is older, evict it
    assert [t.name for t in evicted] == ["a"]
    assert r.get_state(b) == TileState.RENDERABLE


def test_enforce_budget_gives_up_when_all_kept():
    r = Residency(memory_budget=100)
    a, b = FakeTile("a"), FakeTile("b")
    r.set_renderable(a, 100)
    r.set_renderable(b, 100)
    evicted = r.enforce_budget(keep=[a, b])
    assert evicted == []
    assert r.resident_bytes == 200  # over budget, but nothing evictable


def test_evict_frees_bytes_and_resets_state():
    r = Residency(memory_budget=1000)
    a = FakeTile("a")
    r.set_renderable(a, 400)
    r.evict(a)
    assert r.get_state(a) == TileState.UNLOADED
    assert r.resident_bytes == 0


def test_evict_deletes_the_state_entry():
    """Evicting a tile removes its `_state` row entirely, not just marks it
    UNLOADED, so `_state` cannot accumulate an entry per tile ever touched."""
    r = Residency(memory_budget=1000)
    a = FakeTile("a")
    r.set_renderable(a, 100)
    assert id(a) in r._state and id(a) in r._resident
    r.evict(a)
    assert id(a) not in r._state
    assert id(a) not in r._resident
    assert id(a) not in r._tiles


def test_state_stays_bounded_over_many_touched_then_evicted_tiles():
    """Streaming many distinct tiles through residency evicts to budget while
    keeping `_state`/`_resident` bounded to what is actually resident."""
    budget = 300
    r = Residency(memory_budget=budget)
    for i in range(500):
        t = FakeTile("t%d" % i)
        r.note_wanted([t])
        r.set_renderable(t, 100)
        r.enforce_budget(keep=[t])   # keep the just-loaded tile, evict older ones
    # 100 bytes each, 300-byte budget -> at most 3 resident at any time.
    assert r.resident_bytes <= budget
    assert len(r._resident) <= 3
    assert len(r._state) <= 3


def test_enforce_budget_scans_only_resident_not_all_state():
    """Loaded-then-evicted tiles leave no eviction candidate behind: enforce_budget
    considers only currently-resident tiles."""
    r = Residency(memory_budget=100)
    old = [FakeTile("o%d" % i) for i in range(5)]
    for t in old:
        r.set_renderable(t, 100)
        r.evict(t)                   # each evicted immediately
    assert r._resident == set()
    live = FakeTile("live")
    r.set_renderable(live, 100)
    r.note_wanted([live])
    evicted = r.enforce_budget(keep=[live])
    assert evicted == []             # within budget, and no stale candidates linger
    assert r.get_state(live) == TileState.RENDERABLE
