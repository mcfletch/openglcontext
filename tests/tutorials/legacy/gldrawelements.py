#! /usr/bin/env python
'''Test of the glDrawElements function (draws flower)'''
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
        glVertexPointerd( _flower_geometry.points )
        glEnableClientState(GL_VERTEX_ARRAY)
        glDrawElementsui(
            GL_TRIANGLES,
            _flower_geometry.indices
        )


if __name__ == "__main__":
    TestContext.ContextMainLoop()
