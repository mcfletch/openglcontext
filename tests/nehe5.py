#! /usr/bin/env python
'''=Solid Models (NeHe 5)=

[nehe5.py-screen-0001.png Screenshot]

Renders slightly more complex geometry.

This tutorial is based on the [http://nehe.gamedev.net/data/lessons/lesson.asp?lesson=05 NeHe5 tutorial] by Jeff Molofee and assumes that you are reading along 
with the tutorial, so that only changes from the tutorial are noted 
here.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
import time

class TestContext( BaseContext ):
    """NeHe 5 tutorial"""
    '''There are no new customization points used here.'''
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    def Render( self, mode):
        """Draw scene geometry"""
        BaseContext.Render( self, mode )
        glDisable( GL_LIGHTING) # context lights by default
        glTranslatef(-1.5,0.0,-6.0);
        '''Animating using crude time.time() operation'''
        glRotated( time.time()%(3.0)/3 * 360, 0,1,0)
        self.drawPyramid()

        glLoadIdentity()
        glTranslatef(1.5,0.0,-6.0);
        glRotated( time.time()%(1.0)/1 * -360, 1,0,0)
        self.drawCube()
    def OnIdle( self, ):
        """Request refresh of the context whenever idle"""
        self.triggerRedraw(1)
        return 1
    '''We refactor the tutorial code to create a method for drawing
    the pyramid object and cube objects, instead of including the code
    in the main Render method (just for neatness sake).  The rest of 
    the Render function is all stuff we've seen before.'''
    def drawPyramid( self ):
        """Draw a multicolored pyramid"""
        glBegin(GL_TRIANGLES);
        glColor3f(1.0,0.0,0.0)
        glVertex3f( 0.0, 1.0, 0.0)
        glColor3f(0.0,1.0,0.0)
        glVertex3f(-1.0,-1.0, 1.0)
        glColor3f(0.0,0.0,1.0)
        glVertex3f( 1.0,-1.0, 1.0)
        glColor3f(1.0,0.0,0.0)
        glVertex3f( 0.0, 1.0, 0.0)
        glColor3f(0.0,0.0,1.0)
        glVertex3f( 1.0,-1.0, 1.0);
        glColor3f(0.0,1.0,0.0);
        glVertex3f( 1.0,-1.0, -1.0);
        glColor3f(1.0,0.0,0.0);
        glVertex3f( 0.0, 1.0, 0.0);
        glColor3f(0.0,1.0,0.0);
        glVertex3f( 1.0,-1.0, -1.0);
        glColor3f(0.0,0.0,1.0);
        glVertex3f(-1.0,-1.0, -1.0);
        glColor3f(1.0,0.0,0.0);
        glVertex3f( 0.0, 1.0, 0.0);
        glColor3f(0.0,0.0,1.0);
        glVertex3f(-1.0,-1.0,-1.0);
        glColor3f(0.0,1.0,0.0);
        glVertex3f(-1.0,-1.0, 1.0);
        glEnd()
    def drawCube( self ):
        """Draw a multicolored cube"""
        '''Draw a cube as quads, note that Quads are deprecated in 
        later OpenGL releases, with Triangles being preferred.
        '''
        glBegin(GL_QUADS);
        glColor3f(0.0,1.0,0.0)
        glVertex3f( 1.0, 1.0,-1.0)
        glVertex3f(-1.0, 1.0,-1.0)
        glVertex3f(-1.0, 1.0, 1.0)
        glVertex3f( 1.0, 1.0, 1.0)
        glColor3f(1.0,0.5,0.0)
        glVertex3f( 1.0,-1.0, 1.0)
        glVertex3f(-1.0,-1.0, 1.0)
        glVertex3f(-1.0,-1.0,-1.0)
        glVertex3f( 1.0,-1.0,-1.0)
        glColor3f(1.0,0.0,0.0)
        glVertex3f( 1.0, 1.0, 1.0)
        glVertex3f(-1.0, 1.0, 1.0)
        glVertex3f(-1.0,-1.0, 1.0)
        glVertex3f( 1.0,-1.0, 1.0)
        glColor3f(1.0,1.0,0.0)
        glVertex3f( 1.0,-1.0,-1.0)
        glVertex3f(-1.0,-1.0,-1.0)
        glVertex3f(-1.0, 1.0,-1.0)
        glVertex3f( 1.0, 1.0,-1.0)
        glColor3f(0.0,0.0,1.0)
        glVertex3f(-1.0, 1.0, 1.0)
        glVertex3f(-1.0, 1.0,-1.0)
        glVertex3f(-1.0,-1.0,-1.0)
        glVertex3f(-1.0,-1.0, 1.0)
        glColor3f(1.0,0.0,1.0)
        glVertex3f( 1.0, 1.0,-1.0)
        glVertex3f( 1.0, 1.0, 1.0)
        glVertex3f( 1.0,-1.0, 1.0)
        glVertex3f( 1.0,-1.0,-1.0)
        glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''
Author: [http://nehe.gamedev.net Jeff Molofee (aka NeHe)]

COPYRIGHT AND DISCLAIMER: (c)2000 Jeff Molofee

If you plan to put this program on your web page or a cdrom of
any sort, let me know via email, I'm curious to see where
it ends up :)

If you use the code for your own projects please give me
credit, or mention my web site somewhere in your program 
or it's docs.
'''