"""Teapot node for use in geometry attribute of Shapes"""
from vrml import cache
from OpenGLContext.arrays import array
from OpenGL.arrays import vbo
from OpenGL.GL import *
from OpenGL.GLUT import glutSolidTeapot, glutWireTeapot
from vrml.vrml97 import nodetypes
from vrml import node, field, fieldtypes

class Teapot( nodetypes.Geometry, node.Node ):
    """Simple Teapot geometry (glutSolidTeapot)
    
    Note: this teapot is *not* optimized with display-lists,
    the raw glutSolidTeapot/glutWireTeapot calls are used 
    for each frame!
    """
    PROTO = 'Teapot'
    size = field.newField( 'size','SFFloat',1,1.0 )
    solid = field.newField( 'solid','SFBool',1,True)
    def render (
            self,
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0, # XXX should sort triangle geometry...
            mode = None, # the renderpass object for which we compile
        ):
        """Render the Teapot"""
        glFrontFace(GL_CW)
        try:
            if not self.solid:
                glutWireTeapot( self.size )
            else:
                glutSolidTeapot( self.size )
        finally:
            glFrontFace(GL_CCW)

    def boundingVolume( self, mode ):
        """Create a bounding-volume object for this node"""
        from OpenGLContext.scenegraph import boundingvolume
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                # This vastly overestimates the size!
                size = [self.size*2,self.size*2,self.size*2],
            ),
            ( (self, 'size'), ),
        )