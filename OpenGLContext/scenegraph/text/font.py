"""Abstract base-class for all font implementations"""
import weakref
from OpenGLContext.arrays import *
from OpenGL.GL import *
from OpenGLContext import doinchildmatrix
import logging
log = logging.getLogger( __name__ )

class Font(object):
    """Abstract base-class for all font implementations"""
    fontStyle = None
    def render( 
        self, 
        lines,
        fontStyle=None,
        mode = None, # the renderpass object
    ):
        """Render value in this font, with control-character support

        lines -- list of Line objects to be rendered, alternately
            a string/unicode object to be converted to lines with
            self.toLines( lines, mode=mode )
        mode -- active rendering mode
        """
        if isinstance( lines, (str,unicode)):
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

    def normalise( self, value ):
        """Return a normalised value for the given value

        In our case, this means decoding utf-8 strings
        if they are passed.
        """
        if __debug__:
            log.info( """normalise %r for %s""", repr(value), self, )
        if isinstance( value, str ):
            value = value.decode( 'utf-8' )
        return value
    def toLines( self, value, mode=None ):
        """Convert value to a set of expanded lines

        Basically what this does is split value by line,
        then expand tabs (using 4-spaces per-tab),
        then return a list of Line instances for the
        resulting strings.
        """
        value = self.normalise( value)
        # XXX should be caching all this!!!
        lines = value.split('\n')
        lines = [ Line(line.expandtabs(4), self, mode=mode) for line in lines ]
        if __debug__:
            log.info( """lines %r""", repr(lines),)
        return lines
    def getChar( self, char, mode=None ):
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
    def getSpacing( self, fontStyle, mode=None ):
        """Get the vertical spacing multiplier"""
        if (not fontStyle):
            spacing = 1.0
        else:
            spacing = fontStyle.spacing
            if not fontStyle.topToBottom:
                spacing *= -1.0 # reverse orientation
        return spacing
    def totalHeight( self, lines, spacing, mode=None ):
        """Calculate total height of the line-set"""
        if lines:
            height = lines[0].height
            return abs(spacing*(len(lines)-1)*height)+height
        else:
            return 0
    def totalWidth( self, lines, mode=None ):
        """Calculate total width of the line-set"""
        if lines:
            return max( [line.width for line in lines] )
        else:
            return 0

    ### Abstract-base-class customisation points...
    def lists( self, value, mode=None ):
        """Get a sequence of display-list integers for value

        Basically, this does a bit of trickery to do
        as-required compilation of display-lists, so
        that only those characters actually required
        by the displayed text are compiled.

        NOTE: Must be called from within the rendering
        thread and within the rendering pass!
        """
    def lineHeight(self, mode=None ):
        """Retrieve normal line-height for this font
        """
        return 0
    def leftJustify( self, lines, fontStyle, mode=None  ):
        """Left-justify a list of lines"""
    def centerJustify( self, lines, fontStyle, mode=None  ):
        """Center-justify a list of lines"""
    def rightJustify( self, lines, fontStyle, mode=None  ):
        """Right-justify a list of lines"""
    def createChar( self, char, fontStyle, mode=None ):
        """Create the single-character display list
        """

    def verticalAdjust( self, spacing, lines, fontStyle, mode=None ):
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
            return 0
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
                return 0
        else:
            # baseline of the first line is the normal condition
            return 0
        return adjust
        
    def __del__( self ):
        """Clean up our display lists on deletion"""
        if __debug__:
            log.debug( """Deleting font %s""", self)
        for key,(dl,metrics) in self._displayLists.items():
            try:
                glDeleteLists( dl, 1 )
            except:
                pass

class RenderSelectMixIn( object ):
    """Mix-in providing quadrangle-based invisible-pass rendering

    XXX This should all be display-listed!
    XXX This is only usable for polygonal geometry!
    """
    def leftJustify( self, lines, fontStyle, mode=None  ):
        """Left-justify a list of lines"""
        if mode.visible:
            return super( RenderSelectMixIn, self).leftJustify( lines, fontStyle, mode )
        elif lines:
            return self._leftJustifyQuads( lines, fontStyle, mode )
        else:
            return None
    def rightJustify( self, lines, fontStyle, mode=None  ):
        """Right-justify a list of lines"""
        if mode.visible:
            return super( RenderSelectMixIn, self).rightJustify( lines, fontStyle, mode )
        elif lines:
            return self._rightJustifyQuads( lines, fontStyle, mode )
        else:
            return None
    def centerJustify( self, lines, fontStyle, mode=None  ):
        """Center-justify a list of lines"""
        if mode.visible:
            return super( RenderSelectMixIn, self).centerJustify( lines, fontStyle, mode )
        elif lines:
            return self._centerJustifyQuads( lines, fontStyle, mode )
        else:
            return None

    def _leftJustifyQuads( self, lines, fontStyle, mode=None ):
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
    def _centerJustifyQuads( self, lines, fontStyle, mode=None ):
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
    def _rightJustifyQuads( self, lines, fontStyle, mode=None ):
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

class NoDepthBufferMixIn( object ):
    """Mix-in providing disabling of depth-buffer writes"""
    def render( self, *args, **named ):
        """Special depth-buffer mode for direct-to-screen bitmap fonts

        Basically we don't want the direct-to-screen bitmap
        fonts to generate depth-buffer blocks.
        """
        depthMask = glGetBooleanv( GL_DEPTH_WRITEMASK )
        if depthMask == GL_TRUE:
            glDepthMask( GL_FALSE )
        try:
            super( NoDepthBufferMixIn, self).render( *args, **named )
        finally:
            if depthMask == GL_TRUE:
                glDepthMask( GL_TRUE )

class BitmapFontMixIn( object ):
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
    def render( self, *args, **named ):
        """Special depth-buffer mode for direct-to-screen bitmap fonts

        Basically we don't want the direct-to-screen bitmap
        fonts to generate depth-buffer blocks.
        """
        glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_BLEND)
        try:
            super( BitmapFontMixIn, self).render( *args, **named )
        finally:
            glDisable( GL_BLEND)
        
    def leftJustify( self, lines, fontStyle, mode=None  ):
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
    def centerJustify( self, lines, fontStyle, mode=None  ):
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
    def rightJustify( self, lines, fontStyle, mode=None  ):
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
    
class PolygonalFontMixIn(object):
    """Mix-in providing justification functions for polygonal text"""
    def leftJustify( self, lines, fontStyle, mode=None  ):
        """Left-justify a list of lines (wrapper to do in child matrix)"""
        doinchildmatrix.doInChildMatrix(
            self._leftJustify, lines, fontStyle, mode,
        )
    def _leftJustify( self, lines, fontStyle, mode=None  ):
        """Left-justify a list of lines (actual function)"""
        for line in lines:
            if fontStyle:
                height = line.height * fontStyle.spacing
            else:
                height = line.height
            # should do justification here...
            if len(line.lists):
                glCallLists( line.lists )
                glTranslate( -line.width, -height, 0.0)
            else:
                glTranslate( 0.0, -height, 0.0)
    def centerJustify( self, lines, fontStyle, mode=None  ):
        """Center-justify a list of lines (wrapper to do in child matrix)"""
        doinchildmatrix.doInChildMatrix(
            self._centerJustify, lines, fontStyle, mode,
        )
    def _centerJustify( self, lines, fontStyle, mode=None  ):
        """Center-justify a list of lines"""
        for line in lines:
            height = line.height * fontStyle.spacing
            # should do justification here...
            half = line.width/2.0
            glTranslate( -half, 0.0, 0.0)
            glCallLists( line.lists )
            glTranslate( -half, -height, 0.0)
    def rightJustify( self, lines, fontStyle, mode=None  ):
        """Right-justify a list of lines (wrapper to do in child matrix)"""
        doinchildmatrix.doInChildMatrix(
            self._rightJustify, lines, fontStyle, mode,
        )
    def _rightJustify( self, lines, fontStyle, mode=None  ):
        """Right-justify a list of lines"""
        for line in lines:
            height = line.height * fontStyle.spacing
            # should do justification here...
            glTranslate( -line.width, 0.0, 0.0)
            glCallLists( line.lists )
            glTranslate( 0, -height, 0.0)
    
class Line( object ):
    """Holds meta-data about a rendered line of text"""
    width = None
    height = None
    lists = ()
    def __init__( self, base, font, mode=None ):
        self.font = weakref.proxy(font)
        self.base = base
        self.lists = array( font.lists( base, mode=mode ),'I')
        self.width = self._width( mode=mode )
        self.height = font.lineHeight( mode=mode )
    def _width( self, mode=None ):
        """Calculate the width of the line"""
        width = 0
        for char in self.base:
            list, metrics = self.font.getChar( char, mode=mode )
            log.debug( 'Metrics for %s: %s', char, metrics )
            width += metrics.width
        return width

class CharacterMetrics( object ):
    """Storage for character metrics"""
    def __init__( self, char, width, height):
        self.char = char
        self.width = width
        self.height = height
    def __repr__( self ):
        return '<chr: %r %sx%s>'%( self.char, self.width, self.height)
    
