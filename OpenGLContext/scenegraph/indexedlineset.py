"""IndexedLineSet: polylines with per-vertex or per-line colour

Draws through the shader pass under the core profile, and as a display list
under the compatibility profile. An appearance's X3D `LineProperties`
widens and dashes the lines
(:func:`~OpenGLContext.scenegraph.drawproperties.line_style`): through the
pass's wide-line program, whose geometry stage draws each segment as a quad
facing the screen, or with the fixed-function line width and stipple.
"""
from collections.abc import Iterator, Sequence
from typing import Any, Optional

from OpenGL.GL import *
from OpenGL.GL import glDeleteVertexArrays
from OpenGL.arrays import vbo
from OpenGLContext import displaylist
from OpenGLContext.scenegraph import coordinatebounded, coordinates, drawproperties
from OpenGLContext.scenegraph.vertexsemantics import (
    LOC_COLOR, LOC_POSITION, LOC_TEXCOORD,
)
from vrml.vrml97 import basenodes
import warnings
import ctypes
import numpy as np
from vrml import protofunctions
from itertools import zip_longest


#: ``vbo.VBO`` types as ``None``: PyOpenGL binds the name late, to whichever of
#: the accelerated and the pure-Python class it loaded.
VBO: Any = vbo.VBO


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
    def instanceContentKey(self) -> tuple[Any, ...]:
        """Signature so identical wireframes (same points/index/colour) batch.

        Debug collision proxies share one unit box / unit sphere wireframe, so
        every box proxy collapses to a single instanced line draw, ditto spheres.
        """
        pts = np.asarray(coordinates.points(self.coord), dtype='f').tobytes() if self.coord else b''
        idx = np.asarray(self.coordIndex, dtype='i').tobytes()
        col = np.asarray(self.color.color, dtype='f').tobytes() if self.color else b''
        return ('IndexedLineSet', pts, idx, col, bool(self.colorPerVertex))

    def _expand_line_vertices(self) -> tuple[Any, Any]:
        """Expand the polylines to flat ``GL_LINES`` vertex/colour pairs (M, 3);
        empty for a set with no coordinates."""
        if not self.coord:
            return np.zeros((0, 3), 'f'), np.zeros((0, 3), 'f')
        points = np.asarray(coordinates.points(self.coord), dtype='f')
        indices = expandIndices(self.coordIndex)
        colors = (np.asarray(self.color.color, dtype='f')
                  if self.color and len(self.color.color) else None)
        cidx = (polyline_color_indices(indices, self.colorIndex, bool(self.colorPerVertex),
                                       len(colors))
                if colors is not None else None)
        verts: list[Any] = []
        cols: list[Any] = []
        for pi, poly in enumerate(indices):
            for k in range(len(poly) - 1):
                verts.append(points[poly[k]])
                verts.append(points[poly[k + 1]])
                if colors is not None and cidx is not None:
                    cols.append(colors[cidx[pi][k]][:3])
                    cols.append(colors[cidx[pi][k + 1]][:3])
        pos = np.ascontiguousarray(verts, dtype='f') if verts else np.zeros((0, 3), 'f')
        col = (np.ascontiguousarray(cols, dtype='f') if cols
               else np.ones((len(pos), 3), dtype='f'))
        return pos, col

    def instanceGPU(self, mode: Any) -> "_LineInstanceGPU":
        """Cached ``GL_LINES`` GPU buffers for the shared instanced-line draw path."""
        gpu: Optional[_LineInstanceGPU] = mode.cache.getData(
            self, key='line_instance_gpu')
        if gpu is not None:
            return gpu
        pos, col = self._expand_line_vertices()
        gpu = _LineInstanceGPU(pos, col)
        holder = mode.cache.holder(self, gpu, key='line_instance_gpu')
        for attr in ('coord', 'coordIndex', 'color', 'colorIndex'):
            holder.depend(self, attr)
        for source, name in coordinates.fields(self.coord):
            holder.depend(source, name)
        return gpu

    def compile( self, mode: Any = None ) -> Any:
        """Compile the IndexedLineSet into a display-list
        """
        if self.coord and len(coordinates.points(self.coord)) and len(self.coordIndex):
            dl = displaylist.DisplayList()
            holder = mode.cache.holder(self, dl)
            for field in protofunctions.getFields( self ):
                # change to any field requires a recompile
                holder.depend( self, field )
            for (n, attr) in [*coordinates.fields(self.coord), (self.color, 'color')]:
                if n:
                    holder.depend( n, protofunctions.getField(n,attr) )

            points = coordinates.points(self.coord)
            indices = expandIndices( self.coordIndex )
            #XXX should do sanity checks here...
            if self.color and len(self.color.color):
                colors = self.color.color
                colorIndices: Any = polyline_color_indices(
                    indices, self.colorIndex, bool(self.colorPerVertex), len(colors))
                # compile the color-friendly ILS
                dl.start()
                try:
                    glEnable( GL_COLOR_MATERIAL )
                    for index in range(len(indices)):
                        polyline = indices[index]
                        color: Any = colorIndices[index]
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
        visible: int = 1, # can skip normals and textures if not
        lit: int = 1, # can skip normals if not
        textured: int = 1, # can skip textureCoordinates if not
        transparent: int = 0, # need to sort triangle geometry...
        mode: Any = None, # the renderpass object for which we compile
    ) -> int:
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
            style = drawproperties.line_style(getattr(mode, '_lineProperties', None))
            if style.plain:
                dl()
                return 1
            factor, pattern = drawproperties.stipple(style)
            glLineWidth(style.width)
            if style.pattern:
                glEnable(GL_LINE_STIPPLE)
                glLineStipple(factor, pattern)
            try:
                dl()
            finally:
                glDisable(GL_LINE_STIPPLE)
                glLineWidth(1.0)
        return 1

    def _render_shader(self, mode: Any) -> int:
        """Render using shader pipeline for lines with per-vertex color support.

        All polylines share one cached, version-keyed VBO (rebuilt only when
        coord/color/index change) drawn as per-polyline GL_LINE_STRIP ranges with
        a single cached VAO, instead of generating/uploading/deleting a VBO per
        polyline per frame.
        """
        if not self.coord or not len(coordinates.points(self.coord)) or not len(self.coordIndex):
            return 1

        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return 1

        has_colors = bool(self.color and len(self.color.color) > 0)
        style = drawproperties.line_style(getattr(mode, '_lineProperties', None))
        program = None
        if not style.plain:
            program = shader_program.use_wide_line()
        if program is not None:
            shader_program.set_line_style(style, mode.getViewport(), program)
            if not has_colors:
                # One colour, the constant value of the program's colour input
                glVertexAttrib3f(LOC_COLOR, *(getattr(mode, '_solid_color', None)
                                              or (1.0, 1.0, 1.0, 1.0))[:3])
        elif has_colors:
            shader_program.use_line()
            program = shader_program.line_program
        else:
            shader_program.use(lit=False)
            program = shader_program.unlit_program
            # The colour the Shape's material asks for; white where the caller
            # gave the line neither per-vertex colours nor a material.
            shader_program.set_solid_color(
                getattr(mode, '_solid_color', None) or (1.0, 1.0, 1.0, 1.0), fogged=True)

        shader_program.set_matrices(mode.matrix, mode.projection, program=program)

        vbo_obj, stride, segments = self._line_buffer(mode, has_colors)
        if not segments:
            shader_program.use(lit=True)
            return 1

        # One VAO serves whichever program the pass chose, since both read the
        # semantics at the same locations.
        gpu = self._line_gpu
        vao = gpu['vao']
        if vao is None:
            vao = glGenVertexArrays(1)
            glBindVertexArray(vao)
            vbo_obj.bind()
            glEnableVertexAttribArray(LOC_POSITION)
            glVertexAttribPointer(LOC_POSITION, 3, GL_FLOAT, GL_FALSE, stride, None)
            glEnableVertexAttribArray(LOC_TEXCOORD)
            glVertexAttribPointer(LOC_TEXCOORD, 1, GL_FLOAT, GL_FALSE, stride,
                                  ctypes.c_void_p(12))
            if has_colors:
                glEnableVertexAttribArray(LOC_COLOR)
                glVertexAttribPointer(LOC_COLOR, 3, GL_FLOAT, GL_FALSE, stride,
                                      ctypes.c_void_p(16))
            vbo_obj.unbind()
            glBindVertexArray(0)
            gpu['vao'] = vao

        glBindVertexArray(vao)
        try:
            for first, count in segments:
                glDrawArrays(GL_LINE_STRIP, first, count)
        finally:
            glBindVertexArray(0)

        shader_program.use(lit=True)
        return 1

    def _line_buffer(self, mode: Any, has_colors: bool) -> tuple[Any, int, list[Any]]:
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

        points = np.asarray(coordinates.points(self.coord), dtype='f')
        indices = expandIndices(self.coordIndex)
        colors: Optional[Any] = None
        color_indices: list[Any] = []
        if has_colors:
            colors = np.asarray(self.color.color, dtype='f')
            color_indices = polyline_color_indices(
                indices, self.colorIndex, bool(self.colorPerVertex), len(colors))

        rows: list[Any] = []
        segments: list[tuple[int, int]] = []
        first = 0
        # Position, the distance along the polyline (a dash pattern's
        # coordinate), and a colour where there are colours
        width = 7 if has_colors else 4
        for poly_idx, polyline in enumerate(indices):
            if len(polyline) < 2:
                continue
            block = np.empty((len(polyline), width), dtype='f')
            block[:, 0:3] = points[polyline]
            steps = np.linalg.norm(np.diff(block[:, 0:3], axis=0), axis=1)
            block[:, 3] = np.concatenate([[0.0], np.cumsum(steps)])
            if colors is not None:
                block[:, 4:7] = colors[color_indices[poly_idx]][:, :3]
            rows.append(block)
            segments.append((first, len(polyline)))
            first += len(polyline)

        data = (np.ascontiguousarray(np.concatenate(rows)) if rows
                else np.zeros((0, width), dtype='f'))
        stride = width * 4

        if gpu is None:
            gpu = self._line_gpu = {
                'vbo': VBO(data, usage='GL_DYNAMIC_DRAW'),
                'vao': None,
                'stride': stride,
                'has_colors': has_colors,
                'segments': segments,
            }
        else:
            gpu['vbo'].set_array(data)
            gpu['stride'] = stride
            gpu['has_colors'] = has_colors
            gpu['segments'] = segments
            if gpu['vao'] is not None:
                # The layout may have changed with the data; rebind it against
                # the new upload rather than drawing through stale pointers.
                glDeleteVertexArrays(1, np.array([gpu['vao']], dtype=np.uint32))
                gpu['vao'] = None
        gpu['vbo'].bind()
        gpu['vbo'].unbind()

        holder = mode.cache.holder(self, True, key='line_clean')
        holder.depend(self, 'coord')
        holder.depend(self, 'coordIndex')
        holder.depend(self, 'colorIndex')
        for source, name in coordinates.fields(self.coord):
            holder.depend(source, name)
        if self.color:
            holder.depend(self.color, 'color')
        return gpu['vbo'], gpu['stride'], gpu['segments']

    def yeildVertices( self ) -> Iterator[Any]:
        """Yield set of vertices to be rendered..."""
        # this is an unfinished start to getting OpenGL 3.1 operation
        if self.coord and len(coordinates.points(self.coord)) and len(self.coordIndex):
            points = coordinates.points(self.coord)
            indices = expandIndices( self.coordIndex )
            currentColor = None
            #XXX should do sanity checks here...
            if self.color and len(self.color.color):
                colors = self.color.color
                colorIndices: Any = polyline_color_indices(
                    indices, self.colorIndex, bool(self.colorPerVertex), len(colors))
                # compile the color-friendly ILS
                for index in range(len(indices)):
                    polyline = indices[index]
                    color: Any = colorIndices[index]
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
    ``_MeshGPU`` -- ``attr_layout`` (position and colour at the engine's
    ``LOC_POSITION`` and ``LOC_COLOR``), ``count``,
    ``draw_mode`` (GL_LINES), ``indexed`` (False) and an ``_instance_vao`` slot --
    so lines flow through the identical instancing machinery as meshes.
    """
    def __init__(self, positions: Any, colors: Any) -> None:
        self._pos_vbo = VBO(np.ascontiguousarray(positions, dtype='f'))
        self._col_vbo = VBO(np.ascontiguousarray(colors, dtype='f'))
        self.attr_layout = [(self._pos_vbo, LOC_POSITION, 3),
                            (self._col_vbo, LOC_COLOR, 3)]
        self.idx_vbo = None
        self.indexed = False
        self.count = len(positions)
        self.draw_mode = GL_LINES
        self._instance_vao = None
        self._instance_vbo = None

    def release(self) -> None:
        """Delete the instanced VAO (only safe with the owning context current)."""
        vao = self._instance_vao
        if vao is not None:
            try:
                glDeleteVertexArrays(1, np.array([vao], dtype=np.uint32))
            except Exception:
                pass
            self._instance_vao = None


def polyline_color_indices(polylines: Sequence[Sequence[int]], color_index: Any,
                           per_vertex: bool, color_count: int) -> list[list[int]]:
    """The index into `color_count` colours of each vertex of each polyline

    Per vertex, `color_index` is read as ``coordIndex`` is, polyline by
    polyline, and without one the polylines' own indices are used; a
    polyline given fewer entries than vertices carries its last entry on.
    Per polyline, polyline i takes entry i, or i itself where there is no
    entry; entries past the polylines are not read. An index past the
    colours takes the last colour.
    """
    last = max(color_count - 1, 0)
    given = [int(value) for value in color_index]
    chosen: list[list[int]] = []
    if per_vertex:
        by_polyline = expandIndices(given) if given else [list(poly) for poly in polylines]
        for number, polyline in enumerate(polylines):
            entries = (by_polyline[number] if number < len(by_polyline) and by_polyline[number]
                       else list(polyline))
            entries = entries + [entries[-1]] * (len(polyline) - len(entries))
            chosen.append([min(max(entry, 0), last) for entry in entries[:len(polyline)]])
    else:
        for number, polyline in enumerate(polylines):
            entry = given[number] if number < len(given) else number
            chosen.append([min(max(entry, 0), last)] * len(polyline))
    return chosen


def expandIndices( indices: Any ) -> list[list[int]]:
    """Create a set of poly-line definitions"""
    items: list[list[int]] = []
    current: list[int] = []
    for i in indices:
        if i == -1:
            if len(current)<2:
                # should warn the user
                warnings.warn( """IndexedLineSet Polyline of length < 2""", stacklevel=2)
            else:
                items.append( current )
            current = []
        else:
            current.append( i )
    if current:
        items.append( current )
    return items
