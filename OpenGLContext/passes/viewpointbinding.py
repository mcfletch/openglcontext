"""The scene's Viewpoints: publishing where they are, and binding the active one.

The render pass keeps a path to every ``Viewpoint`` in its scene -- authored in
a VRML97 world, or built by the glTF loader for each of a file's cameras -- and
keeps it current as nodes come and go. :func:`publish_viewpoints` hands those
paths to the scenegraph each frame as ``SceneGraph.viewpointPaths``, which is
where anything outside the pass reads the scene's cameras from, and tells the
context when the set has changed.

:func:`bind_scene_viewpoint` moves the view platform to the viewpoint X3D's
bind stack has bound, for the core-profile pass, which takes its camera from
the view platform only; :func:`next_viewpoint` binds the next.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
from vrml.vrml97 import nodetypes
from vrml.x3d import binding
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
    """Move ``context``'s platform to the scene's bound Viewpoint.

    The core-profile FlatPass drives the camera from the view platform alone.
    This moves the platform to the viewpoint X3D's bind stack has on top
    (:func:`vrml.x3d.binding.current_path`, which binds the first where none
    is), and only when that changes, so it never fights ordinary navigation.
    ``SceneGraph.boundViewpoint`` is the viewpoint the platform was last moved
    to.

    The paths are the ones :func:`publish_viewpoints` gave the scenegraph, so a
    Viewpoint that arrives after the first frame is as bindable as one that was
    there from the start.
    """
    sg = context.getSceneGraph()
    if sg is None:
        return
    view_path = binding.current_path(list(getattr(sg, 'viewpointPaths', ())))
    if view_path is None:
        return
    view = view_path[-1]
    if getattr(sg, 'boundViewpoint', None) is not view:
        view.moveTo(view_path, context)
        sg.boundViewpoint = view


def listed(path: Any, viewer: Any) -> bool:
    """Whether the viewpoint at the end of `path` is offered to a viewer at `viewer`

    Every ViewpointGroup on the path has to offer it
    (:meth:`~OpenGLContext.scenegraph.viewpointgroup.ViewpointGroup.lists`);
    `viewer` is a world position, or None to ask only whether each is
    displayed.
    """
    for index, node in enumerate(path[:-1]):
        lists = getattr(node, 'lists', None)
        if lists is None:
            continue
        local = None
        if viewer is not None:
            placed = path[:index + 1].transformMatrix()
            local = np.append(np.asarray(viewer, np.float64)[:3], 1.0)
            if placed is not None:
                local = local @ np.linalg.inv(np.asarray(placed, np.float64))
        if not (lists(local[:3]) if local is not None else node.displayed):
            return False
    return True


def next_viewpoint(context: Any, step: int = 1) -> Any:
    """Bind the viewpoint `step` along the scene's from the bound one; that viewpoint

    Only the viewpoints offered to the viewer (:func:`listed`) are stepped
    through. None where the scene offers none.
    """
    sg = context.getSceneGraph()
    paths = list(getattr(sg, 'viewpointPaths', ())) if sg is not None else []
    platform = context.getViewPlatform() if paths else None
    viewer = None if platform is None else platform.position
    views = [path[-1] for path in paths if listed(path, viewer)]
    if not views:
        return None
    current = binding.bound(views[0])
    index = next((i for i, view in enumerate(views) if view is current), -step)
    following = views[(index + step) % len(views)]
    following.set_bind = True
    return following
