"""A body's pose between the world's quaternions and a scene ``Transform``'s axis and angle.

The physics world holds orientations as glTF quaternions ``(x, y, z, w)``; a
VRML97 ``Transform`` holds an axis and an angle in radians. The service converts
with :func:`vrml_rotation_to_quat` and :func:`quat_to_vrml_rotation`, and writes
each frame's poses onto the nodes with :func:`write_poses` (or one at a time with
:func:`write_pose`, as the debug overlay does).
"""
from typing import Any

import numpy as np

__all__ = ['quat_to_vrml_rotation', 'vrml_rotation_to_quat', 'write_pose', 'write_poses']

_ROT_FIELD_CACHE: dict[type, Any] = {}


def vrml_rotation_to_quat(rotation: Any) -> np.ndarray:
    """VRML axis-angle ``(x, y, z, angle)`` as a glTF quaternion ``(x, y, z, w)``."""
    x, y, z, a = (float(v) for v in rotation)
    length = max((x * x + y * y + z * z) ** 0.5, 1e-12)
    s = np.sin(0.5 * a) / length
    return np.array([x * s, y * s, z * s, np.cos(0.5 * a)])


def quat_to_vrml_rotation(quat: Any) -> np.ndarray:
    """A glTF quaternion ``(x, y, z, w)`` as VRML axis-angle ``(x, y, z, angle)``.

    A rotation of nothing has no axis of its own and answers ``(0, 1, 0, 0)``.
    """
    q = np.asarray(quat, dtype='d')
    q = q / max(float(np.linalg.norm(q)), 1e-12)
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


#: Each node class's translation and rotation fields, and whether both store a
#: value as the base field does, so a float32 row can be stored as it is.
_POSE_FIELDS: dict[type, tuple[Any, Any, bool]] = {}


def _pose_fields(kind: type, sample: Any) -> tuple[Any, Any, bool]:
    found = _POSE_FIELDS.get(kind)
    if found is None:
        from vrml import field, protofunctions  # noqa: PLC0415 the scenegraph's field machinery, found once per class

        translation = protofunctions.getField(sample, 'translation')
        rotation = protofunctions.getField(sample, 'rotation')
        plain = all(isinstance(one, field.Field) and type(one).fset is field.Field.fset
                    for one in (translation, rotation))
        found = _POSE_FIELDS[kind] = (translation, rotation, plain)
    return found


def write_poses(transforms: Any, positions: Any, axis_angles: Any) -> None:
    """Write row ``i`` of ``positions`` ``(n, 3)`` and ``axis_angles`` ``(n, 4)`` onto ``transforms[i]``.

    The rows are made float32 once, which is what the fields hold, and each
    node is told of its new translation as :func:`write_pose` tells it. A
    node whose fields store values in a way of their own is set through them.
    """
    from vrml.event import announce  # noqa: PLC0415 the scenegraph's event machinery

    places = np.ascontiguousarray(positions, dtype=np.float32)
    turns = np.ascontiguousarray(axis_angles, dtype=np.float32)
    for node, place, turn in zip(transforms, places, turns):
        translation, rotation, plain = _pose_fields(type(node), node)
        if not plain:
            write_pose(node, place, turn)
            continue
        held = node.__dict__
        held['translation'] = place
        held['rotation'] = turn
        announce(('set', translation), node, value=place)
