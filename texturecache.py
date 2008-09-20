"""Cache of compiled textures for a context"""
class TextureCache( dict ):
	"""Cache ID: texture-object mapping

	XXX
		I think there should be one of these per-context,
		but as of yet, there's just the one instance. Will
		need to pass in the mode to the render functions to
		make per-context caches viable.
	"""
	def getTexture( self, pil, textureClass ):
		"""Get a texture for the given pil image and textureClass"""
		ID = pil.info[ 'url' ]
		current = self.get( ID )
		if current:
			return current
		self[ID] = current = textureClass(pil)
		return current
