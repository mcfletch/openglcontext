"""The scene's Viewpoints: publishing where they are, and binding the active one.

The render pass keeps a path to every ``Viewpoint`` in its scene -- authored in
a VRML97 world, or built by the glTF loader for each of a file's cameras -- and
keeps it current as nodes come and go. :func:`publish_viewpoints` hands those
paths to the scenegraph each frame as ``SceneGraph.viewpointPaths``, which is
where anything outside the pass reads the scene's cameras from, and tells the
context when the set has changed.

:func:`bind_scene_viewpoint` bridges the standard VRML97 binding mechanism into
the core-profile pass, which takes its camera from the view platform only.
"""

from collections.abc import Sequence
from typing import Any

from vrml.vrml97 import nodetypes
import logging

log = logging.getLogger(__name__)


def publish_viewpoints(context: Any, pass_: Any) -> None:
    """Give the scenegraph the pass's paths to its Viewpoints, in the order found.

    Assigns ``SceneGraph.viewpointPaths`` and, where that is a different set
    of paths from the last frame's, calls ``context.OnViewpointsChanged`` with
    them: a scene loaded, a camera added or taken away. A pass drawing no
    scenegraph -- the context's own children -- has nowhere to publish to.
    """
    graph = getattr(pass_, 'scene', None)
    if graph is None:
        return
    paths = tuple(pass_.paths.get(nodetypes.Viewpoint, ()))
    known: Sequence[Any] = getattr(graph, 'viewpointPaths', ())
    if len(paths) == len(known) and all(
            path is seen for path, seen in zip(paths, known)):
        return
    graph.viewpointPaths = paths
    changed = getattr(context, 'OnViewpointsChanged', None)
    if changed is not None:
        changed(paths)


def bind_scene_viewpoint(context: Any) -> None:
    """Move ``context``'s platform to the scene's currently-bound Viewpoint.

    The core-profile FlatPass drives the camera purely from the view platform and
    does not itself walk the scenegraph to process Viewpoint bindables. This
    bridges the standard VRML97 viewpoint-binding mechanism -- ``isBound`` /
    ``SceneGraph.boundViewpoint``, cycled by ``Context.OnNextViewpoint`` -- into the
    core profile, so any Viewpoint (from a VRML world or synthesised for a glTF
    camera) becomes bindable there too. It only teleports when the bound viewpoint
    changes, so it never fights ordinary walk-around navigation.

    The paths are the ones :func:`publish_viewpoints` gave the scenegraph, so a
    Viewpoint that arrives after the first frame is as bindable as one that was
    there from the start.
    """
    sg = context.getSceneGraph()
    if sg is None:
        return
    paths = list(getattr(sg, 'viewpointPaths', ()))
    if not paths:
        return
    view = view_path = None
    for path in paths:
        if getattr(path[-1], 'isBound', None):
            view, view_path = path[-1], path
    if view is None:
        bound = getattr(sg, 'boundViewpoint', None)
        if bound is not None:
            for i, path in enumerate(paths):
                if path[-1] is bound:
                    view_path = paths[(i + 1) % len(paths)]
                    view = view_path[-1]
                    break
        if view is None:
            view_path = paths[0]
            view = view_path[-1]
        view.isBound = True
    if getattr(sg, 'boundViewpoint', None) is not view:
        view.moveTo(view_path, context)
        sg.boundViewpoint = view
