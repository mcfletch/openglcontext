#! /usr/bin/env python
'''=Flat and Smooth Colors (NeHe 3)=

[nehe3.py-screen-0001.png Screenshot]

Introduces:
    
    * glColor

This tutorial is based on the [http://nehe.gamedev.net/data/lessons/lesson.asp?lesson=03 NeHe3 tutorial] by Jeff Molofee and assumes that you are reading along 
with the tutorial, so that only changes from the tutorial are noted 
here.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *

class TestContext( BaseContext ):
    """Colorises the NeHe2 geometry"""
    initialPosition = (0,0,0)
    def Render( self, mode = 0):
        """Renders the geometry for the scene."""
        '''Unlike the nehe tutorial, we need to explicitly disable
        lighting, as the context automatically enables lighting
        to avoid a common class of new user errors where unlit
        geometry does not appear due to lack of light.'''
        BaseContext.Render( self, mode )
        glDisable( GL_CULL_FACE)
        glDisable( GL_LIGHTING)
        
        '''Now we return to the tutorial, in this geometry we are 
        specifying a colour for each vertex.'''
        glTranslatef(-1.5,0.0,-6.0);
        glBegin(GL_TRIANGLES)
        glColor3f(1,0,0)
        glVertex3f( 0.0,  1.0, 0.0)
        glColor3f(0,1,0)
        glVertex3f(-1.0, -1.0, 0.0)
        glColor3f(0,0,1)
        glVertex3f( 1.0, -1.0, 0.0)
        glEnd()

        glTranslatef(3.0,0.0,0.0);
        '''Here we specify the colour once for the entire piece of 
        geometry.'''
        glColor3f(0.5,0.5,1.0)
        glBegin(GL_QUADS)
        glVertex3f(-1.0,-1.0, 0.0)
        glVertex3f( 1.0,-1.0, 0.0)
        glVertex3f( 1.0, 1.0, 0.0)
        glVertex3f(-1.0, 1.0, 0.0)
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