"""Matrix, quaternion, bounds and camera-orientation math for the glTF loader.

Small, self-contained numeric helpers with no glTF-document dependency -- they
turn a node's TRS/matrix into an OpenGLContext ``Transform``, convert glTF's
xyzw quaternions to VRML axis-angle, produce a row-vector world matrix matching
what the ``Transform`` applies at render time, grow an axis-aligned bounding box
by a transformed local box, and build a camera look orientation. Kept together so
the scene builder and mesh loader share one implementation of each.
"""
from __future__ import annotations

import math

import numpy as np

from OpenGLContext.scenegraph.basenodes import Transform
from OpenGLContext.scenegraph.transform import MatrixTransform
from vrml.vrml97 import transformmatrix


def _bounds_from_points(points):
    p = np.asarray(points, dtype='d')
    return p.min(axis=0), p.max(axis=0)


def _transform_for(node, force_trs=False):
    """Build a Transform whose matrix equals the node's local TRS/matrix.

    ``force_trs`` builds a plain TRS ``Transform`` even if the node carries a
    ``matrix`` -- used for animation targets (a Player writes TRS fields, which a
    baked ``MatrixTransform`` would ignore). A conforming asset never puts a
    ``matrix`` on an animated node, so the matrix branch is simply skipped.
    """
    if node.matrix and not force_trs:
        # A glTF `matrix` is column-major (p_parent = M_col @ p_local). VRML is
        # row-vector (p_parent = p_local @ M_row), and M_row = M_col.T, which is
        # exactly the flat array reshaped without transposing. Apply it exactly
        # rather than decomposing into TRS -- decomposition silently drops
        # 180-degree rotations (ambiguous axis) and cannot represent mirrors.
        m_row = np.asarray(node.matrix, dtype='d').reshape(4, 4)
        return MatrixTransform(localMatrix=m_row)
    t = Transform()
    if node.translation:
        t.translation = tuple(node.translation)
    if node.scale:
        t.scale = tuple(node.scale)
    if node.rotation:
        t.rotation = _quat_to_xyzr(node.rotation)
    return t


def _quat_to_xyzr(q):
    x, y, z, w = [float(v) for v in q]
    # Normalize first: a slightly non-unit quaternion (common in exported assets)
    # otherwise yields a wrong angle from acos(w) and an unnormalized axis.
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n < 1e-12:
        return (0.0, 1.0, 0.0, 0.0)
    x, y, z, w = x / n, y / n, z / n, w / n
    w = max(-1.0, min(1.0, w))
    angle = 2.0 * math.acos(w)
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-6:
        return (0.0, 1.0, 0.0, 0.0)
    return (x / s, y / s, z / s, float(angle))


def _local_matrix_rv(transform_node):
    """Row-vector local matrix for a Transform (matches transformMatrix usage)."""
    baked = getattr(transform_node, '_forward', None)
    if baked is not None:
        return np.asarray(baked, dtype='d')
    m = np.asarray(transformmatrix.transformMatrix(
        translation=transform_node.translation,
        rotation=transform_node.rotation,
        scale=transform_node.scale,
    ), dtype='d')
    # transformMatrix collapses an identity transform to a scalar
    return m if m.shape == (4, 4) else np.eye(4)


def look_orientation(forward, up=(0, 1, 0)):
    """VRML97 axis-angle orientation (x, y, z, angle) for a camera looking along
    ``forward`` with roughly ``up`` upward.

    Builds the rotation whose local -Z maps to ``forward`` (the VRML/glTF camera
    convention) as a quaternion, then returns it in axis-angle form. Used both to
    drive a view platform directly and to author a ``Viewpoint`` node's
    ``orientation`` (a Viewpoint placed at the scene root reproduces the same pose).
    """
    f = np.asarray(forward, 'd')
    f = f / (np.linalg.norm(f) or 1.0)
    zc = -f                                   # camera +Z points backward
    xc = np.cross(np.asarray(up, 'd'), zc)
    xc = xc / (np.linalg.norm(xc) or 1.0)
    yc = np.cross(zc, xc)
    m = np.column_stack((xc, yc, zc))         # world-space camera axes
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        qw = 0.25 * s
        qx, qy, qz = (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        qw = (m[2, 1] - m[1, 2]) / s
        qx, qy, qz = 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        qw = (m[0, 2] - m[2, 0]) / s
        qx, qy, qz = (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        qw = (m[1, 0] - m[0, 1]) / s
        qx, qy, qz = (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    angle = 2.0 * math.acos(max(-1.0, min(1.0, qw)))
    s = math.sqrt(max(0.0, 1.0 - qw * qw))
    if s < 1e-6:
        return (0.0, 1.0, 0.0, 0.0)
    return (qx / s, qy / s, qz / s, angle)


def _expand_bounds(world_matrix, local_bounds, world_min, world_max):
    lo, hi = local_bounds
    corners = np.array([[x, y, z, 1.0]
                        for x in (lo[0], hi[0])
                        for y in (lo[1], hi[1])
                        for z in (lo[2], hi[2])])
    # row-vector convention (p' = p @ M), matching the Transform nodes
    wc = (corners @ world_matrix)[:, :3]
    world_min[:] = np.minimum(world_min, wc.min(axis=0))
    world_max[:] = np.maximum(world_max, wc.max(axis=0))
