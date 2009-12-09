#! /usr/bin/env python
'''Tests rendering of the Box geometry object
'''
#import OpenGL 
#OpenGL.FULL_LOGGING = True 
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph import imagetexture, shape, material, appearance, box, scenegraph,light
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string, time

images = [
    "nehe_glass.bmp",
    "pimbackground_FR.jpg",
    "nehe_wall.bmp",
    "marbleface.jpeg",
]

sizes = [
    (.5,2,.25),
    (1,1,1),
    (2,2,2),
    (3,2,3),
    (4,3,3),
    (3,3,3),
]

class TestContext( BaseContext ):
    currentImage = 0
    currentSize = 0
#	def Render( self, mode = 0):
#		BaseContext.Render( self, mode )
#		self.shape.Render( mode )
    def OnInit( self ):
        """Scene set up and initial processing"""
        print """You should see an elongated box over a white background
    The box should have a mapped texture (a stained-glass window)
    and should be centered on the window.
"""
        print 'press i to choose another texture for the box'
        self.addEventHandler(
            'keypress', name = 'i', function = self.OnImageSwitch
        )
        print 'press s to choose another size for the box'
        self.addEventHandler(
            'keypress', name = 's', function = self.OnSizeSwitch
        )
        self.shape = shape.Shape(
            geometry = box.Box( size=sizes[0] ),
            appearance = appearance.Appearance(
                material =material.Material(
                    diffuseColor =(1,1,1)
                ),
                texture = imagetexture.ImageTexture(
                    url = [images[0]]
                ),
            ),
        )
        self.sg = scenegraph.SceneGraph(
            children = [ 
                self.shape, 
#				light.PointLight( location=(4,4,8)), 
            ],
        )
    def OnImageSwitch( self, event=None ):
        """Choose a new mapped texture"""
        self.currentImage = currentImage = self.currentImage+1
        newImage = images[currentImage%len(images)]
        self.shape.appearance.texture.url = [ newImage ]
        print "new image (loading) ->", newImage
    def OnSizeSwitch( self, event=None ):
        """Choose a new size"""
        self.currentSize = currentSize = self.currentSize+1
        newSize = sizes[currentSize%len(sizes)]
        self.shape.geometry.size = newSize
        print "new size ->", newSize
        self.triggerRedraw(1)
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
