"""Matrix, quaternion, bounds and camera-orientation math for the glTF loader.

Small, self-contained numeric helpers with no glTF-document dependency -- they
turn a node's TRS/matrix into an OpenGLContext ``Transform``, convert glTF's
xyzw quaternions to VRML axis-angle, produce a row-vector world matrix matching
what the ``Transform`` applies at render time, place a local bounding box in the
world, say where a model ends for the purpose of framing it, and build a camera
look orientation. Kept together so the scene builder and mesh loader share one
implementation of each.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.scenegraph.transform import MatrixTransform
from vrml.vrml97 import transformmatrix

if TYPE_CHECKING:
    import pygltflib
    # ``Transform`` is registered into basenodes dynamically (plugin entry points),
    # so mypy cannot see it there; take the type from its defining module.
    from OpenGLContext.scenegraph.transform import Transform
else:
    from OpenGLContext.scenegraph.basenodes import Transform


def _bounds_from_points(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    p = np.asarray(points, dtype='d')
    return p.min(axis=0), p.max(axis=0)


def _transform_for(node: "pygltflib.Node", force_trs: bool = False) -> "Transform":
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


def _quat_to_xyzr(q: Sequence[float]) -> Tuple[float, float, float, float]:
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


def _local_matrix_rv(transform_node: "Transform") -> np.ndarray:
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


def look_orientation(forward: Sequence[float],
                     up: Sequence[float] = (0, 1, 0)) -> Tuple[float, float, float, float]:
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


def _world_box(world_matrix: np.ndarray,
               local_bounds: Tuple[np.ndarray, np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """A local axis-aligned box placed in the world, as a world-aligned box."""
    lo, hi = local_bounds
    corners = np.array([[x, y, z, 1.0]
                        for x in (lo[0], hi[0])
                        for y in (lo[1], hi[1])
                        for z in (lo[2], hi[2])])
    # row-vector convention (p' = p @ M), matching the Transform nodes
    wc = (corners @ world_matrix)[:, :3]
    return wc.min(axis=0), wc.max(axis=0)


# -- where a model ends, for the purpose of framing it --------------------

#: A part is only ever called stray when the model is *mostly somewhere else*:
#: the whole extent has to be this many times the extent of the crowd (below)
#: before anything is left out. So a model that merely thins out towards its
#: edges, or a scene that genuinely is two things far apart, is framed whole.
STRAY_RATIO = 4.0

#: The share of a model, by vertex count, that has to sit close together to be
#: the crowd whose size the ratio above is measured against.  Below this share
#: there is no crowd, only a spread, and a spread is the model.
STRAY_CROWD = 0.9

#: Where the model ends, once the ratio says it ends somewhere: at the first
#: empty shell, a part this many times further out than everything kept so far.
STRAY_GAP = 2.0


class ModelBounds(NamedTuple):
    """The box to frame a model by, and what was stranded outside it."""

    minimum: np.ndarray
    maximum: np.ndarray
    #: Parts left out of the box because they sit far outside the model.
    strays: int = 0
    #: How far the farthest of them reaches, in radii of the framed box.
    reach: float = 0.0


def _share_at(cumulative: np.ndarray, share: float) -> int:
    """Where in a run of cumulative weight ``share`` of the total is reached."""
    return min(int(np.searchsorted(cumulative, share * cumulative[-1])),
               len(cumulative) - 1)


def _weighted_median(points: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """The per-axis weighted median of a set of points.

    A middle that a handful of far-flung points cannot drag, which the centre
    of a bounding box very much can -- and the distances every judgement below
    makes are distances from here.
    """
    middle = np.empty(points.shape[1])
    for axis in range(points.shape[1]):
        order = np.argsort(points[:, axis])
        cumulative = np.cumsum(weights[order])
        at = min(int(np.searchsorted(cumulative, cumulative[-1] / 2.0)), len(order) - 1)
        middle[axis] = points[order[at], axis]
    return middle


def framing_bounds(parts: Sequence[Tuple[Any, Any, float]]) -> "Optional[ModelBounds]":
    """The box a camera should frame, given every drawn part of a model.

    ``parts`` is one ``(minimum, maximum, weight)`` per primitive: its
    world-space axis-aligned box, and how much geometry is in it (its vertex
    count). None when there is nothing to frame.

    Normally the answer is the union of them all. But an exported model very
    often carries a part or two stranded far outside itself -- a decal left at
    a hundred times its scale, a duplicate forgotten at the far end of the
    file's coordinate space -- and framing the union then stands the camera so
    far back that the model is a speck. So the union is used only while it
    still describes the model. Two tests, which have to agree before any part
    is left out:

    * the whole extent is more than :data:`STRAY_RATIO` times that of the
      *crowd*, the part of the model lying closest together; and
    * that part sits beyond an empty shell -- more than :data:`STRAY_GAP`
      further out than everything nearer than it.

    Each guards a different mistake. The ratio keeps a model that is merely
    spread out, or a scene that genuinely is two things far apart; the gap
    keeps whatever is still within reach of the crowd, however sparse the
    outskirts get. The strays are still *drawn* -- this decides where to
    stand, not what to render.
    """
    if not parts:
        return None
    lows = np.array([np.asarray(lo, dtype='d') for lo, _, _ in parts])
    highs = np.array([np.asarray(hi, dtype='d') for _, hi, _ in parts])
    # A part with no vertex count still occupies space and gets a say.
    weights = np.array([float(weight) or 1.0 for _, _, weight in parts])
    whole = ModelBounds(lows.min(axis=0), highs.max(axis=0))
    if len(parts) == 1:
        return whole

    middle = _weighted_median((lows + highs) / 2.0, weights)
    # How far each part reaches from that middle: its farthest corner.
    reach = np.linalg.norm(
        np.maximum(np.abs(lows - middle), np.abs(highs - middle)), axis=1)
    order = np.argsort(reach)
    # The crowd -- the part of the model lying closest together -- measured
    # both ways round, because each way alone has a model it mistakes for a
    # stray. By geometry, STRAY_CROWD of the vertices, which a scattering of
    # small stranded parts cannot dilute; and by the median part, so that one
    # densely tessellated detail cannot pass for the whole model. Whichever
    # reaches further is taken as the model's own size.
    crowd = max(reach[order[_share_at(np.cumsum(weights[order]), STRAY_CROWD)]],
                reach[order[len(order) // 2]])
    if reach[order[-1]] <= STRAY_RATIO * crowd:
        return whole

    # Where the model ends: the first part beyond an empty shell. Sorted by
    # reach, "everything kept so far" is just the part before this one -- or
    # the crowd, for the parts inside it -- so the whole walk outward is one
    # comparison against the shifted run.
    ascending = reach[order]
    behind = np.maximum(crowd, np.concatenate([[crowd], ascending[:-1]]))
    beyond = np.flatnonzero(ascending > STRAY_GAP * behind)
    if not len(beyond):
        return whole                    # occupied all the way out after all

    kept, strayed = order[:beyond[0]], order[beyond[0]:]
    minimum, maximum = lows[kept].min(axis=0), highs[kept].max(axis=0)
    radius = float(np.linalg.norm(maximum - minimum) / 2.0) or 1.0
    return ModelBounds(minimum, maximum, len(strayed), float(reach[order[-1]] / radius))
