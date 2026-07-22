"""Tile residency: lifecycle state, memory accounting, and LRU eviction.

Tracks each tile's load state and GPU byte footprint, and evicts the
least-recently-wanted renderable tiles when the resident total exceeds the budget.
Wanted and pinned (parent-fallback) tiles are never evicted, so being over budget is
possible when everything resident is still needed — the budget is a target, not a
hard wall that can strand the current view.

Recency uses a monotonic internal counter (not wall-clock) so ticks are deterministic
and reproducible for tests and replay.
"""


class TileState:
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    RENDERABLE = "renderable"


class Residency:
    def __init__(self, memory_budget):
        self.memory_budget = memory_budget
        self.resident_bytes = 0
        self._state = {}
        self._bytes = {}
        self._recency = {}
        self._tiles = {}
        # Ids of the currently-renderable tiles -- the only eviction candidates.
        # Scanning this instead of all of `_state` keeps `enforce_budget` O(resident)
        # per frame rather than O(every tile ever touched).
        self._resident = set()
        self._tick = 0

    def _touch(self, tile):
        self._tick += 1
        self._recency[id(tile)] = self._tick
        self._tiles[id(tile)] = tile

    def get_state(self, tile):
        return self._state.get(id(tile), TileState.UNLOADED)

    def note_wanted(self, tiles):
        """Refresh recency for tiles wanted this frame (most recently wanted last)."""
        for tile in tiles:
            self._touch(tile)

    def wanted_to_load(self, want):
        """Wanted tiles that are not yet loading or resident, in order."""
        return [t for t in want if self.get_state(t) == TileState.UNLOADED]

    def begin_load(self, tile):
        self._state[id(tile)] = TileState.LOADING
        self._tiles[id(tile)] = tile

    def set_ready(self, tile):
        self._state[id(tile)] = TileState.READY
        self._tiles[id(tile)] = tile

    def set_renderable(self, tile, nbytes):
        prev = self._bytes.get(id(tile), 0)
        self.resident_bytes += nbytes - prev
        self._bytes[id(tile)] = nbytes
        self._state[id(tile)] = TileState.RENDERABLE
        self._tiles[id(tile)] = tile
        self._recency.setdefault(id(tile), self._tick)
        self._resident.add(id(tile))

    def evict(self, tile):
        tid = id(tile)
        self.resident_bytes -= self._bytes.pop(tid, 0)
        self._resident.discard(tid)
        self._recency.pop(tid, None)
        self._tiles.pop(tid, None)
        # Delete the entry rather than marking it UNLOADED: an evicted tile is
        # indistinguishable from one never touched, and `get_state` already
        # defaults to UNLOADED, so `_state` never accumulates dead entries.
        self._state.pop(tid, None)

    def enforce_budget(self, keep):
        """Evict least-recently-wanted renderable tiles until within budget.

        `keep` is the set of tiles that must stay resident (this frame's want set plus
        any parent-fallback pins). Returns the evicted tiles so the caller can free
        their GL resources.
        """
        keep_ids = {id(t) for t in keep}
        evicted = []
        while self.resident_bytes > self.memory_budget:
            candidates = [tid for tid in self._resident if tid not in keep_ids]
            if not candidates:
                break
            victim_id = min(candidates, key=lambda tid: self._recency.get(tid, 0))
            victim = self._tiles[victim_id]
            self.evict(victim)
            evicted.append(victim)
        return evicted
