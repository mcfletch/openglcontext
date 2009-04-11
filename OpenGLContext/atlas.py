"""Texture atlas implementation"""
import math 
from OpenGL.GL import glGetIntegerv, GL_MAX_TEXTURE_SIZE
from OpenGLContext.arrays import zeros, array, dot

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
		x,y,d = array.shape
		assert local.shape[0] - (self.width+x) >= 0
		assert local.shape[1] - (self.yoffset+y) >= 0
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
				(s.width + x <= max_x)
			) 
		]
		for strip in candidates:
			if strip.height == y:
				return strip 
		for strip in candidates:
			strip_mag = math.floor(math.log( strip.height, 2 ))
			img_mag = math.floor(math.log( y, 2 ))
			if strip_mag == img_mag:
				return strip 
		if self.strips:
			last = self.strips[-1]
			current_height = last.yoffset + last.height 
		else:
			current_height = 0
		if current_height + y > max_y:
			raise AtlasError( """Insufficient space to store in this atlas""" )
		strip = _Strip( self, height=y, yoffset= current_height )
		self.strips.append( strip )
		return strip
	
	def size( self ):
		if self._size is None:
			x = y = self.max_size
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
	_uploaded = False
	def __init__( self, atlas, offset, size, array ):
		self.atlas = atlas 
		self.offset = offset 
		self.size = size
		self.array = array
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
		
	def update( self, array ):
		"""Update our texture with the new data in array"""
		self._uploaded = False 
		assert array.size == self.array.size 
		self.array = array 

class AtlasManager( object ):
	"""Collection of atlases within the renderer"""
	def __init__( self, max_size=4096, max_child_size=128 ):
		self.components = {}
		self.max_size = max_size
		self.max_child_size = max_child_size
	def add( self, array ):
		"""Add the given array to the texture atlas"""
		x,y,d = array.shape
		if x > self.max_child_size:
			raise AtlasError( """X size (%s) > %s"""%( x,self.max_child_size ) )
		if y > self.max_child_size:
			raise AtlasError( """Y size (%s) > %s"""%( y,self.max_child_size ) )
		atlases = self.components.setdefault( d, [])
		for atlas in atlases:
			try:
				return atlas.add( array )
			except AtlasError, err:
				pass 
		atlas = Atlas( d, max_size=self.max_size or self.calculate_max_size() )
		atlases.append( atlas )
		return atlas.add( array )
	_MAX_MAX_SIZE = 4096
	def calculate_max_size( self ):
		"""Calculate the maximum size of a texture
		
		Note that this might, for instance, assume a
		single-component texture or some similarly inappropriate
		value...
		"""
		self.max_size = min( (glGetIntegerv(GL_MAX_TEXTURE_SIZE), self._MAX_MAX_SIZE) )
		return self.max_size
