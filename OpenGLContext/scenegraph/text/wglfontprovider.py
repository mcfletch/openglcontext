"""Win32 (win32ui and WGL)-specific font providers
"""
from __future__ import annotations

from typing import Any

from OpenGLContext.scenegraph.text import fontprovider, wglfont

class WGLOutlineFonts( fontprovider.FontProvider ):
    """Font provider for WGL outline (polygon) fonts"""
    format = "polygon"
    def get( self, fontStyle: Any = None, mode: Any = None ) -> wglfont.WGLOutlineFont:
        """Get a WGLOutlineFont object for the given fontStyle

        Basically this object will be able to generate
        character display-lists for use in displaying
        the given font, and will also include
        information for formatting larger paragraphs
        or the like according to the font metrics.
        """
        return wglfont.WGLOutlineFont(
            fontStyle = fontStyle,
        )
fontprovider.FontProvider.registerProvider( WGLOutlineFonts() )

class WGLBitmapFonts( fontprovider.FontProvider ):
    """Font provider for WGL bitmap fonts"""
    format = "bitmap"
    def get( self, fontStyle: Any = None, mode: Any = None ) -> wglfont.WGLBitmapFont:
        """Get a WGLBitmapFont object for the given fontStyle

        Basically this object will be able to generate
        character display-lists for use in displaying
        the given font, and will also include
        information for formatting larger paragraphs
        or the like according to the font metrics.
        """
        return wglfont.WGLBitmapFont(
            fontStyle = fontStyle,
        )
fontprovider.FontProvider.registerProvider( WGLBitmapFonts() )
