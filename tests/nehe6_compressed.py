#! /usr/bin/env python
'''=Compressed Texture Mapping (From NeHe 6)=
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GL.EXT.texture_compression_s3tc import *
import time
try:
    from PIL.Image import open
except ImportError as err:
    from Image import open

class TestContext( BaseContext ):
    """NeHe 6 Demo"""
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    def OnInit( self ):
        """Load the image on initial load of the application"""
        from OpenGL import extensions                              
        if not extensions.hasGLExtension("GL_EXT_texture_compression_s3tc"):
            print "Extension GL_EXT_texture_compression_s3tc required for compressed texture mapping test!"
            raise SystemExit(1)
        self.imageID = self.loadImage ()
    def loadImage( self, imageName = "nehe_wall.bmp" ):
        """Load an image file as a 2D texture using PIL"""
        im = open(imageName)
        try:
            ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBA", 0, -1)
        except SystemError:
            ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBX", 0, -1)
        ID = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, ID)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        glTexImage2D(
            GL_TEXTURE_2D, 0, 
            GL_COMPRESSED_RGBA_S3TC_DXT5_EXT, # internal format...
            ix, iy, 0, 
            GL_RGBA, 
            GL_UNSIGNED_BYTE, 
            image
        )
        return ID

    def Render( self, mode):
        """Render scene geometry"""
        BaseContext.Render( self, mode )
        glDisable( GL_LIGHTING) # context lights by default
        glTranslatef(1.5,0.0,-6.0);
        glRotated( time.time()%(8.0)/8 * -360, 1,0,0)
        self.setupTexture()
        self.drawCube()
    def setupTexture( self ):
        """Render-time texture environment setup"""
        '''Configure the texture rendering parameters'''
        glEnable(GL_TEXTURE_2D)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_DECAL)
        glBindTexture(GL_TEXTURE_2D, self.imageID)
    def drawCube( self ):
        """Draw a cube with texture coordinates"""
        glBegin(GL_QUADS);
        glTexCoord2f(0.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
        glTexCoord2f(1.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);

        glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
        glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);

        glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
        glTexCoord2f(0.0, 0.0); glVertex3f(-1.0,  1.0,  1.0);
        glTexCoord2f(1.0, 0.0); glVertex3f( 1.0,  1.0,  1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);

        glTexCoord2f(1.0, 1.0); glVertex3f(-1.0, -1.0, -1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f( 1.0, -1.0, -1.0);
        glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
        glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);

        glTexCoord2f(1.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
        glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);

        glTexCoord2f(0.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
        glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
        glEnd()
        
    def OnIdle( self, ):
        """Request refresh of the context whenever idle"""
        self.triggerRedraw(1)
        return 1

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
