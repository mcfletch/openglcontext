"""X3D's GaussianSplats: 3D Gaussians drawn as sorted, blended screen-space quads

ISO/IEC 19775-1 4.1, component GaussianSplats; the field semantics and the
colour formula are KHR_gaussian_splatting's, which a glTF primitive with that
extension loads into the same node (:func:`from_arrays`).

A splat set is drawn in the transparent pass with the rest of the blended
geometry: one instanced draw of four vertices per splat. The vertex stage
(``gaussian_splat.vert``) projects each splat's covariance to the screen and
spans its 3-sigma ellipse; the fragment stage applies the Gaussian falloff and
writes premultiplied colour, blended back to front. The arithmetic is
:mod:`OpenGLContext.scenegraph.splatmath`'s.

Costs, for N splats:

- The fields are packed once per change (:class:`~splatmath.SplatSet`) and
  uploaded as two buffer textures: 48 bytes a splat, and 8 to 96 bytes of
  half-float coefficients for degree 0 to 3.
- The order is a 16-bit radix sort of the splats' eye depths, linear in N
  (about 15 ms for a million splats here), and an upload of 4 bytes a splat.
  It is made again only when the view turns more than :data:`SORT_TOLERANCE`
  in the splats' frame or the splats change; moving without turning keeps it.
  Each context keeps :data:`ORDER_SLOTS` orders, so several views, a mirror's
  camera or a light's view each find their own rather than sorting each
  other's away.
- A still frame uploads and sorts nothing.

The node's other fields: ``visible`` false draws nothing; ``castShadow``
draws the splats' cores (where opacity reaches one half) into the shadow
maps; ``pointerEvents`` false leaves the splats out of picking, and true
makes their cores pickable, with the picked point on the core;
``bboxSize``/``bboxCenter`` replace the computed bounds where given.
"""
from __future__ import annotations

import ctypes
import itertools
import logging
import math
from collections.abc import Sequence
from typing import Any, Optional

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_CCW, GL_DEPTH_TEST, GL_FALSE,
    GL_MAX_TEXTURE_BUFFER_SIZE, GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_RGBA16F,
    GL_RGBA32F, GL_SRC_ALPHA, GL_STATIC_DRAW, GL_TEXTURE_BUFFER, GL_TEXTURE0,
    GL_TRIANGLE_STRIP, GL_TRUE, GL_UNSIGNED_INT,
    glActiveTexture, glBindBuffer, glBindTexture, glBindVertexArray, glBlendFunc,
    glBufferData, glColorMaski, glDeleteBuffers, glDeleteProgram, glDeleteTextures,
    glDeleteVertexArrays, glDepthMask, glDrawArraysInstanced, glEnable,
    glEnableVertexAttribArray, glGenBuffers, glGenTextures, glGenVertexArrays,
    glGetIntegerv, glGetUniformLocation, glTexBuffer, glUniform1i, glUniform1ui,
    glUniform2f, glUniform3f, glUniformMatrix4fv, glUseProgram,
    glVertexAttribDivisor, glVertexAttribIPointer,
)
from pydispatch import dispatcher
from vrml.vrml97 import nodetypes
from vrml.x3d import nodes as x3d

from OpenGLContext import contextresources
from OpenGLContext.scenegraph import boundingvolume, splatmath
from OpenGLContext.scenegraph.instancedgl import load_program

log = logging.getLogger(__name__)

__all__ = ['GaussianSplats', 'HARMONIC_FIELDS', 'ORDER_SLOTS', 'SORT_TOLERANCE',
           'from_arrays']

#: The coefficient fields, degree 0 first, as X3D names them.
HARMONIC_FIELDS = tuple(
    'sphericalHarmonicsDegree%dCoef%d' % (degree, coefficient)
    for degree, count in enumerate(splatmath.SH_COEFFICIENTS)
    for coefficient in range(count))

#: The fields a splat set is packed from.
DATA_FIELDS = ('positions', 'orientations', 'scales', 'opacities') + HARMONIC_FIELDS

#: How far the view may turn in the splats' frame before they are sorted
#: again, in radians. Below it the order drawn is the last one sorted.
SORT_TOLERANCE = math.radians(0.25)

#: Orders kept per context, each for whichever view last used it.
ORDER_SLOTS = 4

#: Attribute location of the per-instance splat index in gaussian_splat.vert.
_SPLAT_INDEX = 0

#: Uniforms the program's draws set.
_UNIFORMS = ('uModelView', 'uProjection', 'uViewport', 'uCameraLocal',
             'uGeometry', 'uHarmonics', 'uDegree', 'uHarmonicTexels',
             'uLinearColour', 'uHdrOutput', 'uShadeColour', 'uObjectId')

#: The object-id attachment of the picking framebuffer
#: (OpenGLContext.passes._flat.OBJECT_ID_ATTACHMENT).
_ID_ATTACHMENT = 1


def _first(entry: Any) -> tuple[int]:
    return (int(entry[0]),)


def _delete_buffer(name: int) -> None:
    glDeleteBuffers(1, np.array([name], np.uint32))


def _delete_texture(name: int) -> None:
    glDeleteTextures(1, np.array([name], np.uint32))


def _delete_array(name: int) -> None:
    glDeleteVertexArrays(1, np.array([name], np.uint32))


#: Each node's buffers per context: 'geometry' and 'harmonics' as (name,
#: generation, splat count), and each order slot as (name, DepthOrder,
#: when it was last drawn by :data:`_CLOCK`).
_BUFFERS = contextresources.ContextNames('_splat_buffers', _delete_buffer, _first)
#: Each node's buffer textures per context, by the buffer they read.
_TEXTURES = contextresources.ContextNames('_splat_textures', _delete_texture)
#: Each node's vertex arrays per context, by order slot, as (name,).
_ARRAYS = contextresources.ContextNames('_splat_arrays', _delete_array, _first)
#: The program per context, as (name, uniform locations, texel limit).
_PROGRAMS = contextresources.ContextNames('_splat_programs', glDeleteProgram, _first)


#: Ticks once per ordered draw: which order slot was drawn longest ago.
_CLOCK = itertools.count(1)


class _Programs:
    """What :data:`_PROGRAMS` hangs each context's program on"""


_PROGRAM_OWNER = _Programs()


class GaussianSplats(nodetypes.Rendering, x3d.GaussianSplats):
    """X3D's GaussianSplats, drawn with the transparent geometry

    :attr:`drawn` is the application's switch; :attr:`failed` is set where
    the draw could not be made, after which the node draws nothing and the
    failure has been logged once.
    """

    #: Whether the node draws; the application's switch.
    drawn: bool = True
    #: Whether making or issuing the draw failed; the node then draws nothing.
    failed: bool = False

    def __init__(self, *args: Any, **named: Any) -> None:
        super().__init__(*args, **named)
        self._generation = 0
        self._packed: Optional[splatmath.SplatSet] = None
        self._warned: set[str] = set()
        cls = type(self)
        for name in DATA_FIELDS:
            dispatcher.connect(self._onDataChange, signal=('set', getattr(cls, name)),
                               sender=self)

    def _onDataChange(self, value: Any = None) -> None:
        self._generation += 1
        self._packed = None

    @property
    def generation(self) -> int:
        """A count bumped whenever a field the splats are packed from is set"""
        return self._generation

    @property
    def pickable(self) -> bool:
        """Whether a pick reaches the splats: ``pointerEvents``"""
        return bool(self.pointerEvents)

    def splats(self) -> splatmath.SplatSet:
        """The fields, packed: made on first use and again after a field is set"""
        packed = self._packed
        if packed is None:
            packed = self._packed = splatmath.SplatSet.from_fields(
                self.positions, self.orientations, self.scales, self.opacities,
                [getattr(self, name) for name in HARMONIC_FIELDS])
            self._report(packed)
        return packed

    def _report(self, packed: splatmath.SplatSet) -> None:
        """Warn, once per kind, of fields that left splats out"""
        found = []
        if packed.short:
            found.append('short fields (%s) give %d of %d splats' % (
                ', '.join('%s %d' % item for item in sorted(packed.short.items())),
                packed.count + packed.dropped, len(self.positions)))
        if packed.dropped:
            found.append('%d splats with values that are not finite are left out'
                         % packed.dropped)
        for message in found:
            kind = message.split(' ')[0]
            if kind not in self._warned:
                self._warned.add(kind)
                log.warning('GaussianSplats %s: %s', self.DEF or '', message)

    # ------------------------------------------------------------------
    # What the pass asks of a renderable
    # ------------------------------------------------------------------

    def drawsNothing(self) -> bool:
        """Whether nothing is drawn: not ``visible``, switched off, or no splats"""
        return (not self.visible or not self.drawn or self.failed
                or not self.splats().count)

    def sortKey(self, mode: Any, matrix: Any) -> tuple[Any, ...]:
        """Transparent, sorted with the other blended geometry by its origin"""
        return (True, [], 0.0, None)

    def boundingVolume(self, mode: Any = None) -> Any:
        """``bboxSize``/``bboxCenter`` where given, else every splat's 3-sigma box"""
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        size = np.asarray(self.bboxSize, np.float64)
        volume: Any
        if np.all(size >= 0.0):
            volume = boundingvolume.AABoundingBox(
                size=tuple(float(value) for value in size),
                center=tuple(float(value) for value in self.bboxCenter))
        else:
            extent = self.splats().bounds()
            if extent is None:
                volume = boundingvolume.BoundingVolume()
            else:
                low, high = extent
                volume = boundingvolume.AABoundingBox(
                    size=tuple(float(value) for value in high - low),
                    center=tuple(float(value) for value in (low + high) * 0.5))
        return boundingvolume.cacheVolume(
            self, volume, [(self, name) for name in DATA_FIELDS + ('bboxSize', 'bboxCenter')])

    def Render(self, mode: Any = None) -> int:
        """The shadow pass's draw: the cores, into the depth map; nothing otherwise"""
        if getattr(mode, 'shadow_pass', False) and self.castShadow:
            self._guarded(mode, shadow=True)
        return 1

    def RenderTransparent(self, mode: Any = None) -> int:
        """The splats, back to front, blended over what is drawn"""
        if getattr(mode, 'visible', True) and not getattr(mode, 'shadow_pass', False):
            self._guarded(mode, shadow=False)
        return 1

    # ------------------------------------------------------------------
    # The draw
    # ------------------------------------------------------------------

    def _guarded(self, mode: Any, shadow: bool) -> None:
        """Draw, and switch the node off at its first failure, reported once"""
        if not self.drawn or self.failed:
            return
        try:
            self._draw(mode, shadow)
        except Exception as err:
            self.failed = True
            log.error('GaussianSplats %s not drawn: %s', self.DEF or '', err, exc_info=err)

    def _program(self) -> tuple[int, dict[str, int], int]:
        """This context's program, its uniform locations and its texel limit"""
        held = _PROGRAMS.entries(_PROGRAM_OWNER)
        if held is None:
            raise RuntimeError('no GL context is current')
        found = held.get('program')
        if found is None:
            program = load_program('gaussian_splat.vert', 'gaussian_splat.frag')
            locations = {name: int(glGetUniformLocation(program, name)) for name in _UNIFORMS}
            glUseProgram(program)
            glUniform1i(locations['uGeometry'], 0)
            glUniform1i(locations['uHarmonics'], 1)
            limit = int(glGetIntegerv(GL_MAX_TEXTURE_BUFFER_SIZE))
            found = held['program'] = (program, locations, limit)
        return found

    def _upload(self, packed: splatmath.SplatSet, limit: int) -> tuple[int, int]:
        """Upload the packed splats where this context's copy is older; (count, texels)"""
        buffers = _BUFFERS.entries(self)
        textures = _TEXTURES.entries(self)
        assert buffers is not None and textures is not None
        generation = self._generation
        held = buffers.get('geometry')
        harmonic_texels = packed.harmonic_rows().shape[1] // 4
        count = min(packed.count, limit // 3, limit // max(harmonic_texels, 1))
        if count < packed.count and 'limit' not in self._warned:
            self._warned.add('limit')
            log.warning('GaussianSplats %s: %d splats; this driver holds %d',
                        self.DEF or '', packed.count, count)
        if held is not None and held[1] == generation:
            return held[2], harmonic_texels
        for key, rows, layout in (
                ('geometry', packed.geometry_rows()[:count], GL_RGBA32F),
                ('harmonics', packed.harmonic_rows()[:count].astype(np.float16), GL_RGBA16F)):
            entry = buffers.get(key)
            name = int(glGenBuffers(1)) if entry is None else entry[0]
            glBindBuffer(GL_TEXTURE_BUFFER, name)
            data = np.ascontiguousarray(rows) if len(rows) else np.zeros(4, rows.dtype)
            glBufferData(GL_TEXTURE_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
            buffers[key] = (name, generation, count)
            texture = textures.get(key)
            if texture is None:
                texture = textures[key] = int(glGenTextures(1))
            glBindTexture(GL_TEXTURE_BUFFER, texture)
            glTexBuffer(GL_TEXTURE_BUFFER, layout, name)
        glBindBuffer(GL_TEXTURE_BUFFER, 0)
        glBindTexture(GL_TEXTURE_BUFFER, 0)
        return count, harmonic_texels

    def _ordered(self, packed: splatmath.SplatSet, modelview: Any,
                 count: int) -> int:
        """The vertex array whose order is back to front for `modelview`

        The slot whose order is still good for this view, or else the one used
        longest ago, sorted again.
        """
        buffers = _BUFFERS.entries(self)
        arrays = _ARRAYS.entries(self)
        assert buffers is not None and arrays is not None
        slots = [buffers.get(('order', slot)) for slot in range(ORDER_SLOTS)]
        direction = splatmath.DepthOrder.view_direction(modelview)
        generation = (self._generation, count)
        held = [slot for slot, entry in enumerate(slots)
                if entry is not None and entry[1].holds(direction, generation)]
        if held:
            chosen = held[0]
            name, keeper, _drawn = slots[chosen]
        else:
            chosen = min(range(ORDER_SLOTS),
                         key=lambda slot: -1 if slots[slot] is None else slots[slot][2])
            entry = slots[chosen]
            if entry is None:
                name, keeper = int(glGenBuffers(1)), splatmath.DepthOrder(SORT_TOLERANCE)
            else:
                name, keeper, _drawn = entry
            order, _sorted = keeper.update(packed.centres[:count], modelview, generation)
            glBindBuffer(GL_ARRAY_BUFFER, name)
            data = order if len(order) else np.zeros(1, np.uint32)
            glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
            if chosen not in arrays:
                vao = int(glGenVertexArrays(1))
                glBindVertexArray(vao)
                glEnableVertexAttribArray(_SPLAT_INDEX)
                glVertexAttribIPointer(_SPLAT_INDEX, 1, GL_UNSIGNED_INT, 4, ctypes.c_void_p(0))
                glVertexAttribDivisor(_SPLAT_INDEX, 1)
                glBindVertexArray(0)
                arrays[chosen] = (vao,)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
        buffers[('order', chosen)] = (name, keeper, next(_CLOCK))
        return int(arrays[chosen][0])

    def _draw(self, mode: Any, shadow: bool) -> None:
        packed = self.splats()
        if not packed.count:
            return
        program, uniforms, limit = self._program()
        count, harmonic_texels = self._upload(packed, limit)
        modelview = np.asarray(mode.matrix, np.float64)
        projection = np.asarray(mode.projection, np.float64)
        shader = getattr(mode, 'shader_program', None)
        previous = mode.current_program() if hasattr(mode, 'current_program') else 0
        glUseProgram(program)
        # Which order a shadow map's draw uses does not change what it writes:
        # it keeps the cores and depth-tests them.
        vao = self._ordered(packed, modelview, count)
        if shadow:
            size = float(getattr(mode, 'shadow_resolution', 2048))
            viewport = (size, size)
        else:
            viewport = tuple(float(value) for value in mode.viewport[2:4])
        camera = np.linalg.inv(modelview)[3, :3]
        glUniformMatrix4fv(uniforms['uModelView'], 1, GL_FALSE,
                           np.ascontiguousarray(modelview, np.float32))
        glUniformMatrix4fv(uniforms['uProjection'], 1, GL_FALSE,
                           np.ascontiguousarray(projection, np.float32))
        glUniform2f(uniforms['uViewport'], *viewport)
        glUniform3f(uniforms['uCameraLocal'], *(float(value) for value in camera))
        glUniform1i(uniforms['uDegree'], packed.degree)
        glUniform1i(uniforms['uHarmonicTexels'], harmonic_texels)
        glUniform1i(uniforms['uLinearColour'], int(self.colorSpace == 'LIN_REC709_DISPLAY'))
        glUniform1i(uniforms['uHdrOutput'], int(bool(getattr(shader, 'hdr_output', False))))
        glUniform1ui(uniforms['uObjectId'], int(getattr(shader, '_current_object_id', 0)))
        textures = _TEXTURES.entries(self)
        assert textures is not None
        for unit, key in ((0, 'geometry'), (1, 'harmonics')):
            glActiveTexture(GL_TEXTURE0 + unit)
            glBindTexture(GL_TEXTURE_BUFFER, textures[key])
        glActiveTexture(GL_TEXTURE0)
        from OpenGLContext.passes.instancing import set_cull_state  # noqa: PLC0415 passes import scenegraph
        set_cull_state(mode, False, GL_CCW)
        glBindVertexArray(vao)
        try:
            if shadow:
                glUniform1i(uniforms['uShadeColour'], 0)
                glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, count)
            else:
                self._drawBlended(mode, uniforms, count)
        finally:
            glBindVertexArray(0)
            glActiveTexture(GL_TEXTURE0 + 1)
            glBindTexture(GL_TEXTURE_BUFFER, 0)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_BUFFER, 0)
            glUseProgram(previous)

    def _drawBlended(self, mode: Any, uniforms: dict[str, int], count: int) -> None:
        """The colour draw, and in a picking frame the cores' id draw after it

        The transparent phase's blend factors and depth mask are put back
        afterwards, for the blended shapes drawn after this one.
        """
        shader = getattr(mode, 'shader_program', None)
        picking = bool(getattr(shader, '_pick_active', False)) and self.pickable
        glEnable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)
        glDepthMask(GL_FALSE)
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        if picking:
            from OpenGLContext.passes._flat import disable_object_id_blend  # noqa: PLC0415 passes import scenegraph
            disable_object_id_blend()
            glColorMaski(_ID_ATTACHMENT, GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE)
        try:
            glUniform1i(uniforms['uShadeColour'], 1)
            glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, count)
            if picking:
                glColorMaski(_ID_ATTACHMENT, GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
                glColorMaski(0, GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE)
                glDepthMask(GL_TRUE)
                glUniform1i(uniforms['uShadeColour'], 0)
                glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, count)
        finally:
            if picking:
                glColorMaski(0, GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
                glColorMaski(_ID_ATTACHMENT, GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
            glDepthMask(GL_FALSE)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)


def from_arrays(positions: Any, rotations: Any, scales: Any, opacities: Any,
                harmonics: Sequence[Any], color_space: str = 'SRGB_REC709_DISPLAY',
                **fields: Any) -> GaussianSplats:
    """A GaussianSplats node of per-splat arrays: KHR_gaussian_splatting's attributes

    `harmonics` are the coefficient arrays in order, degree 0 first.
    `color_space` is the node's ``colorSpace`` value; `fields` set others.
    """
    named = dict(positions=np.asarray(positions, np.float32).reshape(-1, 3),
                 orientations=np.asarray(rotations, np.float32).reshape(-1, 4),
                 scales=np.asarray(scales, np.float32).reshape(-1, 3),
                 opacities=np.asarray(opacities, np.float32).ravel(),
                 colorSpace=color_space)
    for name, values in zip(HARMONIC_FIELDS, harmonics):
        named[name] = np.asarray(values, np.float32).reshape(-1, 3)
    named.update(fields)
    return GaussianSplats(**named)
