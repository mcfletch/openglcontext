"""Vertex-array-based geometry node for faces, lines and points"""
from OpenGL.GL import *
from OpenGLContext.arrays import *
import polygonsort
from OpenGLContext import triangleutilities
from OpenGL.arrays import vbo
import logging
log = logging.getLogger( __name__ )

try:
    contiguous
except NameError:
    def contiguous( source, typecode=None ):
        """Force source to be a contiguous array"""
        if isinstance( source, ArrayType):
            if not hasattr(source, 'iscontiguous' ):
                # XXX apparently numpy arrays are always contiguous???
                return source
            if source.iscontiguous() and (typecode is None or typecode==typeCode(source)):
                return source
            else:
                return array(source,typecode or typeCode(source))
        elif typecode:
            return array( source, typecode )
        else:
            return array( source )

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
        vertexArray,# array of vertex coordinates to draw
        colorArray= None, # optional array of vertex colors
        normalArray= None, # optional array of normals
        textureCoordinateArray= None, # optional array of texture coordinates
        objectType= GL_TRIANGLES, # type of primitive, see glDrawArrays, allowed are:
            #GL_POINTS, GL_LINE_STRIP, GL_LINE_LOOP, GL_LINES,
            #GL_TRIANGLE_STRIP, GL_TRIANGLE_FAN,	GL_TRIANGLES, GL_QUAD_STRIP,
            #GL_QUADS, and GL_POLYGON 
        startIndex = 0, # the index from which to draw, see glDrawArrays
        count = -1, # by default, render the whole array (len(vertexArray)), see glDrawArrays
        ccw = 1, # determines winding direction
        solid = 1, # whether backspace culling may be enabled
    ):
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
                vertexArray = contiguous( vertexArray )
            if colorArray  is not None and len(colorArray):
                colorArray = contiguous( colorArray )
            if normalArray is not None and len(normalArray):
                normalArray = contiguous( normalArray )
            if textureCoordinateArray is not None and len(textureCoordinateArray):
                textureCoordinateArray = contiguous( textureCoordinateArray )
        if vbo.get_implementation():
            log.debug( "VBO implementation available" )
            if vertexArray is not None and len(vertexArray):
                vertexArray = vbo.VBO( vertexArray )
            if colorArray is not None and len(colorArray):
                colorArray = vbo.VBO( colorArray )
            if normalArray is not None and len(normalArray):
                normalArray = vbo.VBO( normalArray )
            if textureCoordinateArray is not None and len(textureCoordinateArray):
                textureCoordinateArray = vbo.VBO( textureCoordinateArray )
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
    def callBound( self, function, array ):
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
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0, # need to sort triangle geometry...
            mode = None, # the renderpass object for which we compile
        ):
        """Render the ArrayGeometry object

        called by IndexedFaceSet.render to do the actual
        rendering of the node.
        """
        if not len(self.vertices):
            return 1 # we are already finished
        vboAvailable = bool(vbo.get_implementation())
        glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
        glPushAttrib(GL_ALL_ATTRIB_BITS)
        try:
            glEnableClientState( GL_VERTEX_ARRAY )
            self.callBound( glVertexPointerf, self.vertices)
            if visible and self.colours is not None:
                # make the color field alter the diffuse color, should instead be aware of current material/lighting...
                glColorMaterial( GL_FRONT_AND_BACK, GL_DIFFUSE)
                glEnable( GL_COLOR_MATERIAL )
                glEnableClientState( GL_COLOR_ARRAY )
                self.callBound( glColorPointerf, self.colours)
#			else:
#				glDisableClientState( GL_COLOR_ARRAY )
            if lit and self.normals is not None:
                glEnableClientState( GL_NORMAL_ARRAY )
                self.callBound( glNormalPointerf, self.normals)
                glEnable(GL_NORMALIZE); # should do this explicitly eventually
            else:
                glDisable( GL_LIGHTING )
#				glDisableClientState( GL_NORMAL_ARRAY )
                
            if visible and textured and self.textures is not None:
                glEnableClientState( GL_TEXTURE_COORD_ARRAY )
                self.callBound( glTexCoordPointerf, self.textures )
#			else:
#				glDisableClientState( GL_TEXTURE_COORD_ARRAY )
            glFrontFace( self.ccw)
            if self.solid:# and not transparent:
                glEnable( GL_CULL_FACE )
            else:
                glDisable( GL_CULL_FACE )
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
    def draw( self ):
        """Does the actual rendering after the arrays are set up

        At the moment, is a simple call to glDrawArrays
        """
#		log.debug( 'Drawing array geometry: %s, %s', self.arguments, len(self.vertices) )
        glDrawArrays( *self.arguments )
#		log.debug( 'Finished array geometry' )
    def drawTransparent( self, mode ):
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
        glDrawElementsui(
            objectType,
            indices
        )
        
