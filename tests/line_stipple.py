#! /usr/bin/env python
'''Test of the glDrawArrays function (draws flower)

NOTE: This test uses legacy OpenGL (glLineStipple) and requires
a compatibility profile context.
'''
from __future__ import print_function
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import contextdefinition
from OpenGL.GL import *
import flower_geometry

def bit_pattern( *args ):
    args = list(args[:16])
    args = args + [0]*(16-len(args))
    base = 0
    for arg in args:
        base = base << 1
        base += bool(arg)
    return base

class TestContext( BaseContext):
    # Requires compatibility profile for glLineStipple
    contextDefinition = contextdefinition.ContextDefinition(profile='compatibility')
    def OnInit( self ):
        """Initialisation"""
        print("""Should see flower pattern in gray over white background""")
        glLineStipple( 3, bit_pattern(
            0,0,1,1,
            0,1,0,1,
            0,0,1,1,
            0,0,1,0,
        ))
        glEnable( GL_LINE_STIPPLE )
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glVertexPointerd(flower_geometry.points_expanded )
        glNormalPointerf(flower_geometry.normals_expanded )
        glEnableClientState(GL_VERTEX_ARRAY);
        glEnableClientState(GL_NORMAL_ARRAY);
        glDrawArrays(GL_LINES, 0, len(flower_geometry.points_expanded))

if __name__ == "__main__":
    TestContext.ContextMainLoop()
