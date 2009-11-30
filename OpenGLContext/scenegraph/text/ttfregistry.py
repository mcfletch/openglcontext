"""TTFQuery font registry with a few VRML-specific methods"""
from ttfquery import ttffiles, describe
import re

ITALICS_FINDER = re.compile( '(italic[s]?)$', re.IGNORECASE )

class TTFRegistry( ttffiles.Registry ):
    """Minor specialisation to provide VRML97 fontstyle matching"""
    defaultFontNames = {}
    # data for querying whether a font is one of
    # the commonly-searched-for forms which are not
    # single family specifications
    DEFAULT_FAMILY_SETS = {
        'SERIF':[
            ("SERIF-OLD", "DUTCH-MODERN"), #e.g. times new roman
            ("SERIF-OLD", "ROUNDED-LEGIBILITY"),
            ("SERIF-OLD", "DUTCH-TRADITIONAL"),
            ("SERIF-OLD", None),
            ("SERIF-TRANSITIONAL",None),
            ("SERIF-CLARENDON",None),
            ("SERIF-FREEFORM",None),
            ("SERIF",None),
        ],
        'TYPEWRITER': [
            ("SANS","GOTHIC-TYPEWRITER"),
            ("SERIF-SLAB",'TYPEWRITER'),
            ("SERIF-SLAB",None),
            ('SANS', 'GOTHIC-TYPEWRITER'), #e.g. Lucida Console
            ("SERIF", None ),
        ],
        'SANS': [
            ('SANS', 'GOTHIC-TYPEWRITER'), #e.g. Lucida Console
            ('SANS', 'GOTHIC-NEO-GROTESQUE'), #e.g. Arial
            ('SANS', None),
        ],
    }
    def familyMembers( self, major, minor=None ):
        """Get all (general) fonts for a given family"""
        if minor is None:
            major = major.upper()
            if major in self.DEFAULT_FAMILY_SETS:
                result = []
                for maj,min in self.DEFAULT_FAMILY_SETS[ major ]:
                    result.extend( ttffiles.Registry.familyMembers( self, maj,min))
                return result
        return ttffiles.Registry.familyMembers( self, major, minor )
    
    def defaultFont( self, type='SANS', mode=None ):
        """Attempt to get a default font for the registry"""
        type = type.upper()
        current = self.defaultFontNames.get(type)
        if current:
            return current
        # okay, what if the user has explicitly specified one...
        if type in self.DEFAULT_FAMILY_SETS:
            # check for one in the application data directory...
            if mode and mode.context:
                current = mode.context.getDefaultTTFFont( type.lower())
                if current is not None:
                    self.defaultFontNames[type] = current
                    return current
        # okay, look for fonts of the default families...
        for (major,minor) in self.DEFAULT_FAMILY_SETS.get( type, ()):
            names = self.familyMembers( major, minor )
        if not names:
            raise RuntimeError( """No default font available of type %r"""%( type,))
        if len(names) > 1:
            # potentially multiple fonts match this description...
            # construct temporary fonts and see which has best match for common chars
            from OpenGLContext.scenegraph.text import _toolsfont
            import string, locale, traceback
            testString = string.letters.decode( locale.getpreferredencoding())
            set = []
            for name in names:
                try:
                    testFont = _toolsfont.Font(
                        self.fontFile(
                            self.fontMembers( name )[0]
                        )
                    )
                    count = testFont.countGlyphs( testString )
                    set.append( (count,name) )
                    if count == len(testString):
                        break
                except Exception, err:
                    traceback.print_exc()
            set.sort()
            if not set:
                name = names[0]
            else:
                name = set[-1][-1]
        else:
            name = names[0]
        self.defaultFontNames[ type ] = name
        return name
        
        
    def fontNameFromStyle( self, fontStyle, mode=None ):
        """Attempt to find font-name matching given fontStyle

        returns a font-family name (see fontMembers for method
        to resolve these to particular font-faces)
        """
        fontName = None
        if fontStyle and fontStyle.family:
            for specifier in fontStyle.family:
                try:
                    if specifier.upper() in self.DEFAULT_FAMILY_SETS:
                        return self.defaultFont( specifier, mode=mode )
                    fontName = self.matchName( specifier, single=1)
                except (KeyError,RuntimeError):
                    pass
        if not fontName:
            return self.defaultFont( mode=mode )
        return fontName
    def modifiersFromStyle( self, fontStyle, mode=None ):
        """Determine TTF modifiers (weight, italics flag) from fontStyle"""
        italics = 0
        weight = describe.WEIGHT_NAMES.get( 'normal' )
        if fontStyle and fontStyle.style:
            # find whether includes italics...
            style = fontStyle.style
            matcher = ITALICS_FINDER.search( style )
            if matcher:
                italics = 1
                style = style[:matcher.start()]
            # now determine weight...
            if style:
                style = style.lower()
                weight = describe.WEIGHT_NAMES.get( style, weight )
        return weight, italics
