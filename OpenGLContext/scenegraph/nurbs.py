"""Nurbs-rendering nodes based on VRML97 Nurbs extension

NurbsSurface is a geometry object, drop it
into a shape to see the objects in a scene.

Note: at the moment, we cannot provide the object space
extension, due to what appears to be a bug in the PyOpenGL
library, so the code for that extension is short-circuit.
"""
from vrml.vrml97 import nurbs, nodetypes
from vrml import node, field, fieldtypes
from OpenGL.GLU import *
from OpenGL.GL import *
from OpenGL.GLU.EXT.object_space_tess import *
import logging 
log = logging.getLogger( __name__ )
from OpenGLContext import arrays

object_space_tess = None

def initialise( context=None ):
    """Initialise the NURBs extensions for a context"""
    global object_space_tess
    if object_space_tess is None:
        object_space_tess = gluInitObjectSpaceTessEXT()
    return bool( object_space_tess )

class Polyline2D( nurbs.Polyline2D ):
    """Simple polyline in 2D

    Basically this just calls gluPwlCurve
    """
    def render( self, nurbObject ):
        """Render to the given nurbs object"""
        gluPwlCurve(
            nurbObject,
            self.point,
            GLU_MAP1_TRIM_2
        )
class NurbsCurve2D( nurbs.NurbsCurve2D ):
    """Nurbs curve in 2D

    Basically this just calls gluNurbsCurve
    """
    def render( self, nurbObject ):
        """Render to the given nurbs object"""
        gluNurbsCurve(
            nurbObject,
            self.knot,
            self.controlPoint,
            GLU_MAP1_TRIM_2
        )

class Contour2D( nurbs.Contour2D ):
    """A 2D contour (collection of joined segments)

    children -- a set of polylines and/or curves which are
        joined to form the trimming contour

    Normally used to trim a Nurbs surface...
    """
    def trim( self, nurbObject ):
        """Render the contour as a trim of the current surface"""
        gluBeginTrim( nurbObject )
        try:
            for child in self.children:
                child.render( nurbObject )
        finally:
            gluEndTrim( nurbObject )

def defaultSampling( ):
    """Get a default sampling node"""
    if initialise():
        return NurbsToleranceSample(
            method = "object",
            parametric = 1,
            tolerance = 5
        )
    else:
        return NurbsToleranceSample(
            method = "screen",
            parametric = 1,
            tolerance = 5
        )
        

class _SurfaceRenderer( object ):
    """Abstract class providing surface-rendering framework

    attributes
        geometryType -- string specifying the geometry type
            "polygon", "patch", "edge"
        sampling -- NurbsSampling instance specifying a
            particular sampling methodology
    """
    geometryType = field.newField( 'geometryType', 'SFString', 1, "polygon") # 
    sampling = field.newField( 'sampling', 'SFNode', 1, defaultSampling)
    def render (
            self,
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0, # need to sort triangle geometry...
            mode = None, # the renderpass object
        ):
        """Render the surface, with all the attendant error checking"""
        if lit:
            glEnable( GL_AUTO_NORMAL )
            glEnable( GL_NORMALIZE )
        try:
            nurbObject = gluNewNurbsRenderer()
            try:
                gluBeginSurface( nurbObject );
                # do tessellation configuration here
                try:
                    self.renderProperties( nurbObject )
                    if self.renderSurface( nurbObject ):
                        # no point rendering the trimming
                        # if there is no surface
                        self.renderTrims( nurbObject )
                finally:
                    gluEndSurface( nurbObject );
            finally:
                gluDeleteNurbsRenderer( nurbObject )
        finally:
            if lit:
                glDisable( GL_AUTO_NORMAL )
                glDisable( GL_NORMALIZE )
            
    def renderProperties( self, nurbObject ):
        """Render any properties (such as tessellation)"""
        if self.geometryType == 'edge':
            mode = GLU_OUTLINE_PATCH
        elif self.geometryType == 'patch':
            mode = GLU_OUTLINE_PATCH
        elif self.geometryType == 'polygon':
            mode = GLU_FILL
        else:
            log.warn( """%s declares geometryType of %s -> ignoring""", self, repr( self.geometryType ))
            self.geometryType = 'polygon'
            mode = GLU_FILL
        gluNurbsProperty( nurbObject, GLU_DISPLAY_MODE, mode )
        self.sampling.properties( nurbObject )
    def renderSurface( self, nurbObject ):
        """Render the surface (gluBeginSurface has been called)"""
        return 1
    def renderTrims( self, nurbObject ):
        """Render any trims for the surface"""


class NurbsSurface( _SurfaceRenderer, nurbs.NurbsSurface ):
    """Surface geometry implemented with gluNurbsSurface
    Notes:
        uOrder/vOrder -- is not currently used, as PyOpenGL
            calculates the order from the difference
            between the knot and control point arrays
        weight -- is not currently used, this is just
            not-yet-implemented, it's quite feasible
            to support it
        uTessellation/vTessellation -- not currently used
        color -- if present, is applied to the knot array
            one for one using another call to gluNurbsSurface
    """
    def renderSurface( self, nurbObject ):
        """Render this surface"""
        ## XXX need to add weights
        # do tessellation configuration here
        controlPoint = arrays.reshape(
            self.controlPoint,
            (self.vDimension, self.uDimension, 3)
        )
        if self.ccw:
            glFrontFace(  GL_CCW )
        else:
            glFrontFace(  GL_CW )
        if self.solid:
            glEnable( GL_CULL_FACE )
        else:
            glDisable( GL_CULL_FACE )
        try:
            vKnot = self.vKnot.astype( 'f' )
            uKnot = self.uKnot.astype( 'f' )
            if len(self.color):
                glEnable( GL_COLOR_MATERIAL )
                color = arrays.zeros(
                    (len(self.controlPoint),4),
                    'f',
                )
                color[:,:3] = self.color.astype( 'f' )
                color = arrays.reshape(
                    color,
                    (self.vDimension, self.uDimension, 4),
                )
                gluNurbsSurface(
                    nurbObject,
                    vKnot,
                    uKnot,
                    color,
                    GL_MAP2_COLOR_4
                )
            gluNurbsSurface(
                nurbObject,
                vKnot,
                uKnot,
                controlPoint,
                GL_MAP2_VERTEX_3,
            )
        finally:
            glEnable( GL_CULL_FACE )
            glFrontFace( GL_CCW )
        return 1
            
class TrimmedSurface( _SurfaceRenderer, nurbs.TrimmedSurface ):
    """Trimmed surface geometry

    The TrimmedSurface is just a binding of
    a surface to a set of trimming contours.  There
    is nothing particularly complex done by the
    trimmed surface, it simply defers to the surface
    and the trimming contours.
    """
    def renderProperties( self, nurbObject ):
        """Render any properties (such as tessellation)"""
        self.surface.renderProperties( nurbObject )
    def renderSurface( self, nurbObject ):
        """Render this surface"""
        if self.surface:
            self.surface.renderSurface( nurbObject )
            return 1
        return 0
    def renderTrims( self, nurbObject ):
        """Render any trims for the surface"""
        for trim in self.trimmingContour:
            trim.trim( nurbObject )

class NurbsCurve( nurbs.NurbsCurve ):
    """A 3D nurbs curve (a curvy line in 3D space)

    Notes:
        order -- is not currently used, as PyOpenGL
            calculates the order from the difference
            between the knot and control point arrays
        weight -- is not currently used, this is just
            not-yet-implemented, it's quite feasible
            to support it
        tessellation -- not currently used
    """
    def render (
            self,
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0, # need to sort triangle geometry...
            mode = None, # the renderpass object
        ):
        """Render the curve as a geometry node"""
        if not len(self.knot) and not len(self.controlPoint):
            return 0
        nurbObject = gluNewNurbsRenderer()
        try:
            gluBeginSurface( nurbObject );
            # do tessellation configuration here
            try:
                #self.renderProperties( nurbObject )
                if len(self.color):
                    color = arrays.zeros((len(self.color),4),'d')
                    color[:,:3] = self.color
                    gluNurbsCurve(
                        nurbObject,
                        self.knot,
                        color,
                        GL_MAP1_COLOR_4
                    )
                if len(self.weight):
                    points = arrays.zeros( Numeric.shape(self.controlPoint)[:-1]+(4,), 'd')
                    points[:,:3] = self.controlPoint
                    points[:,3]  = self.weight
                    type = GL_MAP1_VERTEX_4
                else:
                    points = self.controlPoint
                    type = GL_MAP1_VERTEX_3
                gluNurbsCurve(
                    nurbObject,
                    self.knot,
                    points,
                    type
                )
            finally:
                gluEndSurface( nurbObject );
        finally:
            gluDeleteNurbsRenderer( nurbObject )

    def degree( self ):
        """Return degree of a nurbs-curve object"""
        return len(self.knot)-len(self.controlPoint)+1
    def uniform( self ):
        """Check that curve is "uniform"

        * all items in knots are increasing
        * starts with degree items the same
        * ends with degree items the same
        * all 
        """
        deg = self.degree( )
        last = self.knot[0]
        for item in self.knot[1:deg]:
            if item != last:
                return 0, "Doesn't start with degree (%s) equal knots, has %s"%(deg, self.knot[:deg])
        last = self.knot[-1]
        for item in self.knot[-deg:-1]:
            if item != last:
                return 0, "Doesn't end with degree (%s) equal knots, has %s"%(deg,self.knot[-deg:])
        if len(self.knot[deg:-deg]):
            last = self.knot[deg-1]
            lastCount = deg
            for item in self.knot[deg:-(deg-1)]:
                if item <= last:
                    return 0, "Knot %s is less than previous knot %s"%(item, last)
                last = item
        return 1, "Uniform"

    def allIncreasing( self ):
        """Check that all items in knots are increasing"""
        if not len(self.knot):
            return 1, "No knots defined"
        for i in range(len(self.knot)):
            t = self.knot[i:i+2]
            if len(t) == 2:
                if t[0] > t[1]:
                    return 0, "Knot %s (%s) is less than knot %s (%s)"%(
                        i+1,t[1], i, t[0],
                    )
        return 1, "All increasing"

    
class NurbsSampling( node.Node ):
    """A node-type specifying NURBs sampling method and parameters"""

class NurbsToleranceSample( NurbsSampling ):
    """Path-length tolerance sampling

    Can be either screen-space or object space,
        method = "screen" -> tolerance in pixels
        method = "object" -> tolerance in object-space coordinates
    and either parametric or not
        if true, tolerance is parametric tolerance (e.g. 0.5)
    """
    method = field.newField( "method", "SFString", 1, "screen") # "screen"/"object"
    parametric = field.newField( "parametric", "SFBool", 1, 0)
    tolerance = field.newField( "tolerance", "SFFloat", 1, 50.0)
    def properties( self, nurbObject ):
        """Configure this sampling type"""
        ### get the appropriate sampling method...
        methods = (
            GLU_PATH_LENGTH, 
            GLU_PARAMETRIC_ERROR
        )
        if self.method == 'object':
            if not initialise():
                # do regular (non-extension) screen sampling...
                log.warn( """%s declares 'object' sampling method, extension: object_space_tess not available -> ignoring""", self)
                self.method = 'screen'
            else:
                methods = (
                    GLU_OBJECT_PATH_LENGTH_EXT,
                    GLU_OBJECT_PARAMETRIC_ERROR_EXT
                )
        elif self.method != 'screen':
            log.warn( """%s declares %s sampling method, unknown type -> ignoring""", self, repr( self.method))
        method = methods[ self.parametric ]

        gluNurbsProperty( nurbObject, GLU_SAMPLING_METHOD, method )
        if self.parametric:
            gluNurbsProperty( 
                nurbObject, GLU_PARAMETRIC_TOLERANCE, self.tolerance 
            )
        else:
            gluNurbsProperty( 
                nurbObject, GLU_SAMPLING_TOLERANCE, self.tolerance 
            )

class NurbsDomainDistanceSample( NurbsSampling ):
    """Domain-distance parametric u and v coordinate sampling
    """
    uStep = field.newField( "uStep", "SFFloat", 1, 100.0)
    vStep = field.newField( "vStep", "SFFloat", 1, 100.0)
    def properties( self, nurbObject ):
        """Configure this sampling type"""
        gluNurbsProperty( nurbObject, GLU_SAMPLING_METHOD, GLU_DOMAIN_DISTANCE )
        gluNurbsProperty( nurbObject, GLU_U_STEP, self.uStep)
        gluNurbsProperty( nurbObject, GLU_V_STEP, self.vStep)
