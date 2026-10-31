#! /usr/bin/env python
'''Simple demo of a rotating image mapped to a square
'''
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.events.timer import Timer
from OpenGL.GL import *
from OpenGLContext.arrays import array
import os
HERE = os.path.dirname(os.path.abspath(__file__))
NEHE = os.path.join( HERE, 'tutorials', 'nehe' )

scene = sceneGraph(
    children = [
        Transform(
            DEF = "pivot",
            children = [
                Shape(
                    geometry = IndexedFaceSet(
                        coord = Coordinate(
                            point = [[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]],
                        ),
                        coordIndex = [ 0,1,2,3 ],
                        texCoord = TextureCoordinate(
                            point = [[0,0],[1,0],[1,1],[0,1]],
                        ),
                        texCoordIndex = [0,1,2,3 ],
                    ),
                    appearance = Appearance(
                        texture = ImageTexture(
                            url = os.path.join( NEHE, "nehe_glass.bmp" ),
                        ),
                    ),
                )
            ],
        ),
        PointLight(
            location = (0,0,8),
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
    def OnTimerFraction( self, event ):
        """Modify the node"""
        self.trans.rotation = 0,0,1,(self.rot*event.fraction())
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
