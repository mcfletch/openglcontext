#! /usr/bin/env python
'''Test glDrawArrays using string format for the arrays (draws flower)'''
from __future__ import print_function
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
import flower_geometry

class TestContext( BaseContext ):
    def OnInit( self ):
        """Initialisation"""
        print("""Should see flower pattern in gray over white background""")
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glVertexPointer(3, GL_DOUBLE, 0, flower_geometry.points_expanded.tobytes() );
        glNormalPointer(GL_FLOAT, 0, flower_geometry.normals_expanded.tobytes() )
        glEnableClientState(GL_VERTEX_ARRAY);
        glEnableClientState(GL_NORMAL_ARRAY);
        glDrawArrays(GL_TRIANGLES, 0, len(flower_geometry.points_expanded))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
