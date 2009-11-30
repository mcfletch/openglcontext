#! /usr/bin/env python
'''Test of the ATI_vertex_array_object extension

ATI_vertex_array_object creates a "server-side" storage
location for data to be used in array operations.  This
module serves to test the operation of the extension.

XXX There's a problem with the demo in that, after a few
    view rotations the second flower (the large one)
    disappears.  Not sure what's going on there.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string, sys
import flower_geometry

class TestContext( BaseContext):
    def OnInit( self ):
        """Initialisation"""
        print """Should see two flower patterns in gray over white background"""
        global vertex_array_object
        vertex_array_object = self.extensions.initExtension( "GL.ATI.vertex_array_object")
        if not vertex_array_object:
            print 'GL.ATI.vertex_array_object not supported!'
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        print vertex_array_object.__doc__
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        if mode.visible and not mode.transparent:

            # get our data in raw format...
            pointSource = flower_geometry.points_expanded.tostring()
            normalSource = flower_geometry.normals_expanded.tostring()
            
            # Create object buffers, initialising with our raw data
            buffer = vertex_array_object.glNewObjectBufferATI(
                len(pointSource),
                pointSource,
                vertex_array_object.GL_STATIC_ATI
            );
            size = vertex_array_object.glGetObjectBufferivATI(
                buffer, vertex_array_object.GL_OBJECT_BUFFER_SIZE_ATI,
            )
            print 'server-side size', size, 'original size', len(pointSource)
            buffer2 = vertex_array_object.glNewObjectBufferATI(
                len(normalSource),
                normalSource,
                vertex_array_object.GL_STATIC_ATI
            );
            buffer3 = vertex_array_object.glNewObjectBufferATI(
                len(pointSource)+4, # we're testing offsets...
                None, # initialize with no data...
                vertex_array_object.GL_STATIC_ATI
            );
            assert vertex_array_object.glIsObjectBufferATI( buffer ), buffer
            assert vertex_array_object.glIsObjectBufferATI( buffer2 ), buffer2
            assert vertex_array_object.glIsObjectBufferATI( buffer3 ), buffer3

            # Tell the system to use our buffers for the two array-types
            vertex_array_object.glArrayObjectATI(
                GL_VERTEX_ARRAY, 3, GL_DOUBLE,
                0,
                buffer,
                0
            );
            vertex_array_object.glArrayObjectATI(
                GL_NORMAL_ARRAY, 3, GL_DOUBLE,
                0,
                buffer2,
                0
            );

            # Enable
            glEnableClientState(GL_VERTEX_ARRAY);
            glEnableClientState(GL_NORMAL_ARRAY);

            # Draw
            glDrawArrays(GL_TRIANGLES, 0, len(flower_geometry.points_expanded));

            glTranslate( 2,0,0)

            temp = flower_geometry.points_expanded * (2,2,5)
##			print flower_geometry.points_expanded
            newPointSource = temp.tostring()

            vertex_array_object.glUpdateObjectBufferATI(
                buffer3, 4, # 4 is offset
                len(newPointSource),newPointSource,
                vertex_array_object.GL_DISCARD_ATI,
            )
            vertex_array_object.glArrayObjectATI(
                GL_VERTEX_ARRAY, 3, GL_DOUBLE,
                0,
                buffer3,
                4 # offset
            );
            glDrawArrays(GL_TRIANGLES, 0, len(temp));
            
            # Disable
            glDisableClientState(GL_VERTEX_ARRAY);
            glDisableClientState(GL_NORMAL_ARRAY);

            # get it rendered before we delete the buffers
            # normally this isn't necessary because we'd be keeping
            # the buffers until the geometry was deleted.
            glFlush() 
            # Free object buffers
            vertex_array_object.glDeleteObjectBufferATI(buffer)
            vertex_array_object.glDeleteObjectBufferATI(buffer2)

if __name__ == "__main__":
    TestContext.ContextMainLoop()