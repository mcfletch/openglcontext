"""Per-tile static collision for streamed terrain.

Turns each terrain tile the streamer is *drawing* into a static `trimesh`
collider in a physics world, so a character walks the surface and a car drives
on it. Wire it into `TilesetRuntime`/`TilesTerrain` through the `on_drawn` hook.

**The set of colliders is the set of drawn tiles, and nothing else.** A streamer
keeps tiles it is not drawing: a coarse parent stays resident so it can be shown
again the moment the camera pulls back, and siblings hang around until the
budget wants their space. Their geometry is the same ground at a different
resolution, half a metre from the ground on screen -- a second surface under
everything, and a car at speed catches the step between them, which reads as
hitting a wall in the middle of an open road.

Tracking the drawn set also bounds the working set: a session that drives across
a map for an hour costs what one view of it costs.
`PhysicsWorld.remove_body` frees the slot for the next tile to arrive in; a
world without that call keeps the body and is told so, once.
"""
import logging
from typing import TYPE_CHECKING, Any

from omi_physics import model
from OpenGLContext.physics import gltf_world

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

log = logging.getLogger(__name__)


class TerrainColliders:
    """Static trimesh colliders for the tiles a streamer is drawing."""

    def __init__(self, world: "PhysicsWorld", min_hull_size: float = 0.0) -> None:
        self.world = world
        self.min_hull_size = min_hull_size
        self._bodies: dict[int, int] = {}   # id(tile) -> body index
        # Kept for API compatibility; stays empty because unremovable handles
        # are dropped rather than queued (see :meth:`on_evicted`).
        self.pending_removals: list[Any] = []
        self._warned_no_removal = False

    def on_drawn(self, pairs: Any) -> None:
        """Hold colliders for exactly these ``(tile, drawable)`` pairs.

        Called once per streaming tick with what is about to be drawn. A tile
        already held keeps the collider it has -- rebuilding a trimesh every
        frame would cost more than the physics it feeds.
        """
        wanted = {}
        for tile, drawable in pairs:
            wanted[id(tile)] = (tile, drawable)
        for key in list(self._bodies):
            if key not in wanted:
                self._release(key)
        for key, (tile, drawable) in wanted.items():
            if key not in self._bodies:
                self.on_renderable(tile, drawable)

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
        """Take the evicted tile's collider out of the physics world.

        A world whose `PhysicsWorld` has no `remove_body` keeps the body; the
        handle is dropped rather than queued, and the fact is logged once. A
        list of handles that could never be acted on would grow for as long as
        the stream ran.
        """
        self._release(id(tile))

    def _release(self, key: int) -> None:
        """Drop the collider held for a tile, by its identity."""
        body = self._bodies.pop(key, None)
        if body is None:
            return
        remove = getattr(self.world, 'remove_body', None)
        if callable(remove):
            remove(body)
            return
        if not self._warned_no_removal:
            self._warned_no_removal = True
            log.warning(
                "PhysicsWorld has no remove_body; tile colliders that are no "
                "longer drawn remain in the world. Handles are dropped, not "
                "queued, to keep the working set bounded.")

    @property
    def collider_count(self) -> int:
        return len(self._bodies)
