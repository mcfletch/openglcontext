from OpenGLContext.atlas import AtlasManager,NumpyAdapter
from OpenGLContext.arrays import zeros, array, allclose, dot
import unittest

class TestAtlas( unittest.TestCase ):
	"""Tests for generic atlas algorithms"""
	def setUp( self ):
		self.atlasManager = AtlasManager( max_size=256 )
	
	def test_assignment( self ):
		"""Test that assignments go to the correct strips"""
		map = self.atlasManager.add( NumpyAdapter( zeros( (64,64,4),'B' )) )
		assert len(self.atlasManager.components) == 1
		assert len(self.atlasManager.components[4]) == 1
		atlas = self.atlasManager.components[4][0]
		assert map.atlas is atlas
		assert len(atlas.strips) == 1, len(atlas.strips)
		
		# this one should pack into the same strip
		map = self.atlasManager.add( NumpyAdapter( zeros( (64,64,4),'B' )) )
		assert len(self.atlasManager.components) == 1
		assert len(self.atlasManager.components[4]) == 1
		atlas = self.atlasManager.components[4][0]
		assert map.atlas is atlas
		assert len(atlas.strips) == 1, len(atlas.strips)
		
		# this one should pack into another strip
		map = self.atlasManager.add( NumpyAdapter( zeros( (32,32,4),'B' ) ))
		assert len(self.atlasManager.components) == 1
		assert len(self.atlasManager.components[4]) == 1
		atlas = self.atlasManager.components[4][0]
		assert map.atlas is atlas
		assert len(atlas.strips) == 2, len(atlas.strips)

	def test_matrix( self ):
		"""Test that a texture matrix can produce a proper scale/offset"""
		map = self.atlasManager.add( NumpyAdapter( zeros( (64,64,4),'B' ) ))
		matrix = map.matrix()
		assert matrix is not None 
		bottom_left = dot( array( [0,0,0,1],'f'), matrix )
		assert allclose( bottom_left, [0,0,0,1] ), bottom_left
		top_right = dot( array( [1,1,0,1],'f'), matrix )
		assert allclose( top_right, [.25,.25,0,1] ), top_right

		map = self.atlasManager.add( NumpyAdapter( zeros( (64,64,4),'B' ) ))
		matrix = map.matrix()
		assert matrix is not None 
		bottom_left = dot( array( [0,0,0,1],'f'), matrix )
		assert allclose( bottom_left, [.25,0,0,1] ), (bottom_left,matrix)
		top_right = dot( array( [1,1,0,1],'f'), matrix )
		assert allclose( top_right, [.5,.25,0,1] ), (top_right,matrix)

		set = dot( array( [[0,0,0,1],[1,1,0,1]],'f'), matrix )
		assert allclose( set, [[.25,0,0,1],[.5,.25,0,1]] ), (set,matrix)

	def test_release( self ):
		map = self.atlasManager.add( zeros( (64,64,4),'B' ) )
		del map
		print 'creating second'
		map2 = self.atlasManager.add( zeros( (64,64,4),'B' ) )
		assert map2.offset == (0,0), map2.offset
		
