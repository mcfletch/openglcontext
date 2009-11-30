#! /usr/bin/env python
"""Multi-texturing test/sample"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext import texture
import sys

multitexture = None

class TestContext( BaseContext ):
    def OnInit( self ):
        """Load the image on initial load of the application"""
        global multitexture
        multitexture = self.extensions.initExtension( "GL.ARB.multitexture")
        if not multitexture:
            print 'GL_ARB_multitexture not supported!'
            sys.exit(1)
        self.image = self.loadImage ("nehe_wall.bmp")
        self.lightmap = self.loadLightMap( "lightmap1.jpg" )
        
    def loadImage( self, imageName = "nehe_wall.bmp" ):
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
        multitexture.glActiveTextureARB(multitexture.GL_TEXTURE0_ARB);
        return texture.Texture( open(imageName) )
    def loadLightMap( self, imageName = "lightmap1.jpg" ):
        """Load an image from a file using PIL as a lightmap (greyscale)
        """
        try:
            from PIL.Image import open
        except ImportError, err:
            from Image import open
        multitexture.glActiveTextureARB(multitexture.GL_TEXTURE1_ARB); 
        glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
        return texture.Texture( open(imageName) )

    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        multitexture.glActiveTextureARB(multitexture.GL_TEXTURE0_ARB); 
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_DECAL)
        self.image()
        multitexture.glActiveTextureARB(multitexture.GL_TEXTURE1_ARB);
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        self.lightmap()
        self.drawCube()

    def drawCube( self ):
        glBegin(GL_QUADS);
        glNormal3f( 0,0,1 )
        mTexture(0.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
        mTexture(1.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
        mTexture(1.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
        mTexture(0.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);
        glEnd()

def mTexture( a,b ):
    multitexture.glMultiTexCoord2fARB(multitexture.GL_TEXTURE0_ARB, a,b)
    multitexture.glMultiTexCoord2fARB(multitexture.GL_TEXTURE1_ARB, a,b) 

if __name__ == "__main__":
    TestContext.ContextMainLoop()