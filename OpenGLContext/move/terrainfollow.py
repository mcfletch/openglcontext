"""A document's WALK viewer kept on the ground under gravity -- no GL

X3D (19775-1, 23.4.4 NavigationInfo) asks WALK navigation for "some form of
terrain following and gravity", with down the -Y axis of the bound
viewpoint's coordinate system (23.3.1). Where a document's bound
NavigationInfo has WALK as its first type, and the context declares no
movement modes of its own (a declared walking mode keeps its own body on the
ground, :mod:`OpenGLContext.move.physicswalk`), :func:`follow` keeps the
viewer's eye ``avatarSize[1]`` above the ground once a frame:

- until the viewer first has ground below it after a viewpoint is bound, it
  falls; once there is, it is put on that ground, at its eye height;
- after that, a viewer above its eye height falls at :data:`GRAVITY`, metres
  per second per second, until it is at its eye height, and one below it by
  less than ``avatarSize[2]`` (the step height) steps up.

A viewer with nothing below it falls without end, as X_ITE's does.

The ground is every shape the scene draws, found below the eye and within
``avatarSize[0]`` (the collision radius) of the line through it. A
``Collision`` group whose ``enabled`` is false is not ground; one with a
``proxy`` is ground only through the proxy.
"""
from __future__ import annotations

import logging
import weakref
from collections.abc import Iterable, Iterator
from typing import Any, Optional

import numpy as np
from numpy.typing import ArrayLike

from OpenGLContext.scenegraph import meshdata
from OpenGLContext.scenegraph import pickgeometry

log = logging.getLogger(__name__)

__all__ = ['GRAVITY', 'REACH', 'TerrainFollower', 'beneath', 'clearance', 'follow',
           'grounds_below', 'walking']

#: Acceleration of a falling viewer, metres per second per second (standard gravity).
GRAVITY = 9.80665

#: How far below the eye ground is looked for, metres.
REACH = 1.0e4

#: A rise smaller than this is not stepped up, metres.
SETTLED = 0.01


def walking(info: Any) -> bool:
    """Whether `info`'s first navigation type is WALK"""
    for value in getattr(info, 'type', ()) or ():
        return str(value).strip().strip('"').upper() == 'WALK'
    return False


class TerrainFollower:
    """A viewer's fall: its speed, and whether it has stood on the ground since its bind"""

    def __init__(self, landed: bool = False) -> None:
        #: Speed along the up vector, metres per second; negative falling.
        self.speed = 0.0
        #: Whether the viewer has had ground below it since its viewpoint was bound.
        self.landed = landed

    def step(self, clearance: Optional[float], dt: float, eye_height: float,
             step_height: float, gravity: float = GRAVITY) -> float:
        """How far to move the eye along the up vector this frame

        clearance -- the eye's height above the ground below it, or None
            where there is none
        dt -- seconds since the last step
        """
        if not self.landed and clearance is not None:
            self.landed = True
            self.speed = 0.0
            excess = clearance - eye_height
            if excess > 0 or -excess < step_height:
                return -excess
            return 0.0
        if clearance is None or clearance > eye_height:
            self.speed -= gravity * dt
            moved = self.speed * dt
            if clearance is not None and moved <= eye_height - clearance:
                self.speed = 0.0
                return eye_height - clearance
            return moved
        excess = clearance - eye_height
        self.speed = 0.0
        if SETTLED < -excess < step_height:
            return -excess
        return 0.0


def _probes(eye: np.ndarray, down: np.ndarray, radius: float) -> np.ndarray:
    """The eye and four points `radius` from it, across the down vector"""
    across = np.cross(down, (1.0, 0.0, 0.0))
    if np.linalg.norm(across) < 1e-6:
        across = np.cross(down, (0.0, 0.0, 1.0))
    across /= np.linalg.norm(across)
    other = np.cross(down, across)
    return np.array([eye, eye + across * radius, eye - across * radius,
                     eye + other * radius, eye - other * radius])


def clearance(eye: ArrayLike, down: ArrayLike, radius: float,
              grounds: Iterable[tuple[np.ndarray, np.ndarray]],
              reach: float = REACH) -> Optional[float]:
    """The distance below `eye`, along `down`, to the nearest ground; None for none

    grounds -- each a ``(triangles, matrix)``: ``(n, 3, 3)`` corners in their
        own frame and the row-vector matrix placing them
    radius -- ground within this distance of the line through the eye counts
    """
    eye_ = np.asarray(eye, dtype=np.float64)[:3]
    down_ = np.asarray(down, dtype=np.float64)[:3]
    down_ = down_ / np.linalg.norm(down_)
    starts = _probes(eye_, down_, radius)
    ends = starts + down_ * reach
    nearest: Optional[float] = None
    for triangles, matrix in grounds:
        try:
            inverse = np.linalg.inv(np.asarray(matrix, dtype=np.float64))
        except np.linalg.LinAlgError:
            continue
        local_starts = starts @ inverse[:3, :3] + inverse[3, :3]
        local_ends = ends @ inverse[:3, :3] + inverse[3, :3]
        found = pickgeometry.segment_triangles(local_starts, local_ends, triangles)
        if len(found.t):
            distance = float(found.t.min()) * reach
            if nearest is None or distance < nearest:
                nearest = distance
    return nearest


def _collision_state(path: Any) -> tuple[bool, Optional[Any]]:
    """Whether the shape at the end of `path` is ground, and the innermost
    Collision group with a proxy on the way to it, where there is one"""
    from vrml.x3d.nodes import Collision  # noqa: PLC0415 the X3D declarations, beside their use
    proxied = None
    current = getattr(path, 'parent', None)
    while current is not None and len(current):
        node = current[-1]
        if isinstance(node, Collision):
            if not node.enabled:
                return False, None
            if node.proxy and proxied is None:
                proxied = node
        current = getattr(current, 'parent', None)
    return proxied is None, proxied


def _shapes_under(node: Any, path: Any) -> Iterator[tuple[Any, Any]]:
    """Each shape at or under `node`, reached by `path`"""
    if getattr(node, 'geometry', None):
        yield node, path
        return
    children = getattr(node, 'renderedChildren', None)
    if children is not None:
        for child in children():
            if child:
                yield from _shapes_under(child, path + child)


def _matrix(path: Any) -> np.ndarray:
    found = path.transformMatrix()
    return np.identity(4) if found is None else np.asarray(found, dtype=np.float64)


def _triangles(geometry: Any) -> Optional[np.ndarray]:
    """`geometry`'s triangles in its own frame, ``(n, 3, 3)``; None for none"""
    found = meshdata.geometry_arrays(geometry)
    if found is None:
        return None
    positions = np.asarray(found.attributes['POSITION'], dtype=np.float64)
    corners = (np.arange((len(positions) // 3) * 3) if found.indices is None
               else np.asarray(found.indices, dtype=np.int64).ravel())
    corners = corners[:(len(corners) // 3) * 3]
    if not len(corners):
        return None
    triangles: np.ndarray = positions[corners].reshape(-1, 3, 3)
    return triangles


def beneath(points: np.ndarray, matrices: np.ndarray, eye: ArrayLike,
            down: ArrayLike, radius: float) -> np.ndarray:
    """Which boxes may hold ground below the eye, within `radius` of the line through it

    points -- ``(n, 8, 4)`` corners, each box in its own frame
    matrices -- ``(n, 4, 4)`` row-vector matrices placing them
    """
    eye_ = np.asarray(eye, dtype=np.float64)[:3]
    down_ = np.asarray(down, dtype=np.float64)[:3]
    down_ = down_ / np.linalg.norm(down_)
    if not len(points):
        return np.zeros(0, dtype=bool)
    # Each box's bounding sphere, placed: its centre and radius in the world
    corners = np.asarray(points, dtype=np.float64)[..., :3]
    low, high = corners.min(axis=1), corners.max(axis=1)
    rows = np.asarray(matrices, dtype=np.float64)
    centres = np.matmul(((low + high) * 0.5)[:, np.newaxis, :], rows[:, :3, :3])[:, 0]
    centres += rows[:, 3, :3] - eye_
    spans = np.linalg.norm(np.matmul(((high - low) * 0.5)[:, np.newaxis, :],
                                     np.abs(rows[:, :3, :3]))[:, 0], axis=1)
    along = centres @ down_
    across = np.linalg.norm(centres - along[:, np.newaxis] * down_, axis=1)
    found: np.ndarray = (along + spans >= 0) & (across <= radius + spans)
    return found


def grounds_below(gathered: Any, eye: ArrayLike, down: ArrayLike,
                  radius: float) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """The triangles that may be ground below the eye, each with its matrix

    gathered -- the frame's walk of the scene
        (:class:`~OpenGLContext.passes._flat.GatheredPaths`): the shapes, and
        their bounds tested at once
    """
    drawing = np.asarray(gathered.drawing, dtype=bool)
    bounded = np.asarray(gathered.bounded, dtype=bool)
    near = np.zeros(len(drawing), dtype=bool)
    if bounded.any():
        chosen = np.nonzero(bounded)[0]
        near[chosen] = beneath(np.asarray(gathered.points)[chosen],
                               np.asarray(gathered.matrices)[chosen], eye, down, radius)
    proxies: dict[Any, Any] = {}
    for index in np.nonzero(drawing & (near | ~bounded))[0]:
        path = gathered.paths[index]
        shape = gathered.nodes[index]
        if not getattr(shape, 'geometry', None):
            continue
        ground, proxied = _collision_state(path)
        if proxied is not None:
            proxies.setdefault(proxied, path)
        if not ground:
            continue
        triangles = _triangles(shape.geometry)
        if triangles is not None:
            yield triangles, _matrix(path)
    for group, path in proxies.items():
        base = path
        while base is not None and len(base) and base[-1] is not group:
            base = getattr(base, 'parent', None)
        if base is None or not len(base):
            continue
        for shape, shape_path in _shapes_under(group.proxy, base + group.proxy):
            triangles = _triangles(shape.geometry)
            if triangles is not None:
                yield triangles, _matrix(shape_path)


#: Each context's follower, the viewpoint it was made for, and when it last stepped.
_followers: weakref.WeakKeyDictionary[Any, tuple[Any, TerrainFollower, float]] = (
    weakref.WeakKeyDictionary())


def follow(context: Any, gathered: Any, info: Any, now: float) -> None:
    """Move `context`'s viewer as gravity and the ground below say, once a frame

    gathered -- the frame's walk of the scene
    info -- the bound NavigationInfo, or None for none
    now -- the frame's time, seconds
    """
    if info is None or not walking(info) or context.getNavigation() is not None:
        _followers.pop(context, None)
        return
    sg = context.getSceneGraph()
    platform = getattr(context, 'platform', None)
    if sg is None or platform is None:
        return
    view = getattr(sg, 'boundViewpoint', None)
    held = _followers.get(context)
    if held is None or held[0] is not view:
        follower, last = TerrainFollower(), now
    else:
        _, follower, last = held
    _followers[context] = (view, follower, now)
    from OpenGLContext.move.navigationinfo import avatar_of  # noqa: PLC0415 a sibling, beside its use
    radius, eye_height, step_height = avatar_of(info)
    up = _up(sg)
    eye = np.asarray(platform.position, dtype=np.float64)[:3]
    found = clearance(eye, -up, radius, grounds_below(gathered, eye, -up, radius))
    moved = follower.step(found, max(0.0, now - last), eye_height, step_height)
    if moved:
        platform.setPosition(eye + up * moved)


def _up(sg: Any) -> np.ndarray:
    """The +Y axis of the bound viewpoint's coordinate system, in the world"""
    from vrml.x3d import binding  # noqa: PLC0415 beside its use
    path = binding.current_path(list(getattr(sg, 'viewpointPaths', ())))
    up = np.array([0.0, 1.0, 0.0])
    if path is not None:
        matrix = path.transformMatrix()
        if matrix is not None:
            turned = up @ np.asarray(matrix, dtype=np.float64)[:3, :3]
            length = np.linalg.norm(turned)
            if length > 0:
                up = turned / length
    return up
