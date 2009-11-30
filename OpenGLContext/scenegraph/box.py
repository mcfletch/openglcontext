"""Box node for use in geometry attribute of Shapes"""
from vrml import cache
from OpenGLContext.arrays import array
from OpenGL.arrays import vbo
from OpenGL.GL import *
from vrml.vrml97 import basenodes
from vrml import protofunctions

class Box( basenodes.Box ):
    """Simple Box object of given size centered about local origin

    The Box geometry node can be used in the geometry
    field of a Shape node to be displayed. Use Transform
    nodes to position the box within the world.

    The Box includes texture coordinates and normals.

    Attributes of note within the Box object:

        size -- x,y,z tuple giving the size of the box
        listID -- used internally to store the display list
            used to display the box during rendering

    Reference:
        http://www.web3d.org/technicalinfo/specifications/vrml97/part1/nodesRef.html#Box
    """
    def compile( self, mode=None ):
        """Compile the box as a display-list"""
        if vbo.get_implementation():
            vb = vbo.VBO( array( list(yieldVertices( self.size )), 'f'))
            def draw( textured=True,lit=True ):
                vb.bind()
                try:
                    glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
                    try:
                        glEnableClientState( GL_VERTEX_ARRAY )
                        if lit:
                            glEnableClientState( GL_NORMAL_ARRAY )
                            glNormalPointer( GL_FLOAT, 32, vb+8 )
                        if textured:
                            glEnableClientState( GL_TEXTURE_COORD_ARRAY )
                            glTexCoordPointer( 2, GL_FLOAT, 32, vb )
                        glVertexPointer( 3, GL_FLOAT, 32, vb+20 )
                        glDrawArrays( GL_TRIANGLES, 0, 36 )
                    finally:
                        glPopClientAttrib()
                finally:
                    vb.unbind()
        else:
            vb = array( list(yieldVertices( self.size )), 'f')
            def draw(textured=True,lit=True):
                glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
                try:
                    glInterleavedArrays( GL_T2F_N3F_V3F, 0, vb )
                    glDrawArrays( GL_TRIANGLES, 0, 36 )
                finally:
                    glPopClientAttrib()
        holder = mode.cache.holder(self, draw)
        holder.depend( self, protofunctions.getField(self, 'size') )
        return draw
    def render (
            self,
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0, # XXX should sort triangle geometry...
            mode = None, # the renderpass object for which we compile
        ):
        """Render the Box (build and) call the display list"""
        # do we have a cached array-geometry?
        vb = mode.cache.getData(self)
        if not vb:
            vb = self.compile( mode=mode )
        if vb:
            vb(textured=textured,lit=lit)
        return 1
    def boundingVolume( self, mode ):
        """Create a bounding-volume object for this node"""
        from OpenGLContext.scenegraph import boundingvolume
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                size = self.size,
            ),
            ( (self, 'size'), ),
        )

def yieldVertices(size):
    x,y,z = size 
    x,y,z = x/2.0,y/2.0,z/2.0
    normal = ( 0.0, 0.0, 1.0)
    yield (0.0, 0.0)+ normal + (-x,-y,z);
    yield (1.0, 0.0)+ normal + (x,-y,z);
    yield (1.0, 1.0)+ normal + (x,y,z);
    yield (0.0, 0.0)+ normal + (-x,-y,z);
    yield (1.0, 1.0)+ normal + (x,y,z);
    yield (0.0, 1.0)+ normal + (-x,y,z);

    normal = ( 0.0, 0.0,-1.0);
    yield (1.0, 0.0)+ normal + (-x,-y,-z);
    yield (1.0, 1.0)+ normal + (-x,y,-z);
    yield (0.0, 1.0)+ normal + (x,y,-z);
    yield (1.0, 0.0)+ normal + (-x,-y,-z);
    yield (0.0, 1.0)+ normal + (x,y,-z);
    yield (0.0, 0.0)+ normal + (x,-y,-z);

    normal = ( 0.0, 1.0, 0.0)
    yield (0.0, 1.0)+ normal + (-x,y,-z);
    yield (0.0, 0.0)+ normal + (-x,y,z);
    yield (1.0, 0.0)+ normal + (x,y,z);
    yield (0.0, 1.0)+ normal + (-x,y,-z);
    yield (1.0, 0.0)+ normal + (x,y,z);
    yield (1.0, 1.0)+ normal + (x,y,-z);

    normal = ( 0.0,-1.0, 0.0)
    yield (1.0, 1.0)+ normal + (-x,-y,-z);
    yield (0.0, 1.0)+ normal + (x,-y,-z);
    yield (0.0, 0.0)+ normal + (x,-y,z);
    yield (1.0, 1.0)+ normal + (-x,-y,-z);
    yield (0.0, 0.0)+ normal + (x,-y,z);
    yield (1.0, 0.0)+ normal + (-x,-y,z);

    normal = ( 1.0, 0.0, 0.0)
    yield (1.0, 0.0)+ normal + (x,-y,-z);
    yield (1.0, 1.0)+ normal + (x,y,-z);
    yield (0.0, 1.0)+ normal + (x,y,z);
    yield (1.0, 0.0)+ normal + (x,-y,-z);
    yield (0.0, 1.0)+ normal + (x,y,z);
    yield (0.0, 0.0)+ normal + (x,-y,z);

    normal = (-1.0, 0.0, 0.0)
    yield (0.0, 0.0)+ normal + (-x,-y,-z);
    yield (1.0, 0.0)+ normal + (-x,-y,z);
    yield (1.0, 1.0)+ normal + (-x,y,z);
    yield (0.0, 0.0)+ normal + (-x,-y,-z);
    yield (1.0, 1.0)+ normal + (-x,y,z);
    yield (0.0, 1.0)+ normal + (-x,y,-z);
