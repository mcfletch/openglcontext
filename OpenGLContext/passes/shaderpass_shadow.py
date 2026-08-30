"""Shadow-uniform subsystem for :class:`VRML97ShaderProgram`.

Packs the shadow sampler-unit layout, the per-slot spot/CSM/point bind calls, and
the global shadow parameters. Everything here targets ``self._shadow_prog``
(retargetable onto the vertex-colour program) and leans on the uniform-cache
substrate (``_set_uniform*`` / ``_get_location``) on the composing class.

Mixed into ``VRML97ShaderProgram`` as a base, so ``self`` is the whole program
object. The class ``__init__`` owns the mutable shadow state
(``_shadow_program``, ``_shadow_samplers_program``, ``shadow_cube_array``, the
per-driver instance ``MAX_SHADOW_LIGHTS``) that these methods read.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from OpenGL.GL import (
    GL_FALSE, GL_TEXTURE0, GL_TEXTURE_2D_ARRAY, GL_TEXTURE_CUBE_MAP,
    GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_COMPARE_MODE, GL_NONE, GL_NEAREST,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
    glGenSamplers, glSamplerParameteri, glActiveTexture, glBindTexture,
    glBindSampler, glUniformMatrix4fv,
)

from OpenGLContext.passes.shadersource import HARD_MAX_SHADOW_LIGHTS

if TYPE_CHECKING:
    from OpenGLContext.passes.shadowmath import Matrix4


class _ShadowUniformMixin:
    """Shadow sampler layout + per-light shadow uniform binding."""

    if TYPE_CHECKING:
        program: Optional[int]
        vertex_color_program: Optional[int]
        _shadow_program: Optional[int]
        _shadow_samplers_program: set
        shadow_cube_array: bool

        def _set_uniform1i(self, name: str, value: int, program: Optional[int]) -> None: ...

        def _set_uniform1f(self, name: str, value: float, program: Optional[int]) -> None: ...

        def _set_uniform3f(self, name: str, value: Any, program: Optional[int]) -> None: ...

        def _get_location(self, name: str, program: Optional[int]) -> int: ...

    # Packed shadow-sampler texture units. Spot maps and directional
    # cascades share ONE sampler2DArrayShadow (+ one raw view); point shadows a
    # single cube-array sampler when available, else one cube sampler per slot.
    # The material map stays at unit 0, so the lit program tops out at ~6 fragment
    # texture image units instead of the 20 the per-slot layout demanded.
    MAX_SHADOW_LIGHTS: int = HARD_MAX_SHADOW_LIGHTS
    MAX_CASCADES: int = 4
    SHADOW_ARRAY_UNIT: int = 4      # sampler2DArrayShadow (spot + CSM depth)
    SHADOW_ARRAY_RAW_UNIT: int = 5  # sampler2DArray (same texture, PCSS blocker search)
    SHADOW_CUBE_BASE: int = 6       # samplerCubeArrayShadow at 6, OR shadowCube_0.. at 6..
    SHADOW_KIND = {'spot': 0, 'directional': 1, 'point': 2}

    _pcss_sampler: Optional[int] = None

    @property
    def _shadow_prog(self) -> Optional[int]:
        return self._shadow_program if self._shadow_program is not None else self.program

    def shadow_receiver_programs(self) -> List[int]:
        """Programs whose shadow uniforms bindShadowUniforms must set.

        The lit program (or the PBR program) plus the vertex-colour program, which
        now includes the shadow code. unlit/point/line don't sample shadows.
        """
        return [p for p in (self.program, self.vertex_color_program) if p is not None]

    def _pcss_sampler_object(self) -> int:
        """A sampler object with comparison off, for raw-depth PCSS reads."""
        if self._pcss_sampler is None:
            samp = glGenSamplers(1)
            glSamplerParameteri(samp, GL_TEXTURE_COMPARE_MODE, GL_NONE)
            glSamplerParameteri(samp, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glSamplerParameteri(samp, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            self._pcss_sampler = int(samp)
        return self._pcss_sampler

    def init_shadow_samplers(self) -> None:
        """Point every shadow sampler uniform at its reserved texture unit.

        Done once per program so the shadow samplers never alias unit 0 (the
        material texture) and so the program validates even when shadows are
        disabled. The mapping is static, so repeat calls within a frame are
        skipped: the callers invoke it defensively each frame.
        """
        if self._shadow_prog in self._shadow_samplers_program:
            return
        self._shadow_samplers_program.add(self._shadow_prog)
        self._set_uniform1i('shadowArray', self.SHADOW_ARRAY_UNIT, self._shadow_prog)
        self._set_uniform1i('shadowArrayRaw', self.SHADOW_ARRAY_RAW_UNIT, self._shadow_prog)
        if self.shadow_cube_array:
            self._set_uniform1i('shadowCubeArray', self.SHADOW_CUBE_BASE, self._shadow_prog)
        else:
            for slot in range(self.MAX_SHADOW_LIGHTS):
                self._set_uniform1i(f'shadowCube_{slot}', self.SHADOW_CUBE_BASE + slot, self._shadow_prog)

    def set_shadow_count(self, count: int) -> None:
        """Set the number of active shadow-casting lights."""
        self._set_uniform1i('shadowCount', max(0, min(count, self.MAX_SHADOW_LIGHTS)), self._shadow_prog)

    def set_shadow_params(self, resolution: int = 2048,
                          normal_offset: float = 0.0, soft: bool = False,
                          gather: bool = False, light_size: float = 0.01,
                          eye_to_world: Optional['Matrix4'] = None) -> None:
        """Set the shadow parameters every slot shares.

        The depth bias is not among them: it converts against each map's own
        projection, so it is set per slot by the bind_*_slot methods.
        """
        self._set_uniform1f('shadowTexel', 1.0 / float(max(1, resolution)), self._shadow_prog)
        self._set_uniform1f('shadowNormalOffset', float(normal_offset), self._shadow_prog)
        self._set_uniform1i('shadowSoft', 1 if soft else 0, self._shadow_prog)
        self._set_uniform1f('shadowLightSize', float(light_size), self._shadow_prog)
        if eye_to_world is not None:
            self.set_eye_to_world(eye_to_world)

    def set_eye_to_world(self, eye_to_world: 'Matrix4') -> None:
        """Upload the inverse camera-view matrix (eye -> world).

        Used by shadow cube lookups and by IBL to sample the world-oriented
        environment probe, so it must be set whenever either is active.
        """
        loc = self._get_location('eyeToWorld', self._shadow_prog)
        if loc != -1:
            glUniformMatrix4fv(loc, 1, GL_FALSE, eye_to_world.astype('f'))

    def _set_cascade_matrix(self, slot: int, cascade: int, matrix: 'Matrix4') -> None:
        idx = slot * self.MAX_CASCADES + cascade
        loc = self._get_location(f'shadowMatrix[{idx}]', self._shadow_prog)
        if loc != -1:
            glUniformMatrix4fv(loc, 1, GL_FALSE, matrix.astype('f'))

    def _set_depth_bias(self, slot: int, cascade: int, terms: Any) -> None:
        """Set one map's world-bias-to-depth coefficients (shadowmath.depth_bias_terms)."""
        idx = slot * self.MAX_CASCADES + cascade
        self._set_uniform3f(f'shadowDepthBias[{idx}]',
                            tuple(float(t) for t in terms), self._shadow_prog)

    def _bind_shadow_texture(self, unit: int, target: int, texture_id: int) -> None:
        glActiveTexture(GL_TEXTURE0 + unit)
        glBindTexture(target, texture_id)
        glActiveTexture(GL_TEXTURE0)

    def bind_shadow_array(self, texture_id: Optional[int]) -> None:
        """Bind the shared spot+CSM depth array once per frame.

        Both a comparison view (hardware PCF) and a raw view (PCSS blocker search)
        of the *same* array texture are bound; the raw unit gets a sampler object
        that turns depth comparison off.
        """
        if self._shadow_prog is None or not texture_id:
            return
        self._bind_shadow_texture(self.SHADOW_ARRAY_UNIT, GL_TEXTURE_2D_ARRAY, texture_id)
        self._bind_shadow_texture(self.SHADOW_ARRAY_RAW_UNIT, GL_TEXTURE_2D_ARRAY, texture_id)
        glBindSampler(self.SHADOW_ARRAY_RAW_UNIT, self._pcss_sampler_object())

    def bind_cube_array(self, texture_id: Optional[int]) -> None:
        """Bind the shared point-light cube-array once per frame (packed path)."""
        if self._shadow_prog is None or not texture_id or not self.shadow_cube_array:
            return
        self._bind_shadow_texture(self.SHADOW_CUBE_BASE, GL_TEXTURE_CUBE_MAP_ARRAY, texture_id)

    def bind_spot_slot(self, slot: int, light_index: int,
                       shadow_matrix_eye: 'Matrix4',
                       bias_terms: Any = (0.0, 0.0, 0.0)) -> None:
        """Point a slot at a spot light (layer slot*MAX_CASCADES of the array)."""
        if slot >= self.MAX_SHADOW_LIGHTS or self._shadow_prog is None:
            return
        self._set_uniform1i(f'shadowLightIndex[{slot}]', light_index, self._shadow_prog)
        self._set_uniform1i(f'shadowKind[{slot}]', self.SHADOW_KIND['spot'], self._shadow_prog)
        self._set_cascade_matrix(slot, 0, shadow_matrix_eye)
        self._set_depth_bias(slot, 0, bias_terms)

    def bind_csm_slot(self, slot: int, light_index: int,
                      matrices_eye: Any, splits: Any,
                      bias_terms: Any = None) -> None:
        """Point a slot at a directional light's cascades (array layer block)."""
        if slot >= self.MAX_SHADOW_LIGHTS or self._shadow_prog is None:
            return
        self._set_uniform1i(f'shadowLightIndex[{slot}]', light_index, self._shadow_prog)
        self._set_uniform1i(f'shadowKind[{slot}]', self.SHADOW_KIND['directional'], self._shadow_prog)
        count = min(len(matrices_eye), self.MAX_CASCADES)
        self._set_uniform1i(f'cascadeCount[{slot}]', count, self._shadow_prog)
        for c in range(count):
            self._set_cascade_matrix(slot, c, matrices_eye[c])
            idx = slot * self.MAX_CASCADES + c
            self._set_uniform1f(f'cascadeSplit[{idx}]', float(splits[c]), self._shadow_prog)
            self._set_depth_bias(slot, c,
                                 bias_terms[c] if bias_terms else (0.0, 0.0, 0.0))

    def bind_cube_slot(self, slot: int, light_index: int,
                       cube_texture_id: Optional[int],
                       light_pos_world: Any, near: float, far: float,
                       bias_terms: Any = (0.0, 0.0, 0.0)) -> None:
        """Point a slot at a point light. Fallback path binds a per-slot cube map;
        the cube-array path shares one texture bound via :meth:`bind_cube_array`."""
        if slot >= self.MAX_SHADOW_LIGHTS or self._shadow_prog is None:
            return
        if not self.shadow_cube_array and cube_texture_id:
            self._bind_shadow_texture(self.SHADOW_CUBE_BASE + slot, GL_TEXTURE_CUBE_MAP, cube_texture_id)
        self._set_uniform1i(f'shadowLightIndex[{slot}]', light_index, self._shadow_prog)
        self._set_uniform1i(f'shadowKind[{slot}]', self.SHADOW_KIND['point'], self._shadow_prog)
        self._set_uniform3f(f'cubeLightPos[{slot}]', tuple(light_pos_world), self._shadow_prog)
        self._set_uniform1f(f'cubeNear[{slot}]', float(near), self._shadow_prog)
        self._set_uniform1f(f'cubeFar[{slot}]', float(far), self._shadow_prog)
        # The cube reads its bias from the slot's first layer entry: its six faces
        # share one projection, so one conversion serves them all.
        self._set_depth_bias(slot, 0, bias_terms)
