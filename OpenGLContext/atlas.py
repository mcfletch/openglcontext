"""Texture atlas implementation"""
import math, weakref, logging
from OpenGL.GL import *
from OpenGLContext.arrays import zeros, array, dot, ArrayType
from OpenGLContext import texture
from vrml.vrml97 import transformmatrix

log = logging.getLogger( __name__ )

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
        """Add the given PIL image to our atlas' image"""
        x,y = image.size
        if start is None:
            start = self.start_coord( x )
        offset = (start,self.yoffset)
        map = Map( self.atlas, offset, (x,y), image )
        self.maps.append( weakref.ref( map, self._remover( offset )) )
        self.atlas.need_updates.append( weakref.ref(map) )
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
        self.texture = None
        log.info( 
            'Allocating a %s-component texture atlas of size %sx%s',
            components,
            max_size,max_size,
        )
    
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
    
    def render( self ):
        """Render this texture to the context"""
        if self.texture is None:
            format = [0, GL_LUMINANCE, GL_LUMINANCE_ALPHA, GL_RGB, GL_RGBA ][self.components]
            self.texture = texture.Texture(format=format)
            x,y,d = self.size()
            self.texture.store( 
                d,
                format,
                x,y,
                None 
            )
        self.texture()
        needs = self.need_updates[:]
        del self.need_updates[:len(needs)]
        for need in needs:
            need = need()
            if need is not None:
                need.update( self.texture )
        return self.texture
    def cached( self, mode ):
        """Get cached version of this texture
        
        Note: currently we do *not* properly use mode-level caching
        for the texture object
        """
        return self.render()
    def debugImageTexture( self, mode ):
        """Create a debugging image texture for this texture atlas 
        """
        from OpenGLContext.scenegraph.imagetexture import ImageTexture,Image
        from OpenGLContext.texture import NumpyAdapter
        from vrml import protofunctions
        format = NumpyAdapter.shapeToMode( self.components )
        instance = ImageTexture(
            image = Image.new(format, (1,1), '#ffff00'),
        )
        holder = mode.cache.holder(instance, self.texture)
        return instance

class Map( object ):
    """Object representing a sub-texture within a texture atlas
    
    A Map object is a dependent version of an OpenGLContext.texture.Texture
    object, i.e. it tries to offer the same API, but with support for 
    Atlas-based maps instead of stand-alone ones.
    """
    _matrix = None
    _coords = None
    _uploaded = False
    def __init__( self, atlas, offset, size, image ):
        self.atlas = atlas 
        self.offset = offset 
        self.size = size
        self.image = image
        self.components = self.atlas.components
    def matrix( self ):
        """Calculate a 4x4 transform matrix for texcoords
        
        To manipulate texture coordinates with this matrix 
        they need to be in homogenous coordinates, i.e. a 
        "regular" 2d coordinate of (x,y) becomes (x,y,0.0,1.0)
        so that it can pick up the translations.
        
        dot( coord, matrix ) produces the transformed 
        coordinate for processing.
        
        returns 4x4 translation matrix
        """
        if self._matrix is None:
            # translate by self.offset/atlas.size
            # scale by self.size/atlas.size
            tx,ty,d = self.atlas.size()
            tx,ty = float(tx),float(ty)
            x,y = self.offset
            sx,sy = self.size 
            self._matrix = transformmatrix.transformMatrix (
                translation = (x/tx,y/ty,0),
                scale = (sx/tx,sy/ty,1),
            )
        return self._matrix
    def coords( self ):
        """Return our bottom-left and top-right coordinate pairs"""
        if self._coords is None:
            tx,ty,d = self.atlas.size()
            tx,ty = float(tx),float(ty)
            x,y = self.offset
            sx,sy = self.size 
            self._coords = array( ((x/tx,y/ty),((x+sx)/tx,(y+sy)/ty)), 'f')
        return self._coords
    
    def replace( self, image ):
        """Replace our current image with given (PIL) image"""
        self._uploaded = False 
        self.image = image 
        self.atlas.need_updates.append( weakref.ref(self) )
    def update( self, texture ):
        """Update texture with (new) data in self.image
        
        This just calls texture.update with our metadata
        in order to do the actual copy of the data-pointer.
        """
        texture.update( 
            self.offset, self.size, 
            texture.pilAsString( self.image),
        )
        self._uploaded = True
    @property 
    def texture( self ):
        """Retrieve our texture"""
        return self.atlas.cached( None )
    def __call__( self ):
        """Enable/call our texture"""
        self.atlas.render()
        # should also load our texture-transform matrix.
        glMatrixMode( GL_TEXTURE )
        glLoadMatrixd( self.matrix() )
        glMatrixMode( GL_MODELVIEW )

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
        if isinstance( image, ArrayType ):
            image = texture.NumpyAdapter( image )
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
