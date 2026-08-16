"""Binding the scene's active Viewpoint into the view platform.

The core-profile FlatPass drives the camera purely from the view platform and does
not walk the scenegraph looking for bindable Viewpoints. This bridges the standard
VRML97 viewpoint-binding mechanism into it, so a Viewpoint authored in a VRML world
-- or synthesised for a glTF camera -- becomes bindable there too.
"""

from vrml.vrml97 import nodetypes
from OpenGLContext import visitor
import logging

log = logging.getLogger(__name__)


def bind_scene_viewpoint(context):
    """Move ``context``'s platform to the scene's currently-bound Viewpoint.

    The core-profile FlatPass drives the camera purely from the view platform and
    does not itself walk the scenegraph to process Viewpoint bindables. This
    bridges the standard VRML97 viewpoint-binding mechanism -- ``isBound`` /
    ``SceneGraph.boundViewpoint``, cycled by ``Context.OnNextViewpoint`` -- into the
    core profile, so any Viewpoint (from a VRML world or synthesised for a glTF
    camera) becomes bindable there too. It only teleports when the bound viewpoint
    changes, so it never fights ordinary walk-around navigation.

    The viewpoint paths are cached on the SceneGraph (invalidated naturally when the
    context's scenegraph is swapped for a fresh one), so a scene with no viewpoints
    costs one traversal and nothing thereafter.
    """
    sg = context.getSceneGraph()
    if sg is None:
        return
    paths = getattr(sg, '_core_viewpoint_paths', None)
    if paths is None:
        paths = visitor.find(context, (nodetypes.Viewpoint,))
        sg._core_viewpoint_paths = paths
        sg.viewpointPaths = paths[:]
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
