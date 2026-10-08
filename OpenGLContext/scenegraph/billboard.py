"""VRML97's and X3D's Billboard: a group turned toward the viewer

About a non-zero ``axisOfRotation`` the children turn until their local +Z
points at the viewer's projection onto the plane perpendicular to the axis;
with ``0 0 0`` local +Z points at the viewer and local +Y lines up with the
viewer's up (X3D 19775-1, Navigation, Billboard).

The render pass turns each Billboard once a frame, from the first view's
camera, before the frame's paths are gathered
(:meth:`OpenGLContext.passes._flat.FlatPass.faceBillboards`, through a
:class:`Facing`): it hands :meth:`Billboard.face` the eye and the up direction
in the Billboard's parent coordinates. A Billboard whose camera, parent
matrix and axis are those of the last frame is not worked out again. The
rotation is held in a field the Billboard's matrices depend on, so the cached
matrices of the paths through it are worked out again only when it turns.
"""
import math
from typing import Any, Optional

import numpy as np
from OpenGL.GL import glRotated
from vrml import cache, field
from vrml.vrml97 import basenodes, transformmatrix

from OpenGLContext.scenegraph import grouping

__all__ = ['Billboard', 'Facing', 'billboard_rotation', 'viewer_in']

#: Where a Billboard keeps the matrices a path through it reads, in vrml's cache.
MATRICES_KEY = 'billboard-local'
#: A rotation that turns nothing.
UNTURNED = (0.0, 0.0, 1.0, 0.0)
#: Lengths below this are taken as zero: the viewer on the axis, or at the centre.
EPSILON = 1e-9


def billboard_rotation(axis: Any, eye: Any, up: Any = (0.0, 1.0, 0.0)) -> tuple[float, ...]:
    """The rotation (x, y, z, angle) that turns a Billboard's children toward `eye`

    `axis` is the ``axisOfRotation``; `eye` and `up` are the viewer's position
    and up direction in the Billboard's coordinates. Where the turn is
    undefined -- the viewer on the axis or at the centre, an axis along Z --
    the children are left unturned.
    """
    axis = np.asarray(axis, float)
    eye = np.asarray(eye, float)
    length = float(np.linalg.norm(axis))
    if length < EPSILON:
        return _facing(eye, np.asarray(up, float))
    axis = axis / length
    toward = eye - (eye @ axis) * axis
    front = np.array((0.0, 0.0, 1.0)) - axis[2] * axis
    if np.linalg.norm(toward) < EPSILON or np.linalg.norm(front) < EPSILON:
        return UNTURNED
    angle = math.atan2(float(axis @ np.cross(front, toward)), float(front @ toward))
    return (float(axis[0]), float(axis[1]), float(axis[2]), angle)


def _facing(eye: np.ndarray, up: np.ndarray) -> tuple[float, ...]:
    """The rotation taking +Z to `eye` and +Y to `up` across it: viewer alignment"""
    distance = float(np.linalg.norm(eye))
    if distance < EPSILON:
        return UNTURNED
    z = eye / distance
    y = up - (up @ z) * z
    if np.linalg.norm(y) < EPSILON:
        # Looking straight along the up direction: any Y across Z will do
        y = np.cross(z, (1.0, 0.0, 0.0))
        if np.linalg.norm(y) < EPSILON:
            y = np.cross(z, (0.0, 1.0, 0.0))
    y = y / np.linalg.norm(y)
    x = np.cross(y, z)
    return _rotation_of(np.column_stack((x, y, z)))


def _rotation_of(matrix: np.ndarray) -> tuple[float, ...]:
    """The axis and angle of a 3x3 rotation matrix (columns the turned axes)"""
    cosine = max(-1.0, min(1.0, (float(np.trace(matrix)) - 1.0) / 2.0))
    angle = math.acos(cosine)
    if angle < EPSILON:
        return UNTURNED
    if math.pi - angle < 1e-6:
        # A half turn: the axis is the column of matrix + I with the largest length
        symmetric = (matrix + np.identity(3)) / 2.0
        column = symmetric[:, int(np.argmax(np.diag(symmetric)))]
        axis = column / np.linalg.norm(column)
    else:
        axis = np.array((matrix[2, 1] - matrix[1, 2], matrix[0, 2] - matrix[2, 0],
                         matrix[1, 0] - matrix[0, 1])) / (2.0 * math.sin(angle))
    return (float(axis[0]), float(axis[1]), float(axis[2]), angle)


def viewer_in(parent: Any, modelview: Any) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """(eye, up) of the camera whose modelview is `modelview`, in the coordinates
    `parent` (a world matrix, row vectors) places; None where they are scaled
    to nothing"""
    to_eye = np.asarray(parent, float) @ np.asarray(modelview, float)
    try:
        from_eye = np.linalg.inv(to_eye)
    except np.linalg.LinAlgError:
        return None
    eye = np.array((0.0, 0.0, 0.0, 1.0)) @ from_eye
    up = np.array((0.0, 1.0, 0.0, 0.0)) @ from_eye
    return eye[:3] / eye[3], up[:3]


def parent_matrix(path: Any) -> Any:
    """The world matrix of the coordinates the Billboard at the end of `path`
    turns in: its parent path's own, kept by the cache, where the path was
    built from it; else the path's own with the Billboard's turn taken out"""
    parent = getattr(path, 'parent', None)
    if parent is not None and len(parent) == len(path) - 1:
        return parent.transformMatrix()
    inverse = path[-1].localMatrices().data[1]
    world = path.transformMatrix()
    return world if inverse is None else inverse @ world


class Facing:
    """Turns a frame's Billboards toward its camera -- no GL

    Each frame :meth:`face` is given the Billboards' paths, outermost first,
    and the camera's modelview. A Billboard is worked out again where the
    camera, its parent's matrix (the cache's array, compared by identity) or
    its axis differs from the last frame's.
    """

    def __init__(self) -> None:
        self._seen: dict[int, tuple[Any, Any, bytes, tuple[float, ...]]] = {}

    def face(self, paths: Any, modelview: Any) -> int:
        """Turn each Billboard at the end of `paths`; how many were worked out"""
        camera = np.asarray(modelview, float).tobytes()
        seen: dict[int, tuple[Any, Any, bytes, tuple[float, ...]]] = {}
        worked = 0
        for path in paths:
            node = path[-1]
            parent = parent_matrix(path)
            axis = tuple(float(value) for value in node.axisOfRotation)
            held = self._seen.get(id(path))
            if (held is None or held[0] is not path or held[1] is not parent
                    or held[2] != camera or held[3] != axis):
                viewer = viewer_in(parent, modelview)
                if viewer is not None:
                    node.face(*viewer)
                worked += 1
            seen[id(path)] = (path, parent, camera, axis)  # noqa: OGC131 the entry holds the path, so its id is not reused while kept
        self._seen = seen
        return worked


class Billboard(grouping.Grouping, basenodes.Billboard):
    """Billboard node: a group turned toward the viewer

    Reference:
        https://www.web3d.org/documents/specifications/19775-1/V4.0/Part01/components/navigation.html#Billboard
    """

    #: The rotation the pass last turned it by; not one of the node's fields.
    facing = field.newField(' facing', 'SFRotation', 0, UNTURNED)

    def face(self, eye: Any, up: Any = (0.0, 1.0, 0.0)) -> bool:
        """Turn toward a viewer at `eye`, `up` its up direction, in the parent's
        coordinates; whether the rotation changed"""
        turned = billboard_rotation(self.axisOfRotation, eye, up)
        if np.allclose(turned, np.asarray(self.facing, float), atol=1e-7):
            return False
        self.facing = turned
        return True

    def transform(self, mode: Any = None, translate: int = 1, scale: int = 1,
                  rotate: int = 1) -> None:
        """Turn the fixed-function matrix as the pass last turned the node"""
        x, y, z, angle = (float(value) for value in self.facing)
        if rotate and angle:
            glRotated(math.degrees(angle), x, y, z)

    def localMatrices(self, translate: bool = True, scale: bool = True,
                      rotate: bool = True) -> Any:
        """The holder of this node's (forward, inverse) matrices, its turn
        toward the viewer; None, None where it is unturned"""
        key = (MATRICES_KEY, bool(rotate))
        holder: Optional[Any] = cache.CACHE.getHolder(self, key=key)
        if holder is not None and holder.data is not None:
            return holder
        if holder is None:
            holder = cache.CACHE.holder(self, None, key=key)
            holder.depend(self, 'facing')
        facing = np.asarray(self.facing, float)
        if rotate and facing[3]:
            holder.data = transformmatrix.localMatrices(rotation=facing)
        else:
            holder.data = (None, None)
        return holder
