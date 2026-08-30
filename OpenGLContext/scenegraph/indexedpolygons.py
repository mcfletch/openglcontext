"""Indexed data array geometry type"""

from vrml.vrml97 import nodetypes
from vrml import node, field, protofunctions
from OpenGLContext.scenegraph import coordinatebounded
from OpenGLContext import triangleutilities
from OpenGLContext.scenegraph import polygonsort
from OpenGLContext.scenegraph.winding import apply_winding_cull
from OpenGL.arrays import vbo

from OpenGL.GL import *
from OpenGLContext.arrays import *
import logging

log = logging.getLogger(__name__)
from math import pi


def triangulate_index(index, polygonSides):
    """``index`` rewritten as triangles, for whatever ``polygonSides`` names.

    ``polygonSides`` is a vertex count -- 3 or 4 -- or ``GL_QUAD_STRIP``, the
    same three values :meth:`IndexedPolygons.render` accepts.  Quads and quad
    strips are fixed-function primitives that a core profile does not draw, and
    the geometry they describe is perfectly ordinary: a quad is two triangles
    and a quad strip is a triangle strip with its vertices in a different order.
    Rewriting the indices is what lets a node that names either one draw under
    both profiles.

    A two-dimensional ``index`` is one primitive per row, which is what the
    shape of such an array says and what keeps two strips from being joined by a
    sliver spanning the gap between them.  Vertices that do not complete a
    primitive are dropped, as GL drops them.

    Returns ``index`` itself when it already describes triangles.
    """
    if polygonSides == 3:
        return index
    index = asarray(index)
    if index.ndim > 1:
        rows = [triangulate_index(row, polygonSides) for row in index]
        return (concatenate(rows) if rows
                else index.reshape((0,)).astype(index.dtype))
    if polygonSides == 4:
        quads = index[: (len(index) // 4) * 4].reshape((-1, 4))
        triangles = quads[:, (0, 1, 2, 0, 2, 3)]
    elif polygonSides == GL_QUAD_STRIP:
        # A quad strip's nth quad is (v[2n], v[2n+1], v[2n+3], v[2n+2]) -- the
        # far edge is given before the near one, which is why this is not simply
        # a triangle strip.
        pairs = index[: (len(index) // 2) * 2].reshape((-1, 2))
        if len(pairs) < 2:
            return index[:0]
        near, far = pairs[:-1], pairs[1:]
        triangles = concatenate(
            [near[:, (0, 1)], far[:, 1:2], near[:, 0:1], far[:, (1, 0)]], axis=1)
    else:
        raise ValueError(
            """%s is not a polygonSides value that can be drawn as triangles"""
            % (polygonSides,))
    return triangles.reshape((-1,))


class Holder(object):
    """Substitutes as object to hold vbo values"""

    coord = None
    normal = None
    color = None
    texCoord = None

    def _enableColors(self, node):
        """Enable the colour array if possible"""
        color = self.color
        if color is not None:
            # make the color field alter the diffuse color
            glColorMaterial(GL_FRONT_AND_BACK, GL_DIFFUSE)
            glEnable(GL_COLOR_MATERIAL)
            glColorPointer(3, GL_FLOAT, 0, color)
            glEnableClientState(GL_COLOR_ARRAY)
            return 1
        else:
            return 0

    def _enableNormals(self, node):
        """Enable the normal array if possible"""
        normal = self.normal
        if normal is not None:
            # make the color field alter the diffuse color
            glNormalPointer(GL_FLOAT, 0, normal)
            glEnableClientState(GL_NORMAL_ARRAY)
            return 1
        else:
            glDisable(GL_LIGHTING)
            log.warning(
                """%s does not define normals, but is being rendered as lit geometry! This is likely an error in your content""",
                node,
            )
            return 0

    def _enableTextures(self, node):
        """Enable the normal array if possible"""
        tex = self.texCoord
        if tex is not None:
            glTexCoordPointer(2, GL_FLOAT, 0, tex)
            glEnableClientState(GL_TEXTURE_COORD_ARRAY)
            return 1
        else:
            return 0

    def _enableCoords(self, node):
        """Enable the point array if possible"""
        coord = self.coord
        if coord is not None:
            glVertexPointer(3, GL_FLOAT, 0, coord)
            glEnableClientState(GL_VERTEX_ARRAY)
            return 1
        else:
            return 0


class VBOHolder(Holder):
    """VBO-based holder"""

    def _enableColors(self, node):
        """Enable the colour array if possible"""
        color = self.color
        if color is not None:
            # make the color field alter the diffuse color
            glColorMaterial(GL_FRONT_AND_BACK, GL_DIFFUSE)
            glEnable(GL_COLOR_MATERIAL)
            glEnableClientState(GL_COLOR_ARRAY)
            color.bind()
            try:
                glColorPointer(3, GL_FLOAT, 0, color)
            finally:
                color.unbind()
            return 1
        else:
            return 0

    def _enableNormals(self, node):
        """Enable the normal array if possible"""
        normal = self.normal
        if normal is not None:
            # make the color field alter the diffuse color
            normal.bind()
            try:
                glNormalPointer(GL_FLOAT, 0, normal)
            finally:
                normal.unbind()
            glEnableClientState(GL_NORMAL_ARRAY)
            return 1
        else:
            glDisable(GL_LIGHTING)
            log.warning(
                """%s does not define normals, but is being rendered as lit geometry! This is likely an error in your content""",
                node,
            )
            return 0

    def _enableTextures(self, node):
        """Enable the normal array if possible"""
        tex = self.texCoord
        if tex is not None:
            tex.bind()
            try:
                glTexCoordPointer(2, GL_FLOAT, 0, tex)
            finally:
                tex.unbind()
            glEnableClientState(GL_TEXTURE_COORD_ARRAY)
            return 1
        else:
            return 0

    def _enableCoords(self, node):
        """Enable the point array if possible"""
        coord = self.coord
        if coord is not None:
            coord.bind()
            try:
                glVertexPointer(3, GL_FLOAT, 0, coord)
            finally:
                coord.unbind()
            glEnableClientState(GL_VERTEX_ARRAY)
            return 1
        else:
            return 0


class IndexedPolygons(
    coordinatebounded.CoordinateBounded, nodetypes.Geometry, node.Node
):
    """Simplified indexed polygon geometry type

    IndexedPolygons provide a simpler mechanism than
    the IndexedFaceSet objects for rendering common
    geometric data sets such as those generated by
    common 3-D modelers.

    IndexedPolygons are basically a set of vertices
    which are compiled so that the individual vertices
    are available as equally-indexed arrays of data
    values, i.e. vertex No. 24 would be represented by:

        coord.point[23]
        color.color[23] # optional
        normal.vector[23] # optional
        texCoord.point[23] # optional

    Note that there is no normal generation available
    also note that only 3 or 4-vertex polygons are
    allowed.

    Basically, the IndexedPolygons node consists of
    a set of data arrays which are enabled or disabled
    by their presence in the node.  Rendering is
    accomplished using the glDrawElementsui function,
    which draws the indexed arrays using the indices
    given.  This allows for very efficient updating
    of the data arrays, since the data arrays are not
    pre-processed by the node at all before rendering.
    """

    # Fields
    polygonSides = field.newField("polygonSides", "SFInt32", 0, 3)
    index = field.newField("index", "MFUInt32", 0, list)
    normal = field.newField("normal", "SFNode", 1, node.NULL)
    solid = field.newField("solid", "SFBool", 0, 1)
    ccw = field.newField("ccw", "SFBool", 0, 1)
    texCoord = field.newField("texCoord", "SFNode", 1, node.NULL)
    color = field.newField("color", "SFNode", 1, node.NULL)
    coord = field.newField("coord", "SFNode", 1, node.NULL)

    def render(
        self,
        visible=1,  # can skip normals and textures if not
        lit=1,  # can skip normals if not
        textured=1,  # can skip textureCoordinates if not
        transparent=0,  # need to sort triangle geometry...
        mode=None,  # the renderpass object for which we compile
    ):
        """Render the IndexedPolygons

        visible -- can skip normals and textures if not
        lit - can skip normals if not
        textured -- can skip textureCoordinates if not
        transparent -- need to sort triangle geometry...
        """
        if not len(self.index):
            return 1

        if getattr(mode, 'shader_mode', False):
            return self._render_shader(mode, visible=visible, lit=lit,
                                       textured=textured, transparent=transparent)

        glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
        glPushAttrib(GL_ALL_ATTRIB_BITS)
        try:
            vbos = self.get_vbos(mode)
            if not vbos._enableCoords(self):
                return 1
            if visible:
                # potentially enable colour and texture arrays
                # do we have a colour-array to enable
                vbos._enableColors(self)
            if textured:
                vbos._enableTextures(self)
            if lit:
                vbos._enableNormals(self)

            # calculate GL constant for # of sides
            if self.polygonSides == 3:
                constant = GL_TRIANGLES
            elif self.polygonSides == 4:
                constant = GL_QUADS
            elif self.polygonSides == GL_QUAD_STRIP:
                constant = GL_QUAD_STRIP
            else:
                raise ValueError(
                    """%s node has unsupported polygonSides value %s (3 or 4 expected)"""
                    % (str(self), self.polygonSides)
                )
            apply_winding_cull(mode, bool(self.ccw), self.solid)

            # do the actual rendering
            if visible and transparent:
                self.drawTransparent(constant, mode=mode)
            else:
                glDrawElementsui(
                    constant,
                    self.index,
                )
        finally:
            glPopAttrib()
            glPopClientAttrib()
        return 1

    def _triangle_index(self, mode):
        """This node's index as triangles, cached against index and polygonSides.

        A quad or a quad strip is rewritten by :func:`triangulate_index`; a node
        that already names triangles gets its own array back untouched.
        """
        index = mode.cache.getData(self, key="triangle_index")
        if index is None:
            index = triangulate_index(self.index, self.polygonSides)
            holder = mode.cache.holder(self, index, key="triangle_index")
            for name in ("index", "polygonSides"):
                holder.depend(self, name)
        return index

    def _get_index_vbo(self, mode):
        """Element-array VBO of the triangle index, cached and index-versioned."""
        ivbo = mode.cache.getData(self, key="shader_index")
        if ivbo is None:
            ivbo = vbo.VBO(
                ascontiguousarray(self._triangle_index(mode), "I"),
                target="GL_ELEMENT_ARRAY_BUFFER")
            holder = mode.cache.holder(self, ivbo, key="shader_index")
            for name in ("index", "polygonSides"):
                holder.depend(self, name)
        return ivbo

    def _render_shader(self, mode, visible=1, lit=1, textured=1, transparent=0):
        """Core-profile shader rendering path (mirrors ArrayGeometry/Quadric).

        Draws the equal-indexed position/normal/texcoord arrays with the VRML97
        shader program via a cached VAO.  Core GL draws only triangles, so a
        node naming quads or a quad strip has its index rewritten into triangles
        once and cached; see :func:`triangulate_index`.
        """
        from OpenGLContext.scenegraph import shadergeometry as sg

        shader_program = getattr(mode, "shader_program", None)
        if shader_program is None or shader_program.program is None:
            return 1

        vbos = self.get_vbos(mode)
        if vbos.coord is None:
            return 1
        index_vbo = self._get_index_vbo(mode)
        program = shader_program.program

        glFrontFace(GL_CCW if self.ccw else GL_CW)
        if self.solid:
            glEnable(GL_CULL_FACE)
        else:
            glDisable(GL_CULL_FACE)

        from OpenGLContext.scenegraph.geometryarrays import (
            GeometryArrays, render_geometry,
        )
        render_geometry(mode, GeometryArrays.separate(
            count=len(self._triangle_index(mode)),
            indices=index_vbo,
            index_type=GL_UNSIGNED_INT,
            positions=vbos.coord,
            normals=vbos.normal if lit else None,
            texcoords=vbos.texCoord if textured else None,
        ), owner=self, where='IndexedPolygons')
        return 1

    def drawTransparent(self, constant, mode=None):
        """Fairly complex mechanism for drawing sorted polygons"""
        # we have to create a temporary array of centres for
        # each polygon, that requires taking the centres and then
        # creating an index-set that re-orders the polygons...
        centers = mode.cache.getData(self, key="centers")
        if centers is None:
            ## cache centers for future rendering passes...
            ordered_points = take(self.coord.point, self.index.astype("i"), 0)
            centers = triangleutilities.centers(
                ordered_points,
                vertexCount=self.polygonSides,
                components=3,
            )
            holder = mode.cache.holder(self, key="centers", data=centers)
            for name in ("polygonSides", "index", "coord"):
                field = protofunctions.getField(self, name)
                holder.depend(self, field)
            for n, attr in [
                (self.coord, "point"),
            ]:
                if n:
                    holder.depend(n, protofunctions.getField(n, attr))
        assert centers is not None

        # get distances to the viewer
        centers = polygonsort.distances(
            centers,
            modelView=mode.getModelView(),
            projection=mode.getProjection(),
            viewport=mode.getViewport(),
        )
        assert len(centers) == len(self.index) // self.polygonSides
        # get the center indices in sorted order
        indices = argsort(centers)
        sortedIndices = self.index[:]
        sortedIndices = reshape(sortedIndices, (-1, self.polygonSides))
        sortedIndices = take(sortedIndices, indices, 0)
        # okay, now we can render...
        glDrawElementsui(
            constant,
            sortedIndices,
        )

    NODE_FIELDS = [
        ("coord", "point"),
        ("normal", "vector"),
        ("color", "color"),
        ("texCoord", "point"),
    ]

    def get_vbos(self, mode):
        """Retrieve vertex buffer object source if we support them or None if not"""
        if vbo.get_implementation():
            vbos = mode.cache.getData(self, key="vbos")
            if vbos is None:
                vbos = VBOHolder()
                # compile our data to a set of vbos
                holder = mode.cache.holder(self, key="vbos", data=vbos)
                for field, attr in self.NODE_FIELDS:
                    node = getattr(self, field)
                    value = getattr(node, attr, None)
                    if value is not None:
                        setattr(vbos, field, vbo.VBO(value))
                        # TODO: this is *way* too general, as it will
                        # cause the *entire* set of VBOs to be discarded
                        # and recreated whenever *anything* changes!
                        holder.depend(node, attr)
                        holder.depend(self, field)
                holder.depend(self, "index")
        else:
            vbos = Holder()
            for field, attr in self.NODE_FIELDS:
                node = getattr(self, field)
                if node:
                    value = getattr(node, attr, ())
                    setattr(vbos, field, vbo.VBO(value))

        return vbos

    def callBound(self, function, array):
        if hasattr(array, "bind"):
            array.bind()
            try:
                return function(array)
            finally:
                array.unbind()
        else:
            return function(array)
