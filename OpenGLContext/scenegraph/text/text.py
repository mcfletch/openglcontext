"""VRML97-like Text node"""
from __future__ import annotations

from typing import Any

from vrml.vrml97 import basenodes
from OpenGLContext import lighting
from OpenGLContext.scenegraph.text import fontprovider
from vrml import cache
from vrml import protofunctions

# Imported to register their providers: Pillow's texture text, and the
# pre-drawn bitmap atlas
from OpenGLContext.scenegraph.text import pillowfont  # noqa: F401 registers the texture provider
try:
    from OpenGLContext.scenegraph.text import shaderfont
except ImportError:
    pass  # Font atlas not available

class Text( basenodes.Text ):
    """VRML97-like Text node for displaying text

    Note that the OpenGLContext Text node provides a number
    of enhancements to the VRML97 text node, the most
    pronounced of which is the ability to specify different
    "geometry formats" as attributes of the fontStyle node.

    Each text node acquires a pointer to a "font" object from
    an appropriate fontprovider, as determined by the
    fontprovider.FontProvider class's getProviderFont method.

    XXX Do not currently support right-to-left fonts
    XXX Do not currently support vertically-ordered fonts
    """
    #: Text is drawn with anti-aliased edges, so its shape is blended
    #: (:meth:`OpenGLContext.scenegraph.shape.Shape.sortKey`).
    softEdges = True

    def effectiveFontStyle( self ) -> Any:
        """The FontStyle the text is drawn with: its own; else, in a VRML97 or
        X3D document, one with FontStyle's defaults (family SERIF); else
        None, the engine's default face"""
        if self.fontStyle:
            return self.fontStyle
        if lighting.in_document( self ):
            return _document_style()
        return None

    def render(
        self,
        visible: int = 1, # can skip normals and textures if not
        lit: int = 1, # can skip normals if not
        textured: int = 1, # can skip textureCoordinates if not
        mode: Any = None, # the renderpass object
    ) -> Any:
        """Render a text-node

        Depending on the geometry format of the text,
        the resulting text may be bitmaps blitted directly
        to the screen, polygonal text rendered in 3-D,
        or line-set text outlines rendered in 3-D.
        """
        dataSet = mode.context.cache.getData(self)
        if not dataSet:
            dataSet = self.compile( mode=mode )
        provider, font, lines = dataSet
        if provider and font and lines:
            return font.render( lines, fontStyle=self.effectiveFontStyle(), mode=mode )
        else:
            return 0
    def compile( self, mode: Any = None ) -> tuple[Any, Any, Any]:
        """Compile the text node to provider, font, lines-set"""
        value = '\n'.join( self.string )
        ensure = getattr( getattr( mode, 'context', None ), 'ensureFontProviders', None )
        if ensure is not None:
            ensure()
        provider, font = fontprovider.FontProvider.getProviderFont(
            self.effectiveFontStyle(),
            mode=mode
        )
        dataSet: tuple[Any, Any, Any]
        if (not provider) or (not font):
            dataSet = (None,None,None)
        else:
            lines = font.toLines( value, mode=mode )
            dataSet = (provider,font,lines)
        holder = mode.context.cache.holder( self, dataSet )
        holder.depend( self )
        holder.depend( self, 'fontStyle' )
        holder.depend( self, 'string' )
        if self.fontStyle:
            for field in [
                'style','family','size','format',
                'quality','renderFront','renderBack','renderSides',
                'thickness'
            ]:
                if hasattr( self.fontStyle, field ):
                    holder.depend( self.fontStyle, field )
        return dataSet


_DOCUMENT_STYLE: list[Any] = []


def _document_style() -> Any:
    """The FontStyle a document's Text without one is drawn with, made once"""
    if not _DOCUMENT_STYLE:
        from OpenGLContext.scenegraph.basenodes import FontStyle  # noqa: PLC0415 basenodes imports this module
        _DOCUMENT_STYLE.append( FontStyle() )
    return _DOCUMENT_STYLE[0]
