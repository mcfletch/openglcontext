"""Opening an OGC 3D Tiles dataset (``tileset.json``).

Unlike every other format the viewer opens, a tileset is not read once: it is
larger than memory by design, and pages itself in and out against wherever the
camera is, refining detail as you approach.  So this adapter keeps a runtime
alive for the scene it loaded -- which is why an adapter is instantiated per
scene rather than being a singleton -- and does its real work in
:meth:`update`, once a frame, from the viewer's idle loop.

The tiles themselves are glTF, so what finally reaches the card is what the
glTF adapter would have produced; what differs is only *when*.

Everything a tileset needs beyond streaming lives here: framing on the mesh
rather than on a bounding-volume centre, the priming rounds before the first
frame, and the per-frame view projection.
"""
import math
from typing import Any, Optional, Tuple

import numpy as np

from OpenGLContext.viewer.adapters.base import SceneAdapter, ViewerScene

__all__ = ['TilesAdapter', 'opening_pose']

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


def opening_pose(center: Any, radius: float, tile_radius: float = 0.0) -> Any:
    """Where to stand to arrive *in* a dataset rather than outside it.

    Hovers :data:`OPENING_HEIGHT` of the framed radius above the aim point and
    :data:`OPENING_DISTANCE` back from it, looking at the content — so the first
    frame is geometry at a detail level worth streaming, and flying forward goes
    further into the dataset rather than up to it.

    ``tile_radius`` is how big the tile aimed at is, and holds the camera
    :data:`OPENING_TILE_DISTANCE` times that far off when a fraction of the
    dataset would be closer -- a dataset that is one object inside a wide
    bounding volume is otherwise opened from inside it.

    The near plane comes from the height rather than from the whole dataset, or
    a camera a few hundred metres up over a city would clip away everything
    below it.
    """
    from OpenGLContext.viewer import framing
    center = np.asarray(center, dtype='d')
    stand_off = max(radius * OPENING_DISTANCE, tile_radius * OPENING_TILE_DISTANCE)
    height = max(radius * OPENING_HEIGHT, tile_radius * OPENING_HEIGHT * 8.0, 1e-3)
    eye = center + np.array([0.0, height, stand_off])
    pose = framing.look_from(eye, center, radius)
    if pose is None:                    # pragma: no cover - height is never 0
        return None
    return pose._replace(near=max(0.05, height * 0.005), far=max(radius * 8.0,
                                                                height * 100.0))


def _forward(quaternion: Any) -> np.ndarray:
    """World-space look direction for a view platform's orientation."""
    rotation = np.asarray(quaternion.matrix())[:3, :3]
    forward: np.ndarray = rotation.T @ np.array([0.0, 0.0, -1.0])
    return forward


class TilesAdapter(SceneAdapter):
    """A streamed 3D Tiles dataset: bigger than memory, and still arriving."""

    name = 'tiles3d'

    #: Never re-centred.  A tileset's coordinates are the world's -- often
    #: Earth-centred, already shifted to the origin by the runtime for float
    #: precision -- and its tiles are placed in them.
    recentres = False

    #: The live runtime, once a scene has been loaded.
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
        """Take the streaming knobs from the viewer's options.

        Each is left alone when the options do not name it, so the defaults are
        stated once -- here -- rather than also in the command line.
        """
        if getattr(options, 'sse', None) is not None:
            self.sse = float(options.sse)
        if getattr(options, 'memory', None) is not None:
            self.memory = int(options.memory) * 1024 * 1024
        if getattr(options, 'no_recenter', False):
            self.recenter = False
        if getattr(options, 'cache_dir', None):
            self.cacheDirectory = options.cache_dir

    def load(self, source: str) -> ViewerScene:
        """Build the streaming runtime and prime it with the framed view.

        Priming happens against the pose the viewer is about to take, not the
        one it currently has: the residency loads the detail the framed view
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
        return self.sceneFor(self.terrain)

    def sceneFor(self, group: Any) -> ViewerScene:
        """The loaded scene, opening over its content when it is big enough.

        The stand-off follows the tile aimed at, so a dataset that is one
        object is seen whole rather than from inside it.
        """
        pose = opening_pose(self.aim, self.radius, self.aimRadius)
        return ViewerScene(group=group, center=tuple(self.center),
                           radius=self.radius, pose=pose,
                           metric=self.isGeospatial())

    def isGeospatial(self) -> bool:
        """Whether the loaded dataset is placed on the globe, and so in metres."""
        tileset = getattr(self.terrain, 'tileset', None)
        return bool(getattr(tileset, 'geospatial', False))

    def update(self, viewer: Any) -> bool:
        """Page tiles in for wherever the camera now is.  Once a frame."""
        if self.terrain is None:
            return False
        platform = getattr(viewer, 'platform', None)
        eye = self._eye(platform)
        self.terrain.update_for_camera(
            eye, viewer.getViewPort()[1] or 700,
            view_projection=self._viewProjection(viewer, platform, eye))
        return True

    def shutdown(self) -> None:
        """Stop the workers.  Leaving them is how a viewer fails to exit."""
        terrain, self.terrain = self.terrain, None
        if terrain is not None:
            terrain.shutdown()

    # -- framing ----------------------------------------------------------
    def _bounds(self) -> Tuple[np.ndarray, float]:
        """The whole dataset's bounding sphere, aimed at real geometry."""
        from OpenGLContext.loaders.tiles3d.gltf_uploader import make_tile_loader
        return self.boundsOf(self.terrain.tileset.root,
                             make_tile_loader(cache_dir=self.cacheDirectory))

    @staticmethod
    def boundsOf(root: Any, load_tile: Any) -> Tuple[np.ndarray, float]:
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
        pose = opening_pose(self.aim, self.radius, self.aimRadius)
        eye = tuple(float(v) for v in pose.position)
        for _ in range(PRIME_ROUNDS):
            self.terrain.update_for_camera(eye, 700)
            self.terrain.wait_for_loads(timeout=PRIME_TIMEOUT)

    # -- where the camera is ----------------------------------------------
    def _eye(self, platform: Any) -> Tuple[float, ...]:
        if platform is None:
            return tuple(float(v) for v in self.center)
        return tuple(float(v) for v in platform.position[:3])

    def _viewProjection(self, viewer: Any, platform: Any,
                        eye: Tuple[float, ...]) -> np.ndarray:
        """The matrix the streamer culls and measures error against.

        Built here rather than read from the renderer because the streamer runs
        *before* the frame it is preparing tiles for, and because a dataset
        spanning metres to kilometres needs near and far planes scaled to its
        own size rather than the viewer's defaults.
        """
        from OpenGLContext.loaders.tiles3d.frustum import view_projection
        quaternion = getattr(platform, 'quaternion', None)
        if quaternion is not None:
            forward = _forward(quaternion)
        else:
            forward = self.center - np.asarray(eye)
            if not np.asarray(forward).any():       # the eye is at the centre
                forward = np.array([0.0, 0.0, -1.0])
        target = np.asarray(eye) + np.asarray(forward) * self.radius
        width, height = viewer.getViewPort()
        aspect = (width / max(1, height)) or 1.0
        return view_projection(eye, tuple(target), (0, 1, 0), self.fov, aspect,
                               max(1e-4, self.radius * 0.02), self.radius * 60.0)
