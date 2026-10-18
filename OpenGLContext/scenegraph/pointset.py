"""Geometry type for "point-arrays" w/ colour support"""

from OpenGL.GL import *
from OpenGL.GL import glDeleteVertexArrays
from OpenGL.arrays import vbo
from typing import Any
from vrml import field
from vrml.vrml97 import basenodes
from OpenGLContext.scenegraph import coordinatebounded, coordinates, drawproperties
from OpenGLContext.scenegraph.vertexsemantics import (
    LOC_POSITION, LOC_COLOR,
)
from OpenGLContext.arrays import array
from OpenGL.extensions import alternate, available
from OpenGL.GL.ARB.point_parameters import *
from OpenGL.GL.EXT.point_parameters import *
import ctypes
import numpy as np
import logging


#: ``vbo.VBO`` types as ``None``: PyOpenGL binds the name late, to whichever of
#: the accelerated and the pure-Python class it loaded.
VBO: Any = vbo.VBO


log = logging.getLogger(__name__)

glPointParameterf = alternate(
    glPointParameterf, glPointParameterfARB, glPointParameterfEXT
)
glPointParameterfv = alternate(
    glPointParameterfv, glPointParameterfvARB, glPointParameterfEXT
)
RESET_ATTENUATION = array([1, 0, 0], "f")

# MRT draw-buffer index carrying the packed object id (mirrors _flat.py).
_OBJECT_ID_ATTACHMENT = 1


class PointSet(coordinatebounded.CoordinateBounded, basenodes.PointSet):
    """VRML97-style Point-Set object

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PointSet

    `size`, `minSize`, `maxSize` and `attenuation` are the engine's own: the
    point size in pixels, its bounds, and the distance attenuation
    coefficients (constant, linear, quadratic) the fixed-function pipeline
    applies to it. In the shader paths the points are `size` pixels across
    (at least `minSize`); an appearance's X3D `PointProperties` replaces
    them there (:func:`~OpenGLContext.scenegraph.drawproperties.point_size`).
    """

    size = field.newField('size', 'SFFloat', 1, 1.0)
    minSize = field.newField('minSize', 'SFFloat', 1, 0.0)
    maxSize = field.newField('maxSize', 'SFFloat', 1, 1.0)
    attenuation = field.newField('attenuation', 'SFVec3f', 1, [1.0, 0.0, 0.0])

    def pointSize(self, properties: Any = None) -> drawproperties.PointSize:
        """The size points are drawn at: the appearance's `PointProperties`
        where it has one, else this node's own `size`, at least `minSize`"""
        if properties:
            return drawproperties.point_size(properties)
        size = float(max(self.size, self.minSize))
        return drawproperties.PointSize(size, size, size)

    def pointColours(self) -> Any:
        """One colour per point, `(n, 3)`, or None

        The first of the Color node's values where it holds as many as there
        are points or more (X3D 19775-1, 11.4.11); None where there is no
        Color node, or it holds fewer, which is reported once.
        """
        if not self.hasPointColours():
            return None
        count = len(coordinates.points(self.coord))
        return np.asarray(self.color.color, dtype='f').reshape(-1, 3)[:count]

    def hasPointColours(self) -> bool:
        """Whether each point has a colour (:meth:`pointColours`), without
        building the array"""
        if not self.color or not self.coord:
            return False
        count, colours = len(coordinates.points(self.coord)), len(self.color.color)
        if colours < count:
            if not self.__dict__.get('_fewerReported'):
                self.__dict__['_fewerReported'] = True
                log.warning('PointSet %s has fewer colours (%s) than points (%s); '
                            'drawn in its appearance\'s colour', self, colours, count)
            return False
        return True

    def render(
        self,
        visible: int = 1,  # can skip normals and textures if not
        lit: int = 1,  # can skip normals if not
        textured: int = 1,  # can skip textureCoordinates if not
        transparent: int = 0,  # need to sort triangle geometry...
        mode: Any = None,  # the renderpass object
    ) -> int:
        """Render the point-set, requires coord attribute be present

        Each point is drawn in its colour (:meth:`pointColours`) where there
        are colours enough, otherwise in the current colour.
        """
        if not self.coord:
            # can't render nothing
            return 1
        points = np.asarray(coordinates.points(self.coord), dtype='f')
        if not len(points):
            # can't render nothing
            return 1

        # Check for shader mode
        if getattr(mode, 'shader_mode', False):
            return self._render_shader(mode, points, textured=textured)

        # Legacy rendering path. The fields are MFVec3f and MFColor, so both
        # arrays are three components wide.
        glVertexPointer(3, GL_FLOAT, 0, points)
        glEnableClientState(GL_VERTEX_ARRAY)

        colors = self.pointColours() if visible else None
        if colors is not None:
            glColorMaterial(GL_FRONT_AND_BACK, GL_DIFFUSE)
            glEnable(GL_COLOR_MATERIAL)
            glColorPointer(3, GL_FLOAT, 0, colors)
            glEnableClientState(GL_COLOR_ARRAY)
        glDisable(GL_LIGHTING)
        if textured:
            # TODO: check for version/extension first!
            # point-sprites instead of regular points...
            glEnable(GL_POINT_SPRITE)
            glTexEnvi(GL_POINT_SPRITE, GL_COORD_REPLACE, GL_TRUE)
        glPointSize(self.size)
        if available(glPointParameterf):
            glPointParameterf(GL_POINT_SIZE_MIN, self.minSize)
            glPointParameterf(GL_POINT_SIZE_MAX, self.maxSize)
            glPointParameterfv(GL_POINT_DISTANCE_ATTENUATION, self.attenuation)
        glDrawArrays(GL_POINTS, 0, len(points))
        glDisableClientState(GL_VERTEX_ARRAY)
        glDisable(GL_COLOR_MATERIAL)
        if textured:
            glDisable(GL_POINT_SPRITE)
        if available(glPointParameterf):
            glPointParameterf(GL_POINT_SIZE_MIN, 0.0)
            glPointParameterf(GL_POINT_SIZE_MAX, 1.0)
            glPointParameterfv(GL_POINT_DISTANCE_ATTENUATION, RESET_ATTENUATION)
        glPointSize(1.0)
        glDisableClientState(GL_COLOR_ARRAY)
        return 1

    def _render_shader(self, mode: Any, points: Any,
                       textured: int = 1) -> int:
        """Render using shader pipeline."""
        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return 1

        # Use point shader for colored points, unlit for simple points
        has_colors = self.hasPointColours()

        if has_colors:
            shader_program.use_point()
            program = shader_program.point_program
        else:
            shader_program.use(lit=False)
            program = shader_program.unlit_program
            # The colour the Shape's material asks for; white where the caller
            # gave the points neither per-vertex colours nor a material.
            shader_program.set_solid_color(
                getattr(mode, '_solid_color', None) or (1.0, 1.0, 1.0, 1.0), fogged=True)

        shader_program.set_matrices(mode.matrix, mode.projection, program=program)

        size = self.pointSize(getattr(mode, '_pointProperties', None))
        shader_program.set_point_size(size, program)

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

        # Cached VAO+VBO: the point buffer is built once and re-uploaded (into
        # the same buffer) only when coord/color change, then every warm frame is
        # just bind-VAO + draw. One VAO serves whichever program the pass chose,
        # since both read the semantics at the same locations; a data change
        # drops it so the layout is rebound against the re-uploaded buffer.
        vbo_obj, stride = self._point_buffer(mode, points, has_colors)
        gpu = self._point_gpu
        vao = gpu['vao']
        if vao is None:
            vao = glGenVertexArrays(1)
            glBindVertexArray(vao)
            vbo_obj.bind()
            glEnableVertexAttribArray(LOC_POSITION)
            glVertexAttribPointer(LOC_POSITION, 3, GL_FLOAT, GL_FALSE, stride, None)
            if has_colors:
                glEnableVertexAttribArray(LOC_COLOR)
                glVertexAttribPointer(LOC_COLOR, 3, GL_FLOAT, GL_FALSE, stride,
                                      ctypes.c_void_p(12))
            vbo_obj.unbind()
            glBindVertexArray(0)
            gpu['vao'] = vao

        glEnable(GL_PROGRAM_POINT_SIZE)

        # Blend for particle effects; the transparent phase has set the blending
        # it draws with, which this leaves as it is
        pass_blends = bool(getattr(mode, 'transparent', False))
        if not pass_blends:
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        # Keep the packed object-id MRT attachment out of the blend (finding
        # 4.6): blending it uses the id's own alpha byte as the factor, which
        # is 0 for most ids, so the id would be multiplied to zero and the
        # point would be unpickable. Best-effort; drivers without indexed
        # blend enables (or a single-attachment target) simply skip it. The
        # transparent phase has done this for the targets it draws into.
        if not pass_blends:
            try:
                glDisablei(GL_BLEND, _OBJECT_ID_ATTACHMENT)
            except Exception:
                pass

        glBindVertexArray(vao)
        try:
            glDrawArrays(GL_POINTS, 0, len(points))
        finally:
            glBindVertexArray(0)

        if not pass_blends:
            glDisable(GL_BLEND)
        glDisable(GL_PROGRAM_POINT_SIZE)

        # Restore the lit shader
        shader_program.use(lit=True)
        return 1

    def _point_buffer(self, mode: Any, points: Any,
                      has_colors: bool) -> tuple[Any, int]:
        """Return (vbo, stride) for the point data, re-uploading only on change.

        A persistent VBO is kept on the node; when coord/color change (tracked
        through mode.cache field dependencies) the interleaved data is rebuilt and
        re-uploaded into the same buffer via set_array, and the per-program VAOs
        are cleared so the layout is rebound.
        """
        gpu = getattr(self, '_point_gpu', None)
        clean = mode.cache.getData(self, key='point_clean')
        if gpu is not None and clean is not None and gpu['has_colors'] == has_colors:
            return gpu['vbo'], gpu['stride']

        points_array = np.asarray(points, dtype='f')
        if has_colors:
            interleaved = np.empty((len(points), 6), dtype='f')
            interleaved[:, 0:3] = points_array
            interleaved[:, 3:6] = self.pointColours()
            interleaved = np.ascontiguousarray(interleaved)
            stride = 6 * 4
        else:
            interleaved = np.ascontiguousarray(points_array)
            stride = 0

        if gpu is None:
            gpu = self._point_gpu = {
                'vbo': VBO(interleaved, usage='GL_DYNAMIC_DRAW'),
                'vao': None,
                'stride': stride,
                'has_colors': has_colors,
            }
        else:
            gpu['vbo'].set_array(interleaved)
            gpu['stride'] = stride
            gpu['has_colors'] = has_colors
            if gpu['vao'] is not None:
                # The layout may have changed with the data; rebind it against
                # the new upload rather than drawing through stale pointers.
                glDeleteVertexArrays(1, np.array([gpu['vao']], dtype=np.uint32))
                gpu['vao'] = None
        # Force the (re-)upload now so the buffer is populated before draw.
        gpu['vbo'].bind()
        gpu['vbo'].unbind()

        holder = mode.cache.holder(self, True, key='point_clean')
        holder.depend(self, 'coord')
        for source, name in coordinates.fields(self.coord):
            holder.depend(source, name)
        if self.color:
            holder.depend(self.color, 'color')
        return gpu['vbo'], gpu['stride']

    def boundingVolume(self, mode: Any = None) -> Any:
        """Create a bounding-volume object for this node"""
        from OpenGLContext.scenegraph import boundingvolume

        return boundingvolume.volumeFromCoordinate(
            self.coord,
        )
