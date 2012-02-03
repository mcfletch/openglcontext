"""WGL font classes"""
from OpenGLContext.scenegraph.text import fontprovider, font
from OpenGL.WGL import *
from OpenGL.GL import *
import win32ui, win32con
import sys
from OpenGL.WGL import *
import logging
log = logging.getLogger( __name__ )

FAMILYMAPPING = {
    # really-dumb family:font mappings
    "SERIF": "Times New Roman",
    "SANS": "Arial",
    "ROMAN": "Times New Roman",
    "TYPEWRITER": "Courier New",
}

WEIGHTNAMES = [
    ("DEMIBOLD", win32con.FW_DEMIBOLD),
    ("EXTRABOLD", win32con.FW_EXTRABOLD),
    ("SEMIBOLD", win32con.FW_SEMIBOLD),
    ("ULTRABOLD", win32con.FW_ULTRABOLD),
    ("BOLD", win32con.FW_BOLD),

    ("ULTRALIGHT", win32con.FW_ULTRALIGHT),
    ("EXTRALIGHT", win32con.FW_EXTRALIGHT),
    ("LIGHT", win32con.FW_LIGHT),

    ("HEAVY", win32con.FW_HEAVY),
    ("MEDIUM", win32con.FW_MEDIUM),

    ("THIN", win32con.FW_THIN),
]

class WGLFont( font.Font ):
    """A WGL-provided Font (abstract base class)

    This font displays Unicode characters, interpreting
    passed strings as utf-8 encoded Unicode (i.e. it will
    convert strings to Unicode using the utf-8 decoder).
    """
    format = ""
    _lineHeight = 0
    def __init__(
        self,
        fontStyle = None,
        deviation = 0.005,
        extrusion = 0.0,
    ):
        self._displayLists = {}
        self.deviation = deviation
        self.extrusion = extrusion
        self.fontStyle = fontStyle or None
        if __debug__:
            log.info( """Created font %s""", self)

    def lists( self, value, mode=None ):
        """Get a sequence of display-list integers for value

        Basically, this does a bit of trickery to do
        as-required compilation of display-lists, so
        that only those characters actually required
        by the displayed text are compiled.

        NOTE: Must be called from within the rendering
        thread and within the rendering pass!
        """
        for char in value:
            if not char in self._displayLists:
                self.fastCreate( value, mode )
                break; # we just created all of them we can
        items = filter( None, map( self._displayLists.get, value))
        return [ item[0] for item in items]

    def fastCreate( self, source, mode=None ):
        """Create display list & metrics for all items in char

        This is breaking for the "normal" pattern to minimise
        the number of DCs, Handles, etceteras we need to build.
        """
        ### Need to generate a new display-list
        if __debug__:
            log.debug( """  generating displaylists, %s""", repr(source))
        wgldc = wglGetCurrentDC() # the DC that's doing the work
        if wgldc == None:
            if __debug__:
                log.warn( """Unable to build the WGL DC for generating text""")
            return 
        elif wgldc > sys.maxint:
            import struct
            wgldc = struct.unpack( '>i', struct.pack( '>I', wgldc ))[0]
        dc = win32ui.CreateDCFromHandle( wgldc )
        font = self._uiFont()
        dc.SelectObject(
            font
        )
        for char in source:
            if not char in self._displayLists:
                base, metrics = self._createSingleChar(wgldc, char)
                self._displayLists[char] = (base,metrics)
        

    def _uiFont( self ):
        """Get the appropriate UI-library font for this font
        
        Note: for some reason this object is _not_ properly
        reference counted.  You will need to hold a reference
        to it until _after_ you've called wglUseFont*
        """
        specification = {
            'italic': None,
            'underline':None,
            'name':FAMILYMAPPING.get( "SANS"),
        }
        if self.fontStyle:
            if self.fontStyle.family:
                name = self.fontStyle.family[0]
            else:
                name = "SANS"
            specification["name"] = FAMILYMAPPING.get( name, name )
            # size seems a little non-specific
            specification["size"] = int(self.fontStyle.size * 12)
            # need weight seperated
            weight = win32con.FW_NORMAL
            for wname, weight in WEIGHTNAMES:
                if self.fontStyle.style.find( wname ) >= 0:
                    break
            specification["weight"] = weight
            if self.fontStyle.style.find( 'ITALIC' ) >= 0:
                italic = 1
            else:
                italic = None
            specification["italic"] = italic
            if self.fontStyle.style.find( 'UNDERLINE' ) >= 0:
                underline = 1
            else:
                underline = None
            specification["underline"] = underline
        if __debug__:
            log.debug( """font specification %s""", specification)
        return win32ui.CreateFont(
            specification,
        )
    def lineHeight(self, mode=None ):
        """Compute the height of a line for this font

        WGL doesn't really tell us this, so we fudge it...
        """
        if not self._lineHeight:
            heights = []
            for b,m in self._displayLists.itervalues():
                heights.append( m.height )
            self._lineHeight = max( heights )
        return self._lineHeight

    def _createSingleChar( self, wgldc, char, base=None ):
        """Create the single-character (polygonal) display list

        Note:
            This is actually used by both the bitmap and
            polygonal geometry versions, though the metrics
            returned are rather less than useful for bitmap :(
        """
        if base is None:
            base = glGenLists( 1 )
        metrics = GLYPHMETRICSFLOAT()
        try:
            wglUseFontOutlinesW(
                wgldc, # the win32-specific OpenGL Context handle
                ord(char), # character to create
                1, # create a single character
                base, # display list to fill
                self.deviation,
                self.extrusion,
                WGL_FONT_POLYGONS,
                metrics,# metrics float structure to be filled
            )
        except:
            print """couldn't get outline for character""", repr(char)
        realMetrics = font.CharacterMetrics(
            char,
            metrics.gmfCellIncX,
            metrics.gmfptGlyphOrigin.y+metrics.gmfBlackBoxY,
        )
        return base, realMetrics

    def createChar( self, char, mode=None ):
        """Create a single-character display list
        """
##		import pdb
##		pdb.set_trace()
        if __debug__:
            log.warn( """Use of wglfont.createChar, normally should use lists directly""")
        self.fastCreate( char, mode=mode )
        return self.getChar( char, mode=mode )
        

class WGLOutlineFont( font.PolygonalFontMixIn, WGLFont):
    """A WGL-provided Outline Font

    Adds polygonal justification routines to the
    WGLFont class.
    """
    format = "polygon"

class WGLBitmapFont( font.NoDepthBufferMixIn, font.BitmapFontMixIn, WGLFont ):
    """A WGL-provided Bitmap Font

    Note: This is _not_ finished, or even particularly
    functional!  There is no currently satisfying way to
    get bitmap-font metrics from WGL, so there's no way
    to do formatting correctly
    """
    format = "bitmap"
    def _createSingleChar( self, wgldc, char, base=None ):
        """Create the single-character display list

        Because the Bitmap font doesn't get any information
        regarding the metrics, we actually wind up generating
        an outline font first, then overwriting the display-list
        with the bitmap-font display-list.  It's inefficient,
        but I don't see a better way at the moment.
        """
        base, metrics = super( WGLBitmapFont, self)._createSingleChar( wgldc, char, base )
        wglUseFontBitmapsW(
            wgldc, # the win32-specific OpenGL Context handle
            ord(char), # character to create
            1, # create a single character
            base, # display list to fill, overwrites the outline version
        )
        return base, metrics
