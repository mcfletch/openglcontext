"""The pass's side of X3D's ClipPlane: each draw given the planes that clip it

Once a frame :meth:`ClipPlanesMixin.refreshClipPlanes` reads the scene's
enabled ClipPlanes (:class:`~OpenGLContext.passes.clipscope.ClipPlanes`).
Before each draw the shader paths call :meth:`~ClipPlanesMixin.applyClipPlanes`,
which hands the program the planes in the drawn object's frame
(``set_clip_planes``, ``_clipplane_inc.glsl``); the compatibility profile
calls :meth:`~ClipPlanesMixin.applyFixedClipPlanes`, which sets them with
``glClipPlane`` under the object's modelview. A scene without ClipPlanes
costs one test a draw.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Optional

import numpy as np
from OpenGL.GL import (
    GL_CLIP_PLANE0, GL_MAX_CLIP_PLANES, glClipPlane, glDisable, glEnable, glGetIntegerv,
)
from vrml.x3d import nodes as x3dnodes

from OpenGLContext.passes import clipscope

__all__ = ['ClipPlanesMixin']

#: The planes of a draw nothing clips.
UNCLIPPED = np.zeros((0, 4), dtype=np.float32)


class ClipPlanesMixin:
    """Gives each draw of a FlatPass the ClipPlanes that clip it"""

    paths: Any

    #: This frame's enabled ClipPlanes.
    clipPlanes: clipscope.ClipPlanes = clipscope.ClipPlanes()
    #: Whether the last draw was given planes, so an unclipped draw after it
    #: takes them away.
    _clipApplied = False
    #: How many fixed-function clip planes are enabled.
    _fixedClipEnabled = 0
    #: The fixed-function planes this context has, asked once.
    _fixedClipLimit: Optional[int] = None

    def refreshClipPlanes(self) -> None:
        """Read the scene's enabled ClipPlanes for this frame"""
        self.clipPlanes = self.clipPlanes.following(self.paths.get(x3dnodes.ClipPlane, ()))

    def _planesFor(self, path: Optional[Sequence[Any]], tmatrix: Any) -> np.ndarray:
        if path is None or not self.clipPlanes or not clipscope.clipped_by_pass(path[-1]):
            return UNCLIPPED
        return self.clipPlanes.object_planes(path, tmatrix)

    def applyClipPlanes(self, shader: Any, path: Optional[Sequence[Any]], tmatrix: Any) -> None:
        """Give `shader` the planes clipping the draw at the end of `path`, placed by `tmatrix`

        A path of None is a draw nothing clips: an instanced group, whose
        members are never clipped (:meth:`ClipPlanes.apart`).
        """
        if not self.clipPlanes and not self._clipApplied:
            return
        setter = getattr(shader, 'set_clip_planes', None)
        if setter is None:
            return
        planes = self._planesFor(path, tmatrix)
        setter(planes)
        self._clipApplied = bool(len(planes))

    def endClipPlanes(self, shader: Any) -> None:
        """Draw what follows unclipped"""
        if self._clipApplied:
            setter = getattr(shader, 'set_clip_planes', None)
            if setter is not None:
                setter(UNCLIPPED)
            self._clipApplied = False

    def clipApart(self, record: Sequence[Any]) -> Optional[Any]:
        """What keeps a record out of an instanced group: its path, where planes clip it"""
        return self.clipPlanes.apart(record[4]) if self.clipPlanes else None

    def applyFixedClipPlanes(self, path: Sequence[Any], tmatrix: Any) -> None:
        """Set the planes clipping `path`'s draw with glClipPlane, under its modelview"""
        if not self.clipPlanes and not self._fixedClipEnabled:
            return
        if self._fixedClipLimit is None:
            self._fixedClipLimit = min(clipscope.MAX_PLANES,
                                       int(glGetIntegerv(GL_MAX_CLIP_PLANES)))
        planes = self._planesFor(path, tmatrix)[:self._fixedClipLimit]
        for index, plane in enumerate(planes):
            glClipPlane(GL_CLIP_PLANE0 + index, np.asarray(plane, dtype=np.float64))
            glEnable(GL_CLIP_PLANE0 + index)
        for index in range(len(planes), self._fixedClipEnabled):
            glDisable(GL_CLIP_PLANE0 + index)
        self._fixedClipEnabled = len(planes)

    def endFixedClipPlanes(self) -> None:
        """Disable the fixed-function planes the draws enabled"""
        for index in range(self._fixedClipEnabled):
            glDisable(GL_CLIP_PLANE0 + index)
        self._fixedClipEnabled = 0
