"""Teapot node for use in geometry attribute of Shapes

Provides both legacy GLUT-based rendering and modern shader-based rendering
using the embedded Utah Teapot mesh data.
"""
from vrml import cache
from OpenGLContext.arrays import array
from OpenGL.arrays import vbo
from OpenGL.GL import *
from vrml.vrml97 import nodetypes
from vrml import node, field, fieldtypes
import numpy as np
import ctypes
import logging

log = logging.getLogger(__name__)

# Try to import GLUT teapot functions for legacy rendering
try:
    from OpenGL.GLUT import glutSolidTeapot, glutWireTeapot
    HAS_GLUT_TEAPOT = True
except ImportError:
    HAS_GLUT_TEAPOT = False
    log.debug("GLUT teapot not available, using embedded mesh")


class Teapot(nodetypes.Geometry, node.Node):
    """Utah Teapot geometry node.

    Supports both legacy GLUT rendering (when available) and modern
    shader-based rendering using embedded mesh data from the classic
    Utah Teapot model.

    Attributes:
        size: Scale factor for the teapot (default 1.0)
        solid: If True, render filled polygons; if False, render wireframe
        forceEmbedded: If True, always use embedded mesh even when GLUT available
    """
    PROTO = 'Teapot'
    size = field.newField('size', 'SFFloat', 1, 1.0)
    solid = field.newField('solid', 'SFBool', 1, True)
    forceEmbedded = field.newField('forceEmbedded', 'SFBool', 1, False)

    # Cached GL resources (class-level, shared across instances)
    _vao = None
    _vbo = None
    _ebo = None
    _vertex_count = 0
    _index_count = 0
    _initialized = False

    @classmethod
    def _initialize_buffers(cls):
        """Initialize VAO/VBO/EBO with embedded teapot mesh data."""
        if cls._initialized:
            return True

        try:
            from OpenGLContext.scenegraph.teapot_data import VERTEX_DATA, INDICES

            # Convert to numpy arrays
            vertex_data = np.array(VERTEX_DATA, dtype=np.float32)
            index_data = np.array(INDICES, dtype=np.uint32)

            # T2F_N3F_V3F format: 8 floats per vertex
            cls._vertex_count = len(vertex_data) // 8
            cls._index_count = len(index_data)

            # Create VAO
            cls._vao = glGenVertexArrays(1)
            glBindVertexArray(cls._vao)

            # Create and populate VBO
            cls._vbo = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, cls._vbo)
            glBufferData(GL_ARRAY_BUFFER, vertex_data.nbytes, vertex_data, GL_STATIC_DRAW)

            # Create and populate EBO
            cls._ebo = glGenBuffers(1)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, cls._ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, index_data.nbytes, index_data, GL_STATIC_DRAW)

            # Set up vertex attributes for T2F_N3F_V3F format
            # Layout: texcoord (2 floats) + normal (3 floats) + position (3 floats) = 32 bytes
            stride = 8 * 4  # 8 floats * 4 bytes

            # Texture coordinate attribute (location 0 in our shaders)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, None)

            # Normal attribute (location 1 in our shaders)
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))

            # Position attribute (location 2 in our shaders)
            glEnableVertexAttribArray(2)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(20))

            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)

            cls._initialized = True
            log.debug("Teapot buffers initialized: %d vertices, %d indices",
                     cls._vertex_count, cls._index_count)
            return True

        except Exception as e:
            log.error("Failed to initialize teapot buffers: %s", e)
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

        Uses shader-based rendering when in shader mode or forceEmbedded is True,
        falls back to GLUT rendering in legacy mode (if available).
        """
        # Check if we should use embedded mesh
        use_embedded = (
            self.forceEmbedded or
            (mode is not None and getattr(mode, 'shader_mode', False)) or
            not HAS_GLUT_TEAPOT
        )

        if use_embedded:
            self._render_shader(mode)
        else:
            self._render_glut()

    def _render_glut(self):
        """Legacy GLUT-based rendering."""
        glFrontFace(GL_CW)
        try:
            if not self.solid:
                glutWireTeapot(self.size)
            else:
                glutSolidTeapot(self.size)
        finally:
            glFrontFace(GL_CCW)

    def _render_shader(self, mode):
        """Shader-based rendering using embedded mesh data."""
        if not self._initialize_buffers():
            log.warning("Cannot render teapot: buffers not initialized")
            return

        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None or shader_program.program is None:
            log.warning("Cannot render teapot: no shader program")
            return

        # Apply size scaling - update modelview matrix in shader
        if self.size != 1.0:
            current_mv = mode.matrix.copy()
            scale = self.size
            scale_matrix = np.array([
                [scale, 0, 0, 0],
                [0, scale, 0, 0],
                [0, 0, scale, 0],
                [0, 0, 0, 1],
            ], dtype=np.float32)
            scaled_mv = np.dot(current_mv, scale_matrix)
            shader_program.set_matrices(scaled_mv, mode.projection)

        # The GLUT teapot uses CW winding, match that for consistency
        glFrontFace(GL_CW)

        # Bind VAO and draw
        glBindVertexArray(self._vao)

        if self.solid:
            glDrawElements(GL_TRIANGLES, self._index_count, GL_UNSIGNED_INT, None)
        else:
            # Wireframe mode
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            glDrawElements(GL_TRIANGLES, self._index_count, GL_UNSIGNED_INT, None)
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

        glBindVertexArray(0)

        # Restore front face to default CCW
        glFrontFace(GL_CCW)

        # Restore original matrices if we modified them
        if self.size != 1.0:
            shader_program.set_matrices(current_mv, mode.projection)

    def boundingVolume(self, mode):
        """Create a bounding-volume object for this node."""
        from OpenGLContext.scenegraph import boundingvolume
        current = boundingvolume.getCachedVolume(self)
        if current:
            return current
        # The embedded mesh matches GLUT teapot dimensions (size=1.0):
        # X: -0.98 to 0.98 (width ~1.96)
        # Y: -0.77 to 0.77 (height ~1.54)
        # Z: -1.575 to 1.575 (depth ~3.15)
        # These are multiplied by self.size
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                size=[self.size * 2.0, self.size * 1.55, self.size * 3.15],
            ),
            ((self, 'size'),),
        )
