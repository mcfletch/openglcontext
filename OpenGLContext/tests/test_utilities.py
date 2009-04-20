from OpenGLContext.arrays import *
from OpenGLContext.utilities import *
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
