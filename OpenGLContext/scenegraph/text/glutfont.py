"""GLUT-based fonts"""
from __future__ import annotations

from typing import Any, Iterable

from OpenGL import GLUT
from OpenGL.GL import *
from OpenGLContext.scenegraph.text import fontprovider, font
from OpenGLContext.arrays import *
import logging
log = logging.getLogger( __name__ )

#: One GLUT font: the specifier GLUT identifies it by, and its pixel height.
GLUTFontEntry = tuple[Any, int]

class GLUTBitmapFont( font.NoDepthBufferMixIn, font.BitmapFontMixIn, font.Font ):
    """A GLUT-provided Bitmap Font

    XXX current doesn't pay attention to fontStyle, should
    get justification from it at least.
    """
    def __init__(
        self,
        fontStyle: Any = None,
        specifier: Any = None,
        charHeight: int = 0,
    ) -> None:
        """Initialise the bitmap font"""
        self.fontStyle = fontStyle
        if not specifier or not charHeight:
            specifier, charHeight = GLUTFontProvider.match(fontStyle)
        self.specifier = specifier
        self._lineHeight = int(charHeight * 1.2)
        self.charHeight = charHeight
        self._displayLists: dict[str, tuple[int | None, font.CharacterMetrics]] = {}

    def createChar( self, char: str, mode: Any = None ) -> tuple[int | None, font.CharacterMetrics]:
        """Create the single-character display list
        """
        metrics = font.CharacterMetrics(
            char,
            GLUT.glutBitmapWidth(self.specifier, ord(char)),
            self.charHeight
        )
        list = glGenLists (1)
        compiled: int | None = list
        glNewList( list, GL_COMPILE )
        try:
            try:
                if metrics.char != ' ':
                    GLUT.glutBitmapCharacter( self.specifier, ord(char) )
                else:
                    glBitmap( 0,0,0,0, metrics.width, 0, None )
            except Exception:
                glDeleteLists( list, 1 )
                compiled = None
        finally:
            glEndList()
        return compiled, metrics
    def lists( self, value: str, mode: Any = None ) -> list[int]:
        """Get a sequence of display-list integers for value

        Basically, this does a bit of trickery to do
        as-required compilation of display-lists, so
        that only those characters actually required
        by the displayed text are compiled.

        NOTE: Must be called from within the rendering
        thread and within the rendering pass!
        """
        log.debug( """lists %s(%s)""", self, repr(value))
        lists = []
        for char in value:
            list, metrics = self.getChar( char, mode=mode )
            if list is not None:
                lists.append( list )
        log.debug( """lists %s(%s)->%s""", self, repr(value), lists)
        return lists
    def lineHeight(self, mode: Any = None ) -> int:
        """Retrieve normal line-height for this font
        """
        return self._lineHeight

class _GLUTFontProvider (fontprovider.FontProvider):
    """Singleton for creating new GLUTBitmapFonts
    """
    format = "bitmap"
    scale = 12
    bitmapFonts: dict[str, tuple[GLUTFontEntry, ...]] = {
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
    def get( self, fontStyle: Any = None, mode: Any = None ) -> Any:
        """Get/create a GLUT font, but only within a GLUT context

        GLUT bitmap routines (glutBitmapWidth, glutBitmapCharacter) segfault
        when called without a live GLUT context, so we refuse to serve fonts
        in any other backend. getProviderFont catches this and falls back to
        a shader/texture-atlas provider.

        ``mode`` may be a render mode, which carries the context it is drawing
        for, or the context itself: a program that builds its fonts up front
        has a context in hand and no mode yet, and asking it to invent one to
        answer a question about the context is asking the wrong thing.
        """
        for candidate in (getattr( mode, 'context', None ), mode):
            if getattr( candidate, 'providesGLUT', False ):
                return super( _GLUTFontProvider, self ).get( fontStyle, mode )
        raise RuntimeError(
            """GLUT bitmap fonts require a GLUT context; """
            """refusing to use them in a non-GLUT environment"""
        )
    def create( self, fontStyle: Any, mode: Any = None ) -> GLUTBitmapFont:
        """Create a new font for the given fontStyle and mode"""
        family, size = self.match(fontStyle, mode)
        # get pre-existing font, register for this fontStyle
        fontHash = self.fontHash( family,size )
        if fontHash in self.fonts:
            current: GLUTBitmapFont = self.fonts[ fontHash ]
            self.addFont( fontStyle, current )
            return current
        # no pre-existing, create
        bitmapFont = GLUTBitmapFont( fontStyle, specifier=family, charHeight=size )
        self.addFont( fontStyle, bitmapFont )
        # extra registration for imprecise matching...
        self.fonts[ fontHash ] = bitmapFont
        return bitmapFont
    def key( self, fontStyle: Any = None ) -> Any:
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

    def match( self, fontStyle: Any = None, mode: Any = None ) -> GLUTFontEntry:
        """Attempt to find matching font for our fontstyle

        GLUT only provides a tiny number of fonts, so
        this method is just scanning through the entire
        set looking for something close.

        ``fontStyle.family`` is VRML97's preference list, so the first name
        there is a font for wins and the rest are the fallbacks.  Naming
        nothing GLUT has gives 10-point Times, the closest it comes to
        VRML97's default.
        """
        # 10 point roman, closest to VRML semantics...
        family, size = self.bitmapFonts[ "SERIF" ][0]
        current = fontprovider.matchFamily(
            fontStyle,
            lambda specifier: self.bitmapFonts.get( specifier.upper() ),
        )
        if current:
            # find closest size in the set of available sizes...
            target = fontStyle.size * self.scale
            diffs = [abs(target - size) for (family, size) in current]
            best_idx = argmin(diffs)
            diff = diffs[best_idx]
            family, size = current[best_idx]
            if diff:
                log.debug(
                    """Using size %s for GLUT bitmap font, not equal to target %s""",
                    size,
                    target,
                )
        return (family,size)
    def enumerate(self, mode: Any = None) -> Iterable[str]:
        """Iterate through all available fonts (whether instantiated or not)

        Just returns the bitmapFonts keys, which will
        get each of the font-types which are available.
        """
        return self.bitmapFonts.keys()
    @staticmethod
    def fontHash(family: Any, size: int) -> tuple[Any, int]:
        """Given family and size get hashable key for lookups

        A GLUT font specifier is the underlying font's ``void*``, and a
        ``c_void_p`` is not hashable, so the pointer's value stands in for it.
        """
        try:
            hash( (family,size))
        except TypeError:
            return (family.value,size)
        else:
            return (family,size)

GLUTFontProvider = _GLUTFontProvider()
GLUTFontProvider.registerProvider( GLUTFontProvider )
