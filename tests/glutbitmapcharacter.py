#! /usr/bin/env python
'''Draw text with GLUT bitmap fonts'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGLContext.arrays import array
import string, time


def drawText( value, x,y,  windowHeight, windowWidth, step = 18 ):
    """Draw the given text at given 2D position in window
    """
    glMatrixMode(GL_PROJECTION);
    # For some reason the GL_PROJECTION_MATRIX is overflowing with a single push!
    # glPushMatrix()
    matrix = glGetDouble( GL_PROJECTION_MATRIX )
    
    glLoadIdentity();
    glOrtho(0.0, windowHeight or 32, 0.0, windowWidth or 32, -1.0, 1.0)
    glMatrixMode(GL_MODELVIEW);
    glPushMatrix();
    glLoadIdentity();
    glRasterPos2i(x, y);
    lines = 0
##	import pdb
##	pdb.set_trace()
    for character in value:
        if character == '\n':
            glRasterPos2i(x, y-(lines*18))
        else:
            glutBitmapCharacter(GLUT_BITMAP_HELVETICA_18, ord(character));
    glPopMatrix();
    glMatrixMode(GL_PROJECTION);
    # For some reason the GL_PROJECTION_MATRIX is overflowing with a single push!
    # glPopMatrix();
    glLoadMatrixd( matrix ) # should have un-decorated alias for this...
    
    glMatrixMode(GL_MODELVIEW);

class TestContext( BaseContext ):
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    def OnInit( self ):
        BaseContext.OnInit( self )
        print """Should see "hello world" in white in the lower-left corner of black screen"""
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glColor3f( 0,0,1 )
        drawText( 'hello world', 10,20, self.viewportDimensions[0],self.viewportDimensions[1])
    def Background(self, mode = 0):
        ''' Clear the background for a particular rendering mode,
        potentially render a "cool" background node'''
        glClearColor(0,0,0,1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
