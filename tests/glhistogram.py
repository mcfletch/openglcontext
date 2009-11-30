#! /usr/bin/env python
'''Test of the glDrawPixels function including alpha blending

Requires:
    GLUT, PIL, GLUTContext

You should see a black 128x128 box in the lower-left corner of the screen
with the words "Hello From Alpha-ville!" in blue (the background showing
through) and a scrawled "regular image stuff" in red (just part of the
RGB image).
'''

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
import numpy,sys
from OpenGL.GL import *
from OpenGL.GL.ARB.imaging import *

import string

class TestContext( BaseContext ):
    def OnInit( self, ):
        """Initialisation"""
        print """Demonstrates drawing a synthetically-generated image 

    Note: bitmap is drawn in screen coordinates, so does not
    respond to moving around or rescaling the window as would
    a piece of geometry."""
        width,height = 200,50
        self.width, self.height, self.data = width,height,numpy.arange(
            0, .5, .5/(width*height*3),
            dtype='f',
        )
        if not glInitImagingARB():
            print 'No ARB imaging extension supported'
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        if glInitImagingARB():
            # enter histogram mode...
            glHistogram(GL_HISTOGRAM, 256, GL_LUMINANCE, GL_FALSE)
            glEnable( GL_HISTOGRAM )
            
            # draw our pixel scene
            format = GL_RGB
            type = GL_FLOAT
            glPixelStorei(GL_PACK_ALIGNMENT, 1)
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1)

            width, height = self.getViewPort()
            glMatrixMode(GL_PROJECTION);
            # For some reason the GL_PROJECTION_MATRIX is overflowing with a single push!
            # glPushMatrix()
            matrix = glGetDouble( GL_PROJECTION_MATRIX )
            
            glLoadIdentity();
            glOrtho(0.0, height or 32, 0.0, width or 32, -1.0, 1.0)
            glMatrixMode(GL_MODELVIEW);
            glPushMatrix();
            glLoadIdentity();
            glRasterPos2i(40,40);

            glDrawPixels(
                self.width,
                self.height,
                format,
                type,
                self.data,
            )
            
            hist = glGetHistogram(
                GL_HISTOGRAM, GL_FALSE, GL_LUMINANCE,  GL_UNSIGNED_BYTE,
            )
            glDisable( GL_HISTOGRAM )
            hist *= 5 # so that you can see the values...
            glRasterPos2i( 40, 32 )
            glDrawPixelsub( GL_LUMINANCE, hist )
        
            # now clean up...
            glPopMatrix();
            glMatrixMode(GL_PROJECTION);
            # For some reason the GL_PROJECTION_MATRIX is overflowing with a single push!
            # glPopMatrix();
            glLoadMatrixd( matrix ) # should have un-decorated alias for this...
            
            glMatrixMode(GL_MODELVIEW);

    def Background(self, mode = 0):
        '''Clear the background for a particular rendering mode'''
        glClearColor(0.0,0.0,1.0,1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )
        
if __name__ == "__main__":
    TestContext.ContextMainLoop()