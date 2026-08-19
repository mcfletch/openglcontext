"""IndexedLineSet VRML97 node implemented using display-lists"""
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext import displaylist
from OpenGLContext.scenegraph import coordinatebounded
from vrml.vrml97 import basenodes
import warnings
import ctypes
import numpy as np
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
    def instanceContentKey(self):
        """Signature so identical wireframes (same points/index/colour) batch.

        Debug collision proxies share one unit box / unit sphere wireframe, so
        every box proxy collapses to a single instanced line draw, ditto spheres.
        """
        pts = np.asarray(self.coord.point, dtype='f').tobytes() if self.coord else b''
        idx = np.asarray(self.coordIndex, dtype='i').tobytes()
        col = np.asarray(self.color.color, dtype='f').tobytes() if self.color else b''
        return ('IndexedLineSet', pts, idx, col, bool(self.colorPerVertex))

    def _expand_line_vertices(self):
        """Expand the polylines to flat ``GL_LINES`` vertex/colour pairs (M, 3)."""
        points = np.asarray(self.coord.point, dtype='f')
        indices = expandIndices(self.coordIndex)
        has_col = bool(self.color and len(self.color.color))
        colors = np.asarray(self.color.color, dtype='f') if has_col else None
        cidx = None
        if has_col and self.colorPerVertex:
            cidx = (expandIndices(self.colorIndex) if len(self.colorIndex) else indices)
        verts, cols = [], []
        for pi, poly in enumerate(indices):
            pc = cidx[pi] if cidx is not None else None
            for k in range(len(poly) - 1):
                verts.append(points[poly[k]]); verts.append(points[poly[k + 1]])
                if has_col:
                    if pc is not None:
                        cols.append(colors[pc[k]]); cols.append(colors[pc[k + 1]])
                    else:
                        ci = (self.colorIndex[pi] if len(self.colorIndex)
                              else pi % len(colors))
                        c = colors[int(ci)][:3]
                        cols.append(c); cols.append(c)
        pos = np.ascontiguousarray(verts, dtype='f') if verts else np.zeros((0, 3), 'f')
        col = (np.ascontiguousarray(cols, dtype='f') if cols
               else np.ones((len(pos), 3), dtype='f'))
        return pos, col

    def instanceGPU(self, mode):
        """Cached ``GL_LINES`` GPU buffers for the shared instanced-line draw path."""
        gpu = mode.cache.getData(self, key='line_instance_gpu')
        if gpu is not None:
            return gpu
        pos, col = self._expand_line_vertices()
        gpu = _LineInstanceGPU(pos, col)
        holder = mode.cache.holder(self, gpu, key='line_instance_gpu')
        for attr in ('coord', 'coordIndex', 'color', 'colorIndex'):
            holder.depend(self, attr)
        return gpu

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
        """Render using shader pipeline for lines with per-vertex color support.

        All polylines share one cached, version-keyed VBO (rebuilt only when
        coord/color/index change) drawn as per-polyline GL_LINE_STRIP ranges with
        a single cached VAO, instead of generating/uploading/deleting a VBO per
        polyline per frame.
        """
        if not self.coord or not len(self.coord.point) or not len(self.coordIndex):
            return 1

        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return 1

        has_colors = bool(self.color and len(self.color.color) > 0)
        if has_colors:
            shader_program.use_line()
            program = shader_program.line_program
        else:
            shader_program.use(lit=False)
            program = shader_program.unlit_program
            # The colour the Shape's material asks for; white where the caller
            # gave the line neither per-vertex colours nor a material.
            shader_program.set_solid_color(
                getattr(mode, '_solid_color', None) or (1.0, 1.0, 1.0, 1.0))

        shader_program.set_matrices(mode.matrix, mode.projection, program=program)

        vbo_obj, stride, segments = self._line_buffer(mode, has_colors)
        if not segments:
            shader_program.use(lit=True)
            return 1

        gpu = self._line_gpu
        vao = gpu['vao'].get(int(program))
        if vao is None:
            # Where the position goes depends on which program was chosen: the
            # line program reads it at 0 and the unlit one at 2. A buffer bound
            # to the location the shader does not read puts every vertex at the
            # origin, and the line disappears with no GL error to say why.
            position = shader_program.position_location(program)
            vao = glGenVertexArrays(1)
            glBindVertexArray(vao)
            vbo_obj.bind()
            glEnableVertexAttribArray(position)
            glVertexAttribPointer(position, 3, GL_FLOAT, GL_FALSE, stride, None)
            if has_colors:
                glEnableVertexAttribArray(1)
                glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            vbo_obj.unbind()
            glBindVertexArray(0)
            gpu['vao'][int(program)] = vao

        glBindVertexArray(vao)
        try:
            for first, count in segments:
                glDrawArrays(GL_LINE_STRIP, first, count)
        finally:
            glBindVertexArray(0)

        shader_program.use(lit=True)
        return 1

    def _line_buffer(self, mode, has_colors):
        """Return (vbo, stride, segments) for the polylines, rebuilt only on change.

        ``segments`` is a list of (first, count) draw ranges into a single
        concatenated buffer. A persistent VBO is kept on the node and re-uploaded
        via set_array when coord/color/index change; the per-program VAOs are
        cleared on rebuild so their layout is rebound.
        """
        gpu = getattr(self, '_line_gpu', None)
        clean = mode.cache.getData(self, key='line_clean')
        if gpu is not None and clean is not None and gpu['has_colors'] == has_colors:
            return gpu['vbo'], gpu['stride'], gpu['segments']

        points = np.asarray(self.coord.point, dtype='f')
        indices = expandIndices(self.coordIndex)
        colors = None
        color_indices = None
        if has_colors:
            colors = np.asarray(self.color.color, dtype='f')
            if self.colorPerVertex:
                color_indices = (expandIndices(self.colorIndex)
                                 if len(self.colorIndex) else indices)
            elif len(self.colorIndex):
                color_indices = [[ci] * len(indices[i])
                                 for i, ci in enumerate(self.colorIndex)]
            else:
                color_indices = [[i] * len(poly) for i, poly in enumerate(indices)]

        rows = []
        segments = []
        first = 0
        width = 6 if has_colors else 3
        for poly_idx, polyline in enumerate(indices):
            if len(polyline) < 2:
                continue
            block = np.empty((len(polyline), width), dtype='f')
            block[:, 0:3] = points[polyline]
            if has_colors:
                poly_color_indices = (color_indices[poly_idx]
                                      if poly_idx < len(color_indices)
                                      else [0] * len(polyline))
                poly_colors = np.array(
                    [colors[min(ci, len(colors) - 1)][:3]
                     for ci in poly_color_indices], dtype='f')
                block[:, 3:6] = poly_colors
            rows.append(block)
            segments.append((first, len(polyline)))
            first += len(polyline)

        data = (np.ascontiguousarray(np.concatenate(rows)) if rows
                else np.zeros((0, width), dtype='f'))
        stride = width * 4 if has_colors else 0

        if gpu is None:
            gpu = self._line_gpu = {
                'vbo': vbo.VBO(data, usage='GL_DYNAMIC_DRAW'),
                'vao': {},
                'stride': stride,
                'has_colors': has_colors,
                'segments': segments,
            }
        else:
            gpu['vbo'].set_array(data)
            gpu['stride'] = stride
            gpu['has_colors'] = has_colors
            gpu['segments'] = segments
            gpu['vao'] = {}
        gpu['vbo'].bind()
        gpu['vbo'].unbind()

        holder = mode.cache.holder(self, True, key='line_clean')
        holder.depend(self, 'coord')
        holder.depend(self, 'coordIndex')
        holder.depend(self, 'colorIndex')
        if self.coord:
            holder.depend(self.coord, 'point')
        if self.color:
            holder.depend(self.color, 'color')
        return gpu['vbo'], gpu['stride'], gpu['segments']

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

class _LineInstanceGPU(object):
    """GL_LINES vertex buffers for the shared instanced-draw path.

    Exposes the same surface ``draw_instanced_mesh`` reads on a PBRMesh
    ``_MeshGPU`` -- ``attr_layout`` (position@0, colour@1), ``count``,
    ``draw_mode`` (GL_LINES), ``indexed`` (False) and an ``_instance_vao`` slot --
    so lines flow through the identical instancing machinery as meshes.
    """
    def __init__(self, positions, colors):
        self._pos_vbo = vbo.VBO(np.ascontiguousarray(positions, dtype='f'))
        self._col_vbo = vbo.VBO(np.ascontiguousarray(colors, dtype='f'))
        self.attr_layout = [(self._pos_vbo, 0, 3), (self._col_vbo, 1, 3)]
        self.idx_vbo = None
        self.indexed = False
        self.count = len(positions)
        self.draw_mode = GL_LINES
        self._instance_vao = None
        self._instance_vbo = None

    def release(self):
        """Delete the instanced VAO (only safe with the owning context current)."""
        vao = self._instance_vao
        if vao is not None:
            try:
                glDeleteVertexArrays(1, [vao])
            except Exception:
                pass
            self._instance_vao = None


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
