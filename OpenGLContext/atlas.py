"""Texture atlas implementation"""
import math, weakref
from OpenGL.GL import *
from OpenGLContext.arrays import zeros, array, dot
from OpenGLContext import texture

class NumpyAdapter( object ):
	def __init__( self, array ):
		self.size = array.shape[:-1]
		if array.shape[-1] == 3:
			self.mode = 'RGB'
		elif array.shape[-1] == 4:
			self.mode = 'RGBA'
		elif array.shape[-1] == 2:
			self.mode = 'LA'
		else:
			self.mode = 'L'

class _Strip( object ):
	"""Strip within the atlas which takes particular set of images"""
	def __init__( self, atlas, height, yoffset ):
		"""Sets up the strip to receive images"""
		self.atlas = atlas
		self.height = height 
		self.width = 0
		self.yoffset = yoffset
		self.maps = []
	def start_coord( self, x ):
		"""Do we have an empty space sufficient to fit image of width x?
		
		return starting coordinate or -1 if not enough space...
		"""
		last = 0
		for map in self.maps:
			referenced = map()
			if referenced is not None:
				if referenced.offset[0]-last >= x:
					return last
				else:
					last = referenced.offset[0]+referenced.size[0]
		if self.atlas.max_size-last >= x:
			return last 
		return -1
	def add( self, image, start=None ):
		"""Add the given numpy array to our atlas' image"""
		x,y = image.size
		if start is None:
			start = self.start_coord( x )
		offset = (start,self.yoffset)
		map = Map( self.atlas, offset, (x,y), image )
		self.maps.append( weakref.ref( map, self._remover( offset )) )
		return map
	def _remover( self, offset ):
		def remover( *args ):
			self.onRemove( )
		return remover 
	def onRemove( self, *args, **named ):
		"""Remove map by offset (normally a weakref-release callback)"""
		update = False
		for mapRef in self.maps:
			referenced = mapRef()
			if referenced is None:
				try:
					self.maps.remove( mapRef )
				except ValueError, err:
					pass 
				update = True 

class AtlasError( Exception ):
	"""Raised when we can't/shouldn't append to this atlas"""
	

class Atlas( object ):
	"""Collection of textures packed into a single texture
	
	Texture atlases allow the rendering engine to reduce the 
	number of state-changes which occur during the rendering 
	process.  They pack a large number of small textures into 
	a single large texture, producing offset/scale matrices to 
	use for modifying texture coordinates to map from the
	original to the packed coordinates.
	"""
	_local = None
	_size = None
	def __init__( self, components=4, dataType='B', max_size=4096 ):
		self.components = components
		self.dataType = dataType
		self.strips = []
		self.max_size = max_size
		self.need_updates = []
	
	def add( self, image ):
		"""Insert a PIL image of values as a sub-texture
		
		Has to find a place within the atlas to insert the 
		sub-texture and then return the offset/scale factors...
		"""
		max_x = max_y = self.max_size
		x,y = image.size 
		strip,start = self.choose_strip( max_x, max_y, x, y )
		return strip.add( image, start=start )
	def choose_strip( self, max_x,max_y, x,y ):
		"""Find the strip to which we should be added"""
		candidates = [ 
			s 
			for s in self.strips 
			if (
				s.height >= y
			) 
		]
		for strip in candidates:
			if strip.height == y:
				start = strip.start_coord( x )
				if start > -1:
					return strip, start
		for strip in candidates:
			strip_mag = math.floor(math.log( strip.height, 2 ))
			img_mag = math.floor(math.log( y, 2 ))
			if strip_mag == img_mag:
				start = strip.start_coord( x )
				if start > -1:
					return strip, start
		if self.strips:
			last = self.strips[-1]
			current_height = last.yoffset + last.height 
		else:
			current_height = 0
		if current_height + y > max_y:
			raise AtlasError( """Insufficient space to store in this atlas""" )
		strip = _Strip( self, height=y, yoffset= current_height )
		self.strips.append( strip )
		start = strip.start_coord( x )
		return strip, start
	
	def size( self ):
		if self._size is None:
			x = y = self.max_size
			self._size = (x,y,self.components)
		return self._size
	
	def render( self, mode=None ):
		"""Render this texture to the context"""
		tex = self.bind( mode )
		needs = self.need_updates[:]
		del self.need_updates[:len(needs)]
		for need in needs:
			need.update( tex )
		return result
	
	def bind( self, mode=None ):
		"""Bind this texture for use on mode"""
		tex = mode.cache.getData(self)
		if not tex:
			tex = self.compile( mode=mode )
		return tex
	def compile( self, mode=None ):
		# enable the texture...
		tex( )
		# need to check each map for dirty status 
		# update any dirty maps 
		# then do a regular bind with our texture...
		format = [0, GL_LUMINANCE, GL_LUMINANCE_ALPHA, GL_RGB, GL_RGBA ][self.components]
		tex = texture.Texture( format=format )
		x,y,d = self.size()
		# empty init...
		tex.store( self.components, format, x,y, None )
		holder = mode.cache.holder(self, tex)
		return tex

class Map( object ):
	"""Object representing a sub-texture within a texture atlas"""
	_matrix = None
	_uploaded = False
	def __init__( self, atlas, offset, size, image ):
		self.atlas = atlas 
		self.offset = offset 
		self.size = size
		self.image = image
	def matrix( self ):
		"""Calculate a 3x3 transform matrix for texcoords
		
		To manipulate texture coordinates with this matrix 
		they need to be in homogenous coordinates, i.e. a 
		"regular" 2d coordinate of (x,y) becomes (x,y,1.0)
		so that it can pick up the translations.
		
		dot( coord, matrix ) produces the transformed 
		coordinate for processing.
		
		returns 3x3
		"""
		if self._matrix is None:
			# translate by self.offset/atlas.size
			# scale by self.size/atlas.size
			tx,ty,d = self.atlas.size()
			tx,ty = float(tx),float(ty)
			x,y = self.offset
			translate = array([
				[1,0,0],
				[0,1,0],
				[x/tx,y/ty,1],
			],'f')
			x,y = self.size 
			scale = array([
				[x/tx,0,0],
				[0,y/tx,0],
				[0,0,1],
			],'f')
			self._matrix = dot( scale, translate )
		return self._matrix
	
	def update( self, tex ):
		"""Update our texture with the new data in image"""
		tex.update( self.offset, self.size, self.image )
		self._uploaded = True
		assert image.size == self.image.size 
		self.image = image 

class AtlasManager( object ):
	"""Collection of atlases within the renderer"""
	def __init__( self, max_size=4096, max_child_size=128 ):
		self.components = {}
		self.max_size = max_size
		self.max_child_size = max_child_size
	FORMAT_MAPPING = {
		'L':(1,GL_LUMINANCE), 
		'LA':(2,GL_LUMINANCE_ALPHA),
		'RGB':(3,GL_RGB),
		'RGBA':(4,GL_RGBA),
	}
	def formatToComponents( self, format ):
		"""Convert PIL format to component count"""
		return self.FORMAT_MAPPING[ format ][0]
	def add( self, image ):
		"""Add the given image to the texture atlas"""
		x,y = image.size
		if x > self.max_child_size:
			raise AtlasError( """X size (%s) > %s"""%( x,self.max_child_size ) )
		if y > self.max_child_size:
			raise AtlasError( """Y size (%s) > %s"""%( y,self.max_child_size ) )
		d = self.formatToComponents( image.mode )
		atlases = self.components.setdefault( d, [])
		for atlas in atlases:
			try:
				return atlas.add( image )
			except AtlasError, err:
				pass 
		atlas = Atlas( d, max_size=self.max_size or self.calculate_max_size() )
		atlases.append( atlas )
		return atlas.add( image )
	_MAX_MAX_SIZE = 4096
	def calculate_max_size( self ):
		"""Calculate the maximum size of a texture
		
		Note that this might, for instance, assume a
		single-component texture or some similarly inappropriate
		value...
		"""
		self.max_size = min( (glGetIntegerv(GL_MAX_TEXTURE_SIZE), self._MAX_MAX_SIZE) )
		return self.max_size
