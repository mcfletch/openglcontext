#! /usr/bin/env python
'''Test of the glVertex function (draws flower)'''
from OpenGLContext.context import Context as BaseContext
from OpenGL.GL import *
import _flower_geometry

class TestContext( BaseContext ):
    profile = 'compatibility'   # draws with the fixed-function pipeline
    def OnInit( self ):
        """Initialisation"""
        print("""Should see flower pattern in gray over white background""")
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glBegin( GL_TRIANGLES )
        for index in _flower_geometry.indices:
            glVertex3dv( _flower_geometry.points[index] )
        glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
