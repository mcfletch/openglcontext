#! /usr/bin/env python
'''Sample showing manual evaluation of bezier spline patches
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
import string, time

from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph import bezier

class TestContext( BaseContext ):
    
    def OnInit( self ):
        """Create the scenegraph for rendering"""
        points = array([
            [(0,0,0), (1,0,0), (2,0,0), (3,-1,0),(4,0,0)],
            [(-5,0,1), (1,5,1), (2,0,1), (3,-2,0),(4,0,1),],
            [(0,0,2), (1,0,2), (2,0,2), (3,-1,2),(4,0,2)],
        ], 'f')
        points3 = bezier.expand( points)
        
        self.indices = bezier.grid_indices( points3 )
        self.normals = bezier.grid_normals( points3 )
        self.texCoords = bezier.grid_texcoords( points3 )
        
        self.sg = sceneGraph( children = [
            Shape( geometry = PointSet(
                coord = Coordinate( point = points ),
            ), appearance=Appearance( material=Material( emissiveColor=(1,0,0)))),
            
            Shape( 
                geometry = IndexedPolygons(
                    coord = Coordinate( point = points3 ),
                    normal = Normal( vector = self.normals ),
                    texCoord = TextureCoordinate( point = self.texCoords ),
                    index = self.indices,
                    solid = False,
                    ccw = False
                ),
                appearance = Appearance(
                    material = Material(),
                    texture = ImageTexture(
                        url = [ 'wrls/irradiation.jpg' ],
                    ),
                ),
            ),
            
        ] )
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
