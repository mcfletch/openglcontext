"""A group whose children are drawn in a frame the node works out itself

:class:`Framed` is the base of the grouping nodes whose local matrix is not a
translation, rotation and scale read from fields: the geospatial frames
(:mod:`OpenGLContext.scenegraph.geospatial`) and the screen placements of
X3D's Layout component (:mod:`OpenGLContext.scenegraph.layering`). A subclass
gives :meth:`Framed.frameMatrix` and the fields it reads; the node paths ask
for the frame through :meth:`Framed.localMatrices`, which keeps it in
:mod:`vrml.cache` until one of those fields is set.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
from OpenGL.GL import glMultMatrixd
from vrml import cache, protofunctions
from vrml.vrml97 import nodetypes

from OpenGLContext.scenegraph import boundingvolume, grouping

__all__ = ['Framed']


class Framed(grouping.Grouping, nodetypes.Transforming):
    """A group whose frame is worked out by :meth:`frameMatrix`, in double precision

    Matrices are row-vector 4x4, as the engine's are.
    """

    #: The node's own fields its frame is worked out from.
    MATRIX_FIELDS: tuple[str, ...] = ()
    #: Where the frame is kept in :mod:`vrml.cache`.
    FRAME_KEY = 'framed-local-matrices'

    def frameMatrix(self) -> np.ndarray:
        """The row-vector 4x4 frame the children are drawn in"""
        raise NotImplementedError('%s must give its frame' % type(self).__name__)

    def frameDependencies(self) -> list[tuple[Any, str]]:
        """(node, field name) for each field the frame is worked out from"""
        return [(self, name) for name in self.MATRIX_FIELDS]

    def _matrices(self) -> Any:
        """The holder of (forward, inverse), kept until a field it is worked out from is set"""
        holder = cache.CACHE.getHolder(self, key=self.FRAME_KEY)
        if holder is not None and holder.data is not None:
            return holder
        forward = np.asarray(self.frameMatrix(), dtype=np.float64)
        data = (forward, np.linalg.inv(forward))
        if holder is None:
            holder = cache.CACHE.holder(self, data, key=self.FRAME_KEY)
            for source, name in self.frameDependencies():
                holder.depend(source, protofunctions.getField(source, name))
        else:
            holder.data = data
        return holder

    def localMatrices(self, translate: bool = True, scale: bool = True,
                      rotate: bool = True) -> Any:
        """The holder of the forward and inverse frames, as the node paths ask for them

        A request leaving out the translation, the scale or the rotation is
        answered with that part taken out of the whole frame.
        """
        whole = self._matrices()
        if translate and scale and rotate:
            return whole
        key = (self.FRAME_KEY, translate, scale, rotate)
        holder = cache.CACHE.getHolder(self, key=key)
        if holder is not None and holder.data is not None:
            return holder
        forward = whole.data[0].copy()
        if not translate:
            forward[3, :3] = 0.0
        lengths = np.linalg.norm(forward[:3, :3], axis=1)
        if rotate and not scale:
            forward[:3, :3] /= np.where(lengths > 0, lengths, 1.0)[:, None]
        elif scale and not rotate:
            forward[:3, :3] = np.diag(lengths)
        elif not (scale or rotate):
            forward[:3, :3] = np.eye(3)
        data = (forward, np.linalg.inv(forward))
        if holder is None:
            holder = cache.CACHE.holder(self, data, key=key)
            holder.depend_holder(whole)
        else:
            holder.data = data
        return holder

    def localMatrix(self, mode: Any = None) -> np.ndarray:
        """The frame the children are drawn in"""
        found: np.ndarray = self._matrices().data[0]
        return found

    def transform(self, mode: Any = None, translate: int = 1, scale: int = 1,
                  rotate: int = 1) -> None:
        """Multiply the frame into the fixed-function modelview"""
        holder = self.localMatrices(bool(translate), bool(scale), bool(rotate))
        glMultMatrixd(np.ascontiguousarray(holder.data[0], dtype=np.float64))

    def boundingVolume(self, mode: Any = None) -> Any:
        """The children's volumes, carried into the parent's coordinates by the frame"""
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        volumes: list[Any] = []
        dependencies: list[tuple[Any, Optional[str]]] = [(self, 'children')]
        dependencies += self.frameDependencies()
        unbounded = False
        for child in self.children:
            try:
                if hasattr(child, 'boundingVolume'):
                    volume = child.boundingVolume(mode)
                    volumes.append(volume)
                    dependencies.append((volume, None))
            except boundingvolume.UnboundedObject:
                unbounded = True
        try:
            volume = boundingvolume.BoundingBox.union(volumes, self.localMatrix(mode))
        except boundingvolume.UnboundedObject:
            unbounded = True
        if unbounded:
            volume = boundingvolume.UnboundedVolume()
        return boundingvolume.cacheVolume(self, volume, dependencies)
