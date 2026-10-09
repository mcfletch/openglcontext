"""X3D's VolumeRendering data nodes: VolumeData, SegmentedVolumeData, IsoSurfaceVolumeData

Each is drawn with the blended geometry by marching rays through its
``voxels`` (any X3DTexture3DNode, :mod:`OpenGLContext.scenegraph.texture3d`)
across a box ``dimensions`` in size, centred on its origin. Its render styles
decide what each sample shows (:mod:`OpenGLContext.scenegraph.volumestyles`);
the march itself is ``volume.frag``, drawn by
:func:`OpenGLContext.passes.volumepass.draw`. The ten render style nodes
(:mod:`~OpenGLContext.scenegraph.volumestyles`) hold values and draw nothing
themselves.

- Opaque geometry inside or in front of a volume hides what is behind it:
  the pass copies the opaque scene's depth and each ray stops there.
- A volume casts no shadow and receives none.
- A pick reaches the first sample at which the volume is half opaque, along
  the pick's ray (the ray casting 19775-1 41.2.4.3 allows), in the core
  profile; the compatibility profile's colour pick reaches the volume's box.
- ``visible`` false draws nothing. A ``dimensions`` value of zero draws the
  volume as a plane; two or three zeros draw nothing.

Both profiles draw volumes with the same GLSL 3.30 program: a compatibility
context runs it as a core one does.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
from vrml.vrml97 import nodetypes
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import boundingvolume, polygonsort, volumestyles

__all__ = ['IsoSurfaceVolumeData', 'SegmentedVolumeData', 'TABLE_KEY', 'VolumeData',
           'table_texture']

log = logging.getLogger(__name__)

#: The key a texture node's transfer table is kept under in a context's cache.
TABLE_KEY = 'volume-table'
_ORIGIN = np.array([[0.0, 0.0, 0.0, 1.0]], np.float32)


def table_texture(mode: Any, texture: Any) -> Any:
    """A transfer function texture's RGBA table as a GL 3D texture, or None before it has pixels

    A 2D texture is one slice deep. Kept in the context's cache until the
    texture's pixels change.
    """
    held = mode.cache.getData(texture, key=TABLE_KEY)
    if held is not None:
        return held
    table = volumestyles.transfer_table(texture)
    if table is None:
        return None
    from OpenGLContext.texture import VolumeTexture  # noqa: PLC0415 GL only when drawn
    made = VolumeTexture(table if table.ndim == 4 else table[None])
    holder = mode.cache.holder(texture, made, key=TABLE_KEY)
    depend = getattr(texture, 'dependVolume', None)
    if depend is not None:
        depend(holder)
    else:
        holder.depend(texture, 'image')
    return made


class _VolumeData(nodetypes.Rendering, x3d.X3DVolumeDataNode):
    """What the three volume data nodes share: their box, their sorting and their draw

    An application sets :attr:`drawn` false to leave the node undrawn.
    :attr:`failed` is set where the draw could not be made, after which the
    node draws nothing and the failure has been logged once.
    """

    #: Whether the node draws; false leaves it undrawn.
    drawn: bool = True
    #: Whether issuing the draw failed; the node then draws nothing.
    failed: bool = False
    #: A volume is left out of the shadow maps.
    castShadow = False
    # The fields every concrete class declares.
    voxels: Any
    renderStyle: Any
    DEF: str

    def plan(self) -> Optional[volumestyles.Plan]:
        """How the volume is drawn now; None while its voxels have not loaded"""
        return volumestyles.plan(self)

    def drawsNothing(self) -> bool:
        """Whether nothing is drawn: not ``visible``, or switched off"""
        return not self.visible or not self.drawn or self.failed

    def sortKey(self, mode: Any, matrix: Any) -> tuple[Any, ...]:
        """Transparent, sorted with the other blended geometry by its centre's distance"""
        distance = -float(polygonsort.distances(
            _ORIGIN, modelView=matrix, projection=mode.getProjection(),
            viewport=mode.getViewport())[0])
        return (True, [], distance, None)

    def boundingVolume(self, mode: Any = None) -> Any:
        """``bboxSize``/``bboxCenter`` where given, else the box ``dimensions`` across"""
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        size = np.asarray(self.bboxSize, np.float64)
        if np.all(size >= 0.0):
            volume = boundingvolume.AABoundingBox(
                size=tuple(float(value) for value in size),
                center=tuple(float(value) for value in self.bboxCenter))
        else:
            volume = boundingvolume.AABoundingBox(
                size=tuple(abs(float(value)) for value in self.dimensions),
                center=(0.0, 0.0, 0.0))
        return boundingvolume.cacheVolume(
            self, volume, [(self, name) for name in ('dimensions', 'bboxSize', 'bboxCenter')])

    def Render(self, mode: Any = None) -> int:
        """The compatibility profile's colour pick: the box, in the colour the pick set"""
        if (mode is not None and not getattr(mode, 'visible', True)
                and not getattr(mode, 'shader_mode', False)
                and not getattr(mode, 'shadow_pass', False)):
            _pick_box(self.dimensions)
        return 1

    def RenderTransparent(self, mode: Any = None) -> int:
        """The volume, marched and blended over what is drawn"""
        if (getattr(mode, 'visible', True) and not getattr(mode, 'shadow_pass', False)
                and not self.drawsNothing()):
            try:
                self._draw(mode)
            except Exception as err:
                self.failed = True
                log.error('%s %s not drawn: %s', type(self).__name__, self.DEF or '', err,
                          exc_info=err)
        return 1

    def _draw(self, mode: Any) -> None:
        found = self.plan()
        if found is None:
            return
        voxels = self.voxels.cached(mode)
        if voxels is None:
            return
        textures = []
        for slot in found.textures:
            texture = (slot.node.cached(mode) if slot.kind == 'volume'
                       else table_texture(mode, slot.node))
            if texture is None:
                return
            textures.append(texture)
        from OpenGLContext.passes import volumepass  # noqa: PLC0415 GL only when drawn
        pickable = getattr(mode, '_shapePickable', lambda node: True)(self)
        volumepass.draw(mode, found, voxels, tuple(self.dimensions), textures, mode.matrix,
                        pickable)


def _pick_box(dimensions: Any) -> None:
    """The box ``dimensions`` across, through the fixed-function pipeline"""
    from OpenGL import GL  # noqa: PLC0415 only the compatibility pick draws this way
    from OpenGLContext.passes.volumepass import box_corners  # noqa: PLC0415 GL module
    GL.glBegin(GL.GL_TRIANGLES)
    try:
        for corner in box_corners(dimensions):
            GL.glVertex3f(*corner)
    finally:
        GL.glEnd()


class VolumeData(_VolumeData, x3d.VolumeData):
    """X3D's VolumeData: one render style for the whole volume"""


class SegmentedVolumeData(_VolumeData, x3d.SegmentedVolumeData):
    """X3D's SegmentedVolumeData: a render style for each segment identifier"""


class IsoSurfaceVolumeData(_VolumeData, x3d.IsoSurfaceVolumeData):
    """X3D's IsoSurfaceVolumeData: surfaces where the voxels cross given values"""
