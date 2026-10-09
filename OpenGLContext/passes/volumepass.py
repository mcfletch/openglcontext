"""The render pass's side of X3D volume rendering

A volume (:mod:`OpenGLContext.scenegraph.volumedata`) is drawn with the
blended geometry by marching rays through its voxels in its own program
(``volume.vert``, ``volume.frag``). The pass provides what that needs:

- :meth:`VolumePassMixin.opaqueDepth`: the opaque scene's depth as a texture
  the view's size, copied from the depth buffer the first time a draw of the
  transparent phase asks for it, so a ray stops at the first opaque surface;
- :meth:`VolumePassMixin.volumePrograms`: the programs, one for each
  :attr:`~OpenGLContext.scenegraph.volumestyles.Plan.signature`, compiled
  the first time a plan asks and kept, and the box every volume is drawn as.

:func:`draw` draws one volume with the pass's phase state put back after.
"""
from __future__ import annotations

import ctypes
import logging
from collections.abc import Iterable, Sequence
from typing import Any, Optional, cast

import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader

from OpenGLContext.passes.disposal import PassResources, let_go
from OpenGLContext.scenegraph.vertexsemantics import LOC_POSITION

__all__ = ['MAX_STEPS', 'box_corners', 'box_size', 'OpaqueDepth', 'OpaqueDepths', 'VolumePassMixin', 'VolumePrograms',
           'draw']

log = logging.getLogger(__name__)

#: The lights a volume program has slots for.
MAX_LIGHTS = 8
#: The most samples one ray takes.
MAX_STEPS = 2048
#: Voxels between samples along a ray.
STEP = 0.5
#: The size a zero dimension is drawn at, as a share of the largest: a volume
#: with one zero dimension is drawn as a plane (19775-1, 41.3.2).
FLAT = 1e-4
#: The texture units: the voxels, the opaque depth, then the plan's textures.
VOLUME_UNIT = 0
DEPTH_UNIT = 1
FIRST_STYLE_UNIT = 2

#: The unit cube's twelve triangles, wound counter-clockwise seen from outside.
_CUBE = np.array([
    # -x, +x
    (-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, -1, -1), (-1, 1, 1), (-1, 1, -1),
    (1, -1, -1), (1, 1, 1), (1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1),
    # -y, +y
    (-1, -1, -1), (1, -1, 1), (-1, -1, 1), (-1, -1, -1), (1, -1, -1), (1, -1, 1),
    (-1, 1, -1), (-1, 1, 1), (1, 1, 1), (-1, 1, -1), (1, 1, 1), (1, 1, -1),
    # -z, +z
    (-1, -1, -1), (-1, 1, -1), (1, 1, -1), (-1, -1, -1), (1, 1, -1), (1, -1, -1),
    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, -1, 1), (1, 1, 1), (-1, 1, 1),
], np.float32) * 0.5


def box_size(dimensions: Sequence[float]) -> Optional[np.ndarray]:
    """The size a volume's box is drawn at: a zero dimension made :data:`FLAT`
    of the largest; None where every dimension is zero"""
    size = np.abs(np.asarray([float(value) for value in dimensions], np.float64))
    largest = float(size.max()) if size.size else 0.0
    if not largest > 0.0 or not np.isfinite(largest):
        return None
    found: np.ndarray = np.where(size > 0.0, size, largest * FLAT)
    return found


def box_corners(dimensions: Sequence[float]) -> np.ndarray:
    """The box's triangles' corners, ``(36, 3)``, ``dimensions`` across"""
    size = box_size(dimensions)
    if size is None:
        return np.zeros((0, 3), np.float32)
    corners: np.ndarray = (_CUBE * size).astype(np.float32)
    return corners


class OpaqueDepth:
    """A depth texture one view's size, holding a copy of the depth buffer"""

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = max(1, int(width)), max(1, int(height))
        self.texture = int(GL.glGenTextures(1))
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_DEPTH_COMPONENT24, self.width, self.height,
                        0, GL.GL_DEPTH_COMPONENT, GL.GL_UNSIGNED_INT, None)
        for parameter, value in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST),
                                 (GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST),
                                 (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE),
                                 (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE),
                                 (GL.GL_TEXTURE_COMPARE_MODE, GL.GL_NONE)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, parameter, value)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def capture(self, x: int, y: int) -> None:
        """Copy the read framebuffer's depth, the texture's size from ``(x, y)``"""
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        try:
            GL.glCopyTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, int(x), int(y),
                                   self.width, self.height)
        finally:
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def release(self) -> None:
        if self.texture:
            texture, self.texture = self.texture, 0
            GL.glDeleteTextures(1, np.array([texture], np.uint32))


class OpaqueDepths:
    """A pass's depth copies, one for each size of view it draws volumes in"""

    def __init__(self) -> None:
        self.copies: dict[tuple[int, int], OpaqueDepth] = {}

    def for_view(self, width: int, height: int,
                 sizes: Iterable[tuple[int, int]] = ()) -> OpaqueDepth:
        """The copy for a view ``width`` by ``height``; copies of sizes no view
        in ``sizes`` has are released"""
        key = (max(1, int(width)), max(1, int(height)))
        keep = {(max(1, int(w)), max(1, int(h))) for w, h in sizes} | {key}
        for stale in [size for size in self.copies if size not in keep]:
            self.copies.pop(stale).release()
        found = self.copies.get(key)
        if found is None:
            found = self.copies[key] = OpaqueDepth(*key)
        return found

    def release(self) -> None:
        copies, self.copies = self.copies, {}
        for copy in copies.values():
            copy.release()


#: A linked program and its uniforms' locations.
Program = tuple[int, dict[str, int]]

#: The uniforms every volume program has.
_COMMON = ('uModelView', 'uProjection', 'uInverseModelView', 'uInverseProjection',
           'uDimensions', 'uVoxels', 'uViewport', 'uHasSceneDepth', 'uStep', 'uMaxSteps',
           'hdrOutput', 'objectId', 'uPickPass', 'fogMode', 'fogDensity', 'fogColor', 'numLights',
           'lightsOff')
_LIGHT = ('lightType', 'lightColor', 'lightPosition', 'lightDirection', 'lightAttenuation',
          'lightAttenuationFloor', 'lightRange', 'lightRadius', 'lightBeamWidth',
          'lightCutOffAngle', 'lightIntensity', 'lightAmbientIntensity')


def _source(plan: Any) -> tuple[str, str]:
    """The vertex and fragment GLSL for a plan"""
    from OpenGLContext.passes.shadersource import preprocess_shader  # noqa: PLC0415 kept with its use
    modes = {'composite': 0, 'projection': 1, 'isosurface': 2}
    defines = [
        '#define MAX_LIGHTS %d' % (MAX_LIGHTS,),
        '#define VOLUME_MODE %d' % (modes[plan.mode],),
        '#define VOLUME_GRADIENT %d' % (int(plan.gradient and plan.mode != 'projection'),),
        '#define VOLUME_SEGMENTED %d' % (int(plan.segmented),),
        '#define VOLUME_SKIP_CLEAR %d' % (int(plan.clearStaysClear),),
        '#define VOLUME_GRADIENT_TEXTURE %d' % (
            int(any(slot.name == 'gradients' for slot in plan.textures)),),
    ]
    fragment = preprocess_shader('volume.frag', defines)
    marker = '// @VOLUME_STYLES@'
    assert marker in fragment
    return preprocess_shader('volume.vert'), fragment.replace(marker, plan.source())


class VolumePrograms:
    """The volume programs of one context, by plan signature, and the box they draw"""

    def __init__(self) -> None:
        self.programs: dict[tuple[Any, ...], Optional[Program]] = {}
        self.vao = 0
        self.buffer = 0

    def program(self, plan: Any) -> Optional[Program]:
        """The program for ``plan``, linked the first time; None where it will not link"""
        key = plan.signature
        if key in self.programs:
            return self.programs[key]
        found: Optional[Program] = None
        try:
            vertex, fragment = _source(plan)
            name = int(compileProgram(compileShader(vertex, GL.GL_VERTEX_SHADER),
                                      compileShader(fragment, GL.GL_FRAGMENT_SHADER),
                                      validate=False))
        except Exception as err:
            # A compile failure's arguments hold the whole source; the log is first.
            log.error('A volume program would not link: %s',
                      err.args[0] if getattr(err, 'args', None) else err)
        else:
            names = list(_COMMON) + list(plan.uniforms)
            names += ['%s[%d]' % (light, slot) for light in _LIGHT for slot in range(MAX_LIGHTS)]
            names += ['uVolume', 'uSceneDepth'] + [slot.name for slot in plan.textures]
            locations = {uniform: int(GL.glGetUniformLocation(name, uniform))
                         for uniform in names}
            GL.glUseProgram(name)
            for unit, sampler in enumerate(['uVolume', 'uSceneDepth']
                                           + [slot.name for slot in plan.textures]):
                if locations[sampler] != -1:
                    GL.glUniform1i(locations[sampler], unit)
            found = (name, locations)
        self.programs[key] = found
        return found

    def box(self) -> int:
        """The vertex array of the unit cube, made the first time"""
        if not self.vao:
            self.vao = int(GL.glGenVertexArrays(1))
            GL.glBindVertexArray(self.vao)
            self.buffer = int(GL.glGenBuffers(1))
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.buffer)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, _CUBE.nbytes, _CUBE, GL.GL_STATIC_DRAW)
            GL.glVertexAttribPointer(LOC_POSITION, 3, GL.GL_FLOAT, GL.GL_FALSE, 12,
                                     ctypes.c_void_p(0))
            GL.glEnableVertexAttribArray(LOC_POSITION)
            GL.glBindVertexArray(0)
        return self.vao

    def release(self) -> None:
        """Delete every program and the box, with their context current"""
        from OpenGLContext.scenegraph.instancedgl import delete_gl  # noqa: PLC0415 kept with its use
        programs, self.programs = self.programs, {}
        delete_gl(vaos=[self.vao] if self.vao else [],
                  buffers=[self.buffer] if self.buffer else [],
                  programs=[found[0] for found in programs.values() if found is not None])
        self.vao = self.buffer = 0


class VolumePassMixin(PassResources):
    """What a pass gives the volumes it draws: the opaque depth and the programs"""

    #: The view being drawn: x, y, width, height in the window (the pass's).
    viewport: Any

    _opaque_depths: Optional[OpaqueDepths] = None
    #: The depth texture of the transparent phase in progress: None before it
    #: is asked for, 0 where it could not be copied.
    _opaque_depth: Optional[int] = None
    _volume_programs: Optional[VolumePrograms] = None
    #: Whether a failed depth copy has been reported.
    _opaque_depth_failed = False

    def forgetOpaqueDepth(self) -> None:
        """Copy the depth again at the next :meth:`opaqueDepth`: the transparent
        phase of a view is starting"""
        self._opaque_depth = None

    def opaqueDepth(self) -> int:
        """The opaque scene's depth for the view being drawn, as a texture; 0 without

        Copied from the read framebuffer the first time it is asked for in
        each transparent phase. The transparent phase writes no depth, so the
        copy holds the opaque geometry alone.
        """
        if self._opaque_depth is not None:
            return self._opaque_depth
        x, y, width, height = (int(value) for value in self.viewport)
        if self._opaque_depths is None:
            self._opaque_depths = OpaqueDepths()
        sizes = [(frame.rect[2], frame.rect[3]) for frame in getattr(self, 'viewFrames', ())]
        copy = self._opaque_depths.for_view(width, height, sizes)
        try:
            copy.capture(x, y)
        except GL.GLError as err:
            if not self._opaque_depth_failed:
                self._opaque_depth_failed = True
                log.warning('The depth buffer could not be copied (%s); volumes are drawn'
                            ' over the opaque geometry inside them', err)
            self._opaque_depth = 0
        else:
            self._opaque_depth = copy.texture
        return self._opaque_depth

    def volumePrograms(self) -> VolumePrograms:
        """The volume programs of this pass's context"""
        if self._volume_programs is None:
            self._volume_programs = VolumePrograms()
        return self._volume_programs

    def disposeResources(self) -> None:
        """Release the depth copies and the volume programs"""
        let_go(self, '_opaque_depths')
        let_go(self, '_volume_programs')
        self._opaque_depth = None
        super().disposeResources()


# -- drawing ---------------------------------------------------------------------

class _Lamps:
    """Uploads :func:`~OpenGLContext.passes.shaderpass.configure_light_from_node`'s
    lights to a volume program's light uniforms"""

    def __init__(self, locations: dict[str, int]) -> None:
        self.locations = locations

    def set_light(self, index: int, light_type: str = 'directional',
                  color: Sequence[float] = (1.0, 1.0, 1.0),
                  position: Sequence[float] = (0.0, 0.0, 1.0, 0.0),
                  direction: Sequence[float] = (0.0, 0.0, -1.0),
                  attenuation: Sequence[float] = (1.0, 0.0, 0.0), intensity: float = 1.0,
                  beam_width: float = 1.57, cutoff_angle: float = 0.785,
                  light_range: float = 0.0, light_radius: float = 0.0,
                  attenuation_floor: float = 1.0, ambient_intensity: float = 0.0,
                  program: Optional[int] = None) -> None:
        if index >= MAX_LIGHTS:
            return
        types = {'off': 0, 'directional': 1, 'point': 2, 'spot': 3}
        at = self.locations
        GL.glUniform1i(at['lightType[%d]' % index], types.get(light_type, 0))
        GL.glUniform3f(at['lightColor[%d]' % index], *color)
        GL.glUniform4f(at['lightPosition[%d]' % index], *position)
        GL.glUniform3f(at['lightDirection[%d]' % index], *direction)
        GL.glUniform3f(at['lightAttenuation[%d]' % index], *attenuation)
        for name, value in (('lightAttenuationFloor', attenuation_floor),
                            ('lightRange', light_range), ('lightRadius', light_radius),
                            ('lightBeamWidth', beam_width),
                            ('lightCutOffAngle', cutoff_angle),
                            ('lightIntensity', intensity),
                            ('lightAmbientIntensity', ambient_intensity)):
            GL.glUniform1f(at['%s[%d]' % (name, index)], float(value))


def frame_lights(mode: Any) -> tuple[list[tuple[Any, Any]], bool]:
    """The lights the frame binds, ``(node, eye-space matrix)`` in slot order,
    and whether the headlight follows them

    The shader passes' own list where they made one; otherwise the scene's
    lights under the view's modelview.
    """
    lit = getattr(mode, 'shaderLights', None)
    if lit is not None:
        return list(lit), bool(getattr(mode, 'shaderHeadlight', False))
    lamps = getattr(mode, 'sceneLamps', None)
    if lamps is None:
        return [], False
    found = [(node, matrix) for node, _path, matrix in lamps(mode.getModelView(), MAX_LIGHTS)]
    headlight = getattr(mode, 'hasHeadlight', None)
    return found, bool(headlight(len(found))) if headlight is not None else False


def _upload(location: int, kind: str, length: int, value: Any) -> None:
    if location == -1:
        return
    count = max(1, length)
    if kind == 'float':
        GL.glUniform1fv(location, count, np.asarray(value, np.float32).reshape(-1))
    elif kind == 'int':
        GL.glUniform1iv(location, count, np.asarray(value, np.int32).reshape(-1))
    elif kind == 'uint':
        GL.glUniform1uiv(location, count, np.asarray(value, np.uint32).reshape(-1))
    elif kind == 'vec3':
        GL.glUniform3fv(location, count, np.asarray(value, np.float32).reshape(-1))
    elif kind == 'vec4':
        GL.glUniform4fv(location, count, np.asarray(value, np.float32).reshape(-1))
    else:  # pragma: no cover - volumestyles declares no other type
        raise ValueError(kind)


def _matrix(location: int, matrix: Any) -> None:
    GL.glUniformMatrix4fv(location, 1, GL.GL_FALSE, np.ascontiguousarray(matrix, np.float32))


def _fog(mode: Any) -> tuple[int, float, Sequence[float]]:
    """The bound fog's ``(mode, density, colour)`` for the frame"""
    held: Optional[tuple[int, float, Sequence[float]]] = getattr(mode, '_globalFog', None)
    if held is not None:
        return held
    current = getattr(mode, 'currentFog', None)
    path = current() if current is not None else None
    if path is None:
        return 0, 0.0, (0.0, 0.0, 0.0)
    found: tuple[int, float, Sequence[float]] = path[-1].fogParameters(path.transformMatrix())
    return found


def _draw_picked(at: dict[str, int]) -> None:
    """The colour draw with the object id masked, then the id and depth draw"""
    from OpenGLContext.passes._flat import (  # noqa: PLC0415 _flat imports this module
        OBJECT_ID_ATTACHMENT, disable_object_id_blend)
    on, off = (GL.GL_TRUE,) * 4, (GL.GL_FALSE,) * 4
    # glEnable(GL_BLEND) above reached every draw buffer; an id is written, not blended.
    disable_object_id_blend()
    GL.glColorMaski(OBJECT_ID_ATTACHMENT, *off)
    try:
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(_CUBE))
        GL.glColorMaski(OBJECT_ID_ATTACHMENT, *on)
        GL.glColorMaski(0, *off)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthFunc(GL.GL_LEQUAL)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glUniform1i(at['uPickPass'], 1)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(_CUBE))
    finally:
        GL.glUniform1i(at['uPickPass'], 0)
        GL.glColorMaski(0, *on)
        GL.glColorMaski(OBJECT_ID_ATTACHMENT, *on)
        GL.glDepthMask(GL.GL_FALSE)


def draw(mode: Any, plan: Any, voxels: Any, dimensions: Sequence[float],
         textures: Sequence[Any], modelview: Any, pickable: bool = True) -> bool:
    """Draw a volume: ``voxels`` (its data's GL texture) marched by ``plan``

    ``textures`` are the GL textures of the plan's texture slots, in order;
    ``dimensions`` the box's size. In a frame that picks, a ``pickable``
    volume is drawn a second time into the pick's object id and depth, at
    the first sample where it is half opaque. Returns whether it drew.
    Restores the pass's program, blending, depth test and face culling.
    """
    from OpenGLContext.passes.instancing import set_cull_state  # noqa: PLC0415 GL module
    from OpenGLContext.passes.shaderpass import configure_light_from_node  # noqa: PLC0415 GL module
    programs = mode.volumePrograms()
    found = programs.program(plan)
    if found is None:
        return False
    program, at = found
    depth = mode.opaqueDepth()
    previous = mode.current_program() if hasattr(mode, 'current_program') else 0
    size = box_size(dimensions)
    if size is None:
        return False
    modelview = np.asarray(modelview, np.float64)
    projection = np.asarray(mode.projection, np.float64)
    try:
        inverse = np.linalg.inv(modelview)
        unprojection = np.linalg.inv(projection)
    except np.linalg.LinAlgError:
        return False
    GL.glUseProgram(program)
    try:
        _matrix(at['uModelView'], modelview)
        _matrix(at['uProjection'], projection)
        _matrix(at['uInverseModelView'], inverse)
        _matrix(at['uInverseProjection'], unprojection)
        GL.glUniform3f(at['uDimensions'], *size)
        GL.glUniform3f(at['uVoxels'], *(float(value) for value in voxels.size))
        GL.glUniform4f(at['uViewport'], *(float(value) for value in mode.viewport))
        GL.glUniform1i(at['uHasSceneDepth'], int(bool(depth)))
        GL.glUniform1f(at['uStep'], STEP)
        GL.glUniform1i(at['uMaxSteps'], MAX_STEPS)
        GL.glUniform1i(at['hdrOutput'], int(bool(getattr(mode, '_bloom_active', False))))
        shader = getattr(mode, 'shader_program', None)
        GL.glUniform1ui(at['objectId'], int(getattr(shader, '_current_object_id', 0) or 0))
        fog_mode, density, colour = _fog(mode)
        GL.glUniform1i(at['fogMode'], int(fog_mode))
        GL.glUniform1f(at['fogDensity'], float(density))
        GL.glUniform3f(at['fogColor'], *(float(value) for value in tuple(colour)[:3]))
        if plan.lights:
            lamps = _Lamps(at)
            lights, headlight = frame_lights(mode)
            for slot, (light, matrix) in enumerate(lights[:MAX_LIGHTS]):
                configure_light_from_node(cast(Any, lamps), slot, light, matrix)
            count = min(len(lights), MAX_LIGHTS)
            if headlight and count < MAX_LIGHTS:
                lamps.set_light(count, 'directional', direction=(0.0, 0.0, -1.0))
                count += 1
            GL.glUniform1i(at['numLights'], count)
            GL.glUniform1i(at['lightsOff'], int(getattr(shader, '_lights_off', 0) or 0))
        for name, value in plan.values().items():
            kind, length = plan.uniforms[name]
            _upload(at.get(name, -1), kind, length, value)
        GL.glActiveTexture(GL.GL_TEXTURE0 + VOLUME_UNIT)
        GL.glBindTexture(GL.GL_TEXTURE_3D, voxels.texture)
        GL.glActiveTexture(GL.GL_TEXTURE0 + DEPTH_UNIT)
        GL.glBindTexture(GL.GL_TEXTURE_2D, depth)
        for unit, texture in enumerate(textures, FIRST_STYLE_UNIT):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(GL.GL_TEXTURE_3D, texture.texture)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        # The back faces, depth test off: the march finds the box and the
        # opaque surfaces itself, and the camera may be inside the box.
        set_cull_state(mode, True, GL.GL_CW)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glBindVertexArray(programs.box())
        picking = bool(getattr(shader, '_pick_active', False)) and pickable
        GL.glUniform1i(at['uPickPass'], 0)
        if picking:
            _draw_picked(at)
        else:
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(_CUBE))
    finally:
        GL.glBindVertexArray(0)
        GL.glEnable(GL.GL_DEPTH_TEST)
        set_cull_state(mode, False, GL.GL_CCW)
        if not getattr(mode, 'transparent', False):
            GL.glDisable(GL.GL_BLEND)
            GL.glDepthMask(GL.GL_TRUE)
        for unit in range(FIRST_STYLE_UNIT + len(textures) - 1, -1, -1):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(GL.GL_TEXTURE_2D if unit == DEPTH_UNIT else GL.GL_TEXTURE_3D, 0)
        GL.glUseProgram(previous)
    return True
