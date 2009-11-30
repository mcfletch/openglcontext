#! /usr/bin/env python
'''Test of the ARB window_pos extension...

Requires:
    PIL

ARB.window_pos provides for specifying on-screen
raster location without needing to carefully specify
the model-view and perspective matrices.

This module uses the glWindowPos2dARB and glWindowPos2dvARB
functions, as well as testing for proper operation under
malformed parameters to the glWindowPos2dvARB function.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.constants import *
from OpenGL import error
import math, random, traceback, sys
from OpenGLContext.events.timer import Timer

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
        print """You should see two bitmap images traversing the screen
    diagonally.  If the GL.ARB.window_pos extension is not available
    then you will exit immediately.
    """
        self.width, self.height, self.data = self.loadImage()
        global window_pos
        window_pos = self.extensions.initExtension( "GL.ARB.window_pos")
        if not window_pos:
            print 'GL_ARB_window_pos not supported!'
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        self.time = Timer( duration = 8.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
        self.x = 0
        self.y = 0
        
        try:
            window_pos.glWindowPos2dvARB(())
        except (error.CopyError,GLerror,ValueError), err:
            print 'Correct handling of incorrect parameters', err
        except Exception, err:
            traceback.print_exc()
            print 'Incorrect handling of incorrect parameters'
        try:
            window_pos.glWindowPos3dvARB(())
        except (error.CopyError,GLerror, ValueError), err:
            print 'Correct handling of incorrect parameters', err
        except Exception, err:
            traceback.print_exc()
            print 'Incorrect handling of incorrect parameters'
        
    def OnTimerFraction( self, event ):
        """Set new position..."""
        width, height = self.getViewPort()
        self.x = width * event.fraction()
        self.y = height * event.fraction()

    def Render( self, mode = None):
        BaseContext.Render( self, mode )
        # we aren't affected by the matrices (which is the point)
        glTranslate( 100,0,0 )
        if mode.visible and not mode.transparent:
            format = GL_RGBA
            type = GL_UNSIGNED_BYTE
            glEnable(GL_ALPHA_TEST);
            glAlphaFunc(GL_GREATER,0);
            glPixelStorei(GL_PACK_ALIGNMENT, 1)
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1)

            width, height = self.getViewPort()
            window_pos.glWindowPos2dARB(self.x,self.y)

            glDrawPixels(
                self.width,
                self.height,
                format,
                type,
                self.data,
            )
            window_pos.glWindowPos2fvARB(
                GLfloat_2(self.x,self.getViewPort()[1]-self.y)
            )
            glDrawPixels(
                self.width,
                self.height,
                format,
                type,
                self.data,
            )
        
        
if __name__ == "__main__":
    TestContext.ContextMainLoop()