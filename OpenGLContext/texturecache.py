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
    def getTexture( self, pil, textureClass, mode=None, repeating=False,
                    atlasable=True ):
        """Get a texture for the given pil image and textureClass

        repeating -- a texture that tiles cannot share an atlas page with its
            neighbours, so it gets one of its own
        atlasable -- whether an atlas page is acceptable at all.  A page is a
            sub-rectangle of a larger texture, so sampling it needs the
            texture-coordinate transform that places it, which the
            fixed-function pipeline carries on its texture matrix stack.  A
            shader has no such stack, so a caller drawing through one asks for
            a texture of its own.
        """
        current = None
        if hasattr( pil, 'info' ):
            ID = pil.info.get('url')
        else:
            ID = None
            # don't have a URL, can't cache...
        key = (ID, repeating, atlasable)
        if ID is not None:
            current = self.textures.get( key )
            if current:
                return current
        if repeating or not atlasable:
            current = textureClass(pil)
        else:
            try:
                current =  self.atlases.add( pil )
            except atlas.AtlasError:
                current = textureClass(pil)
        if ID is not None and current is not None:
            self.textures[key] = current
        return current
