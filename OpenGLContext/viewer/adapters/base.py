"""What a viewer has to know about one kind of source.

The viewer knows how to show a scene and nothing about file formats; an adapter
knows one format and nothing about showing.  Everything format-specific -- how
to read the file, where its bounds are, what cameras and animations it carries,
whether its coordinates mean anything -- is on this side of the line, so adding
a format is writing one of these rather than editing the viewer.

The scene an adapter produces answers a fixed set of questions, listed on
:class:`ViewerScene`.  :class:`~OpenGLContext.loaders.gltf.scene.GLTFScene`
already answers them and is handed back as it is; a loader that returns
something else is wrapped in a :class:`ViewerScene`.
"""
from collections.abc import Iterable, Sequence
from typing import Any, Optional, cast

from OpenGLContext.loaders.formats import UnknownSourceType
from OpenGLContext.loaders.readers import SceneReader

__all__ = ['SceneAdapter', 'ViewerScene', 'UnknownSourceType', 'scene_bounds']


def scene_bounds(nodes: Iterable[Any]) -> tuple[tuple[float, float, float], float]:
    """The bounding sphere ``(center, radius)`` of a loaded document's nodes.

    What an adapter hands the viewer to frame a camera with, for a format whose
    loader does not work bounds out for itself.  The measuring itself is
    :func:`OpenGLContext.scenegraph.boundingvolume.boundingSphere`, which the
    context also uses to decide where an examine drag pivots.

    A document with nothing measurable in it comes back as the unit sphere at
    the origin, so a viewer built on this still has a distance to stand at
    instead of dividing by nothing.
    """
    from OpenGLContext.scenegraph.boundingvolume import boundingSphere
    found = boundingSphere(list(nodes))
    if found is None:
        return (0.0, 0.0, 0.0), 1.0
    center, radius = found
    return (float(center[0]), float(center[1]), float(center[2])), radius or 1.0


class ViewerScene(object):
    """A loaded scene, in the shape a viewer consumes.

    ``group``
        The renderable root the viewer mounts -- one node, whatever the file
        held.
    ``center``, ``radius``
        The bounding sphere, which is what the camera is framed against.
    ``strays``, ``stray_reach``
        How many parts the source drew far outside that sphere, and how far the
        farthest of them reaches in radii of it.  A format whose loader frames
        the model rather than the file's whole extent says here what it left
        out, so the viewer can tell the user why part of the file starts off
        screen; both are 0 when everything is framed.
    ``viewpoints``, ``cameras``
        One ``Viewpoint`` node per camera the source defines, in document
        order, and a matching dict per camera carrying at least a ``name``.
        Empty when the source has no cameras of its own, in which case the
        viewer frames the whole thing instead.
    ``animations``
        Whatever :meth:`player` can play, or empty.
    ``exposure``
        Camera exposure the source's own lighting asks for; 1.0 is neutral.
    ``metric``
        True when the scene's units are metres, which a geospatial dataset
        knows and a model does not. It is what tells a viewer how big a person
        is in this world rather than guessing from its extent.
    ``pose``
        Where to open the camera, when the adapter knows better than a fit of
        the bounding sphere -- a streamed dataset opens *inside* itself. None
        leaves the viewer to frame the whole scene as it always has.
    ``notices``
        The copyright and licence notices the source carries, as
        :class:`~OpenGLContext.loaders.notices.Notice` records, the whole
        file's first.  Empty when it states none, or when its format has
        nowhere to state them.
    """

    def __init__(self, group: Any,
                 center: Sequence[float] = (0.0, 0.0, 0.0),
                 radius: float = 1.0,
                 viewpoints: Optional[list] = None,
                 cameras: Optional[list] = None,
                 animations: Optional[list] = None,
                 exposure: float = 1.0,
                 sceneGraph: Any = None,
                 pose: Any = None,
                 metric: bool = False,
                 notices: Optional[list] = None) -> None:
        self.group = group
        self.center: tuple[float, ...] = tuple(float(v) for v in center)
        self.radius = float(radius)
        self.strays = 0
        self.stray_reach = 0.0
        self.viewpoints = viewpoints if viewpoints is not None else []
        self.cameras = cameras if cameras is not None else []
        self.animations = animations if animations is not None else []
        self.exposure = exposure
        self.pose = pose
        self.metric = metric
        self.notices = notices if notices is not None else []
        #: The loaded document's own root, when it has one, for its DEF registry.
        self.sceneGraph = sceneGraph

    def player(self, index: int = 0, loop: bool = True) -> Any:
        """The animation player for animation ``index``, or None.

        A format with no animation in it says so by having none to give, rather
        than by the viewer knowing which formats can animate.
        """
        return None


class SceneAdapter(SceneReader):
    """How a viewer opens one kind of source.

    A :class:`~OpenGLContext.loaders.readers.SceneReader` that can also say
    what a viewer needs to show what it read.  Registered under
    :class:`OpenGLContext.plugins.Adapter` against the suffixes and content
    types it handles, so a third party adds a format without touching the
    viewer or this package.  Instantiated per scene: an adapter may keep state
    for the scene it loaded, which is how a streaming format keeps its runtime
    alive.  :meth:`read` returns the format's own result and :meth:`present`
    turns it into a :class:`ViewerScene`.
    """

    #: Whether a scene with no camera of its own may be moved to the origin so
    #: it can be framed.  A *model* may -- its coordinates are arbitrary.  A
    #: *world* may not: its ground is at y=0, its viewpoints are in its own
    #: space, and moving it would put the avatar underground.
    recentres: bool = True

    def present(self, native: Any) -> ViewerScene:
        """What :meth:`read` returned, in the shape a viewer consumes.

        Runs on the render thread, so it does measuring and wrapping and no
        reading.  A result that already answers the questions on
        :class:`ViewerScene` comes back as it is.
        """
        return cast(ViewerScene, native)

    def load(self, source: str) -> ViewerScene:
        """Read ``source`` and return the scene to show: :meth:`read`, presented.

        For a caller with no :class:`~OpenGLContext.loaders.sceneloader.SceneLoader`;
        **runs on whatever thread calls it, so off the render thread it must
        not touch GL.**
        """
        return self.present(self.read(source))

    def update(self, viewer: Any) -> bool:
        """Per-frame work for a source that is still arriving.

        Called from the viewer's idle loop with the viewer itself, so a
        streaming format can page tiles in against the current camera.  Returns
        whether anything changed and the frame should be redrawn.  Static
        formats -- everything read once from a file -- want nothing here.
        """
        return False
