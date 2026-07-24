"""Per-tile static collision for streamed terrain.

Turns each resident terrain tile into a static `trimesh` collider in a physics world,
so a character controller walks the surface (and, later, through caves). Wire it into
`TilesetRuntime`/`TilesTerrain` via the `on_renderable`/`on_evicted` hooks.

Eviction removes a tile's collider through `PhysicsWorld.remove_body` when that
call exists. It does not today, so an evicted tile's static body stays in the world
and we simply drop our handle to it (logging once). We do NOT queue those handles:
a per-frame stream evicts without bound, and a list of handles we can never act on
would grow forever. Resident terrain is bounded, so the live collider set stays
finite even though evicted bodies are not yet reclaimed.
"""
import logging
from typing import TYPE_CHECKING, Any

from omi_physics import model
from OpenGLContext.physics import gltf_world

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

log = logging.getLogger(__name__)


class TerrainColliders:
    """Adds static trimesh colliders for renderable tiles to a physics world."""

    def __init__(self, world: "PhysicsWorld", min_hull_size: float = 0.0) -> None:
        self.world = world
        self.min_hull_size = min_hull_size
        self._bodies: dict[int, int] = {}   # id(tile) -> body index
        # Kept for API compatibility; stays empty because we never accumulate
        # unremovable handles (see the module docstring).
        self.pending_removals: list[Any] = []
        self._warned_no_removal = False

    def on_renderable(self, tile: Any, drawable: Any) -> None:
        if id(tile) in self._bodies:
            return
        extracted = gltf_world.extract_trimesh(
            drawable, min_hull_size=self.min_hull_size)
        if extracted is None:
            return
        points, indices = extracted
        if len(indices) == 0:
            return
        shape = self.world.add_shape(model.Shape.trimesh(points, indices))
        body = self.world.add_body(
            model.Motion(type=model.STATIC),
            collider=model.Collider(shape=shape))
        self._bodies[id(tile)] = body

    def on_evicted(self, tile: Any, drawable: Any) -> None:
        """Forget the evicted tile's collider.

        Removes the body from the world when `PhysicsWorld.remove_body` is
        available; otherwise drops the handle and logs once that eviction-removal
        is unimplemented, rather than growing an unbounded list of handles it can
        never act on.
        """
        body = self._bodies.pop(id(tile), None)
        if body is None:
            return
        remove = getattr(self.world, 'remove_body', None)
        if callable(remove):
            remove(body)
            return
        if not self._warned_no_removal:
            self._warned_no_removal = True
            log.warning(
                "PhysicsWorld has no remove_body; evicted tile colliders remain "
                "in the world. Handles are dropped, not queued, to keep the "
                "working set bounded.")

    @property
    def collider_count(self) -> int:
        return len(self._bodies)
