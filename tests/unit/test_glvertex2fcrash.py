#! /usr/bin/env python
'''Test of the glVertex function (draws flower)'''
from OpenGLContext import testingcontext
from OpenGLContext.context import Context as BaseContext
from OpenGL.GL import *

class TestContext( BaseContext ):
    __test__ = False    # a window to draw in; the name is not a test case
    def OnInit( self ):
        """Initialisation"""
        print("""Should raise TypeError (and catch it to display message)""")
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glBegin( GL_TRIANGLES )
        try:
            glVertex2fv( None )
        except (TypeError,ValueError):
            print('Got expected TypeError on attempting to pass None to glVertex2fv')
        glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
