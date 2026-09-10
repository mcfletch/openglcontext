"""PyGame bitmap and texmap fonts"""
from __future__ import annotations

from typing import Any, Iterable

from OpenGLContext.scenegraph.text import fontprovider, font
from OpenGL.GL import *
# PyOpenGL generates the type-inferring image entry points at import time, so
# they need naming to be seen.
from OpenGL.GL import glDrawPixelsub
from pygame import font as pygame_font
from pygame import surfarray, transform
import pygame
import traceback
from OpenGLContext.arrays import shape, contiguous
import logging
log = logging.getLogger( __name__ )

pygame_font.init()
pygame.init()


class PyGameBitmapFont( font.NoDepthBufferMixIn, font.BitmapFontMixIn, font.Font ):
    """A PyGame-provided Bitmap Font
    """
    format = "bitmap"
    def __init__(
        self,
        fontStyle: Any = None,
        filename: str | None = None,
        size: float | None = None,
    ) -> None:
        """Initialise the font from a TrueType file at a pixel size

        Whichever of filename and size is not given is looked up from
        fontStyle through the provider's TTF registry.
        """
        self._displayLists: dict[str, tuple[int | None, font.CharacterMetrics]] = {}
        self.fontStyle = fontStyle or None
        if filename is None or size is None:
            matchedFile, _weight, _italics, matchedSize = PyGameFontProvider.match(
                fontStyle
            )
            if filename is None:
                filename = matchedFile
            if size is None:
                size = matchedSize
        self.font = pygame_font.Font( filename, int(size))
        self.filename = filename
        self.size = size
        if __debug__:
            log.info( """Created font %s""", self)

    def createChar( self, char: str, mode: Any = None ) -> tuple[int | None, font.CharacterMetrics]:
        """Create the single-character display list
        """
        dataArray, metrics = self.createCharTexture( char, mode=mode )
        if dataArray is not None:
            ## XXX should store dataArray in global cache...
            list = self.textureToList( dataArray, metrics, mode=mode )
            ## XXX list should be stored in a context-specific cache...
            return list, metrics
        return None, metrics

    def textureToList( self, array: Any, metrics: font.CharacterMetrics, mode: Any = None ) -> int:
        """Compile Numeric Python array to a display-list

        XXX:
            use a single texture and coordinates for texmap
            version

            special case ' ' so that it's not rendered as
            an image...
        """
        if shape(array)[-1] == 2:
            pixelFormat = GL_LUMINANCE_ALPHA
        elif shape(array)[-1] == 4:
            pixelFormat = GL_RGBA
        else:
            raise ValueError( """Unsupported array dimension for textureToList, require 2 or 4 items/pixel, got %s"""%(shape(array)[-1],))
        list = glGenLists (1)
        glNewList( list, GL_COMPILE )
        try:
            try:
                if metrics.char != ' ':
                    glPixelStorei(GL_UNPACK_ALIGNMENT,1)
                    glPixelStorei(GL_PACK_ALIGNMENT, 1)
                    glDrawPixelsub(
                        pixelFormat,
                        array,
                    )
                glBitmap( 0,0,0,0, metrics.width,0, None )
            except Exception:
                glDeleteLists( list, 1 )
                raise
        finally:
            glEndList()
        return int( list )

    def createCharTexture( self, char: str, mode: Any = None ) -> tuple[Any, font.CharacterMetrics]:
        """Create character's texture/bitmap as a Numeric array w/ width and height

        This uses PyGame and Numeric to attempt to create
        an anti-aliased luminance texture-map of the given
        character and return it as (data, width, height).
        """
        try:
            letter_render = self.font.render(
                char,
                1,
                (255,255,255)
            )
        except Exception:
            traceback.print_exc()
            return None, font.CharacterMetrics(char,0,0)
        else:
            # XXX Figure out why this rotate appears to be required :(
            letter_render = transform.rotate( letter_render, -90.0)
            colour = surfarray.array3d( letter_render )
            alpha = surfarray.array_alpha( letter_render )
            colour[:,:,1] = alpha
            colour = colour[:,:,:2]
            colour = contiguous( colour ).astype( 'B' )
            # This produces what looks like garbage, but displays correctly
            colour.shape = (colour.shape[1],colour.shape[0],)+colour.shape[2:]
            return colour, font.CharacterMetrics(
                char,
                colour.shape[0],
                colour.shape[1],
            )

    def lists( self, value: str, mode: Any = None ) -> list[int]:
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
    def lineHeight(self, mode: Any = None ) -> int:
        """Retrieve normal line-height for this font
        """
        return int( self.font.get_linesize() )

class _PyGameFontProvider (fontprovider.TTFFontProvider):
    """Singleton for creating new PyGameBitmapFonts
    """
    format = "bitmap"
    scale = 12
    def __init__( self ) -> None:
        super( _PyGameFontProvider, self).__init__()
        self.nameToFile: dict[str, str] = {}

    def create( self, fontStyle: Any, mode: Any = None ) -> PyGameBitmapFont:
        """Create a new font for the given fontStyle and mode"""
        fontFile, weight, italics, size = key = self.match(fontStyle, mode)
        # do we already have this filename + size established?
        if key in self.fonts:
            cached: PyGameBitmapFont = self.fonts[ key ]
            return cached
        bitmapFont = PyGameBitmapFont( fontStyle, filename = fontFile, size = size )
        self.addFont( fontStyle, bitmapFont )
        self.fonts[key] = bitmapFont
        return bitmapFont
    def key( self, fontStyle: Any = None ) -> Any:
        """Calculate the key for the fontStyle"""
        if not fontStyle:
            return None
        attributes = ('family','style','size',)
        result = []
        for a in attributes:
            if hasattr( fontStyle, a):
                item = getattr( fontStyle, a)
                if isinstance( item, list ):
                    item = tuple( item )
                result.append( item )
            else:
                result.append( None )
        return tuple( result )

    def match( self, fontStyle: Any = None, mode: Any = None ) -> tuple[str, int, int, float]:
        """Attempt to find matching font-file for our fontstyle

        Should match any name passed into addFontFile,
        as well as the short filename for the font.
        """
        registry = self.getTTFRegistry()
        if not registry:
            raise RuntimeError(
                """No TrueType font registry available; """
                """scan the system fonts (Context.getTTFFiles) """
                """or call fontprovider.setTTFRegistry before asking for a font"""
            )
        fontName = registry.fontNameFromStyle( fontStyle, mode=mode )
        weight, italics = registry.modifiersFromStyle( fontStyle, mode=mode )
        specificFonts = registry.fontMembers( fontName, weight, italics )
        if not specificFonts:
            # broaden to any weight
            specificFonts = registry.fontMembers( fontName, None, italics )
            if not specificFonts:
                # broaden to every sub-font...
                specificFonts = registry.fontMembers( fontName )
                if not specificFonts:
                    raise RuntimeError( """No concrete fonts found for general font %r (somehow)"""%( fontName, ))
        # okay, just arbitrarily choose the first item, normally will only be one anyway
        specificFont = specificFonts[0]
        fontFile = registry.fontFile( specificFont )
        size = self.scale
        if fontStyle:
            size = self.scale * fontStyle.size
        return fontFile, weight, italics, size

    def enumerate(self, mode: Any = None) -> Iterable[str]:
        """Iterate through all available font-keys (whether instantiated or not)

        These are the names of the fonts this provider has been given files
        for; a name is the key to pass to ``addFontFile``'s registry.
        """
        return self.nameToFile.keys()


PyGameFontProvider = _PyGameFontProvider()
PyGameFontProvider.registerProvider( PyGameFontProvider )
