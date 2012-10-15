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

def weight_array( divisions ):
    assert divisions > 1, """Need at least 1 division"""
    step = 1.0/(divisions-1)
    return array([
        weights(1.0-a)
        for a in arange( 0.0, 1.0 + (.5 * step ), step, dtype='f' )
    ], dtype='f' )
    
def expand( points, divisions= 10 ):
    """Expand points into the final data-set for positions...
    
    3N * 3M array of control points 
        CP <divisions> CP 
        <divisions>
        CP <divisions> CP
    
    return the array 
    """
    def final_count( M ):
        return ((M - 1)//2 * divisions-1) + 1
    M,N,D = points.shape
    assert D in (3,4), """Need a 3 or 4 element point-set"""
    expanded = zeros( (final_count(M),final_count(N),D), dtype=points.dtype )
    expanded[::divisions-1,::divisions-1] = points[::2,::2] 
    
    # expand control curves in one direction...
    # creates a new points array to be used for other direction...
    ws = weight_array( divisions )
    assert len(ws) == divisions, ws
    
    for m in range( 0, M-1, 2 ):
        m_final = m * divisions 
        for n in range( 0, N-1, 2 ):
            n_final = n * divisions
            curves = dot( ws, points[m:m+3,n:n+3] )
            # now get final points...
            verts = dot( ws, curves )
            expanded[ m_final:m_final+divisions, n_final:n_final+divisions,:] = verts
    
    return expanded

class TestContext( BaseContext ):
    
    def OnInit( self ):
        """Create the scenegraph for rendering"""
        points = array([
            [(0,0,0), (1,0,0), (2,0,0)],
            [(-5,0,1), (1,5,1), (2,0,1)],
            [(0,0,2), (1,0,2), (2,0,2)],
        ], 'f')
        points3 = patch( points )
        expanded = expand( points )
        assert points3.shape == expanded.shape, (points3.shape, expanded.shape)
        assert allclose( expanded[::9,::9], points[::2,::2])
        ws = weight_array( 10 )
        points = expanded
        
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
