"""The environmental sensors told each frame what they sense -- no GL

The sensors are pyvrml97's (:mod:`vrml.x3d.sensors`). Once a frame, after the
views are placed, the pass calls :func:`sense` with every sensor's path:

- a `ProximitySensor` or `GeoProximitySensor` is given the viewer's pose,
  the active view's camera;
- a `TransformSensor` is given its `targetObject`'s pose, from the first path
  the scene has to it, and is left where the scene does not draw the target;
- a `VisibilitySensor` is in view where its box is within any view's frustum.

Poses are in the sensor's coordinates (:func:`pose_in`).
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
from numpy.typing import ArrayLike
from vrml.x3d import interpolation
from vrml.x3d import sensors

from OpenGLContext.frustum import boxes_outside

__all__ = ['pose_in', 'sense']


def _quaternion_of(rotation: np.ndarray) -> np.ndarray:
    """The unit quaternion (x, y, z, w) of a column-vector rotation matrix"""
    trace = float(np.trace(rotation))
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        return np.array([(rotation[2, 1] - rotation[1, 2]) / s,
                         (rotation[0, 2] - rotation[2, 0]) / s,
                         (rotation[1, 0] - rotation[0, 1]) / s, 0.25 * s])
    axis = int(np.argmax(np.diag(rotation)))
    i, j, k = axis, (axis + 1) % 3, (axis + 2) % 3
    s = 2.0 * math.sqrt(max(1.0 + rotation[i, i] - rotation[j, j] - rotation[k, k], 1e-12))
    found = np.zeros(4)
    found[i] = 0.25 * s
    found[j] = (rotation[j, i] + rotation[i, j]) / s
    found[k] = (rotation[k, i] + rotation[i, k]) / s
    found[3] = (rotation[k, j] - rotation[j, k]) / s
    return found


def pose_in(placed: ArrayLike, local: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    """(position, rotation) of a thing placed by `placed`, in the coordinates `local` makes

    Both are row-vector local-to-world matrices. The rotation is X3D's
    (axis, angle), with any scale taken out.
    """
    relative = np.asarray(placed, dtype=np.float64) @ np.linalg.inv(np.asarray(local, np.float64))
    rows = relative[:3, :3]
    lengths = np.linalg.norm(rows, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    turned = (rows / lengths).T
    return relative[3, :3].copy(), interpolation.rotation_of(_quaternion_of(turned))


def _matrix(path: Any) -> np.ndarray:
    """The path's local-to-world matrix; a path with no transform is the identity"""
    found = path.transformMatrix()
    return np.identity(4) if found is None else np.asarray(found, dtype=np.float64)


def sense(paths: Iterable[Any], nodePaths: Mapping[Any, Sequence[Any]],
          viewer: ArrayLike, frustums: Sequence[ArrayLike]) -> None:
    """Tell each sensor at the end of `paths` what it senses this frame

    nodePaths -- the paths the scene has to each node, for a
        `TransformSensor`'s target
    viewer -- the active view's camera-to-world matrix, row-vector
    frustums -- the world-space planes of each view, (a, b, c, d) rows
    """
    for path in paths:
        sensor = path[-1]
        if not getattr(sensor, 'enabled', True):
            sensor.sense(False, None)
            continue
        if isinstance(sensor, (sensors.ProximitySensor, sensors.GeoProximitySensor)):
            sensor.observe(*pose_in(viewer, _matrix(path)))
        elif isinstance(sensor, sensors.TransformSensor):
            targets = [found for found in nodePaths.get(sensor.targetObject, ())
                       if not getattr(found, 'broken', False)]
            if targets:
                sensor.observe(*pose_in(_matrix(targets[0]), _matrix(path)))
            else:
                sensor.sense(False, None)
        elif isinstance(sensor, sensors.VisibilitySensor):
            matrix = _matrix(path)[np.newaxis]
            centre = np.asarray(sensor.center, dtype=np.float64)
            half = np.asarray(sensor.size, dtype=np.float64) / 2.0
            sensor.observe(any(not boxes_outside(centre, half, matrix, planes)[0]
                               for planes in frustums))
