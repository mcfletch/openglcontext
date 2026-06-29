"""Teapot node for use in geometry attribute of Shapes

The Utah Teapot (a.k.a. the Newell teapot) is the standard reference object
of computer graphics, modelled by Martin Newell in 1975 at the University of
Utah.  See https://graphics.cs.utah.edu/teapot/ for its history.

Three rendering backends are available, selected automatically in order:

1. a glut-free path that tessellates the 32 Bezier patches of the Newell
   dataset into a vertex array via the GLU NURBS tessellators (works in both
   the legacy and the shader/core pipelines) -- the default,
2. a pre-generated static triangle mesh
   (:mod:`OpenGLContext.scenegraph.teapot_data`), used when GLU NURBS
   tessellation is unavailable, and
3. GLUT's ``glutSolidTeapot`` endpoint, used as a last resort or, via the
   ``useGlut`` field, on request for comparison.
"""
from OpenGL.GL import *
from vrml.vrml97 import nodetypes
from vrml import node, field
import numpy as np
import ctypes
import logging

log = logging.getLogger(__name__)

# GLUT teapot functions for the legacy comparison path.
try:
    from OpenGL.GLUT import glutSolidTeapot, glutWireTeapot
    HAS_GLUT_TEAPOT = True
except ImportError:
    HAS_GLUT_TEAPOT = False
    log.debug("GLUT teapot not available, using NURBS-tessellated mesh")


class Teapot(nodetypes.Geometry, node.Node):
    """Utah Teapot geometry node.

    By default the geometry is generated from the Newell teapot's Bezier
    control points by tessellating each patch with the GLU NURBS tessellators
    (see :mod:`OpenGLContext.scenegraph.teapot_nurbs`); tessellation happens
    once, lazily, on the first render within a GL context.  If that is
    unavailable the node falls back to a pre-generated static mesh, and then
    to GLUT.

    Attributes:
        size: Scale factor for the teapot (default 1.0).  Matches the sizing
            of ``glutSolidTeapot(size)``.
        solid: If True, render filled polygons; if False, render wireframe.
        lid: If True (default), render the teapot lid; if False, omit the
            entire lid (the eight lid patches).  Only the NURBS backend can
            omit the lid; the fallbacks always render the whole teapot.
        useGlut: If True, render with the legacy ``glutSolidTeapot`` endpoint
            (when GLUT is available and not in shader mode), kept for
            comparison.  Default False: use the NURBS-tessellated mesh.
    """
    PROTO = 'Teapot'
    size = field.newField('size', 'SFFloat', 1, 1.0)
    solid = field.newField('solid', 'SFBool', 1, True)
    lid = field.newField('lid', 'SFBool', 1, True)
    useGlut = field.newField('useGlut', 'SFBool', 1, False)

    # Tessellated N3F_V3F arrays, shared across instances (context-independent).
    _base_array = None
    _lid_array = None
    _tessellated = False

    # Shader-path GL resources (assume a single shared GL context, as the
    # original implementation did).
    _base_vao = None
    _base_vbo = None
    _base_count = 0
    _lid_vao = None
    _lid_vbo = None
    _lid_count = 0
    _buffers_initialized = False

    # Pre-generated embedded mesh fallback (T2F_N3F_V3F + indices).
    _pg_array = None
    _pg_indices = None
    _pg_loaded = False
    _pg_vao = None
    _pg_vbo = None
    _pg_ebo = None
    _pg_index_count = 0
    _pg_buffers_initialized = False

    @classmethod
    def _ensure_tessellated(cls):
        """Tessellate the Bezier patches into vertex arrays once."""
        if cls._tessellated:
            return cls._base_array is not None
        try:
            from OpenGLContext.scenegraph.teapot_nurbs import tessellate_teapot
            cls._base_array, cls._lid_array = tessellate_teapot()
            cls._tessellated = True
            return True
        except Exception as e:
            log.error("Failed to tessellate teapot: %s", e)
            cls._tessellated = True
            cls._base_array = None
            return False

    def render(
            self,
            visible=1,
            lit=1,
            textured=1,
            transparent=0,
            mode=None,
    ):
        """Render the Teapot.

        Uses the NURBS-tessellated mesh by default.  The legacy GLUT endpoint
        is used only when useGlut is set, GLUT is available, and we are not in
        shader mode (GLUT's fixed-function teapot cannot render in a core
        profile).
        """
        shader_mode = mode is not None and getattr(mode, 'shader_mode', False)

        # Explicit GLUT override (for comparison) wins when usable.  GLUT's
        # fixed-function teapot cannot render in a core profile.
        if self.useGlut and HAS_GLUT_TEAPOT and not shader_mode:
            self._render_glut()
            return

        # Default chain: NURBS, then the pre-generated mesh, then GLUT.
        if self._render_nurbs(mode):
            return
        if self._render_pregenerated(mode):
            return
        if HAS_GLUT_TEAPOT and not shader_mode:
            self._render_glut()
            return
        log.warning("Cannot render teapot: no rendering backend available")

    def _render_glut(self):
        """Legacy GLUT-based rendering (kept for comparison)."""
        glFrontFace(GL_CW)
        try:
            if not self.solid:
                glutWireTeapot(self.size)
            else:
                glutSolidTeapot(self.size)
        finally:
            glFrontFace(GL_CCW)

    def _render_nurbs(self, mode):
        """Render the NURBS-tessellated mesh.

        Returns True if the NURBS backend handled rendering, False if it is
        unavailable (so the caller can fall back to another backend).
        """
        if not self._ensure_tessellated():
            return False

        if mode is not None and getattr(mode, 'shader_mode', False):
            self._render_nurbs_shader(mode)
        else:
            self._render_nurbs_legacy()
        return True

    # -- legacy fixed-function path ----------------------------------------

    def _render_nurbs_legacy(self):
        """Fixed-function rendering of the interleaved N3F_V3F arrays."""
        glPushAttrib(GL_ENABLE_BIT | GL_POLYGON_BIT)
        glDisable(GL_CULL_FACE)
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
                    self._draw_legacy_array(self._base_array)
                    if self.lid:
                        self._draw_legacy_array(self._lid_array)
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
        glInterleavedArrays(GL_N3F_V3F, 0, array)
        glDrawArrays(GL_TRIANGLES, 0, len(array) // FLOATS_PER_VERTEX)

    # -- shader / core-profile path ----------------------------------------

    @classmethod
    def _initialize_buffers(cls):
        """Build VAOs/VBOs for the tessellated arrays (shader path)."""
        if cls._buffers_initialized:
            return cls._base_vao is not None
        if not cls._ensure_tessellated():
            return False
        try:
            from OpenGLContext.scenegraph.teapot_nurbs import FLOATS_PER_VERTEX
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
                # Interleaved N3F_V3F: normal at offset 0, position at offset 12.
                glEnableVertexAttribArray(1)
                glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, None)
                glEnableVertexAttribArray(2)
                glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
                glBindVertexArray(0)
                return vao, buf, count

            cls._base_vao, cls._base_vbo, cls._base_count = make(cls._base_array)
            cls._lid_vao, cls._lid_vbo, cls._lid_count = make(cls._lid_array)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            cls._buffers_initialized = True
            log.debug("Teapot buffers initialized: %d base, %d lid vertices",
                      cls._base_count, cls._lid_count)
            return cls._base_vao is not None
        except Exception as e:
            log.error("Failed to initialize teapot buffers: %s", e)
            cls._buffers_initialized = True
            return False

    def _render_nurbs_shader(self, mode):
        """Shader-based rendering using the tessellated mesh."""
        if not self._initialize_buffers():
            log.warning("Cannot render teapot: buffers not initialized")
            return

        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None or shader_program.program is None:
            log.warning("Cannot render teapot: no shader program")
            return

        scaled = self.size != 1.0
        if scaled:
            current_mv = mode.matrix.copy()
            scale_matrix = np.array([
                [self.size, 0, 0, 0],
                [0, self.size, 0, 0],
                [0, 0, self.size, 0],
                [0, 0, 0, 1],
            ], dtype=np.float32)
            shader_program.set_matrices(np.dot(current_mv, scale_matrix), mode.projection)

        cull_was_enabled = glIsEnabled(GL_CULL_FACE)
        glDisable(GL_CULL_FACE)
        if not self.solid:
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)

        self._draw_shader_array(self._base_vao, self._base_count)
        if self.lid:
            self._draw_shader_array(self._lid_vao, self._lid_count)

        if not self.solid:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        if cull_was_enabled:
            glEnable(GL_CULL_FACE)

        if scaled:
            shader_program.set_matrices(current_mv, mode.projection)

    @staticmethod
    def _draw_shader_array(vao, count):
        if vao is None or count == 0:
            return
        glBindVertexArray(vao)
        glDrawArrays(GL_TRIANGLES, 0, count)
        glBindVertexArray(0)

    # -- pre-generated embedded-mesh fallback ------------------------------
    #
    # A static T2F_N3F_V3F triangle mesh (see
    # OpenGLContext.scenegraph.teapot_data) used when GLU NURBS tessellation
    # is unavailable.  This is a single mesh, so the lid cannot be toggled.

    @classmethod
    def _ensure_pregenerated(cls):
        """Load the embedded mesh arrays once.  No GL context required."""
        if cls._pg_loaded:
            return cls._pg_array is not None
        try:
            from OpenGLContext.scenegraph.teapot_data import VERTEX_DATA, INDICES
            cls._pg_array = np.array(VERTEX_DATA, dtype=np.float32)
            cls._pg_indices = np.array(INDICES, dtype=np.uint32)
            cls._pg_loaded = True
            return True
        except Exception as e:
            log.error("Pre-generated teapot mesh unavailable: %s", e)
            cls._pg_loaded = True
            cls._pg_array = None
            return False

    def _render_pregenerated(self, mode):
        """Render the embedded mesh fallback.

        Returns True if it handled rendering, False if unavailable.
        """
        if not self._ensure_pregenerated():
            return False
        if mode is not None and getattr(mode, 'shader_mode', False):
            self._render_pregenerated_shader(mode)
        else:
            self._render_pregenerated_legacy()
        return True

    def _render_pregenerated_legacy(self):
        """Fixed-function rendering of the embedded T2F_N3F_V3F mesh."""
        glPushAttrib(GL_ENABLE_BIT | GL_POLYGON_BIT)
        glFrontFace(GL_CW)
        if not self.solid:
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        try:
            if self.size != 1.0:
                glPushMatrix()
                glScalef(self.size, self.size, self.size)
            try:
                glInterleavedArrays(GL_T2F_N3F_V3F, 0, self._pg_array)
                glDrawElements(
                    GL_TRIANGLES, len(self._pg_indices),
                    GL_UNSIGNED_INT, self._pg_indices,
                )
            finally:
                if self.size != 1.0:
                    glPopMatrix()
        finally:
            glFrontFace(GL_CCW)
            glPopAttrib()

    @classmethod
    def _initialize_pregenerated_buffers(cls):
        """Build VAO/VBO/EBO for the embedded mesh (shader path)."""
        if cls._pg_buffers_initialized:
            return cls._pg_vao is not None
        if not cls._ensure_pregenerated():
            return False
        try:
            stride = 8 * 4  # T2F_N3F_V3F
            cls._pg_index_count = len(cls._pg_indices)
            cls._pg_vao = glGenVertexArrays(1)
            glBindVertexArray(cls._pg_vao)
            cls._pg_vbo = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, cls._pg_vbo)
            glBufferData(GL_ARRAY_BUFFER, cls._pg_array.nbytes, cls._pg_array, GL_STATIC_DRAW)
            cls._pg_ebo = glGenBuffers(1)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, cls._pg_ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, cls._pg_indices.nbytes, cls._pg_indices, GL_STATIC_DRAW)
            # texcoord @0 (loc 0), normal @8 (loc 1), position @20 (loc 2)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, None)
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))
            glEnableVertexAttribArray(2)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(20))
            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)
            cls._pg_buffers_initialized = True
            return True
        except Exception as e:
            log.error("Failed to initialize pre-generated teapot buffers: %s", e)
            cls._pg_buffers_initialized = True
            return False

    def _render_pregenerated_shader(self, mode):
        """Shader-based rendering of the embedded mesh."""
        if not self._initialize_pregenerated_buffers():
            return
        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None or shader_program.program is None:
            log.warning("Cannot render teapot: no shader program")
            return

        scaled = self.size != 1.0
        if scaled:
            current_mv = mode.matrix.copy()
            scale_matrix = np.array([
                [self.size, 0, 0, 0],
                [0, self.size, 0, 0],
                [0, 0, self.size, 0],
                [0, 0, 0, 1],
            ], dtype=np.float32)
            shader_program.set_matrices(np.dot(current_mv, scale_matrix), mode.projection)

        glFrontFace(GL_CW)
        if not self.solid:
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        glBindVertexArray(self._pg_vao)
        glDrawElements(GL_TRIANGLES, self._pg_index_count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        if not self.solid:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        glFrontFace(GL_CCW)

        if scaled:
            shader_program.set_matrices(current_mv, mode.projection)

    def boundingVolume(self, mode):
        """Create a bounding-volume object for this node."""
        from OpenGLContext.scenegraph import boundingvolume
        current = boundingvolume.getCachedVolume(self)
        if current:
            return current
        # Extents of the unit (size=1.0) NURBS teapot, oriented y-up to match
        # glutSolidTeapot: width spans the spout and handle (~x 3.0), height
        # ~y 1.6, depth ~z 2.0.  Scaled by self.size.
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                size=[self.size * 3.0, self.size * 1.6, self.size * 2.0],
            ),
            ((self, 'size'),),
        )
