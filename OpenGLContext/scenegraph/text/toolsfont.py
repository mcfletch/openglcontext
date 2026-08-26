"""Filled and extruded 3D glyphs from TrueType outlines
"""
from OpenGLContext.arrays import *
import weakref, sys, os
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLE import *
from OpenGL.arrays import vbo
from OpenGLContext.scenegraph import polygontessellator, vertex
from OpenGLContext.scenegraph.vertexsemantics import (
    LOC_NORMAL, LOC_POSITION,
)
from OpenGLContext.scenegraph.text import _toolsfont, font, fontprovider
from ttfquery import glyphquery
import logging
log = logging.getLogger( __name__ )
import numpy as np

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
        def contourPoint( record ):
            ((x,y),f) = record
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
                            for ((x,y), (dx,dy)) in zip( points, normals ):
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
        def calculateNormal(first,second,third):
            """Calculate an approximate 2D normal for a 3-point set"""
            (x1,y1) = first
            (x2,y2) = second
            (x3,y3) = third
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

    # Shader-compatible geometry building methods
    _shader_geometry_cache = None

    def buildShaderGeometry(self, scale=400.0, thickness=0.0,
                            renderFront=True, renderBack=True, renderSides=True):
        """Build VBO-compatible geometry for shader rendering.

        Returns a dict with:
            'vertices': VBO of interleaved normal(3) + position(3) data
            'vertex_count': number of vertices
            'advance': x advance for this glyph
        """
        if not self.outlines or not self.contours:
            return {
                'vertices': None,
                'vertex_count': 0,
                'advance': self.width / scale
            }

        all_vertices = []

        # Build front cap
        if renderFront:
            front_verts = self._buildCapGeometry(scale, front=True, z_offset=0.0)
            all_vertices.extend(front_verts)

        # Build back cap
        if renderBack and thickness > 0.0:
            back_verts = self._buildCapGeometry(scale, front=False, z_offset=-thickness)
            all_vertices.extend(back_verts)

        # Build sides (extrusion)
        if renderSides and thickness > 0.0:
            side_verts = self._buildExtrusionGeometry(scale, thickness)
            all_vertices.extend(side_verts)

        if not all_vertices:
            return {
                'vertices': None,
                'vertex_count': 0,
                'advance': self.width / scale
            }

        # Convert to numpy array: each vertex is [nx, ny, nz, px, py, pz]
        vertex_array = np.array(all_vertices, dtype='f')
        vertex_vbo = vbo.VBO(vertex_array)

        return {
            'vertices': vertex_vbo,
            'vertex_count': len(all_vertices),
            'advance': self.width / scale
        }

    def _buildCapGeometry(self, scale, front=True, z_offset=0.0):
        """Build triangle geometry for front or back cap.

        Returns list of [nx, ny, nz, px, py, pz] vertex data.
        """
        vertices = [
            [vertex.Vertex(point=(x/scale, y/scale, z_offset)) for (x, y) in outline]
            for outline in self.outlines
        ]
        gluTessNormal(self.tess.controller, 0, 0, 1.0 if front else -1.0)
        contours = self.tess.tessContours(vertices, forceTriangles=True)

        normal = [0.0, 0.0, 1.0] if front else [0.0, 0.0, -1.0]
        result = []

        for v in contours:
            px, py, pz = v.point
            result.append([normal[0], normal[1], normal[2], px, py, pz])

        return result

    def _buildExtrusionGeometry(self, scale, thickness):
        """Build triangle geometry for glyph sides (extrusion).

        Creates quad strips along each contour from z=0 to z=-thickness,
        converted to triangles.

        Returns list of [nx, ny, nz, px, py, pz] vertex data.
        """
        result = []
        extrusion_data = self._calculateExtrusionData(scale)

        for points, normals in extrusion_data:
            n_points = len(points)
            if n_points < 2:
                continue

            # Create quad strip along the contour
            for i in range(n_points):
                next_i = (i + 1) % n_points

                # Current and next positions
                p0 = points[i]
                p1 = points[next_i]

                # Normals (2D, extend to 3D with z=0)
                n0 = normals[i]
                n1 = normals[next_i]

                # Four corners of the quad:
                # v0: p0 at z=0
                # v1: p1 at z=0
                # v2: p0 at z=-thickness
                # v3: p1 at z=-thickness

                v0 = [p0[0], p0[1], 0.0]
                v1 = [p1[0], p1[1], 0.0]
                v2 = [p0[0], p0[1], -thickness]
                v3 = [p1[0], p1[1], -thickness]

                n0_3d = [n0[0], n0[1], 0.0]
                n1_3d = [n1[0], n1[1], 0.0]

                # Triangle 1: v0, v2, v1 (CCW from outside)
                result.append([n0_3d[0], n0_3d[1], n0_3d[2], v0[0], v0[1], v0[2]])
                result.append([n0_3d[0], n0_3d[1], n0_3d[2], v2[0], v2[1], v2[2]])
                result.append([n1_3d[0], n1_3d[1], n1_3d[2], v1[0], v1[1], v1[2]])

                # Triangle 2: v1, v2, v3 (CCW from outside)
                result.append([n1_3d[0], n1_3d[1], n1_3d[2], v1[0], v1[1], v1[2]])
                result.append([n0_3d[0], n0_3d[1], n0_3d[2], v2[0], v2[1], v2[2]])
                result.append([n1_3d[0], n1_3d[1], n1_3d[2], v3[0], v3[1], v3[2]])

        return result


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

    def __init__(self, *args, **kwargs):
        super(ToolsSolidFont, self).__init__(*args, **kwargs)
        # Shader rendering cache: {char: {'start': int, 'count': int, 'advance': float}}
        self._shader_glyph_index = {}
        self._shader_vbo = None
        self._shader_vbo_chars = set()  # Characters included in the VBO

    def render(self, lines, fontStyle=None, mode=None):
        """Render text, using shader path when in shader mode."""
        # Check for shader mode
        if mode is not None and getattr(mode, 'shader_mode', False):
            # Convert lines to string if needed
            if isinstance(lines, (bytes, str)):
                text = lines if isinstance(lines, str) else lines.decode('utf-8')
            else:
                # Lines is a list of Line objects
                text = '\n'.join(line.base for line in lines)

            # Use shader rendering
            return self._renderShaderJustified(text, fontStyle, mode)

        # Fall back to legacy rendering
        return super(ToolsSolidFont, self).render(lines, fontStyle, mode)

    def _renderShaderJustified(self, text, fontStyle, mode):
        """Render text with shader, handling justification."""
        if fontStyle is None:
            fontStyle = self.fontStyle

        lines = text.split('\n')
        spacing = self.getSpacing(fontStyle=fontStyle, mode=mode)

        # Calculate line widths for justification
        line_data = []
        for line_text in lines:
            width = 0.0
            self.font.ensureGlyphs(line_text)
            for char in line_text:
                glyph = self.font.getGlyph(char)
                if glyph:
                    width += glyph.width / self.getScale()
            line_data.append((line_text, width))

        # Determine justification
        justify = 'LEFT'
        if fontStyle and fontStyle.justify:
            justify = fontStyle.justify[0].upper()
            if justify in ['CENTER', 'MIDDLE', 'CENTRE']:
                justify = 'CENTER'
            elif justify in ['END', 'RIGHT']:
                justify = 'RIGHT'
            else:
                justify = 'LEFT'

        # Calculate vertical adjust
        # For now, simple top-down rendering
        y_offset = 0.0
        line_height = self.lineHeight(mode=mode)

        base_matrix = mode.matrix.copy()

        for line_text, width in line_data:
            if not line_text:
                y_offset -= line_height * spacing
                continue

            # Calculate x offset based on justification
            if justify == 'CENTER':
                x_start = -width / 2.0
            elif justify == 'RIGHT':
                x_start = -width
            else:
                x_start = 0.0

            # Build transform for this line
            line_matrix = base_matrix.copy()
            # Apply y offset
            line_matrix[3, 0] += y_offset * base_matrix[1, 0]
            line_matrix[3, 1] += y_offset * base_matrix[1, 1]
            line_matrix[3, 2] += y_offset * base_matrix[1, 2]
            # Apply x start offset
            line_matrix[3, 0] += x_start * base_matrix[0, 0]
            line_matrix[3, 1] += x_start * base_matrix[0, 1]
            line_matrix[3, 2] += x_start * base_matrix[0, 2]

            # Temporarily set mode.matrix for renderShader
            old_matrix = mode.matrix
            mode.matrix = line_matrix
            try:
                self.renderShader(line_text, mode)
            finally:
                mode.matrix = old_matrix

            y_offset -= line_height * spacing

        return lines

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

    def _getShaderParams(self):
        """Get rendering parameters from fontStyle."""
        scale = self.getScale()
        renderFront, renderBack, renderSides, thickness = True, True, True, 0.0
        if self.fontStyle:
            if hasattr(self.fontStyle, 'renderFront') and not self.fontStyle.renderFront:
                renderFront = False
            if hasattr(self.fontStyle, 'renderBack') and not self.fontStyle.renderBack:
                renderBack = False
            if hasattr(self.fontStyle, 'renderSides') and not self.fontStyle.renderSides:
                renderSides = False
            if hasattr(self.fontStyle, 'thickness'):
                thickness = self.fontStyle.thickness
        return scale, renderFront, renderBack, renderSides, thickness

    def _ensureShaderVBO(self, text):
        """Ensure VBO contains geometry for all characters in text.

        Rebuilds the VBO if new characters are needed.
        """
        unique_chars = set(text.replace('\n', '').replace('\t', ''))
        new_chars = unique_chars - self._shader_vbo_chars

        if not new_chars and self._shader_vbo is not None:
            return  # VBO already has all needed characters

        # Rebuild VBO with all characters (existing + new)
        all_chars = self._shader_vbo_chars | unique_chars

        scale, renderFront, renderBack, renderSides, thickness = self._getShaderParams()

        all_vertices = []
        glyph_index = {}

        for char in sorted(all_chars):
            glyph = self.font.getGlyph(char)
            if glyph and glyph.outlines and glyph.contours:
                geom = glyph.buildShaderGeometry(
                    scale=scale,
                    thickness=thickness,
                    renderFront=renderFront,
                    renderBack=renderBack,
                    renderSides=renderSides
                )

                if geom['vertices'] is not None and geom['vertex_count'] > 0:
                    start_index = len(all_vertices)
                    # Extract raw array from VBO for combining
                    all_vertices.extend(geom['vertices'].data.tolist())
                    glyph_index[char] = {
                        'start': start_index,
                        'count': geom['vertex_count'],
                        'advance': geom['advance']
                    }
                else:
                    # Empty glyph (space, etc.)
                    glyph_index[char] = {
                        'start': 0,
                        'count': 0,
                        'advance': glyph.width / scale if glyph else 0.0
                    }
            elif glyph:
                # Glyph exists but has no geometry (e.g., space)
                glyph_index[char] = {
                    'start': 0,
                    'count': 0,
                    'advance': glyph.width / scale
                }

        if all_vertices:
            vertex_array = np.array(all_vertices, dtype='f')
            self._shader_vbo = vbo.VBO(vertex_array)
        else:
            self._shader_vbo = None

        self._shader_glyph_index = glyph_index
        self._shader_vbo_chars = all_chars

    def renderShader(self, text, mode):
        """Render text using shader pipeline.

        Args:
            text: String to render
            mode: Render mode with shader_program
        """
        if not text:
            return

        # Ensure glyphs are loaded
        self.font.ensureGlyphs(text.replace('\n', '').replace('\t', ''))

        # Build/update VBO
        self._ensureShaderVBO(text)

        if self._shader_vbo is None:
            return

        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None or shader_program.program is None:
            return

        # Create VAO
        vao_id = glGenVertexArrays(1)
        glBindVertexArray(vao_id)

        try:
            self._shader_vbo.bind()
            try:
                # Set up vertex attributes
                # Format: normal(3) + position(3) = 6 floats = 24 bytes
                stride = 24
                normal_offset = 0
                position_offset = 12

                from ctypes import c_void_p

                glEnableVertexAttribArray(LOC_POSITION)
                glVertexAttribPointer(LOC_POSITION, 3, GL_FLOAT, GL_FALSE, stride,
                                      c_void_p(position_offset))
                glEnableVertexAttribArray(LOC_NORMAL)
                glVertexAttribPointer(LOC_NORMAL, 3, GL_FLOAT, GL_FALSE, stride,
                                      c_void_p(normal_offset))

                # Render each character with its transform
                x_offset = 0.0
                base_matrix = mode.matrix.copy()

                for char in text:
                    if char == '\n' or char == '\t':
                        continue

                    glyph_info = self._shader_glyph_index.get(char)
                    if glyph_info is None:
                        continue

                    if glyph_info['count'] > 0:
                        # Apply x offset transform
                        char_matrix = base_matrix.copy()
                        # Translate in x for character position
                        char_matrix[3, 0] += x_offset * base_matrix[0, 0]
                        char_matrix[3, 1] += x_offset * base_matrix[0, 1]
                        char_matrix[3, 2] += x_offset * base_matrix[0, 2]

                        shader_program.set_matrices(
                            char_matrix,
                            mode.getProjection(),
                            shader_program.program
                        )

                        glDrawArrays(GL_TRIANGLES, glyph_info['start'], glyph_info['count'])

                    x_offset += glyph_info['advance']

                # Restore original matrix
                shader_program.set_matrices(
                    base_matrix,
                    mode.getProjection(),
                    shader_program.program
                )

                glDisableVertexAttribArray(2)
                glDisableVertexAttribArray(1)
            finally:
                self._shader_vbo.unbind()
        finally:
            glBindVertexArray(0)
            glDeleteVertexArrays(1, [vao_id])
        
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
