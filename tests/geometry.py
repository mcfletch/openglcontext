#! /usr/bin/env python
'''Tests rendering of the Box geometry object
'''
import OpenGL
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL import *
from OpenGLContext.events.timer import Timer
from OpenGLContext.arrays import array, pi
import string, time

images = [
    "nehe_glass.bmp",
    "pimbackground_FR.jpg",
    "nehe_wall.bmp",
    "marbleface.jpeg",
    "wrls/irradiation.jpg",
    "wrls/yingyang.png",
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
                specularColor = (.5,.5,.5),
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
        self.teapot = Shape(
            geometry = Teapot(),
            appearance = self.appearance,
        )
        self.sphere = Shape(
            geometry = Sphere(),
            appearance = self.appearance,
        )
        self.ifs = Shape(
            geometry = IndexedFaceSet(
                coord = Coordinate(
                    point = [[-1,0,0],[1,0,0],[1,1,0],[-1,1,0]],
                ),
                coordIndex = [ 0,1,2,-1,0,2,3],
                color = Color(
                    color = [[0,0,1],[1,0,0]],
                ),
                colorIndex = [ 0,1,0,-1,0,0,1],
                solid = False,
                normalPerVertex=True,
            ),
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
                Transform(
                    translation = (0,-4,0),
                    children = [self.teapot],
                    scale = (.5,.5,.5),
                ),
                Transform(
                    translation = (4,-4,0),
                    children = [self.sphere],
                ),
                Transform(
                    translation = (-4,-4,0),
                    children = [self.ifs],
                ),
                SimpleBackground(
                    color = (.5,.5,.5),
                ),
            ],
            scale = (.75,.75,.75),
        )
        self.time = Timer( duration = 15.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
    def OnTimerFraction( self, event ):
        self.sg.rotation = array([0,1,0,event.fraction()*pi*2],'f')
        self.appearance.material.diffuseColor = [event.fraction()]*3
        self.triggerRedraw( False )
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
        self.teapot.geometry.size = newSize
        self.sphere.geometry.radius = newSize
        print "new size ->", newSize
        self.triggerRedraw(True)
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
