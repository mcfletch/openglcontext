"""GeneratedTiles: a scenegraph node that streams tiles made on demand.

The node is a ``Group`` whose children are the generated tiles currently
selected for the camera, as :class:`~OpenGLContext.scenegraph.tilesterrain.TilesTerrain`
is for a baked tileset. Each frame the owning context calls
:meth:`update_for_camera`: the tileset makes the tiles the camera has come near
and drops those it has left, and one streaming tick loads, uploads and evicts
(see :mod:`OpenGLContext.loaders.tiles3d.generated` for the generator it takes).

A generator builds its tiles from materials it shares, so releasing a tile
deletes its meshes and leaves the materials' textures alone (``own_materials``).
"""
import math
from typing import Any, Optional

import numpy as np

from OpenGLContext.loaders.tiles3d.generated import GeneratedTileset, TileGenerator
from OpenGLContext.loaders.tiles3d.gltf_uploader import GLTileUploader
from OpenGLContext.loaders.tiles3d.runtime import TilesetRuntime
from OpenGLContext.scenegraph.group import Group

__all__ = ['GeneratedTiles']

#: Rounds of "make, load, upload" a priming call runs at most, which is more than
#: the runtime's per-frame upload cap needs for a view a few tiles deep.
PRIME_ROUNDS = 8


class GeneratedTiles(Group):
    """Tiles from a generator, made as the camera nears them and dropped as it leaves.

    ``reach`` is the distance in metres within which a tile is made and
    ``retain`` the distance beyond which it is dropped (a quarter more than
    ``reach`` by default). ``memory_budget`` is in bytes, counted from what the
    generator reports for each tile. ``max_sse`` is the screen-space error in
    pixels the runtime tolerates, and ``fovy`` the camera's vertical field of
    view in radians that error is measured against.
    """

    def __init__(self, generator: TileGenerator, reach: float,
                 retain: Optional[float] = None,
                 memory_budget: int = 256 * 1024 * 1024, max_sse: float = 16.0,
                 fovy: Optional[float] = None, max_uploads_per_update: int = 4,
                 workers: int = 2, own_materials: bool = False,
                 **named: Any) -> None:
        super().__init__(**named)
        self.fovy = math.radians(45.0) if fovy is None else fovy
        self.tileset = GeneratedTileset(generator, reach, retain)
        self.runtime = TilesetRuntime(
            self.tileset, self.tileset.loader, GLTileUploader(own_materials),
            memory_budget=memory_budget, fovy=self.fovy, max_sse=max_sse,
            max_uploads_per_update=max_uploads_per_update, workers=workers)

    def update_for_camera(self, camera: Any, viewport_height: float,
                          view_projection: Any = None) -> list[Any]:
        """Make and drop tiles for ``camera``, run one streaming tick, and return the tiles to draw.

        Call it with the GL context current: the tiles dropped have their GL
        objects deleted here. ``view_projection``, a 4x4 matrix, culls the tiles
        outside the view.
        """
        position = np.asarray(camera, dtype='d')
        for tile in self.tileset.ensure(position).retired:
            self.runtime.discard(tile)
        drawables = self.runtime.update(position, viewport_height,
                                        view_projection=view_projection)
        if list(self.children) != drawables:
            self.children = drawables
        return drawables

    def prime(self, camera: Any, viewport_height: float, timeout: float = 5.0) -> None:
        """Stream until the view around ``camera`` is drawn, before the first frame."""
        for _ in range(PRIME_ROUNDS):
            self.update_for_camera(camera, viewport_height)
            if self.wait_for_loads(timeout) and not self.runtime.pending_uploads:
                break
        self.update_for_camera(camera, viewport_height)

    def wait_for_loads(self, timeout: float = 5.0) -> bool:
        """Wait up to ``timeout`` seconds for the tiles asked for to be made."""
        return self.runtime.wait_for_loads(timeout=timeout)

    def shutdown(self) -> None:
        """Stop the workers that make the tiles."""
        self.runtime.shutdown()

    def dispose(self) -> None:
        """Delete the GL objects of every tile drawn, with the context current."""
        for tile in list(self.tileset.root.children):
            self.runtime.discard(tile)
        self.tileset.clear()
        self.children = []
