"""Reading an OGC 3D Tiles dataset (``tileset.json``).

A tileset is not read once: it is larger than memory by design, and pages itself
in and out against wherever the camera is, refining detail as you approach.  So
reading one builds a :class:`~OpenGLContext.scenegraph.tilesterrain.TilesTerrain`
-- the node that streams -- and primes it with the first tiles of the view the
dataset opens on, and the result is that node.  A reader is instantiated per
request so it can keep what it measured: the dataset's bounds and where its
content is.

The tiles themselves are glTF, so what finally reaches the card is what the
glTF reader would have produced; what differs is only *when*.  The terrain is
mounted in a scene and told where the camera is each frame
(``update_for_camera``); :meth:`TilesReader.shutdown` stops its workers.
"""
import math
from typing import Any, Optional

import numpy as np

from OpenGLContext.loaders.readers import SceneReader

__all__ = ['TilesReader', 'leaf_tile', 'opening_aim', 'opening_eye']

#: Where the camera opens over a dataset, as fractions of its framed radius: how
#: high above the content it hovers, and how far back from the aim point it
#: stands.  A dataset is somewhere to be rather than an object to look at, and
#: fitting the whole bounding sphere puts a city kilometres away, where it is a
#: smudge and every tile is at its coarsest.
OPENING_HEIGHT = 0.05
OPENING_DISTANCE = 0.12

#: How far back the opening view stands from the tile it aims at, as a multiple
#: of that tile's own radius.  A city is spread over its whole extent, so a
#: fraction of the dataset lands over streets; a dataset that is one object in a
#: wide bounding volume is *all* at the aim point, and the same fraction lands
#: inside it.  Taking whichever is further keeps both in view.
OPENING_TILE_DISTANCE = 2.5

#: Vertical field of view the streamer measures screen-space error against.  It
#: has to agree with what is actually rendered, or the dataset refines to a
#: detail level the frame does not show.
DEFAULT_FOV = math.radians(55.0)
#: Screen-space error target in pixels: how wrong a tile may look before a finer
#: one is fetched.  Lower is sharper and slower.
DEFAULT_SSE = 16.0
#: Resident tile memory, in bytes.
DEFAULT_MEMORY = 512 * 1024 * 1024
#: Workers decoding tile payloads off the render thread.
DEFAULT_WORKERS = 4
#: Rounds of "stream, then wait" before the first frame, so the viewer opens on
#: geometry rather than on an empty sky while the first tiles arrive.
PRIME_ROUNDS = 12
#: Longest to wait for one of those rounds.
PRIME_TIMEOUT = 6.0


def leaf_tile(tile: Any) -> Any:
    """Descend to the first tile that actually carries drawable content.

    An external-tileset or grouping tile has no content of its own; its geometry
    lives below it.  Framing on the first content tile aims the camera at real
    mesh rather than at wherever a bounding volume happens to be centred.
    """
    while tile.content_uri is None and tile.children:
        tile = tile.children[0]
    return tile


def opening_aim(root: Any) -> "tuple[np.ndarray, float]":
    """The point over the dataset to open the camera above.

    The content tile nearest the middle of the extent, which in a city is the
    middle of the city.  Aiming at the *first* content tile instead lands
    wherever the tree happens to start -- a corner, and the corner of a city is
    a park.  A tileset with no content at all leaves the extent's own centre,
    since there is nothing better to say.

    Its radius comes back too, because how far to stand off depends on the size
    of what is being looked at rather than on the size of the dataset.
    """
    center, radius = root.bounding_volume.bounding_sphere()
    center = np.asarray(center, dtype='d')
    nearest, best, extent = None, None, float(radius or 0.0)
    for tile in root.iter_tiles():
        if not tile.has_content:
            continue
        position, tile_radius = tile.bounding_volume.bounding_sphere()
        position = np.asarray(position, dtype='d')
        # Horizontally nearest: a tall tile is no further away for being tall.
        distance = float(np.linalg.norm((position - center)[[0, 2]]))
        if best is None or distance < best:
            nearest, best, extent = position, distance, float(tile_radius or 0.0)
    return (center if nearest is None else nearest), extent


def opening_eye(center: Any, radius: float, tile_radius: float = 0.0) -> Any:
    """Where to stand to arrive *in* a dataset rather than outside it.

    Hovers :data:`OPENING_HEIGHT` of the framed radius above the aim point and
    :data:`OPENING_DISTANCE` back from it, so the first frame is geometry at a
    detail level worth streaming.  ``tile_radius`` is how big the tile aimed at
    is, and holds the eye :data:`OPENING_TILE_DISTANCE` times that far off when
    a fraction of the dataset would be closer.  Answers the eye and its height.
    """
    center = np.asarray(center, dtype='d')
    stand_off = max(radius * OPENING_DISTANCE, tile_radius * OPENING_TILE_DISTANCE)
    height = max(radius * OPENING_HEIGHT, tile_radius * OPENING_HEIGHT * 8.0, 1e-3)
    return center + np.array([0.0, height, stand_off]), height


class TilesReader(SceneReader):
    """A streamed 3D Tiles dataset: bigger than memory, and still arriving."""

    name = 'tiles3d'

    #: The live runtime, once a dataset has been read.
    terrain: Any = None

    def __init__(self, fov: float = DEFAULT_FOV, sse: float = DEFAULT_SSE,
                 memory: int = DEFAULT_MEMORY, recenter: bool = True,
                 cacheDirectory: Optional[str] = None) -> None:
        self.fov = fov
        self.sse = sse
        self.memory = memory
        self.recenter = recenter
        self.cacheDirectory = cacheDirectory
        self.radius = 1.0
        self.center = np.zeros(3)
        #: Where over the dataset the camera opens, and how big the tile it
        #: aims at is; see :func:`opening_aim`.
        self.aim = np.zeros(3)
        self.aimRadius = 0.0

    def configure(self, options: Any) -> None:
        """Take the streaming knobs from ``options``.

        ``sse`` (pixels), ``memory`` (megabytes), ``no_recenter`` and
        ``cache_dir``, each left alone when the options do not name it, so the
        defaults are stated once -- here -- rather than also in a command line.
        """
        if getattr(options, 'sse', None) is not None:
            self.sse = float(options.sse)
        if getattr(options, 'memory', None) is not None:
            self.memory = int(options.memory) * 1024 * 1024
        if getattr(options, 'no_recenter', False):
            self.recenter = False
        if getattr(options, 'cache_dir', None):
            self.cacheDirectory = options.cache_dir

    def read(self, source: str) -> Any:
        """Build the streaming runtime and prime it with the opening view.

        Priming happens against the pose the viewer is about to take, not the
        one it currently has: the residency loads the detail the opening view
        needs, and refining from a default pose inside the dataset would fetch
        the finest tiles and then evict them the moment the camera jumped out.
        """
        from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
        self.terrain = TilesTerrain(
            source, fovy=self.fov, max_sse=self.sse, workers=DEFAULT_WORKERS,
            memory_budget=self.memory, recenter=self.recenter,
            cache_dir=self.cacheDirectory)
        self.center, self.radius = self._bounds()
        self.aim, self.aimRadius = opening_aim(self.terrain.tileset.root)
        self._prime()
        return self.terrain

    def isGeospatial(self) -> bool:
        """Whether the loaded dataset is placed on the globe, and so in metres."""
        tileset = getattr(self.terrain, 'tileset', None)
        return bool(getattr(tileset, 'geospatial', False))

    def shutdown(self) -> None:
        """Stop the workers.  Leaving them is how a program fails to exit."""
        terrain, self.terrain = self.terrain, None
        if terrain is not None:
            terrain.shutdown()

    # -- framing ----------------------------------------------------------
    def _bounds(self) -> tuple[np.ndarray, float]:
        """The whole dataset's bounding sphere, aimed at real geometry."""
        from OpenGLContext.loaders.tiles3d.gltf_uploader import make_tile_loader
        return self.boundsOf(self.terrain.tileset.root,
                             make_tile_loader(cache_dir=self.cacheDirectory))

    @staticmethod
    def boundsOf(root: Any, load_tile: Any) -> tuple[np.ndarray, float]:
        """``(centre, radius)`` for a tileset, from its extent and its mesh.

        The root bounding volume gives the extent.  The first content tile's
        own centre, transformed to world space, gives an aim point that lands on
        geometry even when the bounding-volume centre does not coincide with any
        -- and it is trusted only when it falls *inside* the extent, so a
        mis-transformed tile throws the camera nowhere.  A tile that will not
        load simply leaves the bounding centre, since framing is not worth
        failing a whole dataset over.
        """
        center, radius = root.bounding_volume.bounding_sphere()
        center = np.asarray(center, dtype='d')
        radius = float(radius or 1.0)
        try:
            leaf = leaf_tile(root)
            scene, _ = load_tile(leaf)
            aim = (leaf.content_transform
                   @ np.append(np.asarray(scene.center, 'd'), 1.0))[:3]
            if np.linalg.norm(aim - center) <= radius:
                center = aim
        except Exception:
            pass                # no content, or it would not load: the extent will do
        return center, radius

    def _prime(self) -> None:
        """Stream against the pose the viewer will take, before the first frame."""
        eye = tuple(float(v) for v in opening_eye(self.aim, self.radius,
                                                  self.aimRadius)[0])
        for _ in range(PRIME_ROUNDS):
            self.terrain.update_for_camera(eye, 700)
            self.terrain.wait_for_loads(timeout=PRIME_TIMEOUT)
