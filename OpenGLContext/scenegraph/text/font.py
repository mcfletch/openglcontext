"""Abstract base-class for all font implementations"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

import weakref
from OpenGLContext.arrays import *
from OpenGL.GL import *
# PyOpenGL generates the type-inferring entry points at import time, so they
# need naming to be seen.
from OpenGL.GL import glTranslate, glVertex
from OpenGLContext import doinchildmatrix
import logging
log = logging.getLogger( __name__ )

if TYPE_CHECKING:
    class _FontHost:
        """What the mix-ins below need of the ``Font`` they are mixed into.

        They are always declared before ``Font`` in a font class's bases, so
        every name here is resolved along the MRO at run time; aliasing this
        to ``object`` keeps that MRO exactly as it was.
        """
        def render( self, lines: Any, fontStyle: Any = None, mode: Any = None ) -> Any: ...
        def getSpacing( self, fontStyle: Any, mode: Any = None ) -> float: ...
        def verticalAdjust(
            self, spacing: float, lines: Any, fontStyle: Any, mode: Any = None
        ) -> float: ...
        def layout(
            self, lines: Any, fontStyle: Any = None, mode: Any = None
        ) -> Iterator[tuple[Any, float, float]]: ...
        def leftJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> Any: ...
        def centerJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> Any: ...
        def rightJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> Any: ...
else:
    _FontHost = object


class Font(object):
    """Abstract base-class for all font implementations

    Class attributes:
        shader_compatible -- whether ``render`` can draw in a core-profile
            pass.  A font that only calls the fixed-function pipeline leaves
            this false and is offered to compatibility-profile passes alone;
            the provider publishes the same flag so that font-provider
            selection can skip it (see ``fontprovider.FontProvider``).
    """
    fontStyle: Any = None
    shader_compatible = False
    #: character: (display-list-or-None, metrics), filled by getChar.  A
    #: concrete font creates it in its own __init__.
    _displayLists: dict[str, tuple[Any, CharacterMetrics]]

    def render(
        self,
        lines: Any,
        fontStyle: Any = None,
        mode: Any = None, # the renderpass object
    ) -> Any:
        """Render value in this font, with control-character support

        lines -- list of Line objects to be rendered, alternately
            a string/bytes object to be converted to lines with
            self.toLines( lines, mode=mode )
        mode -- active rendering mode
        """
        if isinstance( lines, (bytes,str)):
            lines = self.toLines( lines, mode=mode )
        if fontStyle is None:
            fontStyle = self.fontStyle
        if (not fontStyle) or (not fontStyle.justify) or fontStyle.justify[0].upper() in ['FIRST','BEGIN','LEFT']:
            self.leftJustify( lines, fontStyle, mode=mode )
        elif fontStyle.justify[0].upper() in ['CENTER','MIDDLE','CENTRE']:
            self.centerJustify( lines, fontStyle, mode=mode )
        else:
            self.rightJustify( lines, fontStyle, mode=mode )
        return lines

    def normalise( self, value: bytes | str ) -> str:
        """Return a normalised value for the given value

        In our case, this means decoding utf-8 strings
        if they are passed.
        """
        log.debug( """normalise %r for %s""", value, self, )
        if isinstance( value, bytes ):
            return value.decode( 'utf-8' )
        return value
    def toLines( self, value: bytes | str, mode: Any = None ) -> list[Line]:
        """Convert value to a set of expanded lines

        Basically what this does is split value by line,
        then expand tabs (using 4-spaces per-tab),
        then return a list of Line instances for the
        resulting strings.
        """
        text = self.normalise( value)
        # XXX should be caching all this!!!
        lines = [
            Line(line.expandtabs(4), self, mode=mode)
            for line in text.split('\n')
        ]
        log.debug( """lines %r""", lines)
        return lines
    def getChar( self, char: str, mode: Any = None ) -> tuple[Any, CharacterMetrics]:
        """Get (and/or create) a single-character display-list (with metrics)"""
        if __debug__:
            log.debug( """  char, %s""", repr(char))
        current = self._displayLists.get( char )
        if current:
            if __debug__:
                log.debug( """  found current, %s""", current)
        else:
            ### Need to generate a new display-list
            if __debug__:
                log.debug( """  generating displaylist, %s""", repr(char))
            current = self.createChar(char, mode=mode)
            self._displayLists[char] = current
            if __debug__:
                log.debug( """  success, %s, %s""", *current)
        return current
    #: Fraction of its own width each line is shifted by, for every VRML97
    #: spelling of the major (first) justification value.
    JUSTIFY_X: dict[str, float] = {
        'BEGIN': 0.0, 'FIRST': 0.0, 'LEFT': 0.0,
        'MIDDLE': -0.5, 'CENTER': -0.5, 'CENTRE': -0.5,
        'END': -1.0, 'RIGHT': -1.0,
    }

    def layout(
        self, lines: Any, fontStyle: Any = None, mode: Any = None
    ) -> Iterator[tuple[Any, float, float]]:
        """Yield (line, x, y) for each line, in the text's own units

        x and y are offsets from the origin the Text node is drawn at.  The
        major justification decides x from the line's own width; the minor one
        decides where the block as a whole starts, and the spacing how far
        apart the baselines are.
        """
        spacing = self.getSpacing( fontStyle=fontStyle, mode=mode )
        y = self.verticalAdjust( spacing, lines, fontStyle=fontStyle, mode=mode )
        fraction = 0.0
        if fontStyle and fontStyle.justify:
            fraction = self.JUSTIFY_X.get( fontStyle.justify[0].upper(), 0.0 )
        for line in lines:
            yield line, line.width * fraction, y
            y -= line.height * spacing

    def getSpacing( self, fontStyle: Any, mode: Any = None ) -> float:
        """Get the vertical spacing multiplier"""
        if (not fontStyle):
            spacing = 1.0
        else:
            spacing = fontStyle.spacing
            if not fontStyle.topToBottom:
                spacing *= -1.0 # reverse orientation
        return float( spacing )
    def totalHeight( self, lines: Any, spacing: float, mode: Any = None ) -> float:
        """Calculate total height of the line-set"""
        if lines:
            height = lines[0].height
            return float( abs(spacing*(len(lines)-1)*height)+height )
        else:
            return 0.0
    def totalWidth( self, lines: Any, mode: Any = None ) -> float:
        """Calculate total width of the line-set"""
        if lines:
            return float( max( [line.width for line in lines] ) )
        else:
            return 0.0

    ### Abstract-base-class customisation points...
    def lists( self, value: str, mode: Any = None ) -> list[int]:
        """Get a sequence of display-list integers for value

        Basically, this does a bit of trickery to do
        as-required compilation of display-lists, so
        that only those characters actually required
        by the displayed text are compiled.

        NOTE: Must be called from within the rendering
        thread and within the rendering pass!
        """
        return []
    def lineHeight(self, mode: Any = None ) -> float:
        """Retrieve normal line-height for this font
        """
        return 0
    def leftJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> Any:
        """Left-justify a list of lines"""
    def centerJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> Any:
        """Center-justify a list of lines"""
    def rightJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> Any:
        """Right-justify a list of lines"""
    def createChar( self, char: str, mode: Any = None ) -> tuple[Any, CharacterMetrics]:
        """Create the single-character display list and its metrics

        Returns (display-list-or-None, CharacterMetrics); a font drawing from
        vertex buffers has no list to return, and getChar keeps the metrics
        either way.
        """
        raise NotImplementedError( """%s does not implement createChar"""%(
            self.__class__.__name__,
        ))

    def verticalAdjust(
        self, spacing: float, lines: Any, fontStyle: Any, mode: Any = None
    ) -> float:
        """Calculate adjustement for first line's position

        This needs to take into account the fontStyle's
        "minor" alignment, which specifies one of:
            FIRST -- use the bottom of the first line
            BEGIN -- if topToBottom true, top of top line, bottom
                of bottom line otherwise
            MIDDLE -- y-coordinate middle of the middle-most line
            END -- if topToBottom true, bottom edge of the last line
        """
        if not lines:
            return 0.0
        # do we have a specification at all:
        if fontStyle and fontStyle.justify and len(fontStyle.justify)>1:
            # an explicitly-specified "minor" alignment
            spec = fontStyle.justify[1]
        else:
            spec = "FIRST"
        if spec == "MIDDLE":
            total = self.totalHeight( lines, spacing, mode=mode )
            middle = total / 2.0
            # now, move up/down depending on text direction
            if spacing < 0.0: # bottomToTop
                adjust = -middle
            else:
                adjust = middle - (lines[0].height)
        elif spec == "END":
            total = self.totalHeight( lines, spacing, mode=mode )
            # now, move up/down depending on text direction
            if spacing < 0.0: # bottomToTop
                adjust = -total #- lines[0].height
            else:
                adjust = total - (lines[0].height)
        elif spec == "BEGIN":
            if spacing > 0.0: # top to bottom
                adjust = -lines[0].height
            else:
                return 0.0
        else:
            # baseline of the first line is the normal condition
            return 0.0
        return float( adjust )

    def __del__( self ) -> None:
        """Clean up our display lists on deletion"""
        if __debug__:
            log.debug( """Deleting font %s""", self)
        displayLists = getattr(self, '_displayLists', None)
        if displayLists is None:
            return
        for _key,(dl,_metrics) in displayLists.items():
            try:
                glDeleteLists( dl, 1 )
            except Exception:
                pass

class RenderSelectMixIn( _FontHost ):
    """Mix-in providing quadrangle-based invisible-pass rendering

    XXX This should all be display-listed!
    XXX This is only usable for polygonal geometry!
    """
    def leftJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> Any:
        """Left-justify a list of lines"""
        if mode.visible:
            return super( RenderSelectMixIn, self).leftJustify( lines, fontStyle, mode )
        elif lines:
            return self._leftJustifyQuads( lines, fontStyle, mode )
        else:
            return None
    def rightJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> Any:
        """Right-justify a list of lines"""
        if mode.visible:
            return super( RenderSelectMixIn, self).rightJustify( lines, fontStyle, mode )
        elif lines:
            return self._rightJustifyQuads( lines, fontStyle, mode )
        else:
            return None
    def centerJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> Any:
        """Center-justify a list of lines"""
        if mode.visible:
            return super( RenderSelectMixIn, self).centerJustify( lines, fontStyle, mode )
        elif lines:
            return self._centerJustifyQuads( lines, fontStyle, mode )
        else:
            return None

    def _leftJustifyQuads( self, lines: Any, fontStyle: Any, mode: Any = None ) -> None:
        """Draw left-justified quadrangles"""
        # This code is not OpenGL 3.1 compatible
        spacing = self.getSpacing( fontStyle=fontStyle, mode=mode )
        adjust = self.verticalAdjust( spacing, lines, fontStyle=fontStyle, mode=mode )
        hAdjust = 0.0
        glBegin( GL_QUADS )
        try:
            for line in lines:
                if fontStyle:
                    height = line.height * fontStyle.spacing
                else:
                    height = line.height
                # should do justification here...
                glVertex( hAdjust, adjust, 0 )
                glVertex( hAdjust+line.width, adjust, 0 )
                glVertex( hAdjust+line.width, adjust+line.height, 0 )
                glVertex( hAdjust, adjust+line.height, 0 )
                adjust += -height
        finally:
            glEnd()
    def _centerJustifyQuads( self, lines: Any, fontStyle: Any, mode: Any = None ) -> None:
        """Draw center-justified quadrangles"""
        # This code is not OpenGL 3.1 compatible
        spacing = self.getSpacing( fontStyle=fontStyle, mode=mode )
        adjust = self.verticalAdjust( spacing, lines, fontStyle=fontStyle, mode=mode )
        hAdjust = 0.0
        glBegin( GL_QUADS )
        try:
            for line in lines:
                if fontStyle:
                    height = line.height * fontStyle.spacing
                else:
                    height = line.height
                halfWidth = line.width/2.0
                # should do justification here...
                glVertex( hAdjust-halfWidth, adjust, 0 )
                glVertex( hAdjust+halfWidth, adjust, 0 )
                glVertex( hAdjust+halfWidth, adjust+line.height, 0 )
                glVertex( hAdjust-halfWidth, adjust+line.height, 0 )
                adjust += -height
        finally:
            glEnd()
    def _rightJustifyQuads( self, lines: Any, fontStyle: Any, mode: Any = None ) -> None:
        """Draw right-justified quadrangles"""
        # This code is not OpenGL 3.1 compatible
        spacing = self.getSpacing( fontStyle=fontStyle, mode=mode )
        adjust = self.verticalAdjust( spacing, lines, fontStyle=fontStyle, mode=mode )
        hAdjust = 0.0
        glBegin( GL_QUADS )
        try:
            for line in lines:
                if fontStyle:
                    height = line.height * fontStyle.spacing
                else:
                    height = line.height
                # should do justification here...
                glVertex( hAdjust-line.width, adjust, 0 )
                glVertex( hAdjust, adjust, 0 )
                glVertex( hAdjust, adjust+line.height, 0 )
                glVertex( hAdjust-line.width, adjust+line.height, 0 )
                adjust += -height
        finally:
            glEnd()

class NoDepthBufferMixIn( _FontHost ):
    """Mix-in providing disabling of depth-buffer writes"""
    def render( self, *args: Any, **named: Any ) -> Any:
        """Special depth-buffer mode for direct-to-screen bitmap fonts

        Basically we don't want the direct-to-screen bitmap
        fonts to generate depth-buffer blocks.
        """
        depthMask = glGetBooleanv( GL_DEPTH_WRITEMASK )
        if depthMask == GL_TRUE:
            glDepthMask( GL_FALSE )
        try:
            return super( NoDepthBufferMixIn, self).render( *args, **named )
        finally:
            if depthMask == GL_TRUE:
                glDepthMask( GL_TRUE )

class BitmapFontMixIn( _FontHost ):
    """Mix-in providing justification routines for bitmap fonts

    For OpenGL 3.1 and beyond, we'll need some more
    bookkeeping done at the font level, basically we'll
    have X textures/shaders per font.  The characters to
    render for the shader will all be composed into a single
    VBO to be rendered.  Changing the text will update the
    VBO set (which is a fairly small data-set, as it's just
    the quads involved).

    Each character needs a reference to the texture involved
    as well as the texture-coordinates for the 4 vertices.

    So we're going to wind up getting a general "compile"
    operation that iterates over all lines which use a Font,
    gathering the (translated) coordinates to pass to the
    renderer, when those are all gathered, we render the
    data-set to the card in one go...
    """
    def render( self, *args: Any, **named: Any ) -> Any:
        """Special depth-buffer mode for direct-to-screen bitmap fonts

        Basically we don't want the direct-to-screen bitmap
        fonts to generate depth-buffer blocks.
        """
        glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_BLEND)
        try:
            return super( BitmapFontMixIn, self).render( *args, **named )
        finally:
            glDisable( GL_BLEND)

    def leftJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> None:
        """Left-justify a list of lines"""
        # need to use raster-position for everything...
        glRasterPos3f( 0,0,0)
        spacing = self.getSpacing( fontStyle=fontStyle, mode=mode )
        adjust = self.verticalAdjust( spacing, lines, fontStyle=fontStyle, mode=mode )
        if adjust:
            glBitmap( 0,0,0,0, 0,adjust, None )
        for line in lines:
            if fontStyle:
                height = line.height * spacing
            else:
                height = line.height
            # should do justification here...
            glCallLists( line.lists )
            glBitmap( 0,0,0,0, -line.width,-height, None )
    def centerJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> None:
        """Center-justify a list of lines"""
        glRasterPos3f( 0,0,0)
        spacing = self.getSpacing( fontStyle=fontStyle, mode=mode )
        adjust = self.verticalAdjust( spacing, lines, fontStyle=fontStyle, mode=mode )
        if adjust:
            glBitmap( 0,0,0,0, 0,adjust, None )
        for line in lines:
            height = line.height * spacing
            # should do justification here...
            half = line.width/2.0
            glBitmap( 0,0,0,0, -half,0, None )
            glCallLists( line.lists )
            # return to center and scroll down a line
            glBitmap( 0,0,0,0, -half,-height, None )
    def rightJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> None:
        """Right-justify a list of lines"""
        glRasterPos3f( 0,0,0)
        spacing = self.getSpacing( fontStyle=fontStyle, mode=mode )
        adjust = self.verticalAdjust( spacing, lines, fontStyle=fontStyle, mode=mode )
        if adjust:
            glBitmap( 0,0,0,0, 0,adjust, None )
        for line in lines:
            height = line.height * spacing
            # should do justification here...
            glBitmap( 0,0,0,0, -line.width,0, None )
            glCallLists( line.lists )
            glBitmap( 0,0,0,0, 0,-height, None )

class PolygonalFontMixIn( _FontHost ):
    """Mix-in providing justification functions for polygonal text

    ``layout`` settles where each line goes, so all three justifications are
    one walk of the matrix stack: step to the line's place, call its display
    lists, step back.
    """
    def leftJustify( self, lines: Any, fontStyle: Any, mode: Any = None ) -> None:
        """Left-justify a list of lines (wrapper to do in child matrix)"""
        doinchildmatrix.doInChildMatrix(
            self._renderLines, lines, fontStyle, mode,
        )
    centerJustify = rightJustify = leftJustify
    def _renderLines( self, lines: Any, fontStyle: Any, mode: Any = None ) -> None:
        """Call each line's display lists where the layout puts it"""
        for line, x, y in self.layout( lines, fontStyle, mode=mode ):
            if not len(line.lists):
                continue
            glTranslate( x, y, 0.0 )
            glCallLists( line.lists )
            # the lists advance x by the line's width as they draw, so the
            # step back has to undo that as well as the step out
            glTranslate( -x-line.width, -y, 0.0 )

class Line( object ):
    """Holds meta-data about a rendered line of text"""
    #: display-list names for the line's characters, as a GL-ready array
    lists: Any
    width: float
    height: float
    def __init__( self, base: str, font: Font, mode: Any = None ) -> None:
        self.font = weakref.proxy(font)
        self.base = base
        self.lists = array( font.lists( base, mode=mode ),'I')
        self.width = self._width( mode=mode )
        self.height = font.lineHeight( mode=mode )
    def _width( self, mode: Any = None ) -> float:
        """Calculate the width of the line"""
        width = 0.0
        for char in self.base:
            list, metrics = self.font.getChar( char, mode=mode )
            log.debug( 'Metrics for %s: %s', char, metrics )
            width += metrics.width
        return width

class CharacterMetrics( object ):
    """Storage for character metrics"""
    def __init__( self, char: str, width: float, height: float ) -> None:
        self.char = char
        self.width = width
        self.height = height
    def __repr__( self ) -> str:
        return '<chr: %r %sx%s>'%( self.char, self.width, self.height)

