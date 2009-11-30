#! /usr/bin/env python
'''=Animating Rotation of a Polygon (NeHe 4)=

[nehe4.py-screen-0001.png Screenshot]

This tutorial uses the (legacy) OpenGL glRotated function to 
setup a model-view matrix which animates the spin of geometry 
about an axis.

This tutorial is based on the [http://nehe.gamedev.net/data/lessons/lesson.asp?lesson=04 NeHe4 tutorial] by Jeff Molofee and assumes that you are reading along 
with the tutorial, so that only changes from the tutorial are noted 
here.

'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
'''The time module is used to provide crude animation support'''
import time

class TestContext( BaseContext ):
    """This context customizes 3 points in the BaseContext"""
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    '''
    The OnIdle method (if present) is called whenever the GUI library
    has completed all pending event processing and signals an "idle"
    state.  By calling:
    
        self.triggerRedraw( force = 1 )
    
    We force a redraw of the context to show the next "frame" of the
    animation.
    '''
    def OnIdle( self, ):
        """Request refresh of the context whenever idle"""
        self.triggerRedraw(1)
        return 1
    def Render( self, mode = 0):
        """Render the scene geometry"""
        BaseContext.Render( self, mode )
        glDisable( GL_LIGHTING) # context lights by default
        glDisable( GL_CULL_FACE)
        glTranslatef(-1.5,0.0,-6.0);
        '''The call to time.time creates a float value which is
        converted to a fraction of three seconds then multiplied
        by 360 (degrees) to get the current appropriate rotation
        for an object spinning at 1/3 rps.
        
        Note that OpenGL uses *degrees*, not radians!
        '''
        glRotated( time.time()%(3.0)/3 * 360, 0,1,0)
        glBegin(GL_TRIANGLES)
        glColor3f(1,0,0)
        glVertex3f( 0.0,  1.0, 0.0)
        glColor3f(0,1,0)
        glVertex3f(-1.0, -1.0, 0.0)
        glColor3f(0,0,1)
        glVertex3f( 1.0, -1.0, 0.0)
        glEnd()

        '''Note the need to re-load the identity matrix, as the 
        glRotated/glTranslatef functions modify the current matrix.
        '''
        glLoadIdentity()
        glTranslatef(1.5,0.0,-6.0);
        '''Animating as above, but at 1 rev/s'''
        glRotated( time.time()%(1.0)/1 * -360, 1,0,0)

        glColor3f(0.5,0.5,1.0)
        glBegin(GL_QUADS)
        glVertex3f(-1.0, 1.0, 0.0)
        glVertex3f( 1.0, 1.0, 0.0)
        glVertex3f( 1.0,-1.0, 0.0)
        glVertex3f(-1.0,-1.0, 0.0)
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