#! /usr/bin/env python
'''Test of the glDrawElements function (draws square from string)'''
from __future__ import print_function
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array

points = array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]], 'f')
indices = array( range(len(points)), 'I')

class TestContext( BaseContext ):
    def OnInit( self ):
        """Initialisation"""
        print("""Should see a grey square over white background.
    This is drawn using the "base" or "string" version of
    glDrawElements, the version which mimics the underlying
    OpenGL call using a simple string as the data-source.
    """)
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glVertexPointer( 3, GL_FLOAT, 0, points.tobytes())
        glEnableClientState(GL_VERTEX_ARRAY);
        glDrawElementsui(
            GL_QUADS,
            indices
        )
 

if __name__ == "__main__":
    TestContext.ContextMainLoop()
