#! /usr/bin/env python
'''Test of the glArrayElement function (draws flower)'''
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
        glTranslatef( 0,0,-1)
        glVertexPointerd( _flower_geometry.points_expanded )
        glNormalPointerf( _flower_geometry.normals_expanded )
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)
        glBegin( GL_TRIANGLES )
        for index in range(len(_flower_geometry.points_expanded)):
            glArrayElement( index )
        glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
