"""The scene's Viewpoints: publishing where they are, and binding the active one.

The render pass keeps a path to every ``Viewpoint`` in its scene -- authored in
a VRML97 world, or built by the glTF loader for each of a file's cameras -- and
keeps it current as nodes come and go. :func:`publish_viewpoints` hands those
paths to the scenegraph each frame as ``SceneGraph.viewpointPaths``, which is
where anything outside the pass reads the scene's cameras from, and tells the
context when the set has changed.

:func:`bind_scene_viewpoint` moves the view platform, which the pass takes
its camera from, to the viewpoint X3D's bind stack has bound;
:func:`next_viewpoint` binds the next.
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

    In a scene drawn as layers, the Viewpoints of the layer navigation drives
    (:meth:`~OpenGLContext.passes.layerpass.LayeringPassMixin.layerPaths`).

    Assigns ``SceneGraph.viewpointPaths`` and, where that is a different set
    of paths from the last frame's, calls ``context.OnViewpointsChanged`` with
    them: a scene loaded, a camera added or taken away. A pass drawing no
    scenegraph -- the context's own children -- has nowhere to publish to.
    """
    graph = getattr(pass_, 'scene', None)
    if graph is None:
        return
    # A scene drawn as layers is navigated in one of them, whose viewpoints these are
    layered = getattr(pass_, 'layerPaths', None)
    paths = tuple(layered(nodetypes.Viewpoint) if layered is not None
                  else pass_.paths.get(nodetypes.Viewpoint, ()))
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


def authored_centre(sg: Any) -> Any:
    """The bound viewpoint's centerOfRotation in the world, where the document sets it; else None"""
    view = getattr(sg, 'boundViewpoint', None) if sg is not None else None
    if not view or 'centerOfRotation' not in getattr(view, '__dict__', {}):
        return None
    centre = view.localCentre() if hasattr(view, 'localCentre') else view.centerOfRotation
    local = np.append(np.asarray(centre, dtype='d')[:3], 1.0)
    for path in getattr(sg, 'viewpointPaths', ()):
        if path[-1] is view:
            matrix = path.transformMatrix()
            if matrix is not None:
                local = local @ np.asarray(matrix, dtype='d')
            break
    return local


def speed_scale(context: Any) -> float:
    """What the bound viewpoint multiplies navigation speeds by, with the viewer where it is"""
    sg = context.getSceneGraph()
    view = getattr(sg, 'boundViewpoint', None) if sg is not None else None
    platform = getattr(context, 'platform', None)
    if not view or platform is None or not hasattr(view, 'speedScale'):
        return 1.0
    return float(view.speedScale(platform.position))


#: Where each viewpoint placed the platform when last bound, for retainUserOffsets.
_authored: 'weakref.WeakKeyDictionary[Any, tuple[np.ndarray, Any]]' = weakref.WeakKeyDictionary()
#: The user's offset from each viewpoint that retains it, as it was left.
_offsets: 'weakref.WeakKeyDictionary[Any, tuple[np.ndarray, Any]]' = weakref.WeakKeyDictionary()

#: Each context's transition in progress.
_moving: 'weakref.WeakKeyDictionary[Any, ViewpointTransition]' = weakref.WeakKeyDictionary()


def bind_scene_viewpoint(context: Any) -> None:
    """Move ``context``'s platform to the scene's bound Viewpoint.

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
        _bind_default(context, sg)
        return
    view = view_path[-1]
    previous = getattr(sg, 'boundViewpoint', None)
    if previous is view:
        return
    sg.boundViewpoint = view
    platform = getattr(context, 'platform', None) or context.getViewPlatform()
    info = binding.bound(sg, nodetypes.NavigationInfo)
    kind, seconds = navigationinfo.transition_of(info)
    if platform is None or not previous or previous is _defaults.get(sg):
        view.moveTo(view_path, context)
        _remember(view, platform)
        return
    retained = getattr(previous, 'retainUserOffsets', False) and previous in _authored
    if kind == 'TELEPORT' and not retained:
        view.moveTo(view_path, context)
        _remember(view, platform)
        _restore_offset(view, platform)
        return
    position, orientation = np.array(platform.position, 'd'), platform.quaternion
    if retained:
        # Where the user had moved to from the viewpoint being left.
        was, turned = _authored[previous]
        _offsets[previous] = (position[:3] - was[:3], turned.inverse() * orientation)
    view.moveTo(view_path, context)
    _remember(view, platform)
    _restore_offset(view, platform)
    if kind == 'TELEPORT':
        return
    move = ViewpointTransition(position, orientation, platform.position,
                               platform.quaternion, systemtime.systemTime(), seconds, kind)
    _moving[context] = move
    platform.setPosition(position[:3])
    platform.setOrientation(orientation)


#: The default Viewpoint each document without one is seen through.
_defaults: 'weakref.WeakKeyDictionary[Any, Any]' = weakref.WeakKeyDictionary()


def default_viewpoint(sg: Any) -> Any:
    """The default Viewpoint `sg` is seen through, where it binds none of its own; else None"""
    return _defaults.get(sg)


def _bind_default(context: Any, sg: Any) -> None:
    """See a document that binds no viewpoint through X3D's default one

    X3D and VRML97 give such a world a Viewpoint with every field at its
    default: from (0, 0, 10) looking down -z, ``fieldOfView`` pi/4. The
    context's starting position is that one unless the application set
    another, so only the projection is applied. A scene built in code keeps
    the context's own camera.
    """
    from vrml.x3d.scene import X3DScene  # noqa: PLC0415 beside its one use
    document = isinstance(sg, X3DScene)
    if not document or sg in _defaults:
        return
    from OpenGLContext.scenegraph.viewpoint import Viewpoint  # noqa: PLC0415 the registry's class
    platform = getattr(context, 'platform', None) or context.getViewPlatform()
    if platform is None:
        return
    default = _defaults[sg] = Viewpoint()
    default.project(platform)
    sg.boundViewpoint = default


def _remember(view: Any, platform: Any) -> None:
    """Keep where `view` put the platform, for a viewpoint that retains user offsets"""
    if platform is not None and getattr(view, 'retainUserOffsets', False):
        _authored[view] = (np.array(platform.position, 'd'), platform.quaternion)


def _restore_offset(view: Any, platform: Any) -> None:
    """Put the platform where the user had moved to from `view`, where it retains that"""
    offset = _offsets.pop(view, None) if getattr(view, 'retainUserOffsets', False) else None
    if offset is not None:
        platform.setPosition(np.array(platform.position, 'd')[:3] + offset[0])
        platform.setOrientation(platform.quaternion * offset[1])


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
