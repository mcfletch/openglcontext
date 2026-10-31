"""Per-tile static collision for streamed terrain.

Turns each terrain tile the streamer is *drawing* into a static triangle-mesh
body of a physics service, so a character walks the surface and a car drives
on it. Wire it into `TilesetRuntime`/`TilesTerrain` through the `on_drawn` hook.

**The set of colliders is the set of drawn tiles, and nothing else.** A streamer
keeps tiles it is not drawing: a coarse parent stays resident so it can be shown
again the moment the camera pulls back, and siblings hang around until the
budget wants their space. Their geometry is the same ground at a different
resolution, half a metre from the ground on screen -- a second surface under
everything, and a car at speed catches the step between them, which reads as
hitting a wall in the middle of an open road.

Tracking the drawn set also bounds the working set: a session that drives across
a map for an hour costs what one view of it costs, since a tile that stops
being drawn has its body removed.
"""
from typing import TYPE_CHECKING, Any

from OpenGLContext.physics import gltf_world
from OpenGLContext.physics.proxy import Proxy

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.service import Physics


class TerrainColliders:
    """Static triangle-mesh bodies of ``physics`` for the tiles a streamer is drawing."""

    def __init__(self, physics: "Physics", min_hull_size: float = 0.0) -> None:
        self.physics = physics
        self.min_hull_size = min_hull_size
        #: Each tile's body, keyed by the tile, which hashes by identity.
        self._bodies: dict[Any, "Body"] = {}

    def on_drawn(self, pairs: Any) -> None:
        """Hold colliders for exactly these ``(tile, drawable)`` pairs.

        Called once per streaming tick with what is about to be drawn. A tile
        already held keeps the collider it has -- rebuilding a trimesh every
        frame would cost more than the physics it feeds.
        """
        wanted = dict(pairs)
        for tile in list(self._bodies):
            if tile not in wanted:
                self._release(tile)
        for tile, drawable in wanted.items():
            if tile not in self._bodies:
                self.on_renderable(tile, drawable)

    def on_renderable(self, tile: Any, drawable: Any) -> None:
        """Give ``tile`` a static body of the triangles ``drawable`` draws, unless it has one."""
        if tile in self._bodies:
            return
        extracted = gltf_world.extract_trimesh(
            drawable, min_hull_size=self.min_hull_size)
        if extracted is None:
            return
        points, indices = extracted
        if len(indices) == 0:
            return
        self._bodies[tile] = self.physics.add_static(None, proxy=Proxy.trimesh(points, indices))

    def on_evicted(self, tile: Any, drawable: Any) -> None:
        """Take the evicted tile's body out of the world."""
        self._release(tile)

    def _release(self, tile: Any) -> None:
        """Remove the body held for a tile."""
        body = self._bodies.pop(tile, None)
        if body is not None:
            body.remove()

    @property
    def collider_count(self) -> int:
        """How many tiles have a body."""
        return len(self._bodies)

    def bodies(self) -> list["Body"]:
        """The tiles' bodies, in the order they were made."""
        return list(self._bodies.values())
