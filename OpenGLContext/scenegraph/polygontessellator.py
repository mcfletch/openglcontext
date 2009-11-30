"""Class for tessellating polygons using GLU"""
from OpenGL.GL import *
from OpenGL.GLU import *
try:
    # older PyOpenGL version didn't have the name properly registered, check
    gluTessVertex
except NameError:
    from OpenGL import GLU
    gluTessVertex = GLU._gluTessVertex
from OpenGLContext import utilities
from OpenGLContext import arrays
import traceback


class PolygonTessellator(object):
    """Simplified polygon tessellation for IndexedFaceSets & Fonts

    OpenGLContext 2.0.0b1 has substantially improved this
    class, allowing for multiple-contour tessellation, as
    well as providing mechanisms for returning results
    other than triangle-sets.

    XXX Should have threading lock around tessContours,
        as any single tessellator is non-thread-safe.
    XXX Should be doing a GLU version check for this entire
        module, and degrading to earlier API version if
        necessary.
    """
    def __init__( self, windingRule = GLU_TESS_WINDING_ODD, ccw=True ):
        """Initialise the PolygonTessellator"""
        self.reset()
        self.ccw = ccw
        self.windingRule = windingRule
    _controller = None
    @property
    def controller( self ):
        if not self._controller:
            self._controller = controller = gluNewTess()
            gluTessCallback( controller, GLU_TESS_COMBINE, self.combine )
            gluTessCallback( controller, GLU_TESS_VERTEX, self.vertex )
            gluTessCallback( controller, GLU_TESS_BEGIN, self.begin )
            gluTessCallback( controller, GLU_TESS_END, self.end )
            gluTessProperty( controller, GLU_TESS_WINDING_RULE, self.windingRule )
        return self._controller
    def reset( self, forceTriangles = 1 ):
        """Reset the tessellator for a new polygon"""
        self.result = []
        self.current = []
        self.type = None
        self.forceTriangles = forceTriangles


    def tessContours( self, contours, forceTriangles=1, normal=None ):
        """Tessellate polygon defined by (multiple) contours

        Occasionally will create new vertices as a blending
        of the given vertex objects.

        contours -- list of list of vertices, with each set
            defining a closed contour within the polygon.

        forceTriangles -- if true (default), returns a set of
            GL_TRIANGLES-compatible vertex specifications as
            a list-of-vertex-objects [ Vertex(), Vertex(), ...]

            if false, returns [(type, vertices), ...] where
            type is the type to be specified for glBegin, and
            vertices are a list-of-vertex-objects, with the
            types being any of GL_TRIANGLES, GL_TRIANGLE_STRIP,
            or GL_TRIANGLE_FAN and the vertices being compatible
            with the given type.
            
        normal -- if specified, calls gluTessNormal with the value,
            restores to default after the tessellation is complete

        return value -- see note on forceTriangles
        """
        self.reset( forceTriangles = forceTriangles )
        controller = self.controller
        gluTessBeginPolygon( controller, self )
        if normal:
            gluTessNormal( self.controller, *normal )
        try:
            try:
                for contour in contours:
                    gluTessBeginContour( controller )
                    try:
                        for vertex in contour:
                            gluTessVertex(
                                controller,
                                vertex.point, 
                                vertex
                            )
                    finally:
                        gluTessEndContour( controller )
            finally:
                gluTessEndPolygon ( controller )
        finally:
            if normal:
                gluTessNormal( self.controller, 0.,0.,0. )
        return self.result
        
    def tessellate(self, vertices, forceTriangles=1 ):
        """Tessellate polygon defined by vertices

        Less general form of tessContours, takes a single
        contour and returns the tessellation result for that
        contour.  See tessContours for semantics of
        forceTriangles and the results (which are dependent
        on the value of forceTriangles).
        """
        return self.tessContours( [vertices], forceTriangles=forceTriangles)
        
    def begin( self,  dataType, polygonData=None ):
        """Begin a new tessellation sequence (GLU Tess callback)"""
        assert not self.current, """Tessellation reached begin callback with a non-null current vertex-set, this should never happen: %s"""%(self.current,)
        self.type = dataType
    def vertex( self, vertex, polygonData=None):
        """Register a vertex for the current shape (GLU Tess callback)"""
        #self.current.append( vertex )
        self.current.append( vertex )
    def combine( self, newPosition, vertices, weights, polygonData=None ):
        """Blend vertices with weights to create new vertex object (GLU Tess callback)"""
        from OpenGLContext.scenegraph.vertex import Vertex
        attributes = {
            "point": newPosition,
        }
        vertices = [ v for v in vertices if v is not None]
        weights = [float(w) for w in weights]
        for attribute in ('color', 'textureCoordinate', 'normal'):
            accumulator = None
            # value is between each of the current value if present...
            for vertex, weight in zip(vertices, weights):
                if hasattr( vertex , attribute ) :
                    value = getattr( vertex, attribute)
                    if value is not None:
                        value = arrays.asarray(value,'f') * weight
                        if accumulator is None:
                            accumulator = value
                        else:
                            accumulator += value
            attributes[ attribute ] = accumulator
        # normals don't add quite the same way as everything else,
        # have to use vector addition...
        if attributes["normal"] is not None:
            combined = [
                (v.normal,w)
                for (v,w) in zip(vertices,weights)
                if getattr(v, 'normal',None) is not None
            ]
            if len(combined):
                if len(combined) == 1:
                    attributes['normal'] = combined[0][0]
                else:
                    attributes['normal'] = utilities.combineNormals(
                        [item[0] for item in combined],
                        [item[1] for item in combined],
                    )
        newVertex = apply( Vertex, (), attributes)
        return newVertex
    def end( self, *args, **namedargs ):
        """Record the end of a tessellated shape (GLU Tess callback)

        This method implements the "forceTriangles" semantics by
        unravelling GL_TRIANGLE_FAN or GL_TRIANGLE_STRIP if
        forceTriangles is true.  It also manages the creating of
        the final self.result data-set.
        """
        if self.forceTriangles:
            # convert exotic types to those easily handled by
            # array functions for larger geometry-sets
            if self.type == GL_TRIANGLE_FAN:
                first = self.current[0]
                last = self.current[1]
                result = []
                for next in self.current[2:]:
                    result.append( first )
                    result.append( last )
                    result.append( next )
                    last = next
                if not self.ccw:
                    result.reverse()
                self.result.extend( result )
            elif self.type == GL_TRIANGLE_STRIP:
                result = []
                for marker in range(len(self.current)-2):
                    if marker %2: # odd
                        result.append( self.current[marker] )
                        result.append( self.current[marker+1] )
                        result.append( self.current[marker+2] )
                    else:
                        result.append( self.current[marker+1] )
                        result.append( self.current[marker] )
                        result.append( self.current[marker+2] )
                if not self.ccw:
                    result.reverse()
                self.result.extend( result )
            # what about Quads or Polygons? can they occur?
            elif self.type == GL_TRIANGLES:
                if not self.ccw:
                    self.current.reverse()
                self.result.extend( self.current )
            else:
                raise ValueError(
                    """An unsupported geometry type %s was encountered in the polygon tessellator end callback"""%(
                        self.type,
                    )
                )
        else:
            if not self.ccw:
                self.current.reverse()
            self.result.append( (self.type, self.current))
        self.current = []