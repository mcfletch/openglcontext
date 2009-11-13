from OpenGLContext.arrays import *
from OpenGLContext.utilities import *
from OpenGLContext.vectorutilities import *
import unittest

class TestUtilities( unittest.TestCase ):
    """Tests for generic atlas algorithms"""
    def test_plane2PointNormal( self ):
        for p,n in [
            ([0,1,0], [0,-1,0]),
            ([1,0,0], [1,0,0]),
            ([0,0,1], [0,0,1]),
        ]:
            plane = pointNormal2Plane(p,n)
            p1,n1 = plane2PointNormal(plane)
            assert allclose( p, p1)
            assert allclose(n, n1)
    def test_coplanar( self ):
        assert coplanar( [[0,0,1],[0,1,1],[0,1,2],[0,1,3],[0,0,1],[0,1,1]] )
        assert not coplanar( [[0,0,1],[0,1,1],[0,1,2],[0,1,3],[0,0,1],[1,1,1]] )
        assert not coplanar( [[0,0,1],[1,1,1],[0,1,2],[0,1,3],[0,0,1],[0,1,1]] )
        assert not coplanar( [[0,0,1.005],[1,1,1],[0,1,2],[0,1,3],[0,0,1],[0,1,1]] )

    def test_magnitude( self ):
        data = array( [
            [0,0,0],[1,0,0],[0,1,0],
            [1,0,0],[0,0,0],[0,1,0],
        ],'f')
        mag = magnitude( data )
        assert allclose( mag, [0,1,1,1,0,1] ), mag
    def test_normalize( self ):
        data = array( [
            [2,0,0],[0,2,0],[0,0,2],
            [1,1,0],[-1,1,0],
        ], 'f')
        norms = normalise( data )
        
        self._allclose( norms, array([
            [1,0,0],[0,1,0],[0,0,1],
            [1/sqrt(2),1/sqrt(2),0],[-1/sqrt(2),1/sqrt(2),0],
        ],'f') )
    def test_normalize_zero( self ):
        data = array( [[ 0,0,0 ]],'f')
        result = normalise( data )
        assert allclose( result, [[0,0,0]] )
    def test_crossProduct( self ):
        data = array([
            [0,1,0],[1,0,0],[0,0,1],
            [1,1,0],
        ],'f')
        cps = crossProduct( data, [-1,0,0] )
        expected = array([
            [0,0,1],[0,0,0],[0,-1,0],
            [0,0,1],
        ],'f')
        self._allclose( cps, expected )
    def _allclose( self, target, expected ):
        for a,b in zip( target, expected ):
            assert allclose( a,b),(a,b)
        
    def test_orientToXYZR( self ):
        """Can we do an orientation-to-xyzr rotation properly?"""
        a = (0,0,-1 )
        b = (1,0,0 )
        expected = [(0,1,0,-pi/2),(0,-1,0,pi/2)]
        xyzr = orientToXYZR( a,b )
        found = False 
        for e in expected:
            if allclose( e, xyzr ):
                found = True 
                break 
        assert found, xyzr
    
