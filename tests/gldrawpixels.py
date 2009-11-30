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
from OpenGL.GL import *
import string

class TestContext( BaseContext ):
    def loadImage( self, imageName = 'gldrawpixels.png' ):
        """Load an image from a file using PIL.
        This is closer to what you really want to do than the
        original port's crammed-together stuff that set global
        state in the loading method.  Note the process of binding
        the texture to an ID then loading the texture into memory.
        This didn't seem clear to me somehow in the tutorial.
        """
        try:
            from PIL.Image import open
        except ImportError, err:
            from Image import open
        im = open(imageName)
        try:
            ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBA", 0, -1)
        except SystemError:
            ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBX", 0, -1)
        return ix,iy, image
    def OnInit( self, ):
        """Initialisation"""
        print """Should see black bitmap/square in lower left quadrant over blue background
Should see scrawled "regular image stuff" at top of black square.
Should see typed "Hello From Alpha-ville" in the middle of the
black square.

    Note: bitmap is drawn in screen coordinates, so does not
    respond to moving around or rescaling the window as would
    a piece of geometry."""
        self.width, self.height, self.data = self.loadImage()
        
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        format = GL_RGBA
        type = GL_UNSIGNED_BYTE
        glEnable(GL_ALPHA_TEST);
        glAlphaFunc(GL_GREATER,0);
##		glEnable(GL_BLEND);
##		glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
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