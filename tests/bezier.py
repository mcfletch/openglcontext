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
def control_curves( points, divisions = 10 ):
    """Calculate control curves from control points"""
    return array( [
        list(evaluate(plane)) 
        for plane in points
    ], dtype='f' )
    
def patch( points, divisions = 10 ):
    """Convert the control points into a bezier patch with given sub-divisions"""
    # Convert the control points into control curves
    # For each step along the control curves, calculate the resulting curve
    return array( [
        list(evaluate(plane, divisions)) 
        for plane in transpose(
            control_curves(points,divisions),
            (1,0,2)
        )
    ], 'f')

class TestContext( BaseContext ):
    
    def OnInit( self ):
        """Create the scenegraph for rendering"""
        points = array([
            [(0,0,0), (1,0,0), (2,0,0)],
            [(0,0,1), (1,2,1), (2,0,1)],
            [(0,0,2), (1,0,2), (2,0,2)],
        ], 'f')
        points3 = patch( points )
        self.sg = sceneGraph( children = [
            Shape( geometry = PointSet(
                coord = Coordinate( point = points ),
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
