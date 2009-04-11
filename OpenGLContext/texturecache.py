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
	textures = weakref.WeakValueDictionary()
	atlases = atlas.AtlasManager( max_size = 256)
	def getTexture( self, pil, textureClass, mode=None ):
		"""Get a texture for the given pil image and textureClass"""
		ID = pil.info[ 'url' ]
		current = self.textures.get( ID )
		if current:
			return current
		try:
			self.textures[ID] = current =  self.atlases.add( pil )
		except atlas.AtlasManager, err:
			self.textures[ID] = current = textureClass(pil)
		return current
	
