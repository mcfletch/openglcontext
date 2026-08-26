"""Teapot node for use in geometry attribute of Shapes

The Utah Teapot (a.k.a. the Newell teapot) is the standard reference object
of computer graphics, modelled by Martin Newell in 1975 at the University of
Utah.  See https://graphics.cs.utah.edu/teapot/ for its history.

The geometry is generated from the Newell teapot's 32 bicubic Bezier patches by
tessellating each patch with the GLU NURBS tessellators (see
:mod:`OpenGLContext.scenegraph.teapot_nurbs`), which works in both the legacy
and the shader/core pipelines.  GLU is a practical hard dependency, so there is
no static-mesh fallback; the legacy ``glutSolidTeapot`` endpoint remains only as
an explicit ``useGlut`` comparison option.

Tessellation is distance-LOD aware: the mesh is built (and cached) at a coarser
GLU sampling step the further the camera is, so a teapot that is a small part of
the frame costs far fewer triangles.  Level 0 (close up) reproduces the previous
default sampling, so near appearance is unchanged.
"""
from OpenGL.GL import *
from vrml.vrml97 import nodetypes
from vrml import node, field
import numpy as np
import ctypes
import logging

from OpenGLContext.scenegraph import tessellationlod
from OpenGLContext.scenegraph.vertexsemantics import (
    LOC_TEXCOORD, LOC_NORMAL, LOC_POSITION, LOC_TANGENT,
)

log = logging.getLogger(__name__)

# GLUT teapot functions for the explicit legacy-comparison path.
try:
    from OpenGL.GLUT import glutSolidTeapot, glutWireTeapot
    HAS_GLUT_TEAPOT = True
except ImportError:
    HAS_GLUT_TEAPOT = False
    log.debug("GLUT teapot not available (only affects useGlut=True)")


class Teapot(nodetypes.Geometry, node.Node):
    """Utah Teapot geometry node.

    The geometry is generated from the Newell teapot's Bezier control points by
    tessellating each patch with the GLU NURBS tessellators (see
    :mod:`OpenGLContext.scenegraph.teapot_nurbs`); tessellation happens once per
    LOD level, lazily, on the first render at that level within a GL context.

    Attributes:
        size: Scale factor for the teapot (default 1.0).  Matches the sizing
            of ``glutSolidTeapot(size)``.
        solid: If True, render filled polygons; if False, render wireframe.
        lid: If True (default), render the teapot lid; if False, omit the
            entire lid (the eight lid patches).
        useGlut: If True, render with the legacy ``glutSolidTeapot`` endpoint
            (when GLUT is available and not in shader mode), kept for
            comparison.  Default False: use the NURBS-tessellated mesh.
    """
    PROTO = 'Teapot'
    size = field.newField('size', 'SFFloat', 1, 1.0)
    solid = field.newField('solid', 'SFBool', 1, True)
    lid = field.newField('lid', 'SFBool', 1, True)
    useGlut = field.newField('useGlut', 'SFBool', 1, False)

    # Approximate local bounding sphere of the unit (size=1) y-up teapot, used
    # only to pick a distance-LOD level; precision is not needed, and using an
    # estimate avoids forcing a tessellation just to measure the mesh.
    _UNIT_CENTER = (0.0, 0.0, 0.0)
    _UNIT_RADIUS = 1.9   # ~half-diagonal of the ~3.0 x 1.6 x 2.0 extent

    # Tessellated N3F_V3F arrays per LOD level: {level: (base, lid)}. Shared
    # across instances (the geometry is context-independent).
    _arrays: dict[int, tuple] = {}
    # Retry budget per level: the first render at a level can fail
    # for transient reasons (no current GL context); latching it off disabled the
    # teapot. Retry up to this many times before giving up on that level.
    _tessellate_attempts: dict[int, int] = {}
    _MAX_TESSELLATE_ATTEMPTS = 3

    # Shader-path GL resources per LOD level:
    # {level: {'base_vao','base_count','lid_vao','lid_count'}}.
    _buffers: dict[int, dict] = {}

    # -- tessellation ------------------------------------------------------
    @classmethod
    def _ensure_tessellated(cls, level=0):
        """Tessellate the Bezier patches into vertex arrays for ``level`` once."""
        entry = cls._arrays.get(level)
        if entry is not None:
            return entry[0] is not None
        try:
            from OpenGLContext.scenegraph.teapot_nurbs import (
                tessellate_teapot, steps_for_level,
            )
            base, lid = tessellate_teapot(steps=steps_for_level(level))
            cls._arrays[level] = (base, lid)
            return True
        except Exception as e:
            attempts = cls._tessellate_attempts.get(level, 0) + 1
            cls._tessellate_attempts[level] = attempts
            # Only give up permanently after repeated failures; a single failure
            # may be transient (no current GL context on the first frame), so let
            # a later render retry instead of disabling the level.
            if attempts >= cls._MAX_TESSELLATE_ATTEMPTS:
                log.error("Failed to tessellate teapot (level %d) after %d attempts: %s",
                          level, attempts, e)
                cls._arrays[level] = (None, None)
            else:
                log.warning("Teapot tessellation (level %d) attempt %d failed (will retry): %s",
                            level, attempts, e)
            return False

    def _lod_level(self, mode):
        """Distance-LOD level for this teapot, size-normalized (0 = finest)."""
        center = tuple(c * self.size for c in self._UNIT_CENTER)
        radius = self._UNIT_RADIUS * self.size
        return tessellationlod.lod_level(mode, center, radius)

    # -- instancing --------------------------------------------------------
    # Many shapes sharing one Teapot node (or the same size/lid) collapse into a
    # single instanced draw. The instanced mesh bakes the finest (level-0)
    # tessellation, so instances give up the distance-LOD that the per-object
    # path applies: a field of instanced teapots pays full vertex detail at every
    # distance, trading that for one draw call. The quadrics make the same trade;
    # see plans/INSTANCED-GEOMETRY.md.
    def instanceContentKey(self):
        """Teapots of the same size/lid/solid share one baked mesh -> one draw.

        ``size`` is folded into the instance mesh (the per-instance modelview
        carries only the scene transform), and ``lid``/``solid`` change the mesh
        or its polygon mode, so all three split the batch.
        """
        return ('Teapot', round(float(self.size), 6),
                bool(self.lid), bool(self.solid))

    def _instanceArrays(self):
        """Baked (positions, normals, texcoords) for the instanced mesh, or None.

        The finest (level-0) tessellation with ``size`` folded into the
        positions, de-interleaved from the T2F_N3F_V3F arrays into the shader's
        separate-attribute layout. Returns None when tessellation is unavailable
        (no GLU / no context yet), matching the render path's own guard.
        """
        from OpenGLContext.scenegraph.teapot_nurbs import FLOATS_PER_VERTEX
        if not self._ensure_tessellated(0):
            return None
        base_array, lid_array = self._arrays[0]
        chunks = [base_array]
        if self.lid and lid_array is not None:
            chunks.append(lid_array)
        chunks = [np.asarray(a, dtype='f') for a in chunks
                  if a is not None and len(a)]
        if not chunks:
            return None
        v = np.concatenate(chunks).reshape(-1, FLOATS_PER_VERTEX)
        positions = np.ascontiguousarray(v[:, 5:8] * self.size, dtype='f')
        normals = np.ascontiguousarray(v[:, 2:5], dtype='f')
        texcoords = np.ascontiguousarray(v[:, 0:2], dtype='f')
        return positions, normals, texcoords

    #: Fields the baked instance mesh is built from, so the cache is dropped
    #: when one of them moves.  Named here rather than inline so a test can ask
    #: what the mesh depends on instead of restating it.
    instanceGPU_depend_fields = ('size', 'lid')

    def instanceGPU(self, mode):
        """Cached separate-VBO mesh-GPU (position/normal/texcoord) for instancing."""
        from OpenGLContext.passes.instancing import build_mesh_gpu
        arrays = self._instanceArrays()
        if arrays is None:
            return None
        positions, normals, texcoords = arrays
        return build_mesh_gpu(
            mode, self, positions=positions, normals=normals,
            texcoords=texcoords, indices=None, cache_key='instance_gpu',
            depend_fields=self.instanceGPU_depend_fields)

    def _apply_draw_state(self, mode):
        """Cull backfaces for the instanced draw, as the single-draw path does.

        The tessellated mesh carries reversed interior faces coincident with the
        shell; culling backfaces keeps the exterior clean and shows the interior
        only through the mouth. The pass culls by default, but an earlier
        instanced group (a double-sided PBR mesh) may have disabled it, so the
        state is asked for explicitly rather than assumed.
        """
        from OpenGLContext.passes.instancing import set_cull_state
        glCullFace(GL_BACK)
        set_cull_state(mode, True, GL_CCW)

    # -- render dispatch ---------------------------------------------------
    def render(self, visible=1, lit=1, textured=1, transparent=0, mode=None):
        """Render the Teapot.

        Uses the NURBS-tessellated mesh (distance-LOD selected).  The legacy
        GLUT endpoint is used only when useGlut is set, GLUT is available, and we
        are not in shader mode (GLUT's fixed-function teapot cannot render in a
        core profile).
        """
        shader_mode = mode is not None and getattr(mode, 'shader_mode', False)

        if self.useGlut and HAS_GLUT_TEAPOT and not shader_mode:
            self._render_glut()
            return

        level = self._lod_level(mode)
        if not self._ensure_tessellated(level):
            # Tessellation unavailable (e.g. no GLU / no current context yet).
            if HAS_GLUT_TEAPOT and not shader_mode:
                self._render_glut()
            else:
                log.warning("Cannot render teapot: NURBS tessellation unavailable")
            return

        if shader_mode:
            self._render_shader(mode, level)
        else:
            self._render_legacy(level)

    def _render_glut(self):
        """Explicit legacy GLUT-based rendering (useGlut comparison option)."""
        glFrontFace(GL_CW)
        try:
            if not self.solid:
                glutWireTeapot(self.size)
            else:
                glutSolidTeapot(self.size)
        finally:
            glFrontFace(GL_CCW)

    # -- legacy fixed-function path ----------------------------------------
    def _render_legacy(self, level):
        """Fixed-function rendering of the interleaved N3F_V3F arrays."""
        base_array, lid_array = self._arrays[level]
        glPushAttrib(GL_ENABLE_BIT | GL_POLYGON_BIT)
        # Exterior faces are CCW/outward; interior faces are the reversed copies.
        # Cull backfaces so each surface point shows its exterior from outside and
        # its interior (through the mouth) from inside, with no coincident-face
        # z-fighting.
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)
        glFrontFace(GL_CCW)
        if not self.solid:
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        try:
            if self.size != 1.0:
                glPushMatrix()
                glScalef(self.size, self.size, self.size)
            try:
                glEnableClientState(GL_VERTEX_ARRAY)
                glEnableClientState(GL_NORMAL_ARRAY)
                try:
                    self._draw_legacy_array(base_array)
                    if self.lid:
                        self._draw_legacy_array(lid_array)
                finally:
                    glDisableClientState(GL_VERTEX_ARRAY)
                    glDisableClientState(GL_NORMAL_ARRAY)
            finally:
                if self.size != 1.0:
                    glPopMatrix()
        finally:
            glPopAttrib()

    @staticmethod
    def _draw_legacy_array(array):
        from OpenGLContext.scenegraph.teapot_nurbs import FLOATS_PER_VERTEX
        if array is None or len(array) == 0:
            return
        glInterleavedArrays(GL_T2F_N3F_V3F, 0, array)
        glDrawArrays(GL_TRIANGLES, 0, len(array) // FLOATS_PER_VERTEX)

    # -- shader / core-profile path ----------------------------------------
    @classmethod
    def _initialize_buffers(cls, level):
        """Build VAOs/VBOs for the tessellated arrays of ``level`` (shader path)."""
        entry = cls._buffers.get(level)
        if entry is not None:
            return entry['base_vao'] is not None
        if not cls._ensure_tessellated(level):
            return False
        base_array, lid_array = cls._arrays[level]
        try:
            from OpenGLContext.scenegraph.teapot_nurbs import (
                FLOATS_PER_VERTEX, compute_tangents,
            )
            stride = FLOATS_PER_VERTEX * 4

            def make(array):
                count = len(array) // FLOATS_PER_VERTEX
                if count == 0:
                    return None, None, 0
                vao = glGenVertexArrays(1)
                glBindVertexArray(vao)
                buf = glGenBuffers(1)
                glBindBuffer(GL_ARRAY_BUFFER, buf)
                glBufferData(GL_ARRAY_BUFFER, array.nbytes, array, GL_STATIC_DRAW)
                # Interleaved T2F_N3F_V3F: texcoord@0, normal@8, position@20 bytes.
                glEnableVertexAttribArray(LOC_TEXCOORD)
                glVertexAttribPointer(LOC_TEXCOORD, 2, GL_FLOAT, GL_FALSE, stride, None)
                glEnableVertexAttribArray(LOC_NORMAL)
                glVertexAttribPointer(LOC_NORMAL, 3, GL_FLOAT, GL_FALSE, stride,
                                      ctypes.c_void_p(8))
                glEnableVertexAttribArray(LOC_POSITION)
                glVertexAttribPointer(LOC_POSITION, 3, GL_FLOAT, GL_FALSE, stride,
                                      ctypes.c_void_p(20))
                # Tangents in their own VBO, for PBR normal/bump mapping; the lit
                # shader does not declare the input and ignores it.
                tangents = compute_tangents(array)
                tbuf = glGenBuffers(1)
                glBindBuffer(GL_ARRAY_BUFFER, tbuf)
                glBufferData(GL_ARRAY_BUFFER, tangents.nbytes, tangents, GL_STATIC_DRAW)
                glEnableVertexAttribArray(LOC_TANGENT)
                glVertexAttribPointer(LOC_TANGENT, 4, GL_FLOAT, GL_FALSE, 0, None)
                glBindVertexArray(0)
                return vao, buf, count

            base_vao, base_vbo, base_count = make(base_array)
            lid_vao, lid_vbo, lid_count = make(lid_array)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            cls._buffers[level] = {
                'base_vao': base_vao, 'base_vbo': base_vbo, 'base_count': base_count,
                'lid_vao': lid_vao, 'lid_vbo': lid_vbo, 'lid_count': lid_count,
            }
            log.debug("Teapot buffers (level %d) initialized: %d base, %d lid vertices",
                      level, base_count, lid_count)
            return base_vao is not None
        except Exception as e:
            log.error("Failed to initialize teapot buffers (level %d): %s", level, e)
            cls._buffers[level] = {'base_vao': None, 'base_count': 0,
                                   'lid_vao': None, 'lid_count': 0}
            return False

    def _render_shader(self, mode, level):
        """Shader-based rendering using the tessellated mesh for ``level``."""
        if not self._initialize_buffers(level):
            log.warning("Cannot render teapot: buffers not initialized")
            return

        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None or shader_program.program is None:
            log.warning("Cannot render teapot: no shader program")
            return

        bufs = self._buffers[level]

        def draw():
            cull_was_enabled = glIsEnabled(GL_CULL_FACE)
            # Interior faces are the reversed copies of the shell; cull backfaces
            # so exterior shows from outside and interior through the mouth,
            # without coincident-face z-fighting.
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)
            glFrontFace(GL_CCW)
            if not self.solid:
                glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            self._draw_shader_array(bufs['base_vao'], bufs['base_count'])
            if self.lid:
                self._draw_shader_array(bufs['lid_vao'], bufs['lid_count'])
            if not self.solid:
                glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            if not cull_was_enabled:
                glDisable(GL_CULL_FACE)

        self._with_scaled_matrix(mode, shader_program, draw)

    def _with_scaled_matrix(self, mode, shader_program, draw):
        """Run ``draw`` with ``size`` folded into the modelview, then restore it.

        ``size`` matches glutSolidTeapot's scale argument and is applied here
        rather than baked into the mesh, so every ``size`` shares one cached
        tessellation.  Extracted so the (formerly duplicated) scale block lives
        in one place.
        """
        if self.size == 1.0:
            draw()
            return
        base_mv = mode.matrix.copy()
        scale = np.array([
            [self.size, 0, 0, 0],
            [0, self.size, 0, 0],
            [0, 0, self.size, 0],
            [0, 0, 0, 1],
        ], dtype=np.float32)
        shader_program.set_matrices(np.dot(base_mv, scale), mode.projection)
        try:
            draw()
        finally:
            shader_program.set_matrices(base_mv, mode.projection)

    @staticmethod
    def _draw_shader_array(vao, count):
        if vao is None or count == 0:
            return
        glBindVertexArray(vao)
        glDrawArrays(GL_TRIANGLES, 0, count)
        glBindVertexArray(0)

    # -- bounding volume ---------------------------------------------------
    @classmethod
    def _mesh_aabb(cls):
        """(min, max) corner of the tessellated unit teapot, or None.

        Computed from the level-0 N3F_V3F vertex arrays already in memory rather
        than eyeballed extents that risk frustum-culling the visible teapot.
        Returns None when tessellation is unavailable.
        """
        if not cls._ensure_tessellated(0):
            return None
        base_array, lid_array = cls._arrays[0]
        chunks = []
        from OpenGLContext.scenegraph.teapot_nurbs import FLOATS_PER_VERTEX
        for arr in (base_array, lid_array):
            if arr is None:
                continue
            # T2F_N3F_V3F -> position is the last 3 of each 8-float vertex.
            v = np.asarray(arr, dtype='f').reshape(-1, FLOATS_PER_VERTEX)[:, 5:8]
            if len(v):
                chunks.append(v)
        if not chunks:
            return None
        allv = np.concatenate(chunks, axis=0)
        return allv.min(axis=0), allv.max(axis=0)

    def boundingVolume(self, mode):
        """Create a bounding-volume object for this node."""
        from OpenGLContext.scenegraph import boundingvolume
        current = boundingvolume.getCachedVolume(self)
        if current:
            return current
        aabb = self._mesh_aabb()
        if aabb is not None:
            lo, hi = aabb
            box = boundingvolume.AABoundingBox(
                size=[float((hi[i] - lo[i]) * self.size) for i in range(3)],
                center=[float((hi[i] + lo[i]) * 0.5 * self.size) for i in range(3)],
            )
        else:
            # Fallback when tessellation isn't available yet: eyeballed extents of
            # the unit y-up teapot (spout+handle span ~x3.0, ~y1.6, ~z2.0), scaled.
            box = boundingvolume.AABoundingBox(
                size=[self.size * 3.0, self.size * 1.6, self.size * 2.0])
        return boundingvolume.cacheVolume(self, box, ((self, 'size'),))
