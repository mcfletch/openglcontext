#! /usr/bin/env python
'''Tests operation of SimpleBackground object -> solid color background
'''
from __future__ import print_function
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *

class TestContext( BaseContext ):
    """Tests the SimpleBackground object's rendering.
    """
    def OnInit( self ):
        """Scene set up and initial processing"""
        print('You should see a white/gray triangle over a blue background')
        self.sg = sceneGraph(
            children = [
                SimpleBackground( color = (0,0,1) ),
                Shape(
                    geometry = IndexedFaceSet(
                        coord = Coordinate(
                            point = [[0,1,0],[-1,-1,0],[1,-1,0]],
                        ),
                        coordIndex = [0,1,2]
                    ),
                ),
            ],
        )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
