"""Cache of compiled textures for a context"""
import weakref
from OpenGLContext import atlas
class TextureCache( object ):
	"""Cache ID: texture-object mapping

	XXX
		I think there should be one of these per-context,
		but as of yet, there's just the one instance. Will
		need to pass in the mode to the render functions to
		make per-context caches viable.
	"""
	def __init__( self, atlasSize=None ):
		self.textures = weakref.WeakValueDictionary()
		self.atlases = atlas.AtlasManager( max_size = atlasSize )
	def getTexture( self, pil, textureClass, mode=None ):
		"""Get a texture for the given pil image and textureClass"""
		if hasattr( pil, 'info' ):
			ID = pil.info.get('url')
			if ID is not None:
				current = self.textures.get( ID )
				if current:
					return current
			try:
				self.textures[ID] = current =  self.atlases.add( pil )
			except atlas.AtlasError, err:
				self.textures[ID] = current = textureClass(pil)
		else:
			# don't have a URL, can't cache...
			try:
				current =  self.atlases.add( pil )
			except atlas.AtlasError, err:
				current = textureClass(pil)
		return current
	
