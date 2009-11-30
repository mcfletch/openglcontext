#! /usr/bin/env python
'''IndexedFaceSet object test

Lowest-level test for IFS operation, just creates
a simple IFS and displays it.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *

class TestContext( BaseContext ):
    initialPosition = (0,0,3) # set initial camera position, tutorial does the re-positioning
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        self.shape.Render( mode )
    def OnInit( self ):
        print """Should see multicolor rectangular IFS over white background
    Should fade from red on upper left and lower right corners
    to blue across lower left and upper right corners.
    There should be no lighting applied to the geometry."""
        self.shape = Shape(
            geometry = IndexedFaceSet(
                coord = Coordinate(
                    point = [[-1,0,0],[1,0,0],[1,1,0],[-1,1,0]],
                ),
                coordIndex = [ 0,1,2,-1,0,2,3],
                color = Color(
                    color = [[0,0,1],[1,0,0]],
                ),
                colorIndex = [ 0,1,0,-1,0,0,1],
            ),
        )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
