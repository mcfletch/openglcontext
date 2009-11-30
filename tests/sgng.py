#! /usr/bin/env python
'''Simple demo of a rotating image mapped to a square
'''
import OpenGL 
OpenGL.ERROR_CHECKING = False 
OpenGL.STORE_POINTERS = False 
OpenGL.ERROR_ON_COPY = True

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph import nodepath
from OpenGLContext import visitor
from OpenGLContext.events.timer import Timer
from OpenGL.GL import *
from OpenGLContext.arrays import array, dot
from OpenGLContext.passes import flat
from vrml.vrml97 import nodetypes
from vrml import olist
from vrml.vrml97.transformmatrix import RADTODEG
import weakref,random
from pydispatch.dispatcher import connect

scene = sceneGraph(
    children = [
        Transform(
            DEF = "pivot",
            children = [
                Switch(
                    whichChoice = 0,
                    choice = [
                        Shape(
                            geometry = IndexedFaceSet(
                                coord = Coordinate(
                                    point = [
                                        [-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]
                                    ],
                                ),
                                coordIndex = [ 0,1,2,-1,0,2,3 ],
                                texCoord = TextureCoordinate(
                                    point = [[0,0],[1,0],[1,1],[0,1]],
                                ),
                                texCoordIndex = [0,1,2,-1,0,2,3 ],
                            ),
                            appearance = Appearance(
                                texture = ImageTexture(
                                    url = "nehe_glass.bmp",
                                ),
                            ),
                        ),
                        Shape(
                            geometry = Teapot(),
                            appearance = Appearance(
                                texture = ImageTexture(
                                    url = "nehe_glass.bmp",
                                ),
                            ),
                        ),
                    ],
                ),
            ],
        ),
        PointLight(
            color = (1,0,0),
            location = (4,4,8),
        ),
        Group(),
        CubeBackground(
            backUrl = "pimbackground_BK.jpg",
            frontUrl = "pimbackground_FR.jpg",
            leftUrl = "pimbackground_RT.jpg",
            rightUrl = "pimbackground_LF.jpg",
            topUrl = "pimbackground_UP.jpg",
            bottomUrl = "pimbackground_DN.jpg",
        ),
    ],
)

        

class TestContext( BaseContext ):
    rot = 6.283
    initialPosition = (0,0,3)
    def OnInit( self ):
        self.sg = scene
        self.trans = self.sg.children[0]
        self.time = Timer( duration = 8.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
        self.addEventHandler( "keypress", name="a", function = self.OnAdd)
        glEnable( GL_CULL_FACE )
        glFrontFace( GL_CCW )
    def OnTimerFraction( self, event ):
        """Modify the node"""
        self.trans.rotation = 0,0,1,(self.rot*event.fraction())
    def OnAdd( self, event ):
        """Add a new box to the scene"""
        children = scene.children[2].children
        if len(children) > 20:
            children[:] = []
        else:
            cube = 10
            position = ( 
                (random.random()-.5)*cube,
                (random.random()-.5)*cube,
                (random.random()-.5)*cube 
            )
            color = (random.random(),random.random(),random.random())
            children.append( Transform(
                translation = position,
                children = [
                    Shape(
                        geometry = Box( size=(.4,.4,.4) ), #Teapot( size=.2),
                        appearance = Appearance(
                            material=Material( 
#								diffuseColor = color,
                                diffuseColor = (.8,.8,.8),
                            ),
                            texture = ImageTexture(
                                url = ["pimbackground_FR.jpg"]
                            ),
                        ),
                    ),
                ],
            ))

if __name__ == "__main__":
    from OpenGLContext.passes import renderpass 
    import sys
    if sys.argv[1:]:
        name = 'old.profile'
        renderpass.USE_FLAT = False
    else:
        name = 'new.profile'
    import cProfile
    cProfile.run( "TestContext.ContextMainLoop()", name )

