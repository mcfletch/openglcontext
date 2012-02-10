#! /usr/bin/env python
'''Tests rendering of the Box geometry object
'''
import OpenGL
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string, time

images = [
    "nehe_glass.bmp",
    "pimbackground_FR.jpg",
    "nehe_wall.bmp",
    "marbleface.jpeg",
    "http://www.vrplumber.com/maps/thesis_icon.jpg",
]

cone_sizes = [
    1,
    2,
    3,
    4,
    .5,
    .25,
]

class TestContext( BaseContext ):
    currentImage = 0
    currentSize = 0
    def OnInit( self ):
        """Scene set up and initial processing"""
        print """You should see a cone over a black background
    The cone should have a mapped texture (a stained-glass window)
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
        self.appearance = Appearance(
            material = Material(
                diffuseColor =(1,0,0),
                specularColor = (1,1,1),
            ),
            texture = ImageTexture(
                url = [images[0]]
            ),
        )
        self.cone = Shape(
            geometry = Cone( ),
            appearance = self.appearance,
        )
        self.cylinder = Shape(
            geometry = Cylinder( ),
            appearance = self.appearance,
        )
        self.box = Shape(
            geometry = Box(),
            appearance = self.appearance,
        )
        self.gear = Shape(
            geometry = Gear(),
            appearance = self.appearance,
        )
        self.sg = Transform(
            children = [
                Transform(
                    translation = (4,0,0),
                    children = [self.cone],
                ),
                Transform(
                    translation = (0,0,0),
                    children = [self.box],
                ),
                Transform(
                    translation = (-4,0,0),
                    children = [self.cylinder],
                ),
                Transform(
                    translation = (0,4,0),
                    children = [self.gear],
                    scale = (3,3,3),
                ),
                SimpleBackground(
                    color = (1,1,1),
                ),
            ],
            scale = (.5,.5,.5),
        )
    def OnImageSwitch( self, event=None ):
        """Choose a new mapped texture"""
        self.currentImage = currentImage = self.currentImage+1
        newImage = images[currentImage%len(images)]
        self.appearance.texture.url = [ newImage ]
        print "new image (loading) ->", newImage
    def OnSizeSwitch( self, event=None ):
        """Choose a new size"""
        self.currentSize = currentSize = self.currentSize+1
        newSize = cone_sizes[currentSize%len(cone_sizes)]
        self.cone.geometry.bottomRadius = newSize
        newSize = cone_sizes[(currentSize+1)%len(cone_sizes)]
        self.cone.geometry.height = newSize
        
        self.box.geometry.size = (newSize,newSize,newSize)
        self.cylinder.geometry.height = newSize
        self.cylinder.geometry.radius = newSize * .25
        self.gear.geometry.outer_radius = newSize * .25
        
        print "new size ->", newSize
        self.triggerRedraw(True)
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
