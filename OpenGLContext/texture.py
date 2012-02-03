"""Resource-manager for textures (with PIL conversions)"""
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGLContext.arrays import ArrayType
import traceback,weakref 
import logging
log = logging.getLogger( __name__ )

def _textureDeleter( textureID ):
    """Create function to clean up the texture on deletion"""
    def cleanup( ref ):
        if glDeleteTextures:
            glDeleteTextures( [textureID] )
    return cleanup

class NumpyAdapter( object ):
    @classmethod
    def shapeToMode( cls, size ):
        return {
            3: 'RGB',
            4: 'RGBA',
            2: 'LA',
            1: 'L',
        }[ size ]
    def __init__( self, array ):
        self.size = array.shape[:-1]
        self.mode = self.shapeToMode( array.shape[-1] )
        self.info = { }
        self.array = array 
    def tostring( self,*args,**named ):
        return self.array 
    def resize( self, *args, **named ):
        raise RuntimeError( """Don't support numpy image resizing""" )

class Texture( object ):
    """Holder for an OpenGL compiled texture

    This object holds onto a texture until it
    is deleted.  Provides methods for storing
    raw data or PIL images (store and fromPIL
    respectively)

    Attributes:
        components -- number of components in the image,
            if 0, then there is no currently stored image
        texture -- OpenGL textureID as returned by a call
            to glGenTextures(1), will be freed when the
            Texture object is deleted
        format -- GL_RGB/GL_RGBA/GL_LUMINANCE
    """
    def __init__( self, image=None, format=None ):
        """Initialise the texture, if image is not None, store it

        image -- optional PIL image to store
        """
        self.components = 0
        self.format = format
        self.texture = glGenTextures(1)
        self.cleanup = _textureDeleter( self.texture )
        if image is not None:
            self.fromPIL( image )
    def store(
        self,
        components, format,
        x,y,
        image,
    ):
        """define the texture's parameters...
            components -- number of components (3 or 4 for
                RGB and RGBA respectively)
            format -- GL_RGB, GL_RGBA, GL_LUMINANCE
            x,y -- dimensions of the image
            image -- string, data in raw (unencoded) format

        See:
            glBindTexture, glPixelStorei, glTexImage2D
        """
        self.components = components
        self.format = format
        # make our ID current
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        # copy the texture into the current texture ID
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        glTexImage2D(
            GL_TEXTURE_2D, 0, components, x, y, 0, format, GL_UNSIGNED_BYTE, image
        )
    def __call__( self ):
        """Enable and select the texture...
        See:
            glBindTexture, glEnable(GL_TEXTURE_2D)
        """
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glEnable(GL_TEXTURE_2D)
    
    __enter__ = __call__
    def __exit__( self, typ, val, tb ):
        """Disable for context-manager behaviour"""
        glDisable( GL_TEXTURE_2D )
    
    def update( self, lower_left, size, data ):
        """Update the texture with new data"""
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        # copy the texture into the current texture ID
        glPixelStorei(GL_PACK_ALIGNMENT,1)
        return glTexSubImage2D( 
            GL_TEXTURE_2D,
            0,
            lower_left[0],
            lower_left[1],
            size[0],
            size[1],
            self.format,
            GL_UNSIGNED_BYTE,
            data
        )
    def fromPIL( self, image ):
        """Automated storage of image data from a PIL Image instance

        Uses the ensureRGB method to convert the image to RGB,
        then ensurePow2 to make the image a valid size for OpenGL,
        then calls self.store(...) with the appropriate arguments.

        Returns the number of components in the image
        """
        if isinstance( image, ArrayType ):
            image = NumpyAdapter( image )
        else:
            image = self.ensureRGB( image )
            image = self.ensurePow2( image )
        components, format = getLengthFormat( image )
        x, y, image = image.size[0], image.size[1], self.pilAsString( image )
        self.store(
            components, format,
            x,y,
            image,
        )
        return components
    @staticmethod
    def pilAsString( image ):
        """Convert PIL image to string pointer"""
        return image.tostring("raw", image.mode, 0, -1)
    def ensureRGB( self, image ):
        """Ensure that the PIL image is in RGB mode

        Note:
            This method will create a _new_ PIL image if
            the image is in Paletted mode, otherwise just
            returns the same image object.
        """
        if image.mode == 'P':
            log.info( "Paletted image found, converting: %s", image.info )
            image = image.convert( 'RGB' )
        return image
    def ensurePow2( self, image ):
        """Ensure that the PIL image is pow2 x pow2 dimensions

        Note:
            This method will create a _new_ PIL image if
            the image is not a valid size (It will use BICUBIC
            filtering (from PIL) to do the resizing). Otherwise
            just returns the same image object.
        """
        try:
            from PIL import Image
        except ImportError, err:
            # old style?
            import Image
        BICUBIC = Image.BICUBIC
        ### Now resize non-power-of-two images...
        # should check whether it needs it first!
        newSize = bestSize(image.size[0]),bestSize(image.size[1])
        if newSize != image.size:
            log.warn( 
                "Non-power-of-2 image %s found resizing: %s", 
                image.size, image.info,
            )
            image = image.resize( newSize, BICUBIC )
        return image
    
class MMTexture( Texture ):
    """Mip-mapped texture object

    Note: You'll want your images to use
    minFilter = GL_LINEAR_MIPMAP_NEAREST
    to actually see any effect from using a
    MMTexture.
    """
    def store(
        self,
        components, format,
        x,y,
        image,
    ):
        """define the texture's parameters...
            components -- number of components (3 or 4 for
                RGB and RGBA respectively)
            format -- GL_RGB, GL_RGBA, GL_LUMINANCE
            x,y -- dimensions of the image
            image -- string, data in raw (unencoded) format
        """
        self.components = components
        # make our ID current
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        # copy the texture into the current texture ID
        glPixelStorei(GL_PACK_ALIGNMENT, 1)

        gluBuild2DMipmaps(
            GL_TEXTURE_2D, components, x, y, format, GL_UNSIGNED_BYTE, image,
        )
    def ensurePow2( self, image ):
        """Ensure that the PIL image is pow2 x pow2 dimensions

        Mip-mapping does this already if I'm not mistaken, so
        we just return image unchanged.
        """
        return image

def getLengthFormat( image ):
    """Return PIL image component-length and format

    This returns the number of components, and the OpenGL
    mode constant describing the PIL image's format.  It
    currently only supports GL_RGBA, GL_RGB and GL_LUMINANCE
    formats (PIL: RGBA, RGBX, RGB, and L), the Texture
    object's ensureRGB converts Paletted images to RGB
    before they reach this function.
    """
    if image.mode == "RGB":
        length = 3
        format = GL_RGB
    elif image.mode in ("RGBA","RGBX"):
        length = 4
        format = GL_RGBA
    elif image.mode == "L":
        length = 1
        format = GL_LUMINANCE
    elif image.mode == 'LA':
        length = 2
        format = GL_LUMINANCE_ALPHA
    else:
        raise TypeError ("Currently only support Luminance, RGB and RGBA images. Image is type %s"%image.mode)
    return length, format

def bestSize( dim ):
    """Try to figure out the best power-of-2 size for the given dimension

    At the moment, this is the next-largest power-of-two
    which is also <= glGetInteger( GL_MAX_TEXTURE_SIZE ).
    """
    boundary = min( (glGetInteger( GL_MAX_TEXTURE_SIZE ), dim))
    test = 1
    while test < boundary:
        test = test * 2
    return test
