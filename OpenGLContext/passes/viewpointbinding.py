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

import weakref

import numpy as np
from vrml.vrml97 import nodetypes
from vrml.x3d import binding

from OpenGLContext.events import systemtime
from OpenGLContext.move import navigationinfo
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


class ViewpointTransition:
    """The camera's move from one pose to a newly bound viewpoint's -- no GL

    ``kind`` is LINEAR, straight at a steady pace, or ANIMATE, easing in and
    out; positions are interpolated straight and orientations along the
    shorter arc.
    """

    def __init__(self, position: Any, orientation: Any, target: Any,
                 target_orientation: Any, start: float, duration: float,
                 kind: str = 'LINEAR') -> None:
        self.position = np.asarray(position, dtype='d')[:3]
        self.orientation = orientation
        self.target = np.asarray(target, dtype='d')[:3]
        self.target_orientation = target_orientation
        self.start = float(start)
        self.duration = max(float(duration), 1e-9)
        self.kind = kind

    def at(self, now: float) -> tuple[np.ndarray, Any, bool]:
        """(position, orientation, arrived) at time `now`"""
        fraction = min(max((float(now) - self.start) / self.duration, 0.0), 1.0)
        eased = fraction * fraction * (3.0 - 2.0 * fraction) if self.kind == 'ANIMATE' else fraction
        position = self.position + (self.target - self.position) * eased
        orientation = self.orientation.slerp(self.target_orientation, eased)
        return position, orientation, fraction >= 1.0


#: Each context's transition in progress.
_moving: 'weakref.WeakKeyDictionary[Any, ViewpointTransition]' = weakref.WeakKeyDictionary()


def bind_scene_viewpoint(context: Any) -> None:
    """Move ``context``'s platform to the scene's bound Viewpoint.

    The core-profile FlatPass drives the camera from the view platform alone.
    This moves the platform to the viewpoint X3D's bind stack has on top
    (:func:`vrml.x3d.binding.current_path`, which binds the first where none
    is), and only when that changes, so it never fights ordinary navigation.
    The first viewpoint is jumped to; one bound after it is moved to as the
    bound NavigationInfo's transition says
    (:func:`~OpenGLContext.move.navigationinfo.transition_of`), a frame at a
    time, and the NavigationInfo sends ``transitionComplete`` on arrival.
    ``SceneGraph.boundViewpoint`` is the viewpoint the platform was last moved
    to.

    The paths are the ones :func:`publish_viewpoints` gave the scenegraph, so a
    Viewpoint that arrives after the first frame is as bindable as one that was
    there from the start.
    """
    sg = context.getSceneGraph()
    if sg is None:
        return
    _step_transition(context, sg)
    view_path = binding.current_path(list(getattr(sg, 'viewpointPaths', ())))
    if view_path is None:
        return
    view = view_path[-1]
    previous = getattr(sg, 'boundViewpoint', None)
    if previous is view:
        return
    sg.boundViewpoint = view
    platform = getattr(context, 'platform', None) or context.getViewPlatform()
    info = binding.bound(sg, nodetypes.NavigationInfo)
    kind, seconds = navigationinfo.transition_of(info)
    if not previous or kind == 'TELEPORT' or platform is None:
        view.moveTo(view_path, context)
        return
    position, orientation = np.array(platform.position, 'd'), platform.quaternion
    view.moveTo(view_path, context)
    move = ViewpointTransition(position, orientation, platform.position,
                               platform.quaternion, systemtime.systemTime(), seconds, kind)
    _moving[context] = move
    platform.setPosition(position[:3])
    platform.setOrientation(orientation)


def _step_transition(context: Any, sg: Any) -> None:
    """Move the platform on along the transition in progress, if there is one"""
    move = _moving.get(context)
    if move is None:
        return
    position, orientation, arrived = move.at(systemtime.systemTime())
    platform = getattr(context, 'platform', None) or context.getViewPlatform()
    platform.setPosition(position)
    platform.setOrientation(orientation)
    redraw = getattr(context, 'triggerRedraw', None)
    if redraw is not None:
        redraw(1)
    if arrived:
        del _moving[context]
        info = binding.bound(sg, nodetypes.NavigationInfo)
        if info is not None:
            info.transitionComplete = True


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
