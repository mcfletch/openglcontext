#! /usr/bin/env python
'''=Texture Mapping (NeHe 6)=

[nehe6.py-screen-0001.png Screenshot]


This tutorial is based on the [http://nehe.gamedev.net/data/lessons/lesson.asp?lesson=06 NeHe6 tutorial] by Jeff Molofee and assumes that you are reading along 
with the tutorial, so that only changes from the tutorial are noted 
here.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
import time
try:
    from PIL.Image import open
except ImportError, err:
    from Image import open

class TestContext( BaseContext ):
    """NeHe 6 Demo"""
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    '''OnInit is called by the Context class after initialization
    of the context has completed, and before any rendering is
    attempted.  Within this method, you'll generally perform
    your global setup tasks.'''
    def OnInit( self ):
        """Load the image on initial load of the application"""
        self.imageID = self.loadImage ()
    
    '''	We are going to use the Python Imaging Library (PIL) for
    loading images, something which is obviously not seen
    in the original tutorial.
    
    This method combines all of the functionality required to
    load the image with PIL, convert it to a format compatible
    with PyOpenGL, generate the texture ID, and store the image
    data under that texture ID.
    '''
    def loadImage( self, imageName = "nehe_wall.bmp" ):
        """Load an image file as a 2D texture using PIL"""
        '''PIL defines an "open" method which is Image specific!'''
        im = open(imageName)
        try:
            ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBA", 0, -1)
        except SystemError:
            ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBX", 0, -1)
        '''Generate a texture ID'''
        ID = glGenTextures(1)
        '''Make our new texture ID the current 2D texture'''
        glBindTexture(GL_TEXTURE_2D, ID)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        '''Copy the texture data into the current texture ID'''
        glTexImage2D(
            GL_TEXTURE_2D, 0, 3, ix, iy, 0, 
            GL_RGBA, GL_UNSIGNED_BYTE, image
        )
        '''Note that only the ID is returned, no reference to the image
        object or the string data is stored in user space, the data is 
        only present within the GL after this call exits.'''
        return ID

    def Render( self, mode):
        """Render scene geometry"""
        BaseContext.Render( self, mode )
        glDisable( GL_LIGHTING) # context lights by default
        glTranslatef(1.5,0.0,-6.0);
        glRotated( time.time()%(8.0)/8 * -360, 1,0,0)
        self.setupTexture()
        self.drawCube()
    '''This method encapsulates the functions required to set up
    for textured rendering.  The original tutorial made these
    calls once for the entire program.  This organization makes
    more sense if you are likely to have multiple textures.
    '''
    def setupTexture( self ):
        """Render-time texture environment setup"""
        '''Configure the texture rendering parameters'''
        glEnable(GL_TEXTURE_2D)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_DECAL)
        '''Re-select our texture, could use other generated textures
        if we had generated them earlier...'''
        glBindTexture(GL_TEXTURE_2D, self.imageID)
    '''Drawing the cube has changed slightly, because we now need 
    to specify the texture coordinates for each vertex. This is all 
    just taken from the original tutorial.'''
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