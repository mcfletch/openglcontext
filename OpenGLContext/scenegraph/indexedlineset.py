"""IndexedLineSet VRML97 node implemented using display-lists"""
from OpenGL.GL import *
from OpenGLContext import displaylist
from OpenGLContext.scenegraph import coordinatebounded
from vrml.vrml97 import basenodes
import warnings
from vrml import protofunctions
try:
    from itertools import izip_longest as zip_longest
except ImportError:
    from itertools import zip_longest

class IndexedLineSet(
    coordinatebounded.CoordinateBounded,
    basenodes.IndexedLineSet
):
    """VRML97-style Line-Set object

    The IndexedLineSet provides GL_LINE/GL_LINE_STRIP
    geometry, with support for per-vertex or whole-set
    colors.

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#IndexedLineSet
    
    # This code is not OpenGL 3.1 compatible
    """
    def compile( self, mode=None ):
        """Compile the IndexedLineSet into a display-list
        """
        if self.coord and len(self.coord.point) and len(self.coordIndex):
            dl = displaylist.DisplayList()
            holder = mode.cache.holder(self, dl)
            for field in protofunctions.getFields( self ):
                # change to any field requires a recompile
                holder.depend( self, field )
            for (n, attr) in [
                (self.coord, 'point'),
                (self.color, 'color'),
            ]:
                if n:
                    holder.depend( n, protofunctions.getField(n,attr) )
                
            points = self.coord.point
            indices = expandIndices( self.coordIndex )
            #XXX should do sanity checks here...
            if self.color and len(self.color.color):
                colors = self.color.color
                if self.colorPerVertex:
                    if len(self.colorIndex):
                        colorIndices = expandIndices( self.colorIndex )
                    else:
                        colorIndices = indices
                else:
                    if len(self.colorIndex):
                        # each item represents a single polyline colour
                        colorIndices = self.colorIndex
                    else:
                        # each item in color used in turn by each polyline
                        colorIndices = range(len(indices))
                # compile the color-friendly ILS
                dl.start()
                try:
                    glEnable( GL_COLOR_MATERIAL )
                    for index in range(len(indices)):
                        polyline = indices[index]
                        color = colorIndices[index]
                        try:
                            color = int(color)
                        except (TypeError,ValueError):
                            glBegin( GL_LINE_STRIP )
                            try:
                                for i,c in zip_longest(polyline, color):
                                    if c is not None:
                                        # numpy treats None as retrieve all??? why?
                                        currentColor = colors[c]
                                        if currentColor is not None:
                                            glColor3d( *currentColor )
                                    glVertex3f(*points[i])
                            finally:
                                glEnd()
                        else:
                            glColor3d( *colors[color] )
                            glBegin( GL_LINE_STRIP )
                            try:
                                for i in polyline:
                                    glVertex3f(*points[i])
                            finally:
                                glEnd()
                    glDisable( GL_COLOR_MATERIAL )
                finally:
                    dl.end()
            else:
                dl.start()
                try:
                    for index in range(len(indices)):
                        polyline = indices[index]
                        glBegin( GL_LINE_STRIP )
                        try:
                            for i in polyline:
                                glVertex3f(*points[i])
                        finally:
                            glEnd()
                finally:
                    dl.end()
            return dl
        return None

    def render (
        self,
        visible = 1, # can skip normals and textures if not
        lit = 1, # can skip normals if not
        textured = 1, # can skip textureCoordinates if not
        transparent = 0, # need to sort triangle geometry...
        mode = None, # the renderpass object for which we compile
    ):
        """Render the IndexedFaceSet's geometry for a Shape

            visible -- if false, do nothing
            lit - ignored
            textured -- ignored
            transparent -- ignored
        """
        # Check for shader mode
        if getattr(mode, 'shader_mode', False):
            return self._render_shader(mode)

        # Legacy rendering path
        if visible:
            dl = mode.cache.getData(self)
            if not dl:
                dl = self.compile(mode=mode)
            if dl is None:
                return 1
            # okay, is now a (cached) display list object
            dl()
        return 1

    def _render_shader(self, mode):
        """Render using shader pipeline for lines with per-vertex color support."""
        from OpenGL.GL import (
            glEnableVertexAttribArray, glDisableVertexAttribArray,
            glVertexAttribPointer, glDrawArrays, GL_FLOAT, GL_FALSE, GL_LINE_STRIP,
            glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays,
            glGenBuffers, glBindBuffer, glBufferData, glDeleteBuffers,
            GL_ARRAY_BUFFER, GL_DYNAMIC_DRAW,
            glGetUniformLocation,
        )
        import numpy as np
        import ctypes

        if not self.coord or not len(self.coord.point) or not len(self.coordIndex):
            return 1

        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return 1

        points = self.coord.point
        indices = expandIndices(self.coordIndex)

        # Determine if we have per-vertex colors
        has_colors = self.color and len(self.color.color) > 0

        if has_colors:
            # Use line shader with per-vertex colors
            shader_program.use_line()
            program = shader_program.line_program
        else:
            # Fall back to unlit shader with solid white color
            shader_program.use(lit=False)
            program = shader_program.unlit_program
            shader_program.set_solid_color((1.0, 1.0, 1.0, 1.0))

        shader_program.set_matrices(mode.matrix, mode.projection, program=program)

        # Build color data if available
        colors = None
        if has_colors:
            colors = np.asarray(self.color.color, dtype='f')
            # Build color indices matching the coordinate indices
            if self.colorPerVertex:
                if len(self.colorIndex):
                    color_indices = expandIndices(self.colorIndex)
                else:
                    color_indices = indices  # Same as coord indices
            else:
                # Color per polyline - expand to per-vertex
                if len(self.colorIndex):
                    color_indices = [[ci] * len(indices[i]) for i, ci in enumerate(self.colorIndex)]
                else:
                    color_indices = [[i] * len(poly) for i, poly in enumerate(indices)]

        # Create VAO for core profile compatibility
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)

        buffer = None
        try:
            # Line shader uses fixed attribute locations:
            # layout(location = 0) in vec3 aPosition;
            # layout(location = 1) in vec3 aColor;
            pos_loc = 0
            color_loc = 1

            # Draw each polyline
            for poly_idx, polyline in enumerate(indices):
                if len(polyline) < 2:
                    continue

                # Build vertex data for this polyline
                poly_points = np.array([points[i] for i in polyline], dtype='f')

                if has_colors:
                    # Get colors for this polyline
                    poly_color_indices = color_indices[poly_idx] if poly_idx < len(color_indices) else [0] * len(polyline)
                    poly_colors = np.array([colors[min(ci, len(colors)-1)] for ci in poly_color_indices], dtype='f')

                    # Ensure colors have 3 components
                    if poly_colors.ndim == 1:
                        poly_colors = poly_colors.reshape(-1, 3)
                    elif poly_colors.shape[1] > 3:
                        poly_colors = poly_colors[:, :3]

                    # Interleave position and color: [x,y,z,r,g,b, ...]
                    interleaved = np.empty((len(polyline), 6), dtype='f')
                    interleaved[:, 0:3] = poly_points
                    interleaved[:, 3:6] = poly_colors
                    interleaved = np.ascontiguousarray(interleaved)
                    stride = 6 * 4  # 6 floats * 4 bytes
                else:
                    interleaved = np.ascontiguousarray(poly_points)
                    stride = 0

                # Create buffer for this polyline
                if buffer:
                    glDeleteBuffers(1, [buffer])
                buffer = glGenBuffers(1)
                glBindBuffer(GL_ARRAY_BUFFER, buffer)
                glBufferData(GL_ARRAY_BUFFER, interleaved.nbytes, interleaved, GL_DYNAMIC_DRAW)

                # Set up position attribute
                glEnableVertexAttribArray(pos_loc)
                glVertexAttribPointer(pos_loc, 3, GL_FLOAT, GL_FALSE, stride, None)

                # Set up color attribute if we have per-vertex colors
                if has_colors:
                    glEnableVertexAttribArray(color_loc)
                    glVertexAttribPointer(color_loc, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

                glDrawArrays(GL_LINE_STRIP, 0, len(polyline))

                glDisableVertexAttribArray(pos_loc)
                if has_colors:
                    glDisableVertexAttribArray(color_loc)

        finally:
            glBindVertexArray(0)
            glDeleteVertexArrays(1, [vao])
            if buffer:
                glDeleteBuffers(1, [buffer])

        # Restore the lit shader
        shader_program.use(lit=True)
        return 1

    def yeildVertices( self ):
        """Yield set of vertices to be rendered..."""
        # this is an unfinished start to getting OpenGL 3.1 operation
        if self.coord and len(self.coord.point) and len(self.coordIndex):
            points = self.coord.point
            indices = expandIndices( self.coordIndex )
            currentColor = None
            #XXX should do sanity checks here...
            if self.color and len(self.color.color):
                colors = self.color.color
                if self.colorPerVertex:
                    if len(self.colorIndex):
                        colorIndices = expandIndices( self.colorIndex )
                    else:
                        colorIndices = indices
                else:
                    if len(self.colorIndex):
                        # each item represents a single polyline colour
                        colorIndices = self.colorIndex
                    else:
                        # each item in color used in turn by each polyline
                        colorIndices = range(len(indices))
                # compile the color-friendly ILS
                for index in range(len(indices)):
                    polyline = indices[index]
                    color = colorIndices[index]
                    try:
                        color = int(color)
                    except (TypeError,ValueError):
                        for i,c in zip_longest(polyline, color):
                            if c is not None:
                                # numpy treats None as retrieve all??? why?
                                currentColor = colors[c]
                            yield currentColor, points[i]
                    else:
                        for i in polyline:
                            yield colors[color], points[i]
                        yield None
            else:
                for index in range(len(indices)):
                    polyline = indices[index]
                    for i in polyline:
                        yield None, points[i]
                    yield None

def expandIndices( indices ):
    """Create a set of poly-line definitions"""
    items = []
    current = []
    for i in indices:
        if i == -1:
            if len(current)<2:
                # should warn the user
                warnings.warn( """IndexedLineSet Polyline of length < 2""")
            else:
                items.append( current )
            current = []
        else:
            current.append( i )
    if current:
        items.append( current )
    return items
