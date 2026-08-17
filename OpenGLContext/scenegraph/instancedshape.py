"""One shape put down many times, as a single node.

A baked forest is one tree mesh placed a few dozen times per tile. Modelled as a
few dozen nodes it is a few dozen of everything the render pass does per object
-- a world matrix, a bounding volume, a frustum test, a batch key, a caster
record -- before the instancing batcher collapses them into the one draw the
card was always going to do. :class:`InstancedShape` is those placements as one
object: the pass does its per-object work once, and the draw is the same draw.

``placements`` is an ``(N,4,4)`` array of local matrices in the row-vector
convention the rest of the scenegraph uses, so a point lands at
``p @ placement @ pathMatrix`` -- a placement is exactly the matrix a
:class:`~OpenGLContext.scenegraph.transform.Transform` around the shape would
have contributed. :func:`placement_matrices` builds them from the translation /
rotation / scale triples a scatter or a glTF ``EXT_mesh_gpu_instancing`` node
gives.

The node is a :class:`~OpenGLContext.scenegraph.shape.Shape`, so everything that
reads a shape's geometry, appearance, material or pick flag reads this one
unchanged; what differs is that it draws once per placement and bounds all of
them. A set with no placements draws nothing.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
from vrml import field

from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.shape import Shape

__all__ = ['InstancedShape', 'placement_matrices']


def placement_matrices(translations: Any = None, rotations: Any = None,
                       scales: Any = None) -> np.ndarray:
    """``(N,4,4)`` placements from per-instance translation/rotation/scale.

    Each is optional and any that is given fixes the count; a missing one is the
    identity for every instance. ``rotations`` are ``(x,y,z,w)`` quaternions,
    which is the order glTF's ``EXT_mesh_gpu_instancing`` and the OMI physics
    model both use. Scale applies first, then rotation, then translation --
    the order a Transform composes them in.
    """
    count = 0
    for values in (translations, rotations, scales):
        if values is not None:
            count = max(count, len(values))
    matrices = np.zeros((count, 4, 4), dtype='f')
    matrices[:, 0, 0] = matrices[:, 1, 1] = matrices[:, 2, 2] = 1.0
    matrices[:, 3, 3] = 1.0
    if not count:
        return matrices
    if scales is not None:
        scale = np.asarray(scales, dtype='f').reshape(-1, 3)
        matrices[:, 0, 0] = scale[:, 0]
        matrices[:, 1, 1] = scale[:, 1]
        matrices[:, 2, 2] = scale[:, 2]
    if rotations is not None:
        matrices[:, :3, :3] = np.matmul(
            matrices[:, :3, :3], _rotation_matrices(rotations))
    if translations is not None:
        matrices[:, 3, :3] = np.asarray(translations, dtype='f').reshape(-1, 3)
    return matrices


def _rotation_matrices(quaternions: Any) -> np.ndarray:
    """``(N,3,3)`` row-vector rotation matrices from ``(x,y,z,w)`` quaternions.

    Row-vector means the transpose of the column-vector form found in most
    references: a point multiplies the matrix from the left.
    """
    q = np.asarray(quaternions, dtype='f').reshape(-1, 4)
    norms = np.linalg.norm(q, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    x, y, z, w = (q / norms).T
    out = np.empty((len(q), 3, 3), dtype='f')
    out[:, 0, 0] = 1 - 2 * (y * y + z * z)
    out[:, 1, 0] = 2 * (x * y - z * w)
    out[:, 2, 0] = 2 * (x * z + y * w)
    out[:, 0, 1] = 2 * (x * y + z * w)
    out[:, 1, 1] = 1 - 2 * (x * x + z * z)
    out[:, 2, 1] = 2 * (y * z - x * w)
    out[:, 0, 2] = 2 * (x * z - y * w)
    out[:, 1, 2] = 2 * (y * z + x * w)
    out[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return out


class InstancedShape(Shape):
    """A shape and the set of local matrices to draw it at."""

    placements = field.newField('placements', 'SFArray32', 1, list)

    def instancePlacements(self) -> Optional[np.ndarray]:
        """The placements to draw at, or ``None`` when there are none.

        ``None`` rather than an empty array is what the render pass reads to
        mean "one draw, at the record's own matrix", so a shape with nothing
        placed and a plain shape stay distinguishable.
        """
        placements = self.placements
        if placements is None or not len(placements):
            return None
        return np.asarray(placements, dtype='f').reshape(-1, 4, 4)

    def boundingVolume(self, mode: Any = None) -> Any:
        """A box around every placement of the geometry.

        The whole set is culled or drawn together, so one volume covering all of
        it is what the frustum test and the shadow fit need. Cached against the
        geometry and the placements, so it follows a change in either.
        """
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        volume = self._placedVolume(mode)
        return boundingvolume.cacheVolume(
            self, volume,
            ((self, 'geometry'), (self, 'placements'), (volume, None)),
        )

    def _placedVolume(self, mode: Any) -> Any:
        placements = self.instancePlacements()
        geometry = self.geometry
        if placements is None or not geometry:
            return boundingvolume.BoundingVolume()
        if not hasattr(geometry, 'boundingVolume'):
            return boundingvolume.UnboundedVolume()
        try:
            points = np.asarray(geometry.boundingVolume(mode).getPoints(),
                                dtype='f')
        except boundingvolume.UnboundedObject:
            return boundingvolume.UnboundedVolume()
        if not len(points):
            return boundingvolume.BoundingVolume()
        if points.shape[1] == 3:
            points = np.concatenate(
                [points, np.ones((len(points), 1), 'f')], axis=1)
        placed = np.matmul(points[None, :, :], placements).reshape(-1, 4)
        return boundingvolume.AABoundingBox.fromPoints(placed[:, :3])

    def Render(self, mode: Any = None) -> Any:
        """Draw the geometry once per placement.

        This is the path taken when the pass is not batching -- instancing
        switched off, or a set too small to be worth a batch. Each placement
        gets the modelview it belongs at, on the pass and on the bound program,
        and the pass's own matrix is put back as it was afterwards: that one
        belongs to the record rather than to any one placement.
        """
        placements = self.instancePlacements()
        if placements is None:
            return None
        base = mode.matrix
        shader = getattr(mode, 'shader_program', None)
        set_matrices = getattr(shader, 'set_matrices', None)
        try:
            for placement in placements:
                mode.matrix = np.matmul(placement, base)
                if set_matrices is not None:
                    set_matrices(mode.matrix, mode.projection)
                super(InstancedShape, self).Render(mode=mode)
        finally:
            mode.matrix = base
            if set_matrices is not None:
                set_matrices(base, mode.projection)
        return None
