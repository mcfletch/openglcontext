"""TTFQuery font registry with a few VRML-specific methods"""
from __future__ import annotations

from typing import Any

from ttfquery import ttffiles, describe
import re
import logging

log = logging.getLogger( __name__ )

ITALICS_FINDER = re.compile( '(italic[s]?)$', re.IGNORECASE )
from string import ascii_letters

class TTFRegistry( ttffiles.Registry ):
    """Minor specialisation to provide VRML97 fontstyle matching"""
    # data for querying whether a font is one of
    # the commonly-searched-for forms which are not
    # single family specifications
    #
    # Each list is in *preference* order: the first classification with a font
    # installed is the one used, and the entries after it are the fallbacks.
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

    def __init__( self ) -> None:
        super( TTFRegistry, self ).__init__()
        #: generic family name: the font name chosen for it, memoised per
        #: registry so that a second registry scanned from different files
        #: does not inherit this one's answers.
        self.defaultFontNames: dict[str,str] = {}

    def familyMembers( self, major: str, minor: str | None = None ) -> list[str]:
        """Get all (general) fonts for a given family"""
        if minor is None:
            major = major.upper()
            if major in self.DEFAULT_FAMILY_SETS:
                result: list[str] = []
                for maj,min in self.DEFAULT_FAMILY_SETS[ major ]:
                    result.extend( ttffiles.Registry.familyMembers( self, maj,min))
                return result
        return list( ttffiles.Registry.familyMembers( self, major, minor ) )

    def defaultFont( self, type: str = 'SANS', mode: Any = None ) -> str:
        """Attempt to get a default font for the registry"""
        type = type.upper()
        current = self.defaultFontNames.get(type)
        if current:
            return current
        # okay, what if the user has explicitly specified one...
        if type in self.DEFAULT_FAMILY_SETS:
            # check for one in the application data directory...
            if mode and mode.context:
                configured = mode.context.getDefaultTTFFont( type.lower())
                if configured is not None:
                    self.defaultFontNames[type] = str( configured )
                    return str( configured )
        # okay, look for fonts of the default families...
        names: list[str] = []
        for (major,minor) in self.DEFAULT_FAMILY_SETS.get( type, ()):
            names = self.familyMembers( major, minor )
            if names:
                break
        if not names:
            raise RuntimeError( """No default font available of type %r"""%( type,))
        if len(names) > 1:
            # potentially multiple fonts match this description...
            # construct temporary fonts and see which has best match for common chars
            from OpenGLContext.scenegraph.text import _toolsfont
            set: list[tuple[int,str]] = []
            for name in names:
                try:
                    testFont = _toolsfont.Font(
                        self.fontFile(
                            self.fontMembers( name )[0]
                        )
                    )
                    count = testFont.countGlyphs( ascii_letters )
                    set.append( (count,name) )
                    if count == len(ascii_letters):
                        break
                except Exception:
                    log.warning(
                        """Unable to measure glyph coverage of font %r""",
                        name,
                        exc_info = True,
                    )
            set.sort()
            if not set:
                name = names[0]
            else:
                name = set[-1][-1]
        else:
            name = names[0]
        self.defaultFontNames[ type ] = name
        return name


    def fontNameFromStyle( self, fontStyle: Any, mode: Any = None ) -> str:
        """Attempt to find font-name matching given fontStyle

        returns a font-family name (see fontMembers for method
        to resolve these to particular font-faces)

        ``fontStyle.family`` is VRML97's preference list, so the first name
        that resolves to an installed font wins and the rest are the
        fallbacks.
        """
        if fontStyle and fontStyle.family:
            for specifier in fontStyle.family:
                try:
                    if specifier.upper() in self.DEFAULT_FAMILY_SETS:
                        return self.defaultFont( specifier, mode=mode )
                    fontName = self.matchName( specifier, single=1)
                except (KeyError,RuntimeError):
                    pass
                else:
                    if fontName:
                        return str( fontName )
        return self.defaultFont( mode=mode )

    def modifiersFromStyle( self, fontStyle: Any, mode: Any = None ) -> tuple[int,int]:
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
        return int( weight ), italics
