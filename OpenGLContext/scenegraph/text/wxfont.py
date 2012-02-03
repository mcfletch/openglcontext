"""wxPython bitmap and texmap fonts"""
from OpenGLContext.scenegraph.text import fontprovider, font
from OpenGL.GL import *
import wx
import traceback, os
from OpenGLContext.arrays import *
import logging
log = logging.getLogger( __name__ )

##log.setLevel( DEBUG )
class wxBitmapFont( font.NoDepthBufferMixIn, font.BitmapFontMixIn, font.Font ):
    """A wxPython-provided Bitmap Font

    The wxPython fonts are image-based, non-antialiased,
    and available only under wxPython contexts, though
    on Win32 you can actually use them when using a non
    wxPython context (they will crash or application on
    GTK/Linux because the wxPython application object
    is not available under other contexts).

    The primary interest for wxPython fonts is the
    ability to scan all currently installed fonts to find
    a specified font face.  At the moment, only the WGL
    and wxPython fonts are able to do this.

    Note:
        The FontStyle.size field means something different
        for bitmap-format (screen-space) fonts, as compared
        to the VRML97 standard, which only considers 3D
        geometric fonts.  Bitmap fonts are generated at
        approximately 72*FontStyle.size pixels.
    """
    format = "bitmap"
    font = None
    def __init__(
        self,
        fontStyle = None,
        font = None,
    ):
        """Initialize the wxBitmapFont object

        fontStyle -- the FontStyle node which generates
            this font, can be None, in which case VRML97
            default semantics are used.
        font -- the wxPython font used to render the
            bitmaps on which we are based.  Can be None,
            in which case we will find the appropriate font
            using the wx.FontProvider's match method.
        """
        self._displayLists = {}
        self.fontStyle = fontStyle or None
        if not font:
            if __debug__:
                log.info( """wx.BitmapFont passed a null wxPython font, doing lookup for fontStyle %r""", fontStyle)
            family, face, font = wxFontProvider.match( fontStyle )
            if not font:
                raise ValueError("""Could not generate wx.BitmapFont for fontStyle %s"""% (fontStyle,))
        self.font = font
            
    def createChar( self, char, mode=None ):
        """Create the single-character display list
        """
        dataArray, metrics = self.createCharTexture( char, mode=mode )
        if dataArray is not None:
            ## XXX should store dataArray in global cache...
            list = self.textureToList( dataArray, metrics, mode=mode )
            ## XXX list should be stored in a context-specific cache...
            return list, metrics
        else:
            log.warn( """wx.BitmapFont couldn't get display list for character %r""", char)
        return None, metrics
        
    def textureToList( self, array, metrics, mode=None ):
        """Compile string-form image to a display-list

        XXX:
            use a single texture and coordinates for texmap
            version
        """
        shape = len(array)/(metrics.width*metrics.height)
        if shape == 2:
            mode = GL_LUMINANCE_ALPHA
        elif shape == 4:
            mode = GL_RGBA
        elif shape == 3:
            mode = GL_RGB
        else:
            raise ValueError( """Unsupported array dimension for textureToList, require 2 or 4 items/pixel, got %s"""%(shape(array)[-1],))
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        list = glGenLists (1)
        glNewList( list, GL_COMPILE )
        try:
            try:
                if metrics.char != ' ':
                    glDrawPixels(
                        metrics.width,
                        metrics.height,
                        mode,
                        GL_UNSIGNED_BYTE,
                        array
                    )
                glBitmap( 0,0,0,0, metrics.width,0, None )
            except Exception:
                if __debug__:
                    log.warn( """Failure creating display-list for %r""", metrics.char )
                glDeleteLists( list, 1 )
                raise
        finally:
            glEndList()
        return list

    def createCharTexture( self, char, mode=None ):
        """Create character's texture/bitmap as a Numeric array w/ width and height

        This uses PyGame and Numeric to attempt to create
        an anti-aliased luminance texture-map of the given
        character and return it as (data, width, height).
        """
        if __debug__:
            log.info( """Creating texture for %r""", char )
        dc = wx.MemoryDC()
        bm = wx.EmptyBitmap( 1,1 )
        dc.SelectObject(bm)
        dc.SetFont( self.font )
        width, height = dc.GetTextExtent( char )
        bitmap = wx.EmptyBitmap( width, height )
        dc.SelectObject( bitmap )
        #~ dc.SetBackgroundMode( wx.TRANSPARENT )
        dc.SetBackgroundMode( wx.SOLID )
        dc.SetTextForeground( '#ffffff')
        dc.SetTextBackground( '#000000')
        dc.DrawText( char, 0,0)
        dc.SelectObject( wx.NullBitmap )
        image = wx.ImageFromBitmap(bitmap )
        #~ import pdb
        #~ pdb.set_trace()
        #~ directory = '~/bitmaps'
        #~ directory = os.path.expanduser( directory )
        #~ image.SaveFile( '%s/char%s.png'%(directory,ord(char)), wx.BITMAP_TYPE_PNG)
        data = image.GetData()
        data = fromstring( data, 'b')
        data = reshape(data, (height,width,3))
        data = data[::-1,:,:2]
        assert shape(data) == (height, width,2), """Data array has changed shape is %s should be %s"""%(shape(data),(height, width,3))
        data = data.tostring()
        #~ print 'data', repr(data)
        return data, font.CharacterMetrics(
            char,
            width,
            height,
        )
    
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
        for (list, metrics) in self._displayLists.itervalues():
            return metrics.height
        if __debug__:
            log.warn( """lineHeight requested when no characters rasterised, 0-height line may result""")
        return 0

class _wxFontProvider (fontprovider.FontProvider):
    """Singleton for creating new wxBitmapFonts

    Note: This provider MUST NOT be used under a non-wxPython
    context under Linux/GTK, as it WILL cause segmentation
    faults when the wxPython system tries to access the font
    list from the wxPython application.
    """
    format = "bitmap"
    scale = 16
    FAMILYMAPPING = {
        # really-dumb family:font mappings
        "SERIF": (wx.ROMAN,""),
        "SANS": (wx.SWISS, ""),
        "ROMAN": (wx.ROMAN, ""),
        "TYPEWRITER": (wx.MODERN, ""),
    }
    systemNames = None
    def create( self, fontStyle, mode=None ):
        """Create a new font for the given fontStyle and mode"""
        family, face, font = self.match(fontStyle, mode)
        bitmapFont = wxBitmapFont( fontStyle, font = font )
        self.addFont( fontStyle, bitmapFont )
        return bitmapFont

    def match( self, fontStyle, mode=None ):
        """Attempt to find matching wxFont for our fontstyle

        This is a really stupid implementation, it just
        takes the first font that includes the name
        specified in the fontstyle.
        """
        # serif if the VRML default, despite being generally
        # unsuitable for display in small point-sizes :( 
        family, face = self.FAMILYMAPPING.get( "SERIF")
        if fontStyle and fontStyle.family:
            for specifier in fontStyle.family:
                specifier = specifier.lower()
                current = self.FAMILYMAPPING.get( specifier.upper() )
                if current:
                    family, face = current
                    break
                ## wxPython bug causes a memory error if we do GetFacenames,
                ## even if we do it inside the mainloop AFAICS!
                for name in self.enumerate():
                    if name.find( specifier) > -1:
                        self.FAMILYMAPPING[ specifier ] = (wx.DEFAULT, name)
                        family, face = (wx.DEFAULT, name)
        return self.calculatePointSize( fontStyle, family, face, mode )
    def calculatePointSize( self, fontStyle, family, face, mode=None):
        """Approximate point size for fontStyle with font"""
        height = 0
        # find pixel-height
        dc = wx.MemoryDC()
        bm = wx.EmptyBitmap( 1,1 )
        dc.SelectObject(bm)
        if fontStyle and fontStyle.size:
            targetSize = fontStyle.size*self.scale # undefined for bitmap fonts in VRML spec
        else:
            targetSize = self.scale
        font = None
        for testSize in range(1,int(targetSize*3)):
            font = wx.Font(
                testSize,
                family,
                wx.NORMAL,
                wx.NORMAL,
                0,
                face,
            )
            dc.SetFont( font )
            width, height = dc.GetTextExtent( 'F' )
            if height >= targetSize:
                if __debug__:
                    if height != targetSize:
                        log.warn(
                            """wxBitmapFont Using point size %s for pixel size %s, actual pixel size %s""",
                            testSize,
                            targetSize,
                            height
                        )
                break
        if font is None:
            raise ValueError( """Invalid font-size specified (%s), no font found to match that size (target = %s pixels)"""%(fontStyle.size, targetSize))
        return family, face, font
        
    def enumerate(self, mode = None):
        """Iterate through all available font-keys (whether instantiated or not)

        This uses the wxFontEnumerator class to provide a list of
        font names from the wxPython system, (with all names
        lowercased).
        """
        if not self.systemNames:
            ## wxPython with do a memory-access fault if we try this :(
            enumerator = wx.FontEnumerator()
            enumerator.EnumerateFacenames()
            systemNames = enumerator.GetFacenames()
            self.systemNames = systemNames = [item.lower() for item in systemNames]
        return self.systemNames


wxFontProvider = _wxFontProvider()
wxFontProvider.registerProvider( wxFontProvider )
