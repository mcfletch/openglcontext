"""Tiles made when the camera nears them, for a world with no tileset file.

A baked tileset names every tile before the first frame. A world that is
endless, or is cheaper to compute than to store, has no such list: a
:class:`GeneratedTileset` holds no tile until the camera is within ``reach`` of
the place it covers, asks its generator for the tile's bounds and content, and
drops the tile again once the camera is beyond ``retain``.

The generator is any object with three methods:

``keys_near(point, radius)``
    The keys of the tiles within ``radius`` metres of ``point``. A key is any
    hashable value that names a tile: a segment number, a grid cell.
``bounds(key)``
    The tile's bounding volume, in world coordinates.
``generate(key)``
    The tile's content as ``(scene, nbytes)``, where ``scene`` has a ``group``
    node to draw, as a loaded glTF does, and ``nbytes`` counts it against the
    memory budget. Called on a worker thread, so it builds nodes and arrays and
    makes no GL call.

A generator whose tiles are costly to build can have them made in child processes
(:class:`~OpenGLContext.loaders.tiles3d.tileprocess.TileProcesses`) instead of
``generate``: it then also defines ``assemble(key, payload)``, which turns the plain
data a child's maker returned into the same ``(scene, nbytes)``, on a worker thread.

:class:`~OpenGLContext.scenegraph.generatedtiles.GeneratedTiles` is the node
that streams one.
"""
from collections.abc import Hashable, Iterable
from typing import Any, NamedTuple, Optional, Protocol, cast

import numpy as np

from OpenGLContext.loaders.tiles3d.boundingvolume import SphereBV
from OpenGLContext.loaders.tiles3d.tileprocess import TileProcesses
from OpenGLContext.loaders.tiles3d.tileset import (
    BoundingVolume, RuntimeTile, RuntimeTileset,
)

__all__ = ['AssemblingGenerator', 'GeneratedTileset', 'TileChanges', 'TileGenerator']

#: A geometric error so large that the root refines at any distance.
_ALWAYS_REFINE = 1.0e12


class TileGenerator(Protocol):
    """What a :class:`GeneratedTileset` asks of the code that makes its tiles.

    A generator may also define ``origin(key)``, the world position of the tile's
    local origin. The tile is then drawn translated there, and ``generate`` builds
    its geometry around that point rather than around the world's origin, which
    keeps vertex coordinates small, and so precise in 32-bit floats, however far
    from the world's origin the tile lies. Bounding volumes stay in world space.
    """

    def keys_near(self, point: np.ndarray, radius: float) -> Iterable[Any]: ...

    def bounds(self, key: Any) -> BoundingVolume: ...

    def generate(self, key: Any) -> tuple[Any, int]: ...


class AssemblingGenerator(TileGenerator, Protocol):
    """A generator whose tiles are made in child processes: ``assemble`` is given what the
    child's maker returned for ``key`` and answers the tile's ``(scene, nbytes)``."""

    def assemble(self, key: Any, payload: Any) -> tuple[Any, int]: ...


class TileChanges(NamedTuple):
    """The tiles one :meth:`GeneratedTileset.ensure` made, and the ones it dropped."""

    created: list[RuntimeTile]
    retired: list[RuntimeTile]


class GeneratedTileset(RuntimeTileset):
    """A tileset whose tiles are made as the camera moves.

    The root has no content and refines at any distance; its children are the
    tiles made so far, each a leaf. ``reach`` is how far from the camera, in
    metres, a tile is made, and ``retain`` how far one is kept (``reach`` plus a
    quarter, by default), so a camera hovering at a boundary does not make and
    drop the same tile every frame.
    """

    def __init__(self, generator: TileGenerator, reach: float,
                 retain: Optional[float] = None,
                 processes: Optional[TileProcesses] = None) -> None:
        retain = reach * 1.25 if retain is None else retain
        if retain < reach:
            raise ValueError('retain (%s m) is less than reach (%s m), so a tile '
                             'would be dropped as soon as it was made'
                             % (retain, reach))
        root = RuntimeTile(SphereBV((0.0, 0.0, 0.0), 0.0), _ALWAYS_REFINE, 'REPLACE',
                           None, np.identity(4), [])
        super().__init__(root, _ALWAYS_REFINE, {'version': '1.1'})
        self.generator = generator
        #: Child processes that make the tiles' content, or None to have ``generate`` do it.
        self.processes = processes
        self.reach = float(reach)
        self.retain = float(retain)
        self._tiles: dict[Hashable, RuntimeTile] = {}

    def ensure(self, camera: Any) -> TileChanges:
        """Make the tiles within ``reach`` of ``camera`` and drop those beyond ``retain``."""
        point = np.asarray(camera, dtype='d')
        kept = set(self.generator.keys_near(point, self.retain))
        created = [self._make(key)
                   for key in dict.fromkeys(self.generator.keys_near(point, self.reach))
                   if key not in self._tiles]
        retired = [self._tiles.pop(key) for key in list(self._tiles) if key not in kept]
        for tile in retired:
            self.root.children.remove(tile)
            tile.parent = None
        if created or retired:
            self._enclose()
        return TileChanges(created, retired)

    def clear(self) -> None:
        """Drop every tile, as if the camera had never been near: the next :meth:`ensure` makes
        the ones it wants again."""
        for tile in self.root.children:
            tile.parent = None
        self.root.children = []
        self._tiles.clear()
        self._enclose()

    def loader(self, tile: RuntimeTile) -> tuple[Any, int]:
        """A tile's content from the generator: the ``loader_fn`` the runtime takes."""
        if self.processes is not None:
            generator = cast(AssemblingGenerator, self.generator)
            return generator.assemble(tile.content_key, self.processes.make(tile.content_key))
        return self.generator.generate(tile.content_key)

    def _make(self, key: Hashable) -> RuntimeTile:
        placement = np.identity(4)
        origin = getattr(self.generator, 'origin', None)
        if origin is not None:
            placement[:3, 3] = origin(key)
        tile = RuntimeTile(self.generator.bounds(key), 0.0, 'REPLACE', None,
                           placement, [], content_key=key)
        tile.parent = self.root
        self.root.children.append(tile)
        self._tiles[key] = tile
        return tile

    def _enclose(self) -> None:
        """Resize the root's sphere to hold every tile, so culling it culls only what is out."""
        spheres = [tile.bounding_volume.bounding_sphere() for tile in self.root.children]
        if not spheres:
            self.root.bounding_volume = SphereBV((0.0, 0.0, 0.0), 0.0)
            return
        centres = np.array([centre for centre, _ in spheres])
        centre = (centres.min(axis=0) + centres.max(axis=0)) / 2.0
        radius = max(float(np.linalg.norm(c - centre)) + r for c, r in spheres)
        self.root.bounding_volume = SphereBV(centre, radius)

