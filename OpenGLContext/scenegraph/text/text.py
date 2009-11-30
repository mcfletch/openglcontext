"""VRML97-like Text node"""
from vrml.vrml97 import basenodes
from OpenGLContext.scenegraph.text import fontprovider
from vrml import cache
from vrml import protofunctions

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
    def render(
        self,
        visible = 1, # can skip normals and textures if not
        lit = 1, # can skip normals if not
        textured = 1, # can skip textureCoordinates if not
        mode = None, # the renderpass object
    ):
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
            return font.render( lines, fontStyle=self.fontStyle, mode=mode )
        else:
            return 0
    def compile( self, mode=None ):
        """Compile the text node to provider, font, lines-set"""
        value = '\n'.join( self.string )
        provider, font = fontprovider.FontProvider.getProviderFont(
            self.fontStyle,
            mode=mode
        )
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