"""rendering of TTF outlines (as provided by _fonttools)
"""
from OpenGLContext.arrays import *
import weakref, sys, os
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLE import *
from OpenGLContext.scenegraph import polygontessellator, vertex
from OpenGLContext.scenegraph.text import _toolsfont, font, fontprovider
from ttfquery import glyphquery
import logging
log = logging.getLogger( __name__ )

### Now the OpenGL-specific stuff...
class OutlineGlyph( _toolsfont.Glyph ):
    """Glyph that can render to outlines, contours and control-points"""
    DEBUG_RENDER_CONTOUR_HULLS = 0
    DEBUG_RENDER_CONTROL_POINTS = 0
    def renderOutlines( self, scale = 400.0 ):
        """Simplistic rendering of the compiled outlines
        """
        glEnableClientState(GL_VERTEX_ARRAY)
        try:
            ## NOTE: with lighting enabled the line-loop can crash OpenGL when
            ## entered into a display-list!!! Darned if I can see how/why, but
            ## for now, no lighting is allowed!
            glDisable( GL_LIGHTING )
            try:
                for contour in self.outlines:
                    glVertexPointerd( asarray(contour,'d')/scale )
                    glDrawArrays(GL_LINE_LOOP, 0, len(contour))
            finally:
                glEnable( GL_LIGHTING )
        finally:
            glDisableClientState(GL_VERTEX_ARRAY)
    def renderAdvance( self, scale = 400.0):
        """Advance the rendering position by our advance width"""
        glTranslate( self.width/scale, 0,0 )
    def renderContours(self, scale = 400.0):
        """Render the contour "hulls" which control the outline"""
        def contourPoint( ((x,y),f) ):
            if f:
                glColor3f( .3,.5,0)
            else:
                glColor3f( 1,1,0)
            glVertex( x/scale,y/scale,0 )
        glBegin( GL_LINES )
        try:
            for contour in self.contours:
                if contour:
                    contourPoint( contour[0] )
                for item in contour[1:-1]:
                    contourPoint( item )
                    contourPoint( item )
                if len(contour) >=2:
                    contourPoint( contour[-1] )
        finally:
            glEnd()
    def renderControlPoints (self, scale = 400.0):
        """Render the contour control points as dots"""
        glPointSize( 4)
        glBegin( GL_POINTS )
        try:
            for contour in self.contours:
                delta = 1.0/len(contour)
                c = 0.0
                for ((x,y),f),c in [(a,min(c,1.0)) for a in contour]:
                    if f:
                        glColor3f( 0,0,c)
                    else:
                        glColor3f( 1,0,c)
                    glVertex( x/scale,y/scale,0 )
                    c+=delta
        finally:
            glEnd()

class SolidGlyph( OutlineGlyph ):
    """Glyph composed of triangle geometry"""
    tess = polygontessellator.PolygonTessellator()
    DEBUG_RENDER_EXTRUSION_NORMALS = 0
    DEBUG_RENDER_OUTLINES = 0
    def renderExtrusion( self, scale=400.0, distance=1.0):
        """Render the extrusion of the font backward by distance (using GLE)

        This is pretty simple, save that there's no good
        way to specify the normals for the edge properly :( ,
        basically anything we do is going to look weird because
        we can only specify one normal for each vertex on
        the outline.
        """
        gleSetJoinStyle( TUBE_CONTOUR_CLOSED|TUBE_JN_RAW )
        ## TTF defines everything in clockwise order, GLE assumes CCW,
        ## so need to reverse the rendering mode...
        glFrontFace( GL_CW )
        try:
            data = self._calculateExtrusionData( scale )
            for points, normals in data:
                gleExtrusion(
                    points, normals,
                    array((0,1,0),'d'), # up
                    array([(0,0,1),(0,0,0),(0,0,-distance),(0,0,-distance-1.0)],'d'), # spine
                    None,
                )
                if __debug__:
                    if self.DEBUG_RENDER_EXTRUSION_NORMALS:
                        glBegin( GL_LINES )
                        try:
                            for ((x,y), (dx,dy)) in map( None, points, normals ):
                                glColor( 0,1,0)
                                glVertex2d( x,y )
                                glColor( 1,0,0)
                                glVertex2d( x+dx,y+dy )
                        finally:
                            glEnd()
                    
        finally:
            glFrontFace( GL_CCW )
        return data
    def _calculateExtrusionData( self, scale = 400.0 ):
        """Calculate extrusion points + normals for the glyph"""
        def calculateNormal((x1,y1),(x2,y2),(x3,y3)):
            """Calculate an approximate 2D normal for a 3-point set"""
            x,y = -(y3-y1),(x3-x1)
            l = sqrt(x*x+y*y)
            if l == 0:
                # a null 3-point set, we'll skip this point & normal
                return None
            return x/l,y/l
        result = []
        for contour in self.outlines:
            contour = asarray( contour, 'd' )/scale
            points = []
            clen = len(contour)
            normals = []
            for i in range( clen):
                last = contour[((i-1)+clen)%clen]
                current = contour[i]
                next = contour[((i+1)+clen)%clen]
                normal = calculateNormal(last, current, next)
                if normal:
                    normals.append( normal )
                    points.append( current )
            result.append( (asarray(points,'d'), asarray(normals,'d')) )
        return result

    def renderCap( self, scale = 400.0, front = 1):
        """The cap is generated with GLU tessellation routines...
        """
        if self.DEBUG_RENDER_CONTOUR_HULLS:
            self.renderContours( scale )
        if self.DEBUG_RENDER_CONTROL_POINTS:
            self.renderControlPoints( scale )
        contours = self._calculateCapData( scale )
        if front:
            glNormal( 0,0,1 )
            glFrontFace( GL_CCW )
        else:
            glNormal( 0,0,-1)
            glFrontFace( GL_CW )
        try:
            try:
                glEnableClientState( GL_VERTEX_ARRAY )
                for type, vertices in contours:
                    glVertexPointerd( vertices )
                    glDrawArrays(type, 0, len(vertices))
            finally:
                glDisableClientState(GL_VERTEX_ARRAY)
        finally:
            glFrontFace( GL_CCW )
        return contours

    def _calculateCapData(self, scale = 400.0 ):
        """Calculate the tessellated data-sets for this glyph"""
        vertices = [
            [vertex.Vertex( point=(x/scale,y/scale,0.0) ) for (x,y) in outline]
            for outline in self.outlines
        ]
        gluTessNormal( self.tess.controller, 0,0,1.0 )
        contours = self.tess.tessContours( vertices, forceTriangles=0 )
        return [
            (t, asarray([ v.point for v in vertices ],'d'))
            for t, vertices in contours
        ]

class _SolidFont(_toolsfont.Font):
    """Solid-Glyph specialisation of a fonttools-based font"""
    defaultGlyphClass = SolidGlyph
class _OutlineFont(_toolsfont.Font):
    """Outline-Glyph specialisation of a fonttools-based font"""
    defaultGlyphClass = OutlineGlyph

class ToolsFontMixIn( object ):
    """Mixin providing ToolsFont common operations"""
    scale = None
    def __init__(
        self,
        fontStyle = None,
        font = None,
    ):
        """Initialise the 3D-font object

        fontStyle -- fontStyle node for this font, normally
            should be a FontStyle3D node to provide extra
            information regarding extrusion, capping and the
            like.  Otherwise uses defaults for just about
            everything.
        """
        self._displayLists = {}
        self.fontStyle = fontStyle or None
        if font is None:
            font,weight,italics = self.fontProvider.match( fontStyle )
        quality = 3
        if fontStyle and hasattr( fontStyle, 'quality' ):
            quality = fontStyle.quality
        self.font = self.fontClass( font, quality = quality )
    def toLines( self, value, mode=None ):
        """Convert value to a set of expanded lines

        Overridden to do entire compilation of the string
        in one go instead of having each line open the file
        for each character it finds is missing from the cache.
        """
        self.font.ensureGlyphs(
            self.normalise( value).replace('\n','').replace('\t',''),
        )
        return super( ToolsFontMixIn, self ).toLines( value, mode )
        
    def getScale( self ):
        """Calculate scaling from font units to fontStyle size"""
        if not self.scale:
            height = self.font.charHeight
            if self.fontStyle and hasattr( self.fontStyle, 'size'):
                target = self.fontStyle.size
            else:
                target = 1.0
            self.scale = float(height)/target
        return self.scale
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
        return self.font.lineHeight/self.getScale()

    def createChar( self, char, mode=None ):
        """Create the single-character display list"""
        glyph = self.font.getGlyph( char )
        if glyph:
            metrics = font.CharacterMetrics(
                char,
                glyph.width/self.getScale(),
                glyph.height/self.getScale(),
            )
            list = glGenLists (1)
            if list == 0:
                raise RuntimeError( """Unable to generate display list for %s"""%( self, ))
            glNewList( list, GL_COMPILE )
            try:
                try:
                    if glyph.outlines and glyph.contours:
                        self.renderGlyph( glyph, mode=mode )
                    else:
                        glyph.renderAdvance( self.getScale())
                except Exception:
                    glDeleteLists( list, 1 )
                    raise
            finally:
                glEndList()
            return list, metrics
        else:
            return None, None

class ToolsSolidFont( ToolsFontMixIn, font.PolygonalFontMixIn, font.Font ):
    """A FontTools-provided Solid (polygonal) Font"""
    format = "solid"
    fontClass = _SolidFont
    def renderGlyph( self, glyph, mode = None ):
        """Render a single glyph

        This method can render a significant number of
        sub-components:
            front-cap
            rear-cap
            sides
            outlines
            outline-normals
            contours
            control-points
        """
        scale = self.getScale()
        renderFront, renderBack, renderSides, thickness = 1,1,1, 0.0
        if self.fontStyle and hasattr( self.fontStyle, 'renderFront') and not self.fontStyle.renderFront:
            renderFront = 0
        if self.fontStyle and hasattr( self.fontStyle, 'renderBack') and not self.fontStyle.renderBack:
            renderBack = 0
        if self.fontStyle and hasattr( self.fontStyle, 'renderSides') and not self.fontStyle.renderSides:
            renderSides = 0
        if self.fontStyle and hasattr( self.fontStyle, 'thickness'):
            thickness = self.fontStyle.thickness
            
        if renderFront:
            if (not thickness) and renderBack:
                glDisable( GL_CULL_FACE )
                try:
                    glyph.renderCap( scale )
                finally:
                    glEnable( GL_CULL_FACE )
                renderBack = 0
            else:
                glyph.renderCap( scale )
        if renderBack:
            glTranslate( 0,0, -thickness)
            glyph.renderCap( scale, front = 0)
            glTranslate( 0,0, thickness)
        if renderSides and thickness > 0.0:
            # Hmm :( there is something about
            # gleExtrusion that makes this call
            # create a memory fault if it's before
            # the second cap rendering... :( 
            glyph.renderExtrusion( scale, distance = thickness )
        glyph.renderAdvance( scale )
        
class ToolsOutlineFont( ToolsFontMixIn, font.PolygonalFontMixIn, font.Font ):
    """A FontTools-provided Outline (line-set) Font

    XXX should make the debug rendering modes accessible
    """
    format = "outline"
    fontClass = _OutlineFont
    def renderGlyph( self, glyph, mode = None ):
        """Render a single glyph"""
        glyph.renderOutlines( self.getScale() )
        glyph.renderAdvance( self.getScale())

class _ToolsFontProvider( fontprovider.TTFFontProvider):
    """Singleton for creating new ToolsFont fonts
    """
    format = "" # outline or solid
    def __init__( self, fontClass ):
        super( _ToolsFontProvider, self).__init__()
        # map specifier: _toolsfont.Font sub-class
        self.fontClass = fontClass
        self.format = self.fontClass.format
        fontClass.fontProvider = self

    def key( self, fontStyle, mode=None ):
        """Calculate the key for the fontStyle"""
        if not fontStyle:
            return None
        attributes = ('family','size','style','quality','renderFront','renderBack','renderSides')
        result = []
        for a in attributes:
            if hasattr( fontStyle, a):
                item = getattr( fontStyle, a)
                if isinstance( item, list ):
                    item = tuple( item )
                result.append( item )
            else:
                result.append( None )
        return tuple( result )
        
    def create( self, fontStyle, mode=None ):
        """Create a new font for the given fontStyle and mode"""
        file, weight, italics = key = self.match(fontStyle, mode)
        # do we already have this filename + size established?
        bitmapFont = self.fontClass( fontStyle, font = file )
        self.addFont( fontStyle, bitmapFont )
        self.fonts[ key ] = bitmapFont
        return bitmapFont

    def match( self, fontStyle, mode=None ):
        """Attempt to find matching font-file for our fontstyle

        Should match any name passed into addFontFile,
        as well as the short filename for the font.
        """
        registry = self.getTTFRegistry()
        fontName = registry.fontNameFromStyle( fontStyle, mode=mode )
        weight, italics = registry.modifiersFromStyle( fontStyle, mode=mode )
        specificFonts = registry.fontMembers( fontName, weight, italics )
        if not specificFonts:
            # broaden to any weight
            specificFonts = registry.fontMembers( fontName, None, italics )
            if not specificFonts:
                # broaden to every sub-font...
                specificFonts = registry.fontMembers( fontName )
                if not specificFonts:
                    raise RuntimeError( """No concrete fonts found for general font %r (somehow)"""%( fontName, ))
        # okay, just arbitrarily choose the first item, normally will only be one anyway
        specificFont = specificFonts[0]
        fontFile = registry.fontFile( specificFont )
        return fontFile, weight, italics

ToolsSolidFontProvider = _ToolsFontProvider(ToolsSolidFont)
ToolsSolidFontProvider.registerProvider( ToolsSolidFontProvider )

ToolsOutlineFontProvider = _ToolsFontProvider(ToolsOutlineFont)
ToolsOutlineFontProvider.registerProvider( ToolsOutlineFontProvider )
