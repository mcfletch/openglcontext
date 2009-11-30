#! /usr/bin/env python
'''Material object test (test effect of material on texture)

Based on nehe6
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext import drawcube
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL import *
import time


images = [
    "nehe_glass.bmp",
    "pimbackground_FR.jpg",
    "nehe_crate.bmp",
    "nehe_wall.bmp",
    "wrls/irradiation.jpg",
    "wrls/yingyang.png",
]

class TestContext( BaseContext ):
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    currentImage = 0
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glTranslatef(1.5,0.0,-6.0);
        glRotated( time.time()%(8.0)/8 * -360, 1,0,0)
        self.shape.appearance.material.diffuseColor = (time.time()%(3.0)/3, time.time()%(2.0)/2,time.time()%(4.0)/4)
        self.shape.Render( mode )
    def OnInit( self ):
        """Load the image on initial load of the application"""
        print """Should see spinning textured cube over white background
    The texture applied to the cube should be modified by the material
    which will be cycling through the spectrum."""
        print 'press i to choose another image'
        self.addEventHandler(
            'keypress', name = 'i', function = self.OnImageSwitch
        )
        self.shape = Shape(
            appearance = Appearance(
                material = Material(
                    diffuseColor =(1,0,0)
                ),
                texture = ImageTexture(
                    url = [images[0]]
                ),
            ),
            geometry = Teapot(),
        )

        
    def OnIdle( self, ):
        self.triggerRedraw(1)
        return 1
    def OnImageSwitch( self, event=None ):
        self.currentImage = currentImage = self.currentImage+1
        self.shape.appearance.texture.url = [
            images[currentImage%len(images)]
        ]
        self.triggerRedraw(1)
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
