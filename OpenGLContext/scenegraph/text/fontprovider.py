"""Base functionality for font-providers (objects creating fonts)"""

from __future__ import annotations

from typing import Any, Callable, Iterable, TypeVar

import traceback
import logging

log = logging.getLogger(__name__)

T = TypeVar("T")


def matchFamily(fontStyle: Any, lookup: Callable[[str], T | None]) -> T | None:
    """The first font ``lookup`` can find for a name in ``fontStyle.family``

    VRML97 gives ``FontStyle.family`` a list of family names in *preference*
    order, so a provider serves the first name it has a font for and treats
    the names after it as fallbacks.

    lookup -- called with one family name; returns the provider's own
        description of the font for that name, or None if it has none.

    Returns None where the style names no family, or none of the names it
    does name can be served; the caller chooses its own default from there.
    """
    if not fontStyle or not fontStyle.family:
        return None
    for specifier in fontStyle.family:
        result = lookup(specifier)
        if result is not None:
            return result
    return None


class FontProvider(object):
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

    PROVIDER_SEARCH_ORDER = ["solid", "texture", "bitmap"]
    providers: dict[str, list[FontProvider]] = {}
    #: The format this provider serves; a concrete provider names its own.
    format = ""
    #: Whether the fonts this provider creates can draw in a core-profile
    #: pass; a provider that only reaches the fixed-function pipeline leaves
    #: this false and is offered to compatibility-profile passes alone.
    shader_compatible = False

    def __init__(self) -> None:
        """Initialize the provider"""
        self.fonts: dict[Any, Any] = {}

    @classmethod
    def registerProvider(cls, obj: FontProvider) -> None:
        """Register a class as an active font-provider (classmethod)"""
        cls.providers.setdefault(obj.format, []).append(obj)


    @classmethod
    def getProviders(cls, format: str) -> list[FontProvider]:
        """Get providers for a particular format (classmethod)"""
        return cls.providers.get(format, [])


    @classmethod
    def getProviderFont(
        cls, fontStyle: Any, mode: Any = None
    ) -> tuple[FontProvider | None, Any]:
        """Get a font provider & font for given style (classmethod)

        fontStyle -- a FontStyle for FontStyle3D node, or None,
            determines which provider is "prefered"
        mode -- active rendering mode

        cls.PROVIDER_SEARCH_ORDER is used to determine the
        order of fallback formats for the explicitly specified
        format (if there is such a format).

        When mode.shader_mode is True, shader-compatible providers
        are preferred over legacy providers.
        """
        order = cls.PROVIDER_SEARCH_ORDER[:]
        if hasattr(fontStyle, "format") and fontStyle.format:
            format = fontStyle.format.lower()
            while format in order:
                order.remove(format)
            order.insert(0, format)

        # Check if we're in shader mode (core profile)
        shader_mode = getattr(mode, 'shader_mode', False) if mode else False

        for format in order:
            providers = cls.getProviders(format)
            if providers:
                # Prefer shader-compatible (texture-atlas) providers for
                # on-screen displays: they render in both core and
                # compatibility profiles without requiring a GLUT display,
                # so legacy providers (e.g. GLUT) act only as a fallback.
                providers = sorted(
                    providers,
                    key=lambda p: 0 if getattr(p, 'shader_compatible', False) else 1
                )
                for provider in providers:
                    # In shader mode legacy providers cannot run at all
                    if shader_mode and not getattr(provider, 'shader_compatible', False):
                        continue
                    try:
                        return provider, provider.get(fontStyle, mode)
                    except Exception as err:
                        if __debug__:
                            traceback.print_exc()
                        log.warning(
                            """FontProvider %r couldn't find font for %r: %s""",
                            provider,
                            fontStyle,
                            err,
                        )
        log.warning(
            """Couldn't find a provider for fontStyle %r""",
            fontStyle,
        )
        return None, None


    def addFont(self, fontStyle: Any, font: Any, mode: Any = None) -> Any:
        """Add a new font to the font provider

        fontStyle -- the font style defining the font, may
            be None to define the default font
        font -- the provider-specific font object which
            should be a sub-class of
            OpenGLContext.scenegraph.text.font.Font
        mode -- the active rendering mode
        """
        key = self.key(fontStyle)
        self.fonts[key] = font
        return font

    def get(self, fontStyle: Any = None, mode: Any = None) -> Any:
        """Get/create a new font for the given fontStyle & mode

        fontStyle -- the font style defining the font, may
            be None to retrieve the default font
        mode -- the active rendering mode
        """
        key = self.key(fontStyle)
        if key in self.fonts:
            return self.fonts.get(key)
        return self.create(fontStyle, mode)

    def key(self, fontStyle: Any = None) -> Any:
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

    def enumerate(self, mode: Any = None) -> Iterable[Any]:
        """Iterate through all available fonts (whether instantiated or not)

        These are the "low level" specifications for the fonts,
        for providers with "name"-based resolution, these will
        be the font-face-names, while providers with filename-
        based resolution will provide filenames.  Where possible,
        filename-based systems should attempt to provide names
        as well to allow for more flexibility in content
        authoring.
        """
        return ()

    def create(self, fontStyle: Any, mode: Any = None) -> Any:
        """Create a new font for the given fontStyle and mode"""

    def clear(self) -> None:
        """Force clear of the font cache for this provider"""
        self.fonts.clear()


class TTFFontProvider(FontProvider):
    """Direct TrueType-font-file-based provider"""

    TTFRegistry: Any = None

    @classmethod
    def setTTFRegistry(cls, registry: Any) -> None:
        """Set the TTF registry for the class (global if called on TTFFontProvider)"""
        cls.TTFRegistry = registry


    @classmethod
    def getTTFRegistry(cls) -> Any:
        """Set the TTF registry for the class (global if called on TTFFontProvider)"""
        return cls.TTFRegistry



getProviders = FontProvider.getProviders
setTTFRegistry = TTFFontProvider.setTTFRegistry
##
##class DiscreetFontProvider( FontProvider ):
##	"""Provide selection from a discrete list of fonts"""
