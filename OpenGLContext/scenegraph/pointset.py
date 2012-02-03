"""Geometry type for "point-arrays" w/ colour support"""
from OpenGL.GL import *
from vrml.vrml97 import basenodes
from OpenGLContext.scenegraph import coordinatebounded
from OpenGLContext.arrays import array
from OpenGL.extensions import alternate
from OpenGL.GL.ARB.point_parameters import *
from OpenGL.GL.EXT.point_parameters import *
import logging
log = logging.getLogger( __name__ )

glPointParameterf = alternate( 
    glPointParameterf, glPointParameterfARB,glPointParameterfEXT 
)
glPointParameterfv = alternate( 
    glPointParameterfv, glPointParameterfvARB, glPointParameterfEXT 
)
RESET_ATTENUATION = array( [1,0,0],'f')

class PointSet(
    coordinatebounded.CoordinateBounded,
    basenodes.PointSet
):
    """VRML97-style Point-Set object

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PointSet
    """
    def render (
            self,
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0, # need to sort triangle geometry...
            mode = None, # the renderpass object
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
        glVertexPointerf(points)
        glEnableClientState( GL_VERTEX_ARRAY )

        if visible and self.color:
            colors = self.color.color
            if len(colors) != len(points):
                # egads, a content error
                if __debug__:
                    log.warn(
                        """PointSet %s has different number of point (%s) and color (%s) values""",
                        str(self), 
                        len(points), 
                        len(colors),
                    )
            else:
                glColorMaterial( GL_FRONT_AND_BACK, GL_DIFFUSE)
                glEnable( GL_COLOR_MATERIAL )
                glColorPointerf ( colors )
                glEnableClientState( GL_COLOR_ARRAY )
        glDisable( GL_LIGHTING )
        if textured:
            # TODO: check for version/extension first!
            # point-sprites instead of regular points...
            glEnable(GL_POINT_SPRITE);
            glTexEnvi(GL_POINT_SPRITE, GL_COORD_REPLACE, GL_TRUE)
        glPointSize( self.size )
        if glPointParameterf:
            glPointParameterf( GL_POINT_SIZE_MIN, self.minSize )
            glPointParameterf( GL_POINT_SIZE_MAX, self.maxSize )
            glPointParameterfv( GL_POINT_DISTANCE_ATTENUATION, self.attenuation )
        glDrawArrays( GL_POINTS, 0, len(points))
        glDisableClientState( GL_VERTEX_ARRAY )
        glDisable( GL_COLOR_MATERIAL )
        if textured:
            glDisable( GL_POINT_SPRITE )
        if glPointParameterf:
            glPointParameterf( GL_POINT_SIZE_MIN, 0.0 )
            glPointParameterf( GL_POINT_SIZE_MAX, 1.0 )
            glPointParameterfv( GL_POINT_DISTANCE_ATTENUATION, RESET_ATTENUATION )
        glPointSize( 1.0 )
        glDisableClientState( GL_COLOR_ARRAY )
        return 1
    def boundingVolume( self, mode=None ):
        """Create a bounding-volume object for this node"""
        from OpenGLContext.scenegraph import boundingvolume
        return boundingvolume.volumeFromCoordinate(
            self.coord,
        )
