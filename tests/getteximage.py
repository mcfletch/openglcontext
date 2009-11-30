#! /usr/bin/env python
"""Demonstrate/test usage of glGetTexImage"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph import imagetexture

from OpenGL.GL import *
import os

class TestContext( BaseContext ):
    useArrays = 0
    def Render( self, mode ):
        BaseContext.Render( self, mode )
        tt = self.mmtexture.compile( mode )
        if tt:
            tt()
            # now extract the images for redisplay...
            if self.useArrays:
                glRasterPos2f( -1, 0 )
            else:
                glRasterPos2f( 1, 0 )
            for level in range( 4 ):
                if self.useArrays:
                    displayImage = glGetTexImageub( GL_TEXTURE_2D, level, GL_RGBA )
                    glDrawPixelsub( GL_RGBA, displayImage )
                    width,height = displayImage.shape[:2]
                else:
                    displayImage = glGetTexImage( GL_TEXTURE_2D, level, GL_RGBA, GL_UNSIGNED_BYTE )
                    width = glGetTexLevelParameteriv(GL_TEXTURE_2D, level, GL_TEXTURE_WIDTH )
                    height = glGetTexLevelParameteriv(GL_TEXTURE_2D, level, GL_TEXTURE_HEIGHT )
                    glDrawPixels( int(width), int(height), GL_RGBA, GL_UNSIGNED_BYTE, displayImage )
                print 'Level %s --> %s * %s'%( level, width, height )
                glBitmap(0,0,0,0,0,height*2,None)
        else:
            print '''Haven't loaded the texture yet!'''
    def OnInit( self ):
        """Initialise the context, loading texture"""
        print '''You should see 4 scaled versions of red text "testing"

    s -- toggle use of Numeric arrays for storing the image data
        when arrays are being used, images are shifted to left,
        when arrays are not being used, images are shifted to right
        (in order to make the change visible).
'''
        self.mmtexture = imagetexture.MMImageTexture(
            url = os.path.join(
                os.path.dirname( __file__ ),
                'resources',
                'oblongimage.png',
            ),
        )
        self.addEventHandler(
            'keypress', name = 's', function = self.OnUseStrings
        )
    def OnUseStrings( self, event ):
        self.useArrays = not self.useArrays
        print 'Use arrays?', bool( self.useArrays )
        self.triggerRedraw(1)
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()