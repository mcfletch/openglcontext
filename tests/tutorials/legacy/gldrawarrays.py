#! /usr/bin/env python
'''Test of the glDrawArrays function (draws flower)'''
from OpenGLContext.context import Context as BaseContext
from OpenGL.GL import *
import _flower_geometry

class TestContext( BaseContext):
    profile = 'compatibility'   # draws with the fixed-function pipeline
    def OnInit( self ):
        """Initialisation"""
        print("""Should see flower pattern in gray over white background""")
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glVertexPointerd(_flower_geometry.points_expanded )
        glNormalPointerf(_flower_geometry.normals_expanded )
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)
        glDrawArrays(GL_TRIANGLES, 0, len(_flower_geometry.points_expanded))

if __name__ == "__main__":
    TestContext.ContextMainLoop()
