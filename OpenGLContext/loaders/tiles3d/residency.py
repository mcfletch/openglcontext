"""Tile residency: lifecycle state, memory accounting, and LRU eviction.

Tracks each tile's load state and GPU byte footprint, and evicts the
least-recently-wanted renderable tiles when the resident total exceeds the budget.
Wanted and pinned (parent-fallback) tiles are never evicted, so being over budget is
possible when everything resident is still needed — the budget is a target, not a
hard wall that can strand the current view.

Recency uses a monotonic internal counter (not wall-clock) so ticks are deterministic
and reproducible for tests and replay.
"""
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from OpenGLContext.loaders.tiles3d.tileset import RuntimeTile


class TileState:
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    RENDERABLE = "renderable"


class Residency:
    """Each tile's load state, footprint and recency, keyed by the tile itself.

    A tile hashes by identity, as a
    :class:`~OpenGLContext.loaders.tiles3d.tileset.RuntimeTile` does.
    """

    def __init__(self, memory_budget: float) -> None:
        self.memory_budget = memory_budget
        self.resident_bytes: float = 0
        self._state: "dict[RuntimeTile, str]" = {}
        self._bytes: "dict[RuntimeTile, int]" = {}
        self._recency: "dict[RuntimeTile, int]" = {}
        # The currently-renderable tiles -- the only eviction candidates.
        # Scanning this instead of all of `_state` keeps `enforce_budget` O(resident)
        # per frame rather than O(every tile ever touched).
        self._resident: "set[RuntimeTile]" = set()
        self._tick = 0

    def _touch(self, tile: "RuntimeTile") -> None:
        self._tick += 1
        self._recency[tile] = self._tick

    def get_state(self, tile: "RuntimeTile") -> str:
        return self._state.get(tile, TileState.UNLOADED)

    def note_wanted(self, tiles: "Iterable[RuntimeTile]") -> None:
        """Refresh recency for tiles wanted this frame (most recently wanted last)."""
        for tile in tiles:
            self._touch(tile)

    def wanted_to_load(self, want: "Iterable[RuntimeTile]") -> "list[RuntimeTile]":
        """Wanted tiles that are not yet loading or resident, in order."""
        return [t for t in want if self.get_state(t) == TileState.UNLOADED]

    def begin_load(self, tile: "RuntimeTile") -> None:
        self._state[tile] = TileState.LOADING

    def set_ready(self, tile: "RuntimeTile") -> None:
        self._state[tile] = TileState.READY

    def set_renderable(self, tile: "RuntimeTile", nbytes: int) -> None:
        prev = self._bytes.get(tile, 0)
        self.resident_bytes += nbytes - prev
        self._bytes[tile] = nbytes
        self._state[tile] = TileState.RENDERABLE
        self._recency.setdefault(tile, self._tick)
        self._resident.add(tile)

    def evict(self, tile: "RuntimeTile") -> None:
        self.resident_bytes -= self._bytes.pop(tile, 0)
        self._resident.discard(tile)
        self._recency.pop(tile, None)
        # Delete the entry rather than marking it UNLOADED: an evicted tile is
        # indistinguishable from one never touched, and `get_state` already
        # defaults to UNLOADED, so `_state` never accumulates dead entries.
        self._state.pop(tile, None)

    def enforce_budget(self, keep: "Iterable[RuntimeTile]") -> "list[RuntimeTile]":
        """Evict least-recently-wanted renderable tiles until within budget.

        `keep` is the set of tiles that must stay resident (this frame's want set plus
        any parent-fallback pins). Returns the evicted tiles so the caller can free
        their GL resources.
        """
        kept = set(keep)
        evicted: "list[RuntimeTile]" = []
        while self.resident_bytes > self.memory_budget:
            candidates = [tile for tile in self._resident if tile not in kept]
            if not candidates:
                break
            victim = min(candidates, key=lambda tile: self._recency.get(tile, 0))
            self.evict(victim)
            evicted.append(victim)
        return evicted
