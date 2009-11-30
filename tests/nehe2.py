#! /usr/bin/env python
'''=Creating Your First Polygon & Quad (NeHe 2)=

[nehe2.py-screen-0001.png Screenshot]

Introduces:
    
    * glBegin/glEnd
    * glVertex
    * glTranslate

This tutorial is based on the [http://nehe.gamedev.net/data/lessons/lesson.asp?lesson=02 NeHe2 tutorial] by Jeff Molofee and assumes that you are reading along 
with the tutorial, so that only changes from the tutorial are noted 
here.

The previous tutorial discussed this setup procedure at length.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *

class TestContext( BaseContext ):
    """Rendering Context with custom viewpoint and render
    
    Note: will have slightly different results as OpenGLContext
    automatically enables lighting.
    """
    '''The first customization is the initialPosition attribute.  By
    default, the OpenGLContext contexts position your
    eye/camera at (0,0,10), which makes it easy to see most
    meter-sized geometry located at the origin.  Since the
    NeHe tutorial manually repositions the geometry to be in a
    good viewing position under the assumption that the eye
    is at (0,0,0), we need to make that assumption valid.
    '''
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    '''The second customization is the Render method.  This method is
    called if there is no SceneGraph present in the Context.
    (Such as in our tutorial).
    '''
    def Render( self, mode):
        """Render the geometry for the scene."""
        '''Prevents OpenGL from removing faces which face backward'''
        glDisable( GL_CULL_FACE )
        '''Moves the drawing origin 6 units into the screen and 1.5 units to the left'''
        glTranslatef(-1.5,0.0,-6.0);
        '''Starts the (legacy) geometry generation mode'''
        glBegin(GL_TRIANGLES)
        glVertex3f( 0.0,  1.0, 0.0)
        glVertex3f(-1.0, -1.0, 0.0)
        glVertex3f( 1.0, -1.0, 0.0)
        glEnd()
        
        '''Moves the drawing origin again, cumulative change is now (1.5,0.0,6.0)'''
        glTranslatef(3.0,0.0,0.0);

        '''Starts a different geometry generation mode'''
        glBegin(GL_QUADS)
        glVertex3f(-1.0,-1.0, 0.0)
        glVertex3f( 1.0,-1.0, 0.0)
        glVertex3f( 1.0, 1.0, 0.0)
        glVertex3f(-1.0, 1.0, 0.0)
        glEnd();

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