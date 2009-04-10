#! /usr/bin/env python
'''Test of texture atlas behaviour...'''
from OpenGL.GL import *
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
import _fontstyles
import sys
from OpenGLContext.scenegraph.text import pygamefont, fontprovider
from OpenGLContext.arrays import zeros, array

class _Strip( object ):
	"""Strip within the atlas which takes particular set of images"""
	def __init__( self, atlas, height, yoffset ):
		"""Sets up the strip to receive images"""
		self.atlas = atlas
		self.height = height 
		self.width = 0
		self.full = False
		self.yoffset = yoffset
		self.maps = []
	def add( self, array ):
		"""Add the given numpy array to our atlas' image"""
		local = self.atlas.local( )
		x,y,d = array.size
		assert local.shape[0] - (self.width+x) >= 0
		assert local.shape[1] - (self.offset+y) >= 0
		local[ self.width:self.width+x,self.yoffset:self.yoffset+y,:] = array 
		array = local[ self.width:self.width+x,self.yoffset:self.yoffset+y,:]
		# array now points to the value as a sub-array
		offset = (self.width,self.yoffset)
		self.width += x
		if self.width >= local.shape[0]:
			self.full = True 
		map = Map( self.atlas, offset, (x,y), array )
		return map

class AtlasError( Exception ):
	"""Raised when we can't/shouldn't append to this atlas"""
	

class Atlas( object ):
	_local = None
	_size = None
	_MAX_MAX_SIZE = 4096
	_MAX_CHILD_SIZE = 128
	def __init__( self, components=4, dataType='B' ):
		self.components = components
		self.dataType = dataType
		self.strips = []
		self.maps = []
	
	def add( self, array ):
		"""Insert a numpy array of values as a sub-texture
		
		Has to find a place within the atlas to insert the 
		sub-texture and then return the offset/scale factors...
		"""
		local = self.local()
		max_x,max_y,components = local.shape 
		x,y,d = array.shape 
		assert d == components, """Adding texture to atlas with different number of components"""
		strip = self.choose_strip( max_x, max_y, x, y )
		return strip.add( array )
	def choose_strip( self, max_x,max_y, x,y ):
		"""Find the strip to which we should be added"""
		candidates = [ 
			s 
			for s in self.strips 
			if (
				not s.full and 
				s.height >= y and 
				(strip.width + x <= max_x)
			) 
		]
		for strip in candidates:
			if strip.height == y:
				return strip 
		for strip in candidates:
			if math.floor(math.log( strip.height, 2 )) == math.floor(math.log( strip.height, 2 )):
				return strip 
		last = self.strips[-1]
		current_height = last.yoffset + last.height 
		if current_height + y > max_y:
			raise AtlasError( """Insufficient space to store in this atlas""" )
		strip = _Strip( self, height=y, yoffset= current_height )
		return strip
	
	def max_size( self ):
		"""Calculate the maximum size of a texture
		
		Note that this might, for instance, assume a
		single-component texture or some similarly inappropriate
		value...
		"""
		return min( (glGetIntegerv(GL_MAX_TEXTURE_SIZE), self._MAX_MAX_SIZE) )
	def size( self ):
		if self._size is None:
			x = y = self.max_size( )
			self._size = (x,y,self.components)
		return self._size
	def local( self ):
		"""Set up our local array for storage"""
		if self._local is None:
			self._local = zeros( self.size(), self.dataType )
		return self._local
	
	def render( self, mode=None ):
		"""Render this texture to the context"""
		local = self.local( )
		return local
	def bind( self, mode=None ):
		"""Bind this texture for use on mode"""
		# need to check each map for dirty status 
		# update any dirty maps 
		# then do a regular bind with our texture...
		

class Map( object ):
	"""Object representing a sub-texture within a texture atlas"""
	_matrix = None
	def __init__( self, atlas, offset, size, array ):
		self.atlas = atlas 
		self.offset = offset 
		self.size = size
		self.array = array
		self.matrix = self.matrix()
	def matrix( self ):
		"""Calculate a 2x2 transform matrix for texcoords"""
		# translate by self.offset/atlas.size
		# scale by self.size/atlas.size

class TestContext( BaseContext ):
	def OnInit( self ):
		"""Initialize the texture atlas test"""
		self.atlas = Atlas()
	def Render( self, mode=None ):
		print self.atlas.local(mode).shape
	def setupFontProviders( self ):
		"""Load font providers for the context

		See the OpenGLContext.scenegraph.text package for the
		available font providers.
		"""
		fontprovider.setTTFRegistry(
			self.getTTFFiles(),
		)
	testingClass = pygamefont.PyGameBitmapFont
if __name__ == "__main__":
	MainFunction ( TestContext )


