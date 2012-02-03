"""ImageTexture and MMImageTexture nodes using PIL
"""
from OpenGL.GL import *
from OpenGL.GLU import *
import traceback
from OpenGLContext import texture, context
from vrml import cache
from vrml.vrml97 import basenodes, nodetypes
from vrml import node, field, protofunctions, fieldtypes
import logging 
log = logging.getLogger( __name__ )

class _Texture( nodetypes.Texture, node.Node ):
    """Mix-in for rendering static image textures
    """
    minFilter = field.newField(
        ' minFilter', 'SFInt32', 0, GL_NEAREST
    )
    magFilter = field.newField(
        ' magFilter', 'SFInt32', 0, GL_NEAREST
    )
    components = field.newField(
        ' components', 'SFInt32', 1, 0
    )
    def compile( self, mode=None ):
        """Compile (store our image in an OpenGL texture)"""
        tex = self.createTexture( self.image, mode=mode )
        # cache this for later use...
        holder = mode.cache.holder(self, tex)
        holder.depend( self, 'image' )
        if tex is not None:
            self.components = tex.components
        else:
            self.components = 0
        return tex
    def createTexture( self, image, mode=None ):
        """Create a new texture-holding object

        Uses the TextureCache to try to minimise the
        number of textures created
        """
        return mode.context.textureCache.getTexture( 
            image, texture.Texture, mode=mode ,
            repeating = (self.repeatS or self.repeatT)
        )

    def render (
            self,
            visible = 1,
            lit = 1,
            mode = None, # the renderpass object for which we compile
        ):
        """Called by Shape before rendering associated geometry

        visible -- whether a visible rendering pass,
            if not, no normals, colours, or textures
        lit -- whether lighting is enabled, if not, no normals

        returns whether this is a transparent texture
            0 if non-transparent, but a valid texture
            1 if transparent
            None if not yet a valid texture
        """
        if not visible:
            return None
        tex = self.cached( mode )
        if tex:
            if mode.transparent:
                # there is an alpha component...
                glEnable (GL_BLEND)
                glBlendFunc (GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
            elif self.transparent(mode):
                return 1
            tex( )
            # now the stuff not related to the texture in particular
            # i.e. the "image" half of the image texture
            if self.repeatS:
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
            else:
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP)
            if self.repeatT:
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
            else:
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP)
            glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, self.magFilter )
            glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, self.minFilter )
            ### XXX something get's messed up heavily if we actually report the alpha channel's existence :(
            return 0
        return 0
    
    def renderPost(self, mode=None):
        """Called after rendering geometry to disable the texture

        Note: this does *not* disable the blend mode we established, it
        is left to the mode's post-rendering code to do this!  As a result,
        if you use this code outside of a scenegraph you will need to add
        a call to reestablish the blending parameters you desire.
        """
        try:
            glDisable( GL_TEXTURE_2D )
            glMatrixMode( GL_TEXTURE )
            try:
                glLoadIdentity()
            finally:
                glMatrixMode( GL_MODELVIEW )
        except GLerror:
            if glGetBoolean( GL_TEXTURE_2D ):
                log.error( """Unable to disable GL_TEXTURE_2D for node %s""", self )
                
    def cached( self, mode=None ):
        """Retrieve cached texture for this mode"""
        try:
            if not self.image:
                return None 
        except ValueError, err:
            if not len(self.image):
                return None
        tex = mode.cache.getData(self)
        if not tex:
            tex = self.compile( mode=mode )
        return tex
    def transparent( self, mode=None ):
        """Does this texture have an alpha component?"""
        tex = self.cached( mode )
        if tex:
            return tex.components in (2,4)
        return 0
    @classmethod
    def forTexture( cls, tex, mode ):
        """Create a fake image texture node for the given on-card texture object"""
        instance = cls(
            image = Image.new(
                texture.NumpyAdapter.shapeToMode( tex.components ),
                (1,1), '#ff00ff'
            )
        )
        holder = mode.cache.holder(instance, tex)
        return instance

try:
    try:
        from PIL import Image
    except ImportError, err:
        # old style?
        import Image
    from ImageFile import Parser
    log.info( """Loaded Python Image Library (PIL)""" )
except ImportError:
    log.warn( """Python Image Library (PIL) not installed, no Image support available
http://www.pythonware.com/products/pil/index.htm""" )
    class ImageTexture(basenodes.ImageTexture):
        """Dummy/stand-in when no PIL available (does nothing)
        """
        components = field.newField(
            ' components', 'SFInt32', 1, 0
        )
        def render (
                self,
                # Effectively the rendering mode
                visible = 1, # whether a visible rendering pass, if not, no normals, colours, or textures
                # Arguments which the shape controls
                lit = 1, # whether lighting is enabled, if not, no normals
                mode = None, # the renderpass object for which we compile
            ):
            """Pretend to render the image texture"""
            return 1
        def renderPost(self, mode=None ):
            """Pretend to shut down after rendering"""

else:
    class PILImage( field.Field ):
        """Simple field-type for holding PIL image objects"""
        def defaultDefault( self ):
            """Get a default PIL image object"""
            return Image.new('RGB', (1,1), (255,0,0))
        defaultDefault = classmethod( defaultDefault )


    class ImageURLField( fieldtypes.MFString ):
        """Field for managing interactions with an Image's URL value"""
        fieldType = "MFString"
        def __set__( self, client, value, notify=True ):
            """Set the client's URL, then try to load the image"""
            value = super(ImageURLField, self).fset( client, value, notify=True )
            import threading
            threading.Thread(
                name = "Background load of %s"%(value),
                target = client.loadBackground,
                args = ( value, context.Context.allContexts,),
            ).start()
            return value
        fset = __set__
        def fdel( self, client, notify=1 ):
            """Delete the client's URL, which should delete the image as well"""
            value = super( ImageURLField, self).fdel( client, notify )
            del client.image
            return value
        __del__ = fdel

    class ImageTexture( _Texture, basenodes.ImageTexture ):
        """A texture loaded from an image file
        """
        image = PILImage(
            ' image', 1, None
        )
        url = ImageURLField(
            'url', 1, list
        )
        def loadBackground( self, url, contexts=() ):
            """Load an image from the given url in the background

            url -- SF or MFString URL to load relative to the
                node's root's baseURL

            On success:
                Sets the resulting PIL image to the
                client's image property (triggering an un-caching
                and re-compile if there was a previous image).

                if contexts, iterate through the list calling
                context.triggerRedraw(1)
            """
            from OpenGLContext.loaders.loader import Loader
            try:
                baseNode = protofunctions.root(self)
                if baseNode:
                    baseURI = baseNode.baseURI
                else:
                    baseURI = None
                result = Loader( url, baseURL = baseURI )
            except IOError:
                pass
            else:
                if result:
                    baseURL, filename, file, headers = result
                    image = Image.open( file )
                    image.info[ 'url' ] = baseURL
                    image.info[ 'filename' ] = filename
                        
                    if image:
                        self.image = image
                        self.components = -1
                        for context in contexts:
                            c = context()
                            if c:
                                c.triggerRedraw(1)
                        return
            
            # should set client.image to something here to indicate
            # failure to the user.
            log.warn( """Unable to load any image from the url %s for the node %s""", url, str(self))
        def loadFromData( self, data, url=None ):
            """Load (synchronously) from given data"""
            import StringIO
            fh = StringIO.StringIO( data )
            if url is None:
                url = 'memory:%s'%(hash( data ),)
            try:
                image = Image.open( fh )
            except IOError, err:
                log.info( 'IOError %s opening image', err )
            else:
                if image:
                    self.image = image
                    self.image.info['url'] = str(url)
                    self.image.info['file'] = 'memory'
                    self.components = -1
                    return self.image
                else:
                    log.warn( 'Null image' )
            return None
        
    class MMImageTexture( ImageTexture ):
        """Mip-mapped version of ImageTexture

        Only significant differences are the use of
        the MMTexture class instead of Texture and the
        default for minFilter being GL_LINEAR_MIPMAP_NEAREST
        (which allows you to actually see the effects of
        mip-mapping).
        """
        PROTO = "MMImageTexture"
        minFilter = field.newField(
            'minFilter', 'SFInt32', 0, GL_LINEAR_MIPMAP_NEAREST,
        )
        def createTexture( self, image, mode=None ):
            """Create a new texture-holding object"""
            if image:
                return mode.context.textureCache.getTexture( image, texture.MMTexture )
            else:
                return None

class PixelTexture( _Texture, basenodes.PixelTexture ):
    """PixelTexture, in-file node for small textures
    """
    def createTexture( self, image, mode=None ):
        """Create a new texture-holding object

        Uses the TextureCache to try to minimise the
        number of textures created
        """
        # basically just the interpretation of an SFImage
        # field as a texture...
        if len( image ) < 4:
            # don't have any components...
            return None
        width, height, componentCount = map(int,image[:3])
        if not componentCount:
            log.warn( 'bad component count in pixeltexture %s', self )
            return None
        if (not width) or (not height):
            log.warn( '0-size dimension in pixeltexture %s', self )
            return None
        if len(image) != width*height+3:
            log.warn(  
                'PixelTexture has incorrect image size, expected %s items (%s*%s)+3, got %s', 
                width*height+3,
                width,
                height, 
                len(image),
            )
            return None
        import struct
        imageBody = image[3:]
        data = "".join([
            struct.pack( '>L', item )[-componentCount:]
            for item in imageBody
        ])
        tex = texture.Texture( )
        tex.store(
            componentCount,
            [0, GL_LUMINANCE, GL_LUMINANCE_ALPHA, GL_RGB, GL_RGBA ][componentCount],
            width, height,
            data,
        )
        return tex
