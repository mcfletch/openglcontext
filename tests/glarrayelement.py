#! /usr/bin/env python
'''Test of the glArrayElement function (draws flower)'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string
import flower_geometry

class TestContext( BaseContext ):
    def OnInit( self ):
        """Initialisation"""
        print """Should see flower pattern in gray over white background"""
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glTranslatef( 0,0,-1)
        glVertexPointerd( flower_geometry.points_expanded )
        glNormalPointerf( flower_geometry.normals_expanded )
        glEnableClientState(GL_VERTEX_ARRAY);
        glEnableClientState(GL_NORMAL_ARRAY);
        glBegin( GL_TRIANGLES )
        for index in range(len(flower_geometry.points_expanded)):
            glArrayElement( index )
        glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()