"""Geometry type for "point-arrays" w/ colour support"""

from OpenGL.GL import *
from vrml.vrml97 import basenodes
from OpenGLContext.scenegraph import coordinatebounded
from OpenGLContext.arrays import array
from OpenGL.extensions import alternate
from OpenGL.GL.ARB.point_parameters import *
from OpenGL.GL.EXT.point_parameters import *
import logging

log = logging.getLogger(__name__)

glPointParameterf = alternate(
    glPointParameterf, glPointParameterfARB, glPointParameterfEXT
)
glPointParameterfv = alternate(
    glPointParameterfv, glPointParameterfvARB, glPointParameterfEXT
)
RESET_ATTENUATION = array([1, 0, 0], "f")


class PointSet(coordinatebounded.CoordinateBounded, basenodes.PointSet):
    """VRML97-style Point-Set object

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PointSet
    """

    def render(
        self,
        visible=1,  # can skip normals and textures if not
        lit=1,  # can skip normals if not
        textured=1,  # can skip textureCoordinates if not
        transparent=0,  # need to sort triangle geometry...
        mode=None,  # the renderpass object
    ):
        """Render the point-set, requires coord attribute be present

        if color is present (and has the same length as coord), will
        render using colors mapped 1:1, otherwise will use the current
        color.color
        """
        if not self.coord:
            # can't render nothing
            return 1
        points = self.coord.point
        if not len(points):
            # can't render nothing
            return 1

        # Check for shader mode
        if getattr(mode, 'shader_mode', False):
            return self._render_shader(mode, points, textured=textured)

        # Legacy rendering path
        glVertexPointerf(points)
        glEnableClientState(GL_VERTEX_ARRAY)

        if visible and self.color:
            colors = self.color.color
            if len(colors) != len(points):
                # egads, a content error
                if __debug__:
                    log.warning(
                        """PointSet %s has different number of point (%s) and color (%s) values""",
                        str(self),
                        len(points),
                        len(colors),
                    )
            else:
                glColorMaterial(GL_FRONT_AND_BACK, GL_DIFFUSE)
                glEnable(GL_COLOR_MATERIAL)
                glColorPointerf(colors)
                glEnableClientState(GL_COLOR_ARRAY)
        glDisable(GL_LIGHTING)
        if textured:
            # TODO: check for version/extension first!
            # point-sprites instead of regular points...
            glEnable(GL_POINT_SPRITE)
            glTexEnvi(GL_POINT_SPRITE, GL_COORD_REPLACE, GL_TRUE)
        glPointSize(self.size)
        if glPointParameterf:
            glPointParameterf(GL_POINT_SIZE_MIN, self.minSize)
            glPointParameterf(GL_POINT_SIZE_MAX, self.maxSize)
            glPointParameterfv(GL_POINT_DISTANCE_ATTENUATION, self.attenuation)
        glDrawArrays(GL_POINTS, 0, len(points))
        glDisableClientState(GL_VERTEX_ARRAY)
        glDisable(GL_COLOR_MATERIAL)
        if textured:
            glDisable(GL_POINT_SPRITE)
        if glPointParameterf:
            glPointParameterf(GL_POINT_SIZE_MIN, 0.0)
            glPointParameterf(GL_POINT_SIZE_MAX, 1.0)
            glPointParameterfv(GL_POINT_DISTANCE_ATTENUATION, RESET_ATTENUATION)
        glPointSize(1.0)
        glDisableClientState(GL_COLOR_ARRAY)
        return 1

    def _render_shader(self, mode, points, textured=False):
        """Render using shader pipeline."""
        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return 1

        # Use point shader for colored points, unlit for simple points
        has_colors = self.color and len(self.color.color) == len(points)

        if has_colors:
            shader_program.use_point()
            program = shader_program.point_program
        else:
            shader_program.use(lit=False)
            program = shader_program.unlit_program
            # Set default white color for unlit points
            shader_program.set_solid_color((1.0, 1.0, 1.0, 1.0))

        shader_program.set_matrices(mode.matrix, mode.projection, program=program)

        # Set point size uniform (for shader-controlled point sizes)
        point_size = max(self.size, self.minSize)
        point_size_loc = glGetUniformLocation(program, 'pointSize')
        if point_size_loc != -1:
            glUniform1f(point_size_loc, point_size)

        # Check if a texture is bound (from Shape/Appearance) for point sprites
        # The texture ID is stored in the mode by Shape._render_shader
        bound_texture = getattr(mode, '_bound_texture_id', None)
        has_texture_loc = glGetUniformLocation(program, 'hasTexture')
        if has_texture_loc != -1:
            if bound_texture and textured:
                glUniform1i(has_texture_loc, 1)
                # Bind the texture and set sampler uniform
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, bound_texture)
                tex_loc = glGetUniformLocation(program, 'pointTexture')
                if tex_loc != -1:
                    glUniform1i(tex_loc, 0)
            else:
                glUniform1i(has_texture_loc, 0)
                # Unbind any texture
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, 0)

        # Create VAO for core profile compatibility
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)

        buffer = None
        try:
            # Point shader uses fixed attribute locations:
            # layout(location = 0) in vec3 aPosition;
            # layout(location = 1) in vec3 aColor;
            pos_loc = 0
            color_loc = 1

            # Interleave position and color data into a single buffer
            # Format: [x,y,z,r,g,b, x,y,z,r,g,b, ...]
            import numpy as np
            points_array = np.asarray(points, dtype='f')

            if has_colors:
                colors_array = np.asarray(self.color.color, dtype='f')
                # Interleave: each vertex has 6 floats (3 pos + 3 color)
                interleaved = np.empty((len(points), 6), dtype='f')
                interleaved[:, 0:3] = points_array
                interleaved[:, 3:6] = colors_array
                # Ensure contiguous memory layout
                interleaved = np.ascontiguousarray(interleaved)
                stride = 6 * 4  # 6 floats * 4 bytes
            else:
                interleaved = np.ascontiguousarray(points_array)
                stride = 0

            buffer = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, buffer)
            glBufferData(GL_ARRAY_BUFFER, interleaved.nbytes, interleaved, GL_DYNAMIC_DRAW)

            # Set up position attribute
            glEnableVertexAttribArray(pos_loc)
            glVertexAttribPointer(pos_loc, 3, GL_FLOAT, GL_FALSE, stride, None)

            # Set up color attribute if we have per-vertex colors
            if has_colors:
                import ctypes
                glEnableVertexAttribArray(color_loc)
                glVertexAttribPointer(color_loc, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            else:
                color_loc = -1  # Mark as unused for cleanup

            # Set point size (both fixed-function and shader-controlled)
            glPointSize(point_size)
            # Enable shader-controlled point sizes (gl_PointSize in vertex shader)
            glEnable(GL_PROGRAM_POINT_SIZE)

            # Enable blending for particle effects
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            glDrawArrays(GL_POINTS, 0, len(points))

            glDisable(GL_BLEND)
            glDisable(GL_PROGRAM_POINT_SIZE)
            glPointSize(1.0)

            glDisableVertexAttribArray(pos_loc)
            if color_loc >= 0:
                glDisableVertexAttribArray(color_loc)

        finally:
            glBindVertexArray(0)
            glDeleteVertexArrays(1, [vao])
            if buffer:
                glDeleteBuffers(1, [buffer])

        # Restore the lit shader
        shader_program.use(lit=True)
        return 1

    def boundingVolume(self, mode=None):
        """Create a bounding-volume object for this node"""
        from OpenGLContext.scenegraph import boundingvolume

        return boundingvolume.volumeFromCoordinate(
            self.coord,
        )
