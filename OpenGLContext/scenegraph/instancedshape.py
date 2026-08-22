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

from vrml.vrml97 import nodetypes

from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.shape import Shape

__all__ = ['InstancedShape', 'InstancedModel', 'placement_matrices',
           'model_parts']


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


def model_parts(node: Any) -> list:
    """``(shape, matrix)`` for every shape in ``node``, flattened.

    ``matrix`` carries the shape from its own coordinates to ``node``'s, so the
    transforms between them have been composed away and the hierarchy is gone.
    That is what makes a model placeable as a set: a copy of it is one matrix,
    and each part's matrix within the copy never changes.

    Row-vector convention throughout, so a point lands at
    ``p @ matrix @ copyMatrix``.
    """
    found: list = []
    todo = [(node, np.identity(4, dtype='f'))]
    while todo:
        current, matrix = todo.pop(0)
        if isinstance(current, nodetypes.Transforming):
            # A transform that moves nothing offers no matrix rather than an
            # identity, so the shape of what comes back is checked rather than
            # assumed: composing is only meaningful for a 4x4.
            try:
                local = np.asarray(current.localMatrices().data[0], dtype='f')
            except (AttributeError, IndexError, TypeError, ValueError):
                local = None
            if local is not None and local.shape == (4, 4):
                matrix = np.matmul(local, matrix)
        if getattr(current, 'geometry', None) is not None:
            found.append((current, matrix))
        for child in getattr(current, 'children', None) or ():
            todo.append((child, matrix))
    return found


class InstancedModel(Group):
    """A whole model drawn many times, one node per part rather than per copy.

    A model with parts placed by hand is one subtree per copy, and the render
    pass then does its per-object work -- a world matrix, a bounding volume, a
    frustum test, a sort key, a draw -- once for every part of every copy. The
    scene grows with the number of copies whether or not any of them can be
    seen, and a set parked out of the way costs exactly what a set on screen
    does.

    This is the same model as one :class:`InstancedShape` per *part*, each
    carrying every copy's matrix. The pass sees as many objects as the model has
    parts, however many copies there are, and each part draws in one batch.

    Build it from a loaded model and drive it with :meth:`place`::

        pool = InstancedModel(model=art.load('weapons/rocket.glb'))
        pool.place(matrices)        # (N,4,4), one per copy

    ``place`` with nothing draws nothing, which is what an empty set has to
    look like.
    """

    def __init__(self, model: Any = None, parts: Any = None, **named: Any):
        super(InstancedModel, self).__init__(**named)
        self._parts = list(parts) if parts is not None else (
            model_parts(model) if model is not None else [])
        #: One instanced shape per part, in the order the model built them, and
        #: the part's own matrix alongside so `place` need not walk anything.
        self._locals = np.stack([matrix for _shape, matrix in self._parts]) \
            if self._parts else np.zeros((0, 4, 4), 'f')
        self._shapes = [
            InstancedShape(geometry=shape.geometry,
                           appearance=getattr(shape, 'appearance', None))
            for shape, _matrix in self._parts
        ]
        self.children = list(self._shapes)

    def __len__(self) -> int:
        """How many parts the model was flattened into."""
        return len(self._shapes)

    def place(self, copies: Any) -> None:
        """Draw the model once at each of ``copies``, an ``(N,4,4)`` array.

        Each part is placed at its own matrix within the model, composed with
        the copy's -- one array operation per part, rather than a field written
        on a transform per part per copy.
        """
        if copies is None or not len(copies):
            for shape in self._shapes:
                if len(shape.placements):
                    shape.placements = []
            return
        copies = np.asarray(copies, dtype='f').reshape(-1, 4, 4)
        for index, shape in enumerate(self._shapes):
            shape.placements = np.matmul(self._locals[index], copies)
