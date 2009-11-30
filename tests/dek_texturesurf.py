#! /usr/bin/env python
'''DEK's Texturesurf demo, tests glEvalMesh2'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGLContext.arrays import array
from OpenGLContext.scenegraph.basenodes import *
import string, time

## Control points for the bezier surface
ctrlpoints = array([
    [[-1.5, -1.5, 4.0] ,
     [-0.5, -1.5, 2.0] ,
     [0.5, -1.5, -1.0] ,
     [1.5, -1.5, 2.0]] ,
    [[-1.5, -0.5, 1.0] ,
     [-0.5, -0.5, 3.0] ,
     [0.5, -0.5, 0.0] ,
     [1.5, -0.5, -1.0]] ,
    [[-1.5, 0.5, 4.0] ,
     [-0.5, 0.5, 0.0] ,
     [0.5, 0.5, 3.0] ,
     [1.5, 0.5, 4.0]] ,
    [[-1.5, 1.5, -2.0] ,
     [-0.5, 1.5, -2.0] ,
     [0.5, 1.5, 0.0] ,
     [1.5, 1.5, -1.0]] ,
], 'f' )

## Texture control points
texpts = array([
    [[0.0, 0.0],
     [0.0, 1.0]],
    [[1.0, 0.0],
     [1.0, 1.0]],
], 'f')


class TestContext( BaseContext ):
    def Render( self, mode ):
        BaseContext.Render( self, mode )
#		glEnable(GL_DEPTH_TEST)
        glEnable(GL_NORMALIZE)
        self.light.Light( GL_LIGHT0, mode )
        
        glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.imageID)   # 2d texture (x and y size)
        
#		glShadeModel(GL_FLAT)
        glCallList( self.surfaceID )
        
    def buildDisplayList( self):
        glDisable(GL_CULL_FACE)
        
        glEnable(GL_MAP2_TEXTURE_COORD_2)
        glEnable(GL_MAP2_VERTEX_3)
        glEnable(GL_MAP2_NORMAL)
        
        glMap2f(GL_MAP2_NORMAL, 0., 1., 0., 1., ctrlpoints)
        glMap2f(GL_MAP2_VERTEX_3, 0., 1., 0., 1., ctrlpoints)
        glMap2f(GL_MAP2_TEXTURE_COORD_2, 0, 1, 0, 1, texpts)
        glMapGrid2f(20, 0.0, 1.0, 20, 0.0, 1.0)

        displayList = glGenLists(1)
        glNewList( displayList, GL_COMPILE)
        glEvalMesh2(GL_FILL, 0, 20, 0, 20)
        glEndList()
        return displayList
    def OnInit( self ):
        """Load the image on initial load of the application"""
        print """Should see curvy surface with brick-like texture over white background"""
        self.surfaceID = self.buildDisplayList()
        self.imageID = self.loadImage ()
        self.light = SpotLight(
            direction = (-10,0,-10),
            cutOffAngle = 1.57,
            color = (1,1,1),
            location = (10,0,10),
        )
        
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
        glTexImage2D(GL_TEXTURE_2D, 0, 3, ix, iy, 0, GL_RGBA, GL_UNSIGNED_BYTE, image)
        # return the ID for use
        return ID
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()