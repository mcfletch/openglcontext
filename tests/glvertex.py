#! /usr/bin/env python
'''Test of the glVertex function (draws flower)'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array
import flower_geometry

class TestContext( BaseContext ):
    def OnInit( self ):
        """Initialisation"""
        print """Should see flower pattern in gray over white background"""
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glBegin( GL_TRIANGLES )
        for index in flower_geometry.indices:
            glVertex3dv( flower_geometry.points[index] )
        glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()