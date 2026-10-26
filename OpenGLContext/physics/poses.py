"""A body's pose between the world's quaternions and a scene ``Transform``'s axis and angle.

The physics world holds orientations as glTF quaternions ``(x, y, z, w)``; a
VRML97 ``Transform`` holds an axis and an angle in radians. The service converts
with :func:`vrml_rotation_to_quat` and :func:`quat_to_vrml_rotation`, and writes
each frame's poses onto the nodes with :func:`write_pose`, as does the debug overlay.
"""
from typing import Any

import numpy as np
from omi_physics import mathutil

__all__ = ['quat_to_vrml_rotation', 'vrml_rotation_to_quat', 'write_pose']

_ROT_FIELD_CACHE: dict[type, Any] = {}


def vrml_rotation_to_quat(rotation: Any) -> np.ndarray:
    """VRML axis-angle ``(x, y, z, angle)`` as a glTF quaternion ``(x, y, z, w)``."""
    x, y, z, a = rotation
    return mathutil.quat_from_axis_angle((x, y, z), a)


def quat_to_vrml_rotation(quat: Any) -> np.ndarray:
    """A glTF quaternion ``(x, y, z, w)`` as VRML axis-angle ``(x, y, z, angle)``.

    A rotation of nothing has no axis of its own and answers ``(0, 1, 0, 0)``.
    """
    q = mathutil.quat_normalize(np.asarray(quat, dtype='d'))
    w = np.clip(q[3], -1.0, 1.0)
    angle = 2.0 * np.arccos(w)
    s = np.sqrt(max(1.0 - w * w, 0.0))
    if s < 1e-9:
        return np.array([0.0, 1.0, 0.0, 0.0])
    axis = q[:3] / s
    return np.array([axis[0], axis[1], axis[2], angle])


def write_pose(transform: Any, pos_row: Any, aa_row: Any) -> None:
    """Write a pose onto a scene ``Transform``: ``pos_row`` its translation, ``aa_row`` its axis and angle.

    Pass numpy rows, which the fields take on their array path. The rotation
    is set without a change notification: the dispatch on ``translation``
    already invalidates the node's cached matrix, which depends on every
    translation, rotation and scale field.
    """
    transform.translation = pos_row
    kind = type(transform)
    rotation = _ROT_FIELD_CACHE.get(kind)
    if rotation is None:
        from vrml import field, protofunctions  # noqa: PLC0415 the scenegraph's field machinery, found once per class

        declared = protofunctions.getField(transform, 'rotation')
        if not isinstance(declared, field.Field):
            raise TypeError('%s.rotation is an event, which holds no pose' % (kind.__name__,))
        rotation = _ROT_FIELD_CACHE[kind] = declared
    rotation.fset(transform, aa_row, False)
