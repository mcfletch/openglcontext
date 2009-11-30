#! /usr/bin/env python
'''Tests operation of SimpleBackground object -> solid color background
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import context
from OpenGLContext.scenegraph import simplebackground
from OpenGL.GL import *

class TestContext( BaseContext ):
    """Tests the SimpleBackground object's rendering.
    """
    def OnInit( self ):
        """Scene set up and initial processing"""
        print 'You should see a white/gray triangle over a blue background'
        self.Background = simplebackground.SimpleBackground(
            color = (0,0,1),
            bound = 1,
        ).Render
    def Render( self, mode = 0):
        """Render the geometry for the scene."""
        ## Triggers the default operations, which allows for, for example, transparent rendering
        BaseContext.Render( self, mode )
        ## Moves the drawing origin 6 units into the screen and 1.5 units to the left
        glTranslatef(-1.5,0.0,-6.0);
        ## Starts the geometry generation mode
        glBegin(GL_TRIANGLES)
        glVertex3f( 0.0,  1.0, 0.0)
        glVertex3f(-1.0, -1.0, 0.0)
        glVertex3f( 1.0, -1.0, 0.0)
        glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
