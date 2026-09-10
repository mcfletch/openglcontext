"""Vertex-array-based geometry node for faces, lines and points"""
from typing import Any

from OpenGL.GL import *
from ..arrays import *
from . import polygonsort
from .. import triangleutilities
from .winding import apply_winding_cull
from OpenGL.arrays import vbo
import logging


#: ``vbo.VBO`` types as ``None``: PyOpenGL binds the name late, to whichever of
#: the accelerated and the pure-Python class it loaded.
VBO: Any = vbo.VBO


log = logging.getLogger( __name__ )

FORCE_CONTIGUOUS = 1


class ArrayGeometry(object):
    """Vertex-array-based geometry node for faces, lines and points

    The ArrayGeometry class allows for rendering various
    types of geometry using the vertex-array extensions of
    OpenGL 1.1 and above.
    
    The ArrayGeometry is a non-node-object used by the
    IndexedFaceSet for rendering an array of triangle
    vertices.  Originally it also handled the PointSet
    and IndexedLineSet.  The ArrayGeometry object is
    cached using the cache module, and regenerated if
    the holding object changes field values or is
    deleted.
    """
    def __init__ (
        self,
        vertexArray: Any,# array of vertex coordinates to draw
        colorArray: Any = None, # optional array of vertex colors
        normalArray: Any = None, # optional array of normals
        textureCoordinateArray: Any = None, # optional array of texture coordinates
        objectType: int = GL_TRIANGLES, # type of primitive, see glDrawArrays, allowed are:
            #GL_POINTS, GL_LINE_STRIP, GL_LINE_LOOP, GL_LINES,
            #GL_TRIANGLE_STRIP, GL_TRIANGLE_FAN,	GL_TRIANGLES, GL_QUAD_STRIP,
            #GL_QUADS, and GL_POLYGON
        startIndex: int = 0, # the index from which to draw, see glDrawArrays
        count: int = -1, # by default, render the whole array (len(vertexArray)), see glDrawArrays
        ccw: int = 1, # determines winding direction
        solid: int = 1, # whether backspace culling may be enabled
    ) -> None:
        """Initialize the ArrayGeometry

        vertexArray -- array of vertex coordinates to draw
        colorArray = None -- optional array of vertex colors
        normalArray = None -- optional array of normals
        textureCoordinateArray = None -- optional array of
            texture coordinates
        objectType= GL_TRIANGLES -- type of primitive, see
            glDrawArrays.  Allowed values are:
                GL_POINTS, GL_LINE_STRIP, GL_LINE_LOOP, GL_LINES,
                GL_TRIANGLE_STRIP, GL_TRIANGLE_FAN,	GL_TRIANGLES,
                GL_QUAD_STRIP, GL_QUADS, and GL_POLYGON
            though few of those save points, lines and triangles
            have actually been tested.  Only triangles is currently
            used.
        startIndex = 0 -- the index from which to draw,
            see glDrawArrays
        count = -1 -- by default, render the whole array
            (len(vertexArray)), see glDrawArrays
        ccw = 1 -- determines winding direction
            see glFrontFace
        solid = 1 -- whether backspace culling should be enabled
            see glEnable( GL_CULL_FACE )
        """
        log.debug( 'New array geometry node' )
        if FORCE_CONTIGUOUS:
            if vertexArray is not None and len(vertexArray):
                vertexArray = ascontiguousarray( vertexArray )
            if colorArray  is not None and len(colorArray):
                colorArray = ascontiguousarray( colorArray )
            if normalArray is not None and len(normalArray):
                normalArray = ascontiguousarray( normalArray )
            if textureCoordinateArray is not None and len(textureCoordinateArray):
                textureCoordinateArray = ascontiguousarray( textureCoordinateArray )
        # How many components each vertex has in each array. Read from the
        # arrays while they are still arrays: the pointer calls below need it,
        # and a buffer object no longer carries the shape it was built from.
        self.componentCounts = tuple(
            (a.shape[-1] if a is not None and len(a) else 0)
            for a in (vertexArray, colorArray, normalArray, textureCoordinateArray)
        )
        if vbo.get_implementation():
            log.debug( "VBO implementation available" )
            if vertexArray is not None and len(vertexArray):
                vertexArray = VBO( vertexArray )
            if colorArray is not None and len(colorArray):
                colorArray = VBO( colorArray )
            if normalArray is not None and len(normalArray):
                normalArray = VBO( normalArray )
            if textureCoordinateArray is not None and len(textureCoordinateArray):
                textureCoordinateArray = VBO( textureCoordinateArray )
        if count < 0:
            count = len (vertexArray)
        self.vertices = vertexArray
        self.colours = colorArray
        self.normals = normalArray
        self.textures = textureCoordinateArray
        self.arguments = (objectType, startIndex,count)
        log.debug( '  array geometry: %s, %s', self.arguments, len(self.vertices) )
        if ccw:
            self.ccw = GL_CCW
        else:
            self.ccw = GL_CW
        self.solid = solid
    def callBound( self, function: Any, array: Any ) -> Any:
        """Call ``function(array)`` with the array bound if it is a buffer object"""
        if hasattr( array, 'bind' ):
            array.bind()
            try:
                return function(array)
            finally:
                array.unbind()
        else:
            return function(array)
    def render (
            self,
            visible: int = 1, # can skip normals and textures if not
            lit: int = 1, # can skip normals if not
            textured: int = 1, # can skip textureCoordinates if not
            transparent: int = 0, # need to sort triangle geometry...
            mode: Any = None, # the renderpass object for which we compile
        ) -> int:
        """Render the ArrayGeometry object

        called by IndexedFaceSet.render to do the actual
        rendering of the node.
        """
        if not len(self.vertices):
            return 1 # we are already finished

        # Check for shader mode
        if getattr(mode, 'shader_mode', False):
            return int(self._render_shader(mode))

        # Legacy rendering path
        # glNormalPointer takes no size: a normal is always three components.
        vertexSize, colourSize, _normalSize, textureSize = self.componentCounts
        glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
        glPushAttrib(GL_ALL_ATTRIB_BITS)
        try:
            glEnableClientState( GL_VERTEX_ARRAY )
            self.callBound(
                lambda a: glVertexPointer( vertexSize, GL_FLOAT, 0, a ),
                self.vertices,
            )
            if visible and self.colours is not None:
                # make the color field alter the diffuse color, should instead be aware of current material/lighting...
                glColorMaterial( GL_FRONT_AND_BACK, GL_DIFFUSE)
                glEnable( GL_COLOR_MATERIAL )
                glEnableClientState( GL_COLOR_ARRAY )
                self.callBound(
                    lambda a: glColorPointer( colourSize, GL_FLOAT, 0, a ),
                    self.colours,
                )
#			else:
#				glDisableClientState( GL_COLOR_ARRAY )
            if lit and self.normals is not None:
                glEnableClientState( GL_NORMAL_ARRAY )
                self.callBound(
                    lambda a: glNormalPointer( GL_FLOAT, 0, a ),
                    self.normals,
                )
            else:
                glDisable( GL_LIGHTING )
#				glDisableClientState( GL_NORMAL_ARRAY )

            if visible and textured and self.textures is not None:
                glEnableClientState( GL_TEXTURE_COORD_ARRAY )
                self.callBound(
                    lambda a: glTexCoordPointer( textureSize, GL_FLOAT, 0, a ),
                    self.textures,
                )
#			else:
#				glDisableClientState( GL_TEXTURE_COORD_ARRAY )
            apply_winding_cull( mode, self.ccw == GL_CCW, bool(self.solid) )
            # do the actual rendering
            if visible and transparent:
                self.drawTransparent( mode = mode )
            else:
                self.draw()
            # cleanup the environment
        finally:
            glPopAttrib()
            glPopClientAttrib()
        return 1

    def _render_shader(self, mode: Any) -> Any:
        """Render using shader pipeline with separate attribute arrays."""
        from OpenGLContext.scenegraph.geometryarrays import (
            GeometryArrays, render_geometry,
        )

        objectType, startIndex, count = self.arguments
        apply_winding_cull(mode, self.ccw == GL_CCW, bool(self.solid))

        return render_geometry(mode, GeometryArrays.separate(
            count=count,
            draw_mode=objectType,
            positions=self.vertices,
            normals=self.normals,
            texcoords=self.textures,
        ), owner=self, where='ArrayGeometry')
    def draw( self ) -> None:
        """Does the actual rendering after the arrays are set up

        At the moment, is a simple call to glDrawArrays
        """
#		log.debug( 'Drawing array geometry: %s, %s', self.arguments, len(self.vertices) )
        glDrawArrays( *self.arguments )
#		log.debug( 'Finished array geometry' )
    def drawTransparent( self, mode: Any ) -> None:
        """Same as draw, but called when a transparent render is required

        This uses triangleutilities and polygonsort to render
        the polygons in view-depth-sorted order (back to front).

        It does not provide for automatically tesselating
        intersecting transparent polygons, so there will
        be potential rendering artifacts.
        """
        if not hasattr( self, 'centers'):
            self.centers = triangleutilities.centers( self.vertices )
        indices = polygonsort.indices(
            polygonsort.distances(
                self.centers, 
                modelView = mode.getModelView(),
                projection = mode.getProjection(),
                viewport = mode.getViewport(),
            )
        ).astype( 'I' )
        objectType = self.arguments[0]
        assert objectType == GL_TRIANGLES, """Only triangles are sortable, a non-triangle mesh was told to be transparent!"""
        glDrawElements( objectType, indices.size, GL_UNSIGNED_INT, indices )

