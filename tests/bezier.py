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
def weight_array( divisions ):
    assert divisions > 1, """Need at least 1 division"""
    step = 1.0/(divisions-1)
    return array([
        weights(1.0-a)
        for a in arange( 0.0, 1.0 + (.5 * step ), step, dtype='f' )
    ], dtype='f' )

def expand( points, divisions= 10, normals=False, texCoords=False, globalTexCoord=True ):
    """Expand points into the final data-set for positions...
    
    points -- array of 2N+1 x 2M+1 x 3 control points 
    divisions -- number of divisions for each 3x3 control-point area
    normals -- if True, auto-generate normals for the array...
    
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
    if normals:
        D += 3
        
    expanded = zeros( (final_count(M),final_count(N),D), dtype=points.dtype )
    #expanded[::divisions-1,::divisions-1] = points[::2,::2] 
    
    # expand control curves in one direction...
    # creates a new points array to be used for other direction...
    ws = weight_array( divisions )
    assert len(ws) == divisions, ws
    
    for m in range( 0, M-1, 2 ):
        m_final = (m//2) * divisions 
        for n in range( 0, N-1, 2 ):
            n_final = (n//2) * divisions
            curves = dot( ws, points[m:m+3,n:n+3] )
            # now get final points...
            verts = dot( ws, curves )
            expanded[ m_final:m_final+divisions, n_final:n_final+divisions,:3] = verts
    
    return expanded

def grid_indices( expanded ):
    """Create indices array to render expanded vertex array"""
    M,N = expanded.shape[:2]
    quads = (M-1) * (N-1)
    quadbases = arange( 0, quads, dtype='i')
    quadbases = quadbases.repeat( 6 )
    offsets = tile( array( [0,1,N,N,1,1+N], 'i' ), quads )
    return offsets + quadbases

class TestContext( BaseContext ):
    
    def OnInit( self ):
        """Create the scenegraph for rendering"""
        points = array([
            [(0,0,0), (1,0,0), (2,0,0), (3,-1,0),(4,0,0)],
            [(-5,0,1), (1,5,1), (2,0,1), (3,-2,0),(4,0,1),],
            [(0,0,2), (1,0,2), (2,0,2), (3,-1,2),(4,0,2)],
        ], 'f')
        points3 = expand( points )
        indices = grid_indices( points3 )
        
        self.sg = sceneGraph( children = [
            Shape( geometry = PointSet(
                coord = Coordinate( point = points ),
            )),
            Shape( 
                geometry = IndexedPolygons(
                    coord = Coordinate( point = points3 ),
                    index = indices,
                    color = Color(
                        color = [(1,0,0)]*len(indices),
                    ),
                ),
            ),
            
        ] )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
