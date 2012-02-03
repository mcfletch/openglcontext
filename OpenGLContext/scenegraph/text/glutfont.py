"""GLUT-based fonts"""
from OpenGL import GLUT
from OpenGL.GL import *
from OpenGLContext.scenegraph.text import fontprovider, font
from OpenGLContext.arrays import *
import logging
log = logging.getLogger( __name__ )

class GLUTBitmapFont( font.NoDepthBufferMixIn, font.BitmapFontMixIn, font.Font ):
    """A GLUT-provided Bitmap Font

    XXX current doesn't pay attention to fontStyle, should
    get justification from it at least.
    """
    def __init__( self, fontStyle=None, specifier=None, charHeight=0 ):
        """Initialise the bitmap font"""
        self.fontStyle = fontStyle
        if not specifier or not charHeight:
            specifier, charHeight = GLUTFontProvider.match(fontStyle)
        self.specifier = specifier
        self._lineHeight = int(charHeight * 1.2)
        self.charHeight = charHeight
        self._displayLists = {}

    def createChar( self, char, mode=None ):
        """Create the single-character display list
        """
        metrics = font.CharacterMetrics(
            char,
            GLUT.glutBitmapWidth(self.specifier, ord(char)),
            self.charHeight
        )
        list = glGenLists (1)
        glNewList( list, GL_COMPILE )
        try:
            try:
                if metrics.char != ' ':
                    GLUT.glutBitmapCharacter( self.specifier, ord(char) )
                else:
                    glBitmap( 0,0,0,0, metrics.width, 0, None )
            except Exception:
                glDeleteLists( list, 1 )
                list = None
        finally:
            glEndList()
        return list, metrics
    def lists( self, value, mode=None ):
        """Get a sequence of display-list integers for value

        Basically, this does a bit of trickery to do
        as-required compilation of display-lists, so
        that only those characters actually required
        by the displayed text are compiled.

        NOTE: Must be called from within the rendering
        thread and within the rendering pass!
        """
        if __debug__:
            log.info( """lists %s(%s)""", self, repr(value))
        lists = []
        for char in value:
            list, metrics = self.getChar( char, mode=mode )
            if list is not None:
                lists.append( list )
        if __debug__:
            log.info( """lists %s(%s)->%s""", self, repr(value), lists)
        return lists
    def lineHeight(self, mode=None ):
        """Retrieve normal line-height for this font
        """
        return self._lineHeight

class _GLUTFontProvider (fontprovider.FontProvider):
    """Singleton for creating new GLUTBitmapFonts
    """
    format = "bitmap"
    scale = 12
    bitmapFonts = {
        'TYPEWRITER': (
            (GLUT.GLUT_BITMAP_8_BY_13, 13 ),
            (GLUT.GLUT_BITMAP_9_BY_15, 15 ),
        ),
        'SERIF': (
            (GLUT.GLUT_BITMAP_TIMES_ROMAN_10, 10 ),
            (GLUT.GLUT_BITMAP_TIMES_ROMAN_24, 24 ),
        ),
        'SANS': (
            (GLUT.GLUT_BITMAP_HELVETICA_10, 10 ),
            (GLUT.GLUT_BITMAP_HELVETICA_12, 12 ),
            (GLUT.GLUT_BITMAP_HELVETICA_18, 18 ),
        ),
    }
    bitmapFonts['ROMAN'] = bitmapFonts['SERIF']
    def create( self, fontStyle, mode=None ):
        """Create a new font for the given fontStyle and mode"""
        family, size = self.match(fontStyle, mode)
        # get pre-existing font, register for this fontStyle
        fontHash = self.fontHash( family,size )
        if fontHash in self.fonts:
            current = self.fonts.get( fontHash )
            self.addFont( fontStyle, current )
            return current
        # no pre-existing, create
        bitmapFont = GLUTBitmapFont( fontStyle, specifier=family, charHeight=size )
        self.addFont( fontStyle, bitmapFont )
        # extra registration for imprecise matching...
        self.fonts[ fontHash ] = bitmapFont
        return bitmapFont
    def key( self, fontStyle= None ):
        """Calculate our "font key" for the fontStyle

        If the font-key changes, we should be invalidating
        our caches, but at the moment we aren't caching anything
        3-D providers will add the various 3-D-specific fields
        from the FontStyle3D node.
        """
        if not fontStyle:
            return None
        return (
            tuple(fontStyle.family),
            fontStyle.size,
        )

    def match( self, fontStyle=None, mode=None ):
        """Attempt to find matching font for our fontstyle

        GLUT only provides a tiny number of fonts, so
        this method is just scanning through the entire
        set looking for something close.
        """
        # 10 point roman, closest to VRML semantics...
        family, size = self.bitmapFonts.get( "SERIF" )[0]
        if fontStyle and fontStyle.family:
            current = None
            for specifier in fontStyle.family:
                current = self.bitmapFonts.get( specifier.upper() )
            if current:
                # find closest size in the set of available sizes...
                target = fontStyle.size * self.scale
                diff, family,size = min([ (abs(target-size),family,size) for (family,size) in current ])
                if __debug__:
                    if diff:
                        log.info(
                            """Using size %s for GLUT bitmap font, not equal to target %s""",
                            size,
                            target,
                        )
        return (family,size)
    def enumerate(self, mode = None):
        """Iterate through all available fonts (whether instantiated or not)

        Just returns the bitmapFonts keys, which will
        get each of the font-types which are available.
        """
        return self.bitmapFonts.keys()
    def fontHash(family,size):
        """Given family and size get hashable key for lookups
        
        OpenGL-ctypes gives you the underlying GLUT font void*, whereas 
        PyOpenGL gave you an integer value
        """
        try:
            hash( (family,size))
        except TypeError, err:
            return (family.value,size)
        else:
            return (family,size)
    fontHash = staticmethod( fontHash )

GLUTFontProvider = _GLUTFontProvider()
GLUTFontProvider.registerProvider( GLUTFontProvider )
