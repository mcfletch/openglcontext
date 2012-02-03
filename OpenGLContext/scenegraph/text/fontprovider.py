"""Base functionality for font-providers (objects creating fonts)"""
import traceback, weakref
import logging
log = logging.getLogger( __name__ )

class FontProvider( object ):
    """Abstract base class for font-providers

    The font-provider allows you to get a system-specific
    font via the currently registered font-providing system.

    Attributes:
        fonts -- the set of instantiated fonts the provider
            is currently managing.  A mapping from
                key: font
            where key is calculated by the provider's key
            method.

    Class attributes:
        PROVIDER_SEARCH_ORDER -- default search order for
            font provider types.  When you ask for a match
            for a particular fontStyle the search order is
            rearranged to match the fontStyle IFF the
            fontStyle specifies a particular format,
            otherwise the default  search order is used.
        providers -- the set of registered font providers
    """
    PROVIDER_SEARCH_ORDER = ['solid','texture','bitmap']
    providers = {}
    def __init__(self):
        """Initialize the provider"""
        self.fonts = {}
    def registerProvider( cls, obj ):
        """Register a class as an active font-provider (classmethod)"""
        cls.providers.setdefault(obj.format, []).append( obj )
    registerProvider = classmethod( registerProvider )
    def getProviders( cls, format ):
        """Get providers for a particular format (classmethod)"""
        return cls.providers.get( format, [] )
    getProviders = classmethod( getProviders )
    def getProviderFont( cls, fontStyle, mode=None ):
        """Get a font provider & font for given style (classmethod)

        fontStyle -- a FontStyle for FontStyle3D node, or None,
            determines which provider is "prefered"
        mode -- active rendering mode

        cls.PROVIDER_SEARCH_ORDER is used to determine the
        order of fallback formats for the explicitly specified
        format (if there is such a format).
        """
        order = cls.PROVIDER_SEARCH_ORDER[:]
        if hasattr( fontStyle, 'format') and fontStyle.format:
            format = fontStyle.format.lower()
            while format in order:
                order.remove( format )
            order.insert( 0, format )
        for format in order:
            providers = cls.getProviders( format )
            if providers:
                for provider in providers:
                    try:
                        return provider, provider.get( fontStyle, mode )
                    except Exception, err:
                        if __debug__:
                            traceback.print_exc()
                        log.warn(
                            """FontProvider %r couldn't find font for %r: %s""",
                            provider,
                            fontStyle,
                            err
                        )
        log.warn(
            """Couldn't find a provider for fontStyle %r""",
            fontStyle,
        )
        return None, None
    getProviderFont = classmethod( getProviderFont )
            
    def addFont( self, fontStyle, font, mode = None):
        """Add a new font to the font provider

        fontStyle -- the font style defining the font, may
            be None to define the default font
        font -- the provider-specific font object which
            should be a sub-class of
            OpenGLContext.scenegraph.text.font.Font
        mode -- the active rendering mode
        """
        key = self.key (fontStyle)
        self.fonts[key] = font
        return font
    def get( self, fontStyle= None, mode=None ):
        """Get/create a new font for the given fontStyle & mode

        fontStyle -- the font style defining the font, may
            be None to retrieve the default font
        mode -- the active rendering mode
        """
        key = self.key (fontStyle)
        if key in self.fonts:
            return self.fonts.get( key )
        return self.create( fontStyle, mode )
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
            fontStyle.style,
        )

    def enumerate(self, mode = None):
        """Iterate through all available fonts (whether instantiated or not)

        These are the "low level" specifications for the fonts,
        for providers with "name"-based resolution, these will
        be the font-face-names, while providers with filename-
        based resolution will provide filenames.  Where possible,
        filename-based systems should attempt to provide names
        as well to allow for more flexibility in content
        authoring.
        """
    def create( self, fontStyle, mode=None ):
        """Create a new font for the given fontStyle and mode"""

    def clear( self ):
        """Force clear of the font cache for this provider"""
        self.fonts.clear()


class TTFFontProvider( FontProvider ):
    """Direct TrueType-font-file-based provider"""
    TTFRegistry = None
    def setTTFRegistry( cls, registry ):
        """Set the TTF registry for the class (global if called on TTFFontProvider)"""
        cls.TTFRegistry = registry
    setTTFRegistry = classmethod( setTTFRegistry )
    def getTTFRegistry( cls ):
        """Set the TTF registry for the class (global if called on TTFFontProvider)"""
        return cls.TTFRegistry
    getTTFRegistry = classmethod( getTTFRegistry )
    

getProviders = FontProvider.getProviders
setTTFRegistry = TTFFontProvider.setTTFRegistry
##
##class DiscreetFontProvider( FontProvider ):
##	"""Provide selection from a discrete list of fonts"""
