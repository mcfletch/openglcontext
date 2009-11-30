#! /usr/bin/env python
'''Texture Mapping geometry with Convolution

Based on:
    OpenGL Tutorial #6.

    Project Name: Jeff Molofee's OpenGL Tutorial

    Project Description: Texture Mapping.

    Authors Name: Jeff Molofee (aka NeHe)

    Authors Web Site: nehe.gamedev.net

    COPYRIGHT AND DISCLAIMER: (c)2000 Jeff Molofee

        If you plan to put this program on your web page or a cdrom of
        any sort, let me know via email, I'm curious to see where
        it ends up :)

            If you use the code for your own projects please give me credit,
            or mention my web site somewhere in your program or it's docs.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
import time, os,sys
try:
    from PIL.Image import open
except ImportError, err:
    from Image import open
from OpenGL.GL.ARB.imaging import *
from OpenGLContext import arrays

class TestContext( BaseContext ):
    """There is one new customization point used here: OnInit

    OnInit is called by the Context class after initialization
    of the context has completed, and before any rendering is
    attempted.  Within this method, you'll generally perform
    your global setup tasks.

    We also see the use of the python imaging library for
    loading images, something which is obviously not seen
    in the original tutorial.

    Finally, this interpretation reorganizes the code to resemble
    more idiomatic python than the original code.
    """
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    FILTER_SIZE = 4
    convolutionKernel = arrays.zeros( (4,4,4),'f') + (1.0/(FILTER_SIZE*FILTER_SIZE))
    currentImage = 0
    
    def OnInit( self ):
        """Load the image on initial load of the application"""
        print """Uses glConvolutionFilter2D to process the NeHe6 based image
        
    This convolution filter should produce a "blurring" effect on the image.
    The effect is applied on image upload (i.e. glTexImage2D call), so 
    different images can have different convolutions applied.
    """
        if not glInitImagingARB():
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        self.imageIDs = [
            self.loadImage (),
            self.loadImage ( convolve = False ),
        ]
        self.imageIndex = 0
        print '''Press 'c' to toggle between convolved and non-convolved image'''
        self.addEventHandler( "keypress", name="c", function = self.OnConvolve)
    def OnConvolve( self, event ):
        """Convolve (choose the other image) or disable convolution"""
        self.imageIndex += 1
        if self.imageIndex %2:
            print 'Un-convolved image'
        else:
            print 'Convolved image'

        
    def loadImage( self, imageName = 'nehe_wall.bmp', convolve=True ):
        """Load an image file as a 2D texture using PIL

        This method combines all of the functionality required to
        load the image with PIL, convert it to a format compatible
        with PyOpenGL, generate the texture ID, and store the image
        data under that texture ID.

        Note: only the ID is returned, no reference to the image object
        or the string data is stored in user space, the data is only
        present within the OpenGL engine after this call exits.
        """
        im = open(imageName)
        try:
            ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBA", 0, -1)
        except SystemError:
            ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBX", 0, -1)
        # generate a texture ID
        ID = glGenTextures(1)
        # make it current
        glBindTexture(GL_TEXTURE_2D, ID)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        # copy the texture into the current texture ID
        if convolve:
            glEnable(GL_CONVOLUTION_2D);
            glConvolutionParameteri(
                GL_CONVOLUTION_2D,
                GL_CONVOLUTION_BORDER_MODE, 
                GL_CONSTANT_BORDER
            )
            assert glGetConvolutionParameteriv( 
                GL_CONVOLUTION_2D,
                GL_CONVOLUTION_BORDER_MODE, 
            ) == GL_CONSTANT_BORDER, glGetConvolutionParameteriv( 
                GL_CONVOLUTION_2D,
                GL_CONVOLUTION_BORDER_MODE, 
            )
            glConvolutionFilter2D(
                GL_CONVOLUTION_2D, GL_RGBA,
                self.FILTER_SIZE, self.FILTER_SIZE,
                GL_RGBA, GL_FLOAT, self. convolutionKernel
            )
            setFilter = glGetConvolutionFilter(
                GL_CONVOLUTION_2D, GL_RGBA, GL_FLOAT 
            )
            #assert setFilter.shape == (4,4)
            #assert setFilter.dtype == self.convolutionKernel.dtype
        glTexImage2D(GL_TEXTURE_2D, 0, 3, ix, iy, 0, GL_RGBA, GL_UNSIGNED_BYTE, image)
        glDisable( GL_CONVOLUTION_2D )
        # return the ID for use
        return ID

    def Render( self, mode = 0):
        """Render scene geometry"""
        BaseContext.Render( self, mode )
        glDisable( GL_LIGHTING) # context lights by default
        glTranslatef(1.5,0.0,-6.0);
        glRotated( time.time()%(8.0)/8 * -360, 1,0,0)
        self.setupTexture()
        self.drawCube()
    def setupTexture( self ):
        """Render-time texture environment setup

        This method encapsulates the functions required to set up
        for textured rendering.  The original tutorial made these
        calls once for the entire program.  This organization makes
        more sense if you are likely to have multiple textures.
        """
        # texture-mode setup, was global in original
        glEnable(GL_TEXTURE_2D)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_DECAL)
        # re-select our texture, could use other generated textures
        # if we had generated them earlier...
        glBindTexture(GL_TEXTURE_2D, self.imageIDs[ self.imageIndex%2 ])   # 2d texture (x and y size)
            
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
