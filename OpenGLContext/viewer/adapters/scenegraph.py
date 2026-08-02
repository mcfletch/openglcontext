"""Opening anything the scenegraph loaders already read.

:mod:`OpenGLContext.loaders.loader` dispatches a file to a handler that returns
a VRML97 ``SceneGraph`` -- that is how VRML97 and Wavefront OBJ are read, and how
a third-party format registered under :class:`OpenGLContext.plugins.Loader` is
read too.  What it does *not* work out is anything a viewer needs beyond the
nodes: how big the scene is, where its cameras are, or whether its coordinates
mean anything.  This fills that in, once, for all of them.
"""
from typing import Any, List, Tuple

from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.viewpoint import Viewpoint
from OpenGLContext.viewer.adapters.base import (
    SceneAdapter, ViewerScene, scene_bounds,
)

__all__ = ['SceneGraphAdapter', 'camera_name']


def camera_name(viewpoint: Any, index: int) -> str:
    """What to call a viewpoint in the caption and on the command line.

    Its ``description`` is the author's own words for it and is what a reader
    recognises; its DEF is what a ``--camera`` argument is most likely to be
    typed as.  Either beats ``camera3``.
    """
    return (getattr(viewpoint, 'description', '') or getattr(viewpoint, 'DEF', '')
            or 'camera%d' % index)


class SceneGraphAdapter(SceneAdapter):
    """A format whose loader hands back a VRML97 ``SceneGraph``."""

    def load(self, source: str) -> ViewerScene:
        """Parse ``source`` into a scene, measuring it so it can be framed."""
        from OpenGLContext.loaders.loader import Loader
        return self.sceneFrom(Loader.load(source))

    def sceneFrom(self, sceneGraph: Any) -> ViewerScene:
        """Wrap an already-parsed ``SceneGraph`` as a viewable scene.

        The document is handed over very nearly as it was found -- its sky, its
        lights and its sensors stay where the author put them.  The one thing
        moved is its ``Viewpoint`` nodes, which the viewer mounts at the top of
        the scene it builds; that is what makes them bindable and lets
        PageUp/PageDown cycle them.
        """
        viewpoints, rest = self.splitViewpoints(sceneGraph.children)
        center, radius = scene_bounds(rest)
        return ViewerScene(
            group=Group(children=rest),
            center=center, radius=radius,
            viewpoints=viewpoints,
            cameras=[{'name': camera_name(viewpoint, index)}
                     for index, viewpoint in enumerate(viewpoints)],
            sceneGraph=sceneGraph,
        )

    @staticmethod
    def splitViewpoints(children: Any) -> Tuple[List[Any], List[Any]]:
        """The document's top-level viewpoints, and everything else.

        Only top-level ones are offered as cameras.  A ``Viewpoint`` nested
        inside a ``Transform`` is positioned by that transform, so lifting it
        out would silently move it; it is left where it is and simply not
        offered, which is a smaller lie than showing it from the wrong place.
        """
        viewpoints = [child for child in children if isinstance(child, Viewpoint)]
        rest = [child for child in children if not isinstance(child, Viewpoint)]
        return viewpoints, rest
