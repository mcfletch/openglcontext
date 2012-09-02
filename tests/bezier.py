#! /usr/bin/env python
'''Sample showing manual evaluation of bezier spline patches
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
import string, time

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph import nurbs

def weights( a ):
    b = 1.0 - a
    return array([a**2, 2*a*b, b**2],dtype='f')
def epoint( a, cps ):
    """Evaluate a single position on control point float(a) between cps"""
    w = weights( a )
    return dot( w, cps )
def evaluate( cps, divisions = 10 ):
    step = 1.0/(divisions-1)
    for s in arange( 0.0, 1.0 + (.5 * step), step ):
        yield epoint( s, cps )

class TestContext( BaseContext ):
    
    def OnInit( self ):
        """Create the scenegraph for rendering"""
        points = array([
            [(0,0,0), (1,1,0), (2,0,0)],
            [(0,0,1), (1,2,1), (2,0,1)],
            [(0,0,2), (1,1,2), (2,0,2)],
        ], 'f')
        points2 = array( [list(evaluate(plane)) for plane in points], dtype='f' )
        points3 = array( [list(evaluate(plane)) for plane in transpose(points2,(1,0,2))], 'f')
        self.sg = sceneGraph( children = [
            Shape( geometry = PointSet(
                coord = Coordinate( point = points2 ),
            )),
            Shape( 
                geometry = PointSet(
                    coord = Coordinate( point = points3 ),
                    color = Color(
                        color = [(1,0,0)]*len(points3)*len(points3[0]),
                    ),
                ),
            ),
            
        ] )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
