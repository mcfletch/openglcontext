"""Shader-based rendering pass implementing VRML97 lighting model

This module provides a shader-based alternative to the legacy fixed-function
rendering pipeline. It implements the VRML97 lighting model using GLSL shaders.

The shader pass is designed to:
1. Work alongside the existing flatcompat rendering path
2. Provide the same visual output as the fixed-function pipeline
3. Be selectable as an alternative render path
"""
from __future__ import annotations

import os
import re
import logging
from math import cos, sin
from typing import Any, Dict, FrozenSet, Optional, Tuple, TYPE_CHECKING

from OpenGL.GL import (
    GL_FALSE, GL_VERTEX_SHADER, GL_FRAGMENT_SHADER,
    GL_TEXTURE0, GL_TEXTURE_2D, GL_TEXTURE_2D_ARRAY, GL_TEXTURE_CUBE_MAP,
    GL_TEXTURE_CUBE_MAP_ARRAY,
    GL_CURRENT_PROGRAM, GL_TEXTURE_COMPARE_MODE, GL_NONE, GL_NEAREST,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
    glUseProgram, glGetUniformLocation, glGetIntegerv,
    glUniform1i, glUniform1f, glUniform1ui,
    glUniform2fv, glUniform3fv, glUniform4fv, glUniformMatrix3fv, glUniformMatrix4fv,
    glActiveTexture, glBindTexture, glGenSamplers, glSamplerParameteri, glBindSampler,
)
from OpenGL.GL import shaders as GL_shaders
from OpenGLContext.arrays import array
import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from OpenGLContext.texture import Texture

log = logging.getLogger(__name__)

# Type aliases
Color3 = Tuple[float, float, float]
Color4 = Tuple[float, float, float, float]
Vec3 = Tuple[float, float, float]
Vec4 = Tuple[float, float, float, float]
Matrix4 = npt.NDArray[np.float32]
Matrix3 = npt.NDArray[np.float32]

# Shader-text assembly (#include resolution, define injection, shadow budget)
# lives in shadersource; SHADER_DIR / preprocess_shader are re-exported here
# because tests and sibling passes import them from shaderpass.
from OpenGLContext.passes.shadersource import (
    SHADER_DIR,
    SHADOW_INCLUDE_MARKER,
    SHADOW_INCLUDE_PATH,
    HARD_MAX_SHADOW_LIGHTS,
    preprocess_shader,
    required_inputs,
    shadow_defines,
    resolve_shadow_config,
    load_fragment_source,
)
from OpenGLContext.passes.shaderpass_shadow import _ShadowUniformMixin


def normal_matrix(modelview: Matrix4) -> Matrix4:
    """Inverse-transpose of a modelview's upper-left 3x3 (the normal matrix).

    Computed as the cofactor matrix / determinant directly, avoiding a
    ``np.linalg.inv`` (LAPACK) call per shape per frame -- ~3x faster, which
    matters for high-node-count scenes (CAD assemblies, skinned characters).
    Falls back to the plain 3x3 for a singular (degenerate) transform.
    """
    a = modelview.tolist()
    (a00, a01, a02) = a[0][0], a[0][1], a[0][2]
    (a10, a11, a12) = a[1][0], a[1][1], a[1][2]
    (a20, a21, a22) = a[2][0], a[2][1], a[2][2]
    c00 = a11 * a22 - a12 * a21
    c01 = a12 * a20 - a10 * a22
    c02 = a10 * a21 - a11 * a20
    det = a00 * c00 + a01 * c01 + a02 * c02
    if -1e-12 < det < 1e-12:
        return np.ascontiguousarray(modelview[:3, :3], dtype='f')
    inv = 1.0 / det
    # Row-major cofactor matrix already equals adjugate-transpose, so cofactor/det
    # is exactly inv(M).T -- the normal matrix.
    return np.array((
        (c00 * inv, c01 * inv, c02 * inv),
        ((a02 * a21 - a01 * a22) * inv, (a00 * a22 - a02 * a20) * inv, (a01 * a20 - a00 * a21) * inv),
        ((a01 * a12 - a02 * a11) * inv, (a02 * a10 - a00 * a12) * inv, (a00 * a11 - a01 * a10) * inv),
    ), dtype='f')


def _as_floats(value) -> tuple:
    return tuple(float(v) for v in value)


def _vec_uploader(gl_fn):
    """Wrap a glUniform{2,3,4}fv into the (loc, value) upload signature."""
    def upload(loc, value):
        gl_fn(loc, 1, array(value, 'f'))
    return upload


_UPLOAD_2FV = _vec_uploader(glUniform2fv)
_UPLOAD_3FV = _vec_uploader(glUniform3fv)
_UPLOAD_4FV = _vec_uploader(glUniform4fv)


def _affine2d_translate(tx: float, ty: float) -> Matrix3:
    m = np.eye(3, dtype='f')
    m[0, 2] = tx
    m[1, 2] = ty
    return m


def _affine2d_scale(sx: float, sy: float) -> Matrix3:
    m = np.eye(3, dtype='f')
    m[0, 0] = sx
    m[1, 1] = sy
    return m


def _affine2d_rotate(angle: float) -> Matrix3:
    c, s = cos(angle), sin(angle)
    m = np.eye(3, dtype='f')
    m[0, 0], m[0, 1] = c, -s
    m[1, 0], m[1, 1] = s, c
    return m


def texture_transform_matrix(transform_node: Optional[Any]) -> Matrix3:
    """3x3 homogeneous UV transform for a VRML97 TextureTransform node.

    ``None`` yields identity. Composition order matches the VRML97 spec:
    translate(center) -> rotate -> scale -> translate(-center) -> translate.
    The three translation matrices share one builder so the five
    hand-written matrices this replaced can't drift apart.
    """
    if transform_node is None:
        return np.eye(3, dtype='f')
    tx, ty = transform_node.translation
    cx, cy = transform_node.center
    angle = transform_node.rotation
    sx, sy = transform_node.scale
    m = np.eye(3, dtype='f')
    if cx != 0 or cy != 0:
        m = m @ _affine2d_translate(cx, cy)
    if angle != 0:
        m = m @ _affine2d_rotate(angle)
    if sx != 1 or sy != 1:
        m = m @ _affine2d_scale(sx, sy)
    if cx != 0 or cy != 0:
        m = m @ _affine2d_translate(-cx, -cy)
    if tx != 0 or ty != 0:
        m = m @ _affine2d_translate(tx, ty)
    return m


def _ignore(*args: Any, **named: Any) -> None:
    """Accept a call the pass would answer and the shader author already has."""


class ShaderAppearanceProgram(object):
    """Stands in for the pass's programs while an appearance's own one draws.

    A geometry node asks the pass which program to bind its vertex arrays
    against, and then for somewhere to put a material, a light set, a texture
    and the matrices. When the appearance is a ``Shader`` node carrying a GLSL
    program of its own, only the first of those has an answer: the uniforms are
    the shader author's, and ``GLSLObject.render`` has already supplied the ones
    the engine offers by name (``mat_modelproj`` and its relatives). So the
    program is reported and the rest are accepted and dropped.

    The geometry's arrays land where the shader reads them because
    ``GLSLObject.compile`` binds the engine's attribute names to the locations
    :mod:`OpenGLContext.scenegraph.vertexsemantics` declares before it links.
    """

    #: What a geometry node configures on the pass's shader and this one has
    #: nothing to say about. Anything outside the set is an AttributeError
    #: rather than a silent no-op, so a geometry that needs a real answer says
    #: so instead of drawing wrongly.
    _ACCEPTED = frozenset((
        'set_matrices', 'set_solid_color', 'set_text_mode', 'set_vertex_color',
        'set_wave', 'set_texture_enabled', 'set_texture_transform',
        'set_default_texture_transform', 'set_default_material',
        'bind_texture', 'unbind_texture',
    ))

    def __init__(self, program: int) -> None:
        self.program = program
        self.unlit_program = program
        self.vertex_color_program = program
        self.point_program = program
        self.line_program = program
        self.depth_program = program

    def use(self, lit: bool = True, vertex_colors: bool = False) -> bool:
        glUseProgram(self.program)
        return True

    def use_vertex_color(self) -> bool:
        return self.use()

    def use_point(self) -> bool:
        return self.use()

    def use_line(self) -> bool:
        return self.use()

    def use_depth(self) -> bool:
        return self.use()

    def unuse(self) -> None:
        glUseProgram(0)

    def bound_program(self) -> int:
        """The one program this has: an appearance draws with its own."""
        return int(self.program)

    def required_inputs(self, program: Optional[int] = None) -> FrozenSet[str]:
        """Nothing: what this program can be drawn without is its author's.

        The engine knows its own shaders' defaults and reports a geometry that
        cannot feed one (:func:`OpenGLContext.passes.shadersource.required_inputs`).
        A ``Shader`` node's GLSL is outside that agreement, so the check has
        nothing to hold it to.
        """
        return frozenset()

    def __getattr__(self, name: str) -> Any:
        if name in self._ACCEPTED or name.startswith('_set_uniform'):
            return _ignore
        raise AttributeError(name)


class VRML97ShaderProgram(_ShadowUniformMixin):
    """Manages the VRML97 lighting shader program and uniforms.

    This class encapsulates shader compilation, uniform management,
    and provides methods for setting up material and light parameters.
    """

    # Maximum lights supported (matches shader)
    MAX_LIGHTS: int = 8

    def __init__(self) -> None:
        self.program: Optional[int] = None
        self.unlit_program: Optional[int] = None
        self.vertex_color_program: Optional[int] = None  # For per-vertex color geometry
        self.point_program: Optional[int] = None  # For PointSet with per-vertex colors
        self.line_program: Optional[int] = None  # For IndexedLineSet with per-vertex colors
        self.depth_program: Optional[int] = None  # Position-only, for shadow depth passes
        # Cache uniform locations per program: {program_id: {uniform_name: location}}
        self._location_cache: Dict[int, Dict[str, int]] = {}
        # Cache last value uploaded per (program, uniform) so a redundant set
        # (e.g. the same material on many shapes) skips the glUniform call. The
        # cache reflects exactly what we uploaded, so skipping is never stale.
        self._uniform_value_cache: Dict[Optional[int], Dict[str, Any]] = {}
        #: Which material's textures are currently bound, for the pass now
        #: running. Cleared whenever a program is activated, because anything
        #: drawn between passes -- the overlay, a depth map -- binds these units
        #: for itself and what was left on them is no longer known.
        self._boundTextures: Any = None
        self._compiled: bool = False
        # True only after every sub-program linked. Distinct from _compiled (which
        # means "compile was attempted"): a partial failure leaves _compiled=True
        # but _ok=False so use*/use_depth refuse to bind a half-built set of
        # programs.
        self._ok: bool = False
        # Shadow-sampler budget, resolved from the driver at compile time. The
        # class-level MAX_SHADOW_LIGHTS is the ceiling; the instance value may be
        # smaller on a texture-unit-starved driver. shadow_cube_array selects the
        # packed cube-array sampler over per-slot cube samplers.
        self.MAX_SHADOW_LIGHTS: int = type(self).MAX_SHADOW_LIGHTS
        self.shadow_cube_array: bool = False
        # Picking: the current shape's object id follows program switches. The
        # pass sets it on the lit program, but geometry may bind another program
        # (an unlit PointSet, per-vertex line/point) whose objectId uniform would
        # otherwise stay 0 -- making that geometry silently non-pickable. use*()
        # re-applies this to the newly-bound program, but only while _pick_active
        # (id buffer being written), so there is zero cost when not picking.
        self._current_object_id: int = 0
        self._pick_active: bool = False
        # The program this class last bound. Tracking it lets use*()
        # skip re-binding the already-active program every shape, and lets
        # set_matrices/set_object_id find the current program without a
        # glGetIntegerv(GL_CURRENT_PROGRAM) round-trip per draw. Reset each frame
        # by begin_frame() so a cross-frame external bind can't cause a stale skip.
        self._active_program: Optional[int] = None
        # Programs the static shadow sampler->unit mapping has been applied to, so
        # it isn't re-uploaded 2-3x per frame (the mapping never changes). A set,
        # since more than one program (lit + vertex-colour) receives shadows.
        self._shadow_samplers_program: set = set()
        # The program the shadow-uniform setters target. Defaults to the lit
        # program; bindShadowUniforms retargets it to also configure the
        # vertex-colour program so per-vertex-coloured / NURBS geometry gets
        # shadows.
        self._shadow_program: Optional[int] = None

    def begin_frame(self) -> None:
        """Reset per-frame bind tracking; call once at the top of each frame.

        Within a frame every VRML97 program switch goes through use*(), so the
        cached ``_active_program`` stays truthful and use*() can safely skip a
        redundant re-bind. Clearing it here bounds any staleness to a single
        frame (e.g. a background/legacy shader binding its own program).
        """
        self._active_program = None

    def _bind_program(self, program: Optional[int]) -> None:
        """glUseProgram and record the program for the default-arg lookups.

        This deliberately always issues glUseProgram rather than skipping when the
        program "looks" already-active: other passes (the IBL probe build, bloom)
        bind their own programs mid-frame without going through this class, so a
        skip-cache would leave the wrong program bound (verified: it broke IBL
        uniform uploads with GL_INVALID_OPERATION). The cheap driver-side re-bind
        is kept; only the per-draw GL_CURRENT_PROGRAM *read* is eliminated.
        """
        # A new program means the texture units are not known to hold what the
        # last material bound; see :attr:`_boundTextures`.
        self._boundTextures = None
        glUseProgram(program)
        self._active_program = program

    def _program_for_default(self) -> int:
        """Program a default-arg set_matrices/set_object_id targets.

        Geometry calls those right after a use*(), so the class's last-bound
        program is the one being drawn with -- no glGetIntegerv round-trip.
        Falls back to the lit program before anything is bound this frame (or
        after an explicit unbind).
        """
        program = self._active_program or self.program
        assert program is not None  # a program is always compiled+bound at draw time
        return program

    # Every GL program handle the pass may bind; cleared together on failure.
    _PROGRAM_ATTRS: Tuple[str, ...] = (
        'program', 'unlit_program', 'vertex_color_program',
        'point_program', 'line_program', 'depth_program',
    )

    #: The vertex shader each of those is compiled from. A geometry about to
    #: draw asks what the bound program cannot be drawn without, and this is
    #: how the handle it has leads back to the source that says so.
    VERTEX_SOURCES: Dict[str, str] = {
        'program': 'vrml97_lighting.vert',
        'unlit_program': 'vrml97_unlit.vert',
        'vertex_color_program': 'vrml97_vertex_color.vert',
        'point_program': 'vrml97_point.vert',
        'line_program': 'vrml97_line.vert',
        'depth_program': 'shadow_depth.vert',
    }

    def bound_program(self) -> int:
        """The program this has bound, or the lit one before anything is.

        What a geometry node is about to draw with, so what it is checked
        against; :meth:`_program_for_default` is the same answer for uniform
        uploads, where a program is always bound and None cannot happen.
        """
        return int(self._active_program or self.program or 0)

    def required_inputs(self, program: Optional[int] = None) -> FrozenSet[str]:
        """The vertex arrays ``program`` cannot be drawn without.

        Defaults to the program now bound, which is the one a geometry node is
        about to draw with -- the depth pass asks for a position and nothing
        else, where the lit program it shares its vertex arrays with asks for
        more. An unrecognised handle is owed nothing, since the engine can only
        speak for the shaders it compiled.
        """
        program = program or self.bound_program()
        for attribute, source in self.VERTEX_SOURCES.items():
            if program and getattr(self, attribute, None) == program:
                return required_inputs(source)
        return frozenset()

    def _clear_programs(self) -> None:
        """Null every program handle after a failed/partial compile.

        Leaves nothing for a later ``use*`` to bind, so a compile that got halfway
        can't hand a draw a ``None`` (or a linked-but-incomplete) program.
        """
        for name in self._PROGRAM_ATTRS:
            setattr(self, name, None)
        self._ok = False

    @staticmethod
    def _delete_shaders(*shaders) -> None:
        """Flag compiled shader objects for deletion once linked into a program.

        The program keeps them alive until it is itself deleted, so this just
        drops the standalone references that would otherwise leak per recompile.
        """
        from OpenGL.GL import glDeleteShader
        for sh in shaders:
            try:
                glDeleteShader(sh)
            except Exception:
                pass

    def _compile_one(self, label, vert_name, frag_name,
                     validate=True, shadow_frag=False):
        """Compile one program in isolation; return its handle or None.

        A break in any single shader must degrade only that feature, not take
        down the whole shader system. Failures are logged and return
        None so the caller can keep the programs that did compile.
        """
        try:
            # preprocess_shader resolves shared #includes (the _objectid_inc /
            # _lights_inc helpers); a shader with no includes
            # round-trips unchanged. The lit fragment additionally needs the
            # shadow-budget defines, so it goes through load_fragment_source.
            vert_source = preprocess_shader(vert_name)
            if shadow_frag:
                frag_source = load_fragment_source(
                    frag_name, self.MAX_SHADOW_LIGHTS, self.shadow_cube_array)
            else:
                frag_source = preprocess_shader(frag_name)
            vertex = GL_shaders.compileShader(vert_source, GL_VERTEX_SHADER)
            fragment = GL_shaders.compileShader(frag_source, GL_FRAGMENT_SHADER)
            program = GL_shaders.compileProgram(vertex, fragment, validate=validate)
            self._delete_shaders(vertex, fragment)
            return program
        except Exception as err:
            log.error("Failed to compile %s shader (%s/%s): %s",
                      label, vert_name, frag_name, err)
            return None

    def compile(self) -> bool:
        """Compile the shader programs from source files.

        Each program is compiled in isolation so one broken shader degrades only
        its feature; the lit program is the one the system can't do
        without, so ``_ok`` (the return value) tracks it.

        Returns:
            True if the essential (lit) program compiled, False otherwise.
        """
        if self._compiled:
            return self._ok

        # Resolve how many shadow lights (and which cube path) this driver's
        # texture-unit budget allows, then bake it into the fragment source.
        self.MAX_SHADOW_LIGHTS, self.shadow_cube_array = resolve_shadow_config()

        # validate=False on the lit program: it declares shadow samplers of
        # several texture targets that all default to unit 0 at link time (a
        # spurious "different type / same unit" validation failure). Real unit
        # assignment happens via init_shadow_samplers() before drawing.
        self.program = self._compile_one(
            'lit', 'vrml97_lighting.vert', 'vrml97_lighting.frag',
            validate=False, shadow_frag=True)
        self.unlit_program = self._compile_one(
            'unlit', 'vrml97_unlit.vert', 'vrml97_unlit.frag')
        # shadow_frag: the vertex-colour shader now #includes _shadow_inc, so it
        # needs the MAX_SHADOW_LIGHTS defines baked in like the lit program (2a).
        self.vertex_color_program = self._compile_one(
            'vertex_color', 'vrml97_vertex_color.vert', 'vrml97_vertex_color.frag',
            shadow_frag=True)
        self.point_program = self._compile_one(
            'point', 'vrml97_point.vert', 'vrml97_point.frag')
        self.line_program = self._compile_one(
            'line', 'vrml97_line.vert', 'vrml97_line.frag')
        # Position-only depth program for the shadow-map pass.
        self.depth_program = self._compile_one(
            'depth', 'shadow_depth.vert', 'shadow_depth.frag', validate=False)

        self._compiled = True
        self._ok = self.program is not None
        if self._ok:
            # Assign shadow samplers to distinct texture units immediately, even
            # when shadows are disabled: the 2D-array and cube shadow samplers
            # are active in the lit program and must not alias unit 0 (a 2D
            # target) or every draw fails with GL_INVALID_OPERATION.
            try:
                self._bind_program(self.program)
                self.init_shadow_samplers()
                self._bind_program(0)
            except Exception as err:
                log.error("Shadow sampler init failed: %s", err)
            log.info("VRML97 shader programs compiled (lit ok; "
                     "unlit=%s vc=%s point=%s line=%s depth=%s)",
                     self.unlit_program is not None,
                     self.vertex_color_program is not None,
                     self.point_program is not None,
                     self.line_program is not None,
                     self.depth_program is not None)
        else:
            log.error("VRML97 lit shader failed to compile; shader rendering off")
        return self._ok

    def use(self, lit: bool = True, vertex_colors: bool = False) -> bool:
        """Activate the shader program.

        Args:
            lit: If True, use the lighting shader. If False, use unlit shader.
            vertex_colors: If True (and lit=True), use vertex color shader instead.

        Returns:
            True if shader was activated, False otherwise
        """
        if not self._compiled:
            self.compile()
        if not self._ok:
            return False

        if lit and vertex_colors:
            program = self.vertex_color_program
        elif lit:
            program = self.program
        else:
            program = self.unlit_program
        if program:
            self._bind_program(program)
            if self._pick_active:
                self._apply_object_id(program)
        return program is not None

    def use_depth(self) -> Optional[int]:
        """Activate the position-only depth program for shadow passes.

        Returns the program id in use. Falls back to the full lit program when a
        depth-only program was not compiled (keeps non-PBR paths working).
        """
        if not self._compiled:
            self.compile()
        if not self._ok:
            return None
        program = self.depth_program or self.program
        if program:
            self._bind_program(program)
        return program

    def use_vertex_color(self) -> bool:
        """Activate the vertex color shader program.

        Use this for geometry with per-vertex colors (like NURBS with color arrays).

        Returns:
            True if shader was activated, False otherwise
        """
        return self.use(lit=True, vertex_colors=True)

    def use_point(self) -> bool:
        """Activate the point shader program.

        Use this for PointSet geometry with per-vertex colors.
        This is a simple unlit shader that passes through vertex colors.

        Returns:
            True if shader was activated, False otherwise
        """
        if not self._compiled:
            self.compile()
        if not self._ok:
            return False
        if self.point_program:
            self._bind_program(self.point_program)
            if self._pick_active:
                self._apply_object_id(self.point_program)
            return True
        return False

    def use_line(self) -> bool:
        """Activate the line shader program.

        Use this for IndexedLineSet geometry with per-vertex colors.
        This is a simple unlit shader that passes through vertex colors.

        Returns:
            True if shader was activated, False otherwise
        """
        if not self._compiled:
            self.compile()
        if not self._ok:
            return False
        if self.line_program:
            self._bind_program(self.line_program)
            if self._pick_active:
                self._apply_object_id(self.line_program)
            return True
        return False

    def unuse(self) -> None:
        """Deactivate the shader program."""
        self._bind_program(0)

    def _get_location(self, name: str, program: Optional[int] = None) -> int:
        """Get uniform location, caching the result.

        Args:
            name: Uniform name
            program: Shader program (defaults to lit program)

        Returns:
            Uniform location, or -1 if not found
        """
        if program is None:
            program = self.program

        if program is None:
            return -1

        # Use per-program cache
        if program not in self._location_cache:
            self._location_cache[program] = {}
        cache = self._location_cache[program]

        if name not in cache:
            cache[name] = glGetUniformLocation(program, name)
        return cache[name]

    def set_matrices(
        self,
        modelview: Matrix4,
        projection: Matrix4,
        program: Optional[int] = None
    ) -> None:
        """Set the transformation matrices.

        Args:
            modelview: 4x4 modelview matrix (numpy array)
            projection: 4x4 projection matrix (numpy array)
            program: Shader program (defaults to currently active program)

        Note: If no program is specified, uses the currently bound program.
              This allows geometry nodes to update matrices without knowing
              which rendering mode (lit vs unlit) is active.
        """
        if program is None:
            # The program the class last bound -- geometry always
            # calls set_matrices right after a use*(), so this is the drawing
            # program, without a glGetIntegerv(GL_CURRENT_PROGRAM) round-trip.
            program = self._program_for_default()

        # Skip the modelview upload -- and, crucially, the normal-matrix solve --
        # when the matrix is unchanged from the last draw. Merged static scenes
        # render many shapes under one shared transform, so this collapses a
        # per-shape glUniform + cofactor solve into once-per-transform.
        mv = np.ascontiguousarray(modelview, dtype='f')
        mv_changed = not self._uniform_unchanged(program, 'modelViewMatrix', mv.tobytes())
        if mv_changed:
            mv_loc = self._get_location('modelViewMatrix', program)
            if mv_loc != -1:
                glUniformMatrix4fv(mv_loc, 1, GL_FALSE, mv)
        # The projection is constant across every object in a frame; only upload
        # it when it actually changes (camera/frustum), not once per shape.
        self._set_matrix_cached('projectionMatrix', projection, program)

        # Normal matrix (inverse transpose of the upper-left 3x3) tracks modelview,
        # so it only needs recomputing/uploading when modelview changed.
        if mv_changed and (program == self.program or program == self.vertex_color_program):
            normal_loc = self._get_location('normalMatrix', program)
            if normal_loc != -1:
                # Inverse-transpose of the upper-left 3x3 (handles non-uniform
                # scale); a direct cofactor solve, not a per-shape LAPACK inv().
                glUniformMatrix3fv(normal_loc, 1, GL_FALSE, normal_matrix(mv))

    def set_material(
        self,
        diffuse: Color3 = (0.8, 0.8, 0.8),
        specular: Color3 = (0.0, 0.0, 0.0),
        emissive: Color3 = (0.0, 0.0, 0.0),
        ambient_intensity: float = 0.2,
        shininess: float = 0.2,
        transparency: float = 0.0
    ) -> None:
        """Set material uniforms.

        Args match VRML97 Material node fields:
            diffuse: RGB diffuse color (0-1)
            specular: RGB specular color (0-1)
            emissive: RGB emissive color (0-1)
            ambient_intensity: Ambient intensity factor (0-1)
            shininess: Shininess factor (0-1, mapped to 1-128 in shader)
            transparency: Transparency (0=opaque, 1=fully transparent)
        """
        self._set_uniform3f('diffuseColor', diffuse)
        self._set_uniform3f('specularColor', specular)
        self._set_uniform3f('emissiveColor', emissive)
        self._set_uniform1f('ambientIntensity', ambient_intensity)
        self._set_uniform1f('shininess', shininess)
        self._set_uniform1f('transparency', transparency)

    def set_default_material(self) -> None:
        """Set VRML97 default material values."""
        self.set_material(
            diffuse=(0.8, 0.8, 0.8),
            specular=(0.0, 0.0, 0.0),
            emissive=(0.0, 0.0, 0.0),
            ambient_intensity=0.2,
            shininess=0.2,
            transparency=0.0
        )

    def set_scene_ambient(self, ambient: Color3 = (0.2, 0.2, 0.2)) -> None:
        """Set scene ambient color."""
        self._set_uniform3f('sceneAmbient', ambient)

    def set_num_lights(self, count: int, program: Optional[int] = None) -> None:
        """Set the number of active lights."""
        self._set_uniform1i('numLights', min(count, self.MAX_LIGHTS), program)

    def set_light(
        self,
        index: int,
        light_type: str = 'directional',
        color: Color3 = (1.0, 1.0, 1.0),
        position: Vec4 = (0.0, 0.0, 1.0, 0.0),
        direction: Vec3 = (0.0, 0.0, -1.0),
        attenuation: Vec3 = (1.0, 0.0, 0.0),
        intensity: float = 1.0,
        beam_width: float = 1.57,
        cutoff_angle: float = 0.785,
        light_range: float = 0.0,
        program: Optional[int] = None
    ) -> None:
        """Set parameters for a single light.

        Args:
            index: Light index (0 to MAX_LIGHTS-1)
            light_type: 'off', 'directional', 'point', or 'spot'
            color: RGB color (0-1)
            position: XYZ position (w=0 for directional, w=1 for positional)
            direction: XYZ direction (for directional and spot)
            attenuation: (constant, linear, quadratic) factors
            intensity: Light intensity multiplier
            beam_width: Spot inner cone angle (radians)
            cutoff_angle: Spot outer cone angle (radians)
            program: Shader program to set uniforms on (defaults to main lit program)
        """
        if index >= self.MAX_LIGHTS:
            return

        type_map = {'off': 0, 'directional': 1, 'point': 2, 'spot': 3}
        type_val = type_map.get(light_type, 0)

        self._set_uniform1i(f'lightType[{index}]', type_val, program)
        self._set_uniform3f(f'lightColor[{index}]', color, program)
        self._set_uniform4f(f'lightPosition[{index}]', position, program)
        self._set_uniform3f(f'lightDirection[{index}]', direction, program)
        self._set_uniform3f(f'lightAttenuation[{index}]', attenuation, program)
        self._set_uniform1f(f'lightRange[{index}]', light_range, program)
        self._set_uniform1f(f'lightIntensity[{index}]', intensity, program)
        self._set_uniform1f(f'lightBeamWidth[{index}]', beam_width, program)
        self._set_uniform1f(f'lightCutOffAngle[{index}]', cutoff_angle, program)

    def set_default_light(self) -> None:
        """Set up default VRML97 headlight (directional from camera)."""
        self.set_num_lights(1)
        self.set_light(
            0,
            light_type='directional',
            color=(1.0, 1.0, 1.0),
            direction=(0.0, 0.0, -1.0),
            intensity=1.0
        )

    def set_texture_enabled(self, enabled: bool, texture_unit: int = 0) -> None:
        """Enable or disable diffuse texture."""
        self._set_uniform1i('hasDiffuseTexture', 1 if enabled else 0)
        if enabled:
            self._set_uniform1i('diffuseTexture', texture_unit)

    def set_solid_color(self, color: Color4) -> None:
        """Set solid color for unlit shader (used for picking)."""
        loc = self._get_location('solidColor', self.unlit_program)
        if loc != -1:
            glUniform4fv(loc, 1, array(color, 'f'))

    def set_object_id(self, object_id: int, program: Optional[int] = None) -> None:
        """Set object ID for selection buffer (MRT).

        Args:
            object_id: Unique object ID (32-bit unsigned integer)
            program: Shader program (defaults to currently active program)
        """
        # Remember it so a later program switch (use_point/use_line/use(lit=False))
        # can carry the id onto whatever program the geometry actually draws with.
        self._current_object_id = object_id
        if program is None:
            program = self._program_for_default()

        loc = self._get_location('objectId', program)
        if loc != -1:
            glUniform1ui(loc, object_id)

    def set_instancing(self, enabled: bool, program: Optional[int] = None) -> None:
        """Toggle the shader's per-instance path (instanced model + object id).

        When on, the vertex shader reads the modelview and picking id from the
        per-instance attributes (locations 5-9) instead of the per-draw uniforms.
        A single uniform, shared by the vertex and fragment stages.
        """
        if program is None:
            program = self.program
        loc = self._get_location('instancingEnabled', program)
        if loc != -1:
            glUniform1i(loc, 1 if enabled else 0)

    def _apply_object_id(self, program: Optional[int]) -> None:
        """Set the current object id on ``program`` (assumed just bound).

        Called from use*() during picking so geometry that switches away from the
        lit program still writes the right selection id. A no-op program or a
        program lacking the uniform is skipped.
        """
        if not program:
            return
        loc = self._get_location('objectId', program)
        if loc != -1:
            glUniform1ui(loc, self._current_object_id)

    def set_text_mode(
        self,
        enabled: bool,
        text_color: Color4 = (1.0, 1.0, 1.0, 1.0),
        background_color: Color4 = (0.0, 0.0, 0.0, 1.0),
        solid_background: bool = False
    ) -> None:
        """Configure text rendering mode for the unlit shader.

        Args:
            enabled: Enable text rendering mode
            text_color: RGBA color for text (foreground)
            background_color: RGBA color for background (when solid_background=True)
            solid_background: If True, render solid background instead of transparent
        """
        # Set text mode flag
        loc = self._get_location('textMode', self.unlit_program)
        if loc != -1:
            glUniform1i(loc, 1 if enabled else 0)

        # Set text color
        loc = self._get_location('textColor', self.unlit_program)
        if loc != -1:
            glUniform4fv(loc, 1, array(text_color, 'f'))

        # Set background color
        loc = self._get_location('backgroundColor', self.unlit_program)
        if loc != -1:
            glUniform4fv(loc, 1, array(background_color, 'f'))

        # Set solid background flag
        loc = self._get_location('textSolidBg', self.unlit_program)
        if loc != -1:
            glUniform1i(loc, 1 if solid_background else 0)

        # Also set useTexture for text mode (text always uses texture)
        if enabled:
            loc = self._get_location('useTexture', self.unlit_program)
            if loc != -1:
                glUniform1i(loc, 1)

    def bind_texture(self, texture_obj: Optional[Texture], texture_unit: int = 0) -> None:
        """Bind a texture for shader use.

        Args:
            texture_obj: OpenGLContext Texture object (has .texture attribute)
            texture_unit: Texture unit to bind to (default 0)
        """
        if texture_obj is None:
            self.set_texture_enabled(False)
            return

        # Activate texture unit
        glActiveTexture(GL_TEXTURE0 + texture_unit)

        # Bind the texture
        glBindTexture(GL_TEXTURE_2D, texture_obj.texture)

        # Tell shader we have a texture
        self.set_texture_enabled(True, texture_unit)

    def unbind_texture(self, texture_unit: int = 0) -> None:
        """Unbind texture and disable texture sampling."""
        glActiveTexture(GL_TEXTURE0 + texture_unit)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.set_texture_enabled(False)

    def set_texture_transform(self, transform_node: Optional[Any] = None) -> None:
        """Upload the UV transform matrix for a VRML97 TextureTransform node.

        Args:
            transform_node: TextureTransform node, or None for identity
        """
        loc = self._get_location('textureMatrix')
        if loc != -1:
            glUniformMatrix3fv(loc, 1, GL_FALSE, texture_transform_matrix(transform_node))

    def set_default_texture_transform(self) -> None:
        """Set identity texture transform."""
        self.set_texture_transform(None)

    def _set_matrix_cached(self, name: str, matrix: Any, program: Optional[int] = None) -> None:
        """Upload a mat4 uniform, skipping the call when its bytes are unchanged.

        For matrices that repeat across many draws in a frame (projection, an
        identity texture transform) this removes a per-draw glUniformMatrix call.
        """
        m = np.ascontiguousarray(matrix, dtype='f')
        key = m.tobytes()
        if self._uniform_unchanged(program, name, key):
            return
        loc = self._get_location(name, program)
        if loc != -1:
            glUniformMatrix4fv(loc, 1, GL_FALSE, m)

    def _uniform_unchanged(self, program: Optional[int], name: str, value: Any) -> bool:
        """True if ``value`` equals the last value uploaded for this uniform."""
        if program is None:
            program = self.program
        pc = self._uniform_value_cache.get(program)
        if pc is None:
            pc = self._uniform_value_cache[program] = {}
        if name in pc and pc[name] == value:
            return True
        pc[name] = value
        return False

    def _set_uniform(self, name: str, value: Any, program: Optional[int],
                     upload) -> None:
        """Shared scalar/vector uniform upload.

        Skips when the value is unchanged from the last upload for this program,
        resolves the location, then hands off to the type-specific ``upload(loc,
        value)``. ``value`` must already be normalized (int/float/float-tuple) so
        the change-cache key is canonical.
        """
        if self._uniform_unchanged(program, name, value):
            return
        loc = self._get_location(name, program)
        if loc != -1:
            upload(loc, value)

    def _set_uniform1i(self, name: str, value: int, program: Optional[int] = None) -> None:
        self._set_uniform(name, int(value), program, glUniform1i)

    def _set_uniform1f(self, name: str, value: float, program: Optional[int] = None) -> None:
        self._set_uniform(name, float(value), program, glUniform1f)

    def _set_uniform2f(self, name: str, value, program: Optional[int] = None) -> None:
        self._set_uniform(name, _as_floats(value), program, _UPLOAD_2FV)

    def _set_uniform3f(self, name: str, value: Vec3, program: Optional[int] = None) -> None:
        self._set_uniform(name, _as_floats(value), program, _UPLOAD_3FV)

    def _set_uniform4f(self, name: str, value: Vec4, program: Optional[int] = None) -> None:
        self._set_uniform(name, _as_floats(value), program, _UPLOAD_4FV)


class ShaderRenderMode:
    """Render mode flag indicating shader-based rendering is active.

    Geometry nodes can check mode.shader_mode to determine whether
    to use shader-based or legacy rendering.
    """
    shader_mode: bool = True
    shader_program: Optional[VRML97ShaderProgram] = None

    def __init__(self, base_mode: Any, shader_program: VRML97ShaderProgram) -> None:
        """Wrap a base render mode with shader capabilities.

        Args:
            base_mode: The underlying render mode (from flatcompat)
            shader_program: VRML97ShaderProgram instance
        """
        self._base_mode = base_mode
        self.shader_program = shader_program

    def __getattr__(self, name: str) -> Any:
        """Delegate to base mode for any attributes we don't override."""
        return getattr(self._base_mode, name)


# Global shader program instance (lazy initialization)
_shader_program: Optional[VRML97ShaderProgram] = None


def get_shader_program() -> VRML97ShaderProgram:
    """Get the global VRML97 shader program, compiling if needed."""
    global _shader_program
    if _shader_program is None:
        _shader_program = VRML97ShaderProgram()
    return _shader_program


def configure_light_from_node(
    shader_program: VRML97ShaderProgram,
    index: int,
    light_node: Any,
    modelview_matrix: Optional[Matrix4] = None,
    program: Optional[int] = None
) -> None:
    """Configure shader light from a VRML97 Light node.

    Args:
        shader_program: VRML97ShaderProgram instance
        index: Light index (0 to MAX_LIGHTS-1)
        light_node: A VRML97 Light node (DirectionalLight, PointLight, SpotLight)
        modelview_matrix: Modelview matrix to transform light position/direction to eye space.
                         This is required to match fixed-function OpenGL behavior where
                         glLightfv transforms the light by the current modelview matrix.
        program: Shader program to set uniforms on (defaults to main lit program)
    """
    from OpenGLContext.scenegraph import light as light_module

    if not light_node.on:
        shader_program.set_light(index, light_type='off', program=program)
        return

    # Get light color and intensity
    color = tuple(light_node.color)
    intensity = float(light_node.intensity)

    def transform_direction(direction: Vec3) -> Vec3:
        """Transform direction vector by modelview matrix (ignoring translation)."""
        if modelview_matrix is None:
            return direction
        # For directions, use only the upper 3x3 rotation/scale part
        # Note: OpenGLContext matrices are row-major (row vectors), so use d @ M
        d = np.array([direction[0], direction[1], direction[2]], dtype=np.float32)
        mv3 = modelview_matrix[:3, :3]
        transformed = d @ mv3
        # Normalize the result
        length = np.sqrt(np.sum(transformed * transformed))
        if length > 0:
            transformed = transformed / length
        return tuple(transformed)

    def transform_position(position: Vec3) -> Vec4:
        """Transform position by modelview matrix."""
        if modelview_matrix is None:
            return tuple(position) + (1.0,)
        # For positions, use full 4x4 transform
        # Note: OpenGLContext matrices are row-major (row vectors), so use p @ M
        p = np.array([position[0], position[1], position[2], 1.0], dtype=np.float32)
        transformed = p @ modelview_matrix
        # Return as (x, y, z, 1.0) - w=1 for positional light
        return (float(transformed[0]), float(transformed[1]), float(transformed[2]), 1.0)

    # Determine light type and parameters
    if isinstance(light_node, light_module.DirectionalLight):
        # Directional light - direction is constant
        # VRML direction is where light points (e.g., (0,-1,0) means pointing down)
        # Pass to shader as-is; shader will negate to get direction toward light
        orig_direction = tuple(light_node.direction)
        direction = transform_direction(orig_direction)
        shader_program.set_light(
            index,
            light_type='directional',
            color=color,
            direction=direction,
            intensity=intensity,
            program=program,
        )

    elif isinstance(light_node, light_module.SpotLight):
        # Spot light - has position, direction, and cone angles
        position = transform_position(tuple(light_node.location))
        direction = transform_direction(tuple(light_node.direction))
        attenuation = tuple(light_node.attenuation)

        # VRML97 uses cutOffAngle and beamWidth in radians
        cutoff_angle = float(light_node.cutOffAngle)
        beam_width = float(getattr(light_node, 'beamWidth', cutoff_angle))

        shader_program.set_light(
            index,
            light_type='spot',
            color=color,
            position=position,
            direction=direction,
            attenuation=attenuation,
            intensity=intensity,
            beam_width=beam_width,
            cutoff_angle=cutoff_angle,
            light_range=float(getattr(light_node, '_gltf_range', 0.0)),
            program=program,
        )

    elif isinstance(light_node, light_module.PointLight):
        # Point light - has position and attenuation
        position = transform_position(tuple(light_node.location))
        attenuation = tuple(light_node.attenuation)

        shader_program.set_light(
            index,
            light_type='point',
            color=color,
            position=position,
            attenuation=attenuation,
            intensity=intensity,
            light_range=float(getattr(light_node, '_gltf_range', 0.0)),
            program=program,
        )

    else:
        # Unknown light type - treat as directional
        direction = getattr(light_node, 'direction', (0.0, 0.0, -1.0))
        direction = transform_direction(tuple(direction))
        shader_program.set_light(
            index,
            light_type='directional',
            color=color,
            direction=direction,
            intensity=intensity,
            program=program,
        )


def appearance_solid_color(appearance: Any) -> Color4:
    """The one colour an appearance draws geometry that carries no colour of
    its own -- a line, an unlit point cloud.

    A material that emits takes its emissive colour, because that is what an
    unlit surface of it looks like; anything else takes its base/diffuse
    colour. White where there is no material at all, which is what a caller
    who gave the geometry no appearance is asking for.
    """
    material = getattr(appearance, 'material', None) if appearance else None
    if material is None:
        return (1.0, 1.0, 1.0, 1.0)
    alpha = 1.0 - float(getattr(material, 'transparency', 0.0) or 0.0)
    emissive = getattr(material, 'emissiveColor', None)
    if emissive is not None and any(float(part) > 0.0 for part in emissive):
        return (float(emissive[0]), float(emissive[1]), float(emissive[2]),
                alpha)
    base = getattr(material, 'baseColor', None)
    if base is None:
        base = getattr(material, 'diffuseColor', None)
    if base is None:
        return (1.0, 1.0, 1.0, alpha)
    return (float(base[0]), float(base[1]), float(base[2]), alpha)


def configure_material_from_node(
    shader_program: VRML97ShaderProgram,
    material_node: Optional[Any]
) -> None:
    """Configure shader material from a VRML97 Material node.

    Args:
        shader_program: VRML97ShaderProgram instance
        material_node: A VRML97 Material node
    """
    if material_node is None:
        shader_program.set_default_material()
        return

    from OpenGLContext.scenegraph.material_fields import read_material_fields
    f = read_material_fields(material_node)   # shared raw read

    shader_program.set_material(
        diffuse=f.diffuseColor,
        specular=f.specularColor,
        emissive=f.emissiveColor,
        ambient_intensity=f.ambientIntensity,
        shininess=f.shininess,
        transparency=f.transparency,
    )
