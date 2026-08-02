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
from typing import Any, Iterable, Optional, Sequence, Tuple

__all__ = ['SceneAdapter', 'ViewerScene', 'UnknownSourceType', 'scene_bounds']


class UnknownSourceType(ValueError):
    """No adapter is registered for this source."""


def scene_bounds(nodes: Iterable[Any]) -> Tuple[Tuple[float, float, float], float]:
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
    found = boundingSphere(nodes)
    if found is None:
        return (0.0, 0.0, 0.0), 1.0
    center, radius = found
    return center, radius or 1.0


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
    """

    def __init__(self, group: Any,
                 center: Sequence[float] = (0.0, 0.0, 0.0),
                 radius: float = 1.0,
                 viewpoints: Optional[list] = None,
                 cameras: Optional[list] = None,
                 animations: Optional[list] = None,
                 exposure: float = 1.0,
                 sceneGraph: Any = None) -> None:
        self.group = group
        self.center: Tuple[float, ...] = tuple(float(v) for v in center)
        self.radius = float(radius)
        self.strays = 0
        self.stray_reach = 0.0
        self.viewpoints = viewpoints if viewpoints is not None else []
        self.cameras = cameras if cameras is not None else []
        self.animations = animations if animations is not None else []
        self.exposure = exposure
        #: The loaded document's own root, when it has one, for its DEF registry.
        self.sceneGraph = sceneGraph

    def player(self, index: int = 0, loop: bool = True) -> Any:
        """The animation player for animation ``index``, or None.

        A format with no animation in it says so by having none to give, rather
        than by the viewer knowing which formats can animate.
        """
        return None


class SceneAdapter(object):
    """How a viewer opens one kind of source.

    Registered under :class:`OpenGLContext.plugins.Adapter` against the
    suffixes and content types it handles, so a third party adds a format
    without touching the viewer or this package.  Instantiated per scene: an
    adapter may keep state for the scene it loaded, which is how a streaming
    format keeps its runtime alive.
    """

    #: Registry key, for ``--format`` and for error messages.
    name: str = ''

    #: Whether a scene with no camera of its own may be moved to the origin so
    #: it can be framed.  A *model* may -- its coordinates are arbitrary.  A
    #: *world* may not: its ground is at y=0, its viewpoints are in its own
    #: space, and moving it would put the avatar underground.
    recentres: bool = True

    def configure(self, options: Any) -> None:
        """Take what the viewer's options say about *this kind of* source.

        Called before :meth:`load`.  Most formats are read the one way there is
        to read them and want nothing here; a streaming one has a detail target
        and a memory budget, and a user moving from a per-format command to the
        one viewer must not lose the controls they had.
        """

    def load(self, source: str) -> Any:
        """Read ``source`` and return the scene to show.

        **Runs on a worker thread, so it must not touch GL.**  Everything that
        uploads is left to the render thread, which is what lets the window keep
        drawing through a download.
        """
        raise NotImplementedError("%s.load" % (type(self).__name__,))

    def update(self, viewer: Any) -> bool:
        """Per-frame work for a source that is still arriving.

        Called from the viewer's idle loop with the viewer itself, so a
        streaming format can page tiles in against the current camera.  Returns
        whether anything changed and the frame should be redrawn.  Static
        formats -- everything read once from a file -- want nothing here.
        """
        return False

    def shutdown(self) -> None:
        """Release anything the scene is still holding.  Called on teardown."""
