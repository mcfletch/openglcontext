"""Compilers that turn an :class:`~OpenGLContext.scenegraph.indexedfaceset.IndexedFaceSet`
into a renderable form.

``IndexedFaceSet.compile`` weighs the classes in :data:`COMPILER_CLASSES` and
instantiates the winner; each compiler only reads from ``self.target`` (the node),
so the node<->compiler contract is just those two touchpoints plus the registry.
The node lives in :mod:`indexedfaceset`; this module holds the compile pipeline.

The pipeline is mostly pure CPU: ``tessellate`` -> ``polygons`` ->
``buildIndexedSources`` + :class:`IndexedValueSource` build the triangle-soup
vertex stream; :meth:`ArrayGeometryCompiler.expandedArrays` is the single source
of tessellated arrays shared by the per-shape and instanced draw paths.

:mod:`indexedfaceset` re-exports every public name here, so
``from ...indexedfaceset import IndexedPolygonsCompiler`` (and friends) resolves.
"""

import logging
from itertools import zip_longest
from typing import Any, Iterator, Optional

from numpy import add, arccos, array, divide, dot, ones, repeat
from OpenGL.GL import (
    GL_LINES, GL_POLYGON, GL_QUADS, GL_TRIANGLES, glBegin, glColor3dv, glColor3f, glEnd,
    glNormal3dv, glTexCoord2dv, glVertex3dv,
)

from OpenGLContext import triangleutilities, displaylist
from OpenGLContext.debug.logs import getTraceback
from OpenGLContext.scenegraph import arraygeometry
from OpenGLContext.scenegraph import (
    polygon,
    vertex,
    polygontessellator,
    indexedpolygons,
)
from vrml import protofunctions

log = logging.getLogger(__name__)


class DummyRender(object):
    def render(self, *args: Any, **named: Any) -> None:
        pass


DUMMY_RENDER = DummyRender()


class DisplayListRenderer(object):
    def __init__(self, dl: Any) -> None:
        self.dl = dl

    def render(self, *args: Any, **named: Any) -> None:
        self.dl()


COMPILER_CLASSES: list[type["IFSCompiler"]] = []


class IFSCompiler(object):
    _indexedSourceNodes: Optional[list[Any]] = None

    def __init__(self, target: Any) -> None:
        self.target = target

    @classmethod
    def weight(cls, target: Any) -> float:
        """Determine weighting for the target for this style of compilation"""
        return 1.0

    def __call__(self, *args: Any, **named: Any) -> Any:
        """Call the compiler to produce the renderer or None if no renderer needed"""
        if (
            not len(self.target.coordIndex)
            or not self.target.coord
            or not len(self.target.coord.point)
        ):
            return None
        holder = self.buildCacheHolder(mode=named["mode"])
        try:
            compiler = self.compile(*args, **named)
        except Exception as err:
            log.error(
                """Failure during compilation of IndexedFaceSet: %s""",
                getTraceback(err),
            )
            compiler = DUMMY_RENDER
        holder.data = compiler
        return compiler

    def compile(
        self,
        visible: int = 1,
        lit: int = 1,
        textured: int = 1,
        transparent: int = 0,
        mode: Any = None,
    ) -> Any:
        """Compile a renderer to represent the IFS at run-time"""
        raise NotImplementedError

    def buildCacheHolder(self, key: str = "", mode: Any = None) -> Any:
        """Get a cache holder with all dependencies set"""
        holder = mode.cache.holder(self.target, None, key=key)
        for field in protofunctions.getFields(self.target):
            # change to any field requires a recompile
            holder.depend(self.target, field)
        for n, attr in [
            (self.target.coord, "point"),
            (self.target.color, "color"),
            (self.target.texCoord, "point"),
            (self.target.normal, "vector"),
        ]:
            if n:
                holder.depend(n, protofunctions.getField(n, attr))
        return holder

    def tessellate(self, polygons: Any = None, sources: Any = None) -> list[Any]:
        """Tessellate our arrays into triangle-only arrays

        The return value is a list of triangle vertices, with
        each vertex represented by a Vertex instance (see below).

        In addition to tessellation, this function is responsible
        for turning the index-format structures into a set of
        polygons (i.e. identifying the individual polygons within
        the indexed face set).
        """
        # check to see that there's something to do
        if (
            (not len(self.target.coordIndex))
            or (not self.target.coord)
            or (not len(self.target.coord.point))
        ):
            return []

        tessellate = polygontessellator.PolygonTessellator().tessellate
        vertices = []
        if polygons is None:
            polygons = self.polygons(sources=sources)
        for poly in polygons:
            poly.normalise(tessellate)
            vertices.extend(poly)
        return vertices

    def buildIndexedSources(self) -> list["IndexedValueSource"]:
        """Build the set of IndexedValueSource objects for this node

        These are color, normal and texture-coordinate only,
        not the coord set, as that's the driver for the rest.
        """
        points, colors, normals, textureCoordinates = (
            getXNull(self.target.coord, "point"),
            getXNull(self.target.color, "color"),
            getXNull(self.target.normal, "vector"),
            getXNull(self.target.texCoord, "point"),
        )

        return [
            IndexedValueSource(
                self.target.coordIndex,
                indices,
                values,
                perFace,
                name,
                attribute,
                vertexAttribute,
            )
            for indices, values, perFace, name, attribute, vertexAttribute in [
                (self.target.coordIndex, points, False, "coord", "point", "point"),
                (
                    self.target.colorIndex,
                    colors,
                    not self.target.colorPerVertex,
                    "color",
                    "color",
                    "color",
                ),
                (
                    self.target.normalIndex,
                    normals,
                    not self.target.normalPerVertex,
                    "normal",
                    "vector",
                    "normal",
                ),
                (
                    self.target.texCoordIndex,
                    textureCoordinates,
                    0,
                    "texCoord",
                    "point",
                    "textureCoordinate",
                ),
            ]
        ]

    def indexedSourceNodes(self) -> list[Any]:
        """Lookup node-types for our indexed source set"""
        if not self._indexedSourceNodes:
            from OpenGLContext.scenegraph import basenodes

            # basenodes populates its node classes at import time from entry
            # points, so they are invisible to static analysis.
            bn: Any = basenodes
            self._indexedSourceNodes = [
                bn.Coordinate,
                bn.Color,
                bn.Normal,
                bn.TextureCoordinate,
            ]
        return self._indexedSourceNodes

    def polygons(self, sources: Any = None) -> Iterator[Any]:
        """Yield each polygon in the IFS

        The polygon object is a sub-class of list holding
        Vertex objects.
        """
        if sources is None:
            sources = self.buildIndexedSources()
        current = []
        metaIndex = -1
        polygonIndex = 0
        coordIndices = self.target.coordIndex
        points = getXNull(self.target.coord, "point")
        for metaIndex in range(len(coordIndices)):
            point = coordIndices[metaIndex]
            if point >= 0:
                if point >= len(coordIndices):
                    log.info(
                        """Coordindex of node %s declares index %s at meta-index %s, beyond end of coordinate set (len %s), ignoring""",
                        self.target,
                        point,
                        metaIndex,
                        len(coordIndices),
                    )
                    continue
                set = dict(
                    [(s.vertexAttribute, s(metaIndex, polygonIndex)[0]) for s in sources[1:]]
                )
                set["indexKey"] = tuple([s.vertexIndex(metaIndex, polygonIndex) for s in sources])
                current.append(
                    vertex.Vertex(
                        point=points[point],
                        metaIndex=metaIndex,
                        coordIndex=point,
                        **set,
                    )
                )
            else:
                yield polygon.Polygon(
                    polygonIndex,
                    self.target,
                    current,
                    ccw=self.target.ccw,
                )
                polygonIndex += 1
                current = []
        if current:
            yield polygon.Polygon(polygonIndex, self.target, current, ccw=self.target.ccw)


class ArrayGeometryCompiler(IFSCompiler):
    """Compiles to an ArrayGeometry instance for rendering uniform arrays of data"""

    def expandedArrays(self) -> Optional[tuple[Any, Any, Any, Any]]:
        """Tessellate the IFS to expanded triangle-soup arrays.

        Returns ``(vertexArray, colorArray, normalArray, textureCoordinateArray)``
        as raw ``float32`` arrays -- every three vertices is one triangle -- or
        ``None`` when there is nothing to draw. ``compile`` wraps these in an
        ``ArrayGeometry`` (VBOs) for the per-shape path; the instanced draw path
        reuses the same arrays directly (``IndexedFaceSet._instanceArrays``), so
        the tessellation lives in exactly one place.
        """
        ### XXX should store normals regardless of "lit" field and discard lit
        # XXX check to see if we are all using the same indices,
        # if so, we can possibly use IndexedPolygons instead
        # of IndexedFaceSet for rendering...
        vertices = self.tessellate()

        # vertices is now a list of vertices such that
        # every three vertices represents a single triangle
        # good time to build normals if required...
        vertexArray = array([vertex.point for vertex in vertices], "f")
        if len(vertexArray) == 0:
            return None
        if (not self.target.normal) or (not len(self.target.normal.vector)):
            # need to calculate normals
            if self.target.normalPerVertex:
                normalArray = build_normalPerVertex(
                    vertices, self.target.creaseAngle, vertexArray
                )
            else:
                normalArray = triangleutilities.normalPerFace(vertexArray)
                normalArray = repeat(normalArray, [3] * len(normalArray), 0)
        else:
            normalArray = []
            for vertex in vertices:
                if vertex.normal is not None:
                    normalArray.append(vertex.normal)
                elif normalArray:
                    normalArray.append(normalArray[-1])
                else:
                    normalArray.append((0, 0, 1))
            normalArray = array(normalArray, "f")

        if self.target.color and len(self.target.color.color):
            try:
                colorArray = array([vertex.color for vertex in vertices], "f")
            except TypeError:
                colorArray = None
                log.warning(
                    """%s tessellation appears to have created invalid color for tesselated vertex""",
                    self.target,
                )
        else:
            colorArray = None
        if self.target.texCoord and len(self.target.texCoord.point):
            textureCoordinateArray = array(
                [vertex.textureCoordinate for vertex in vertices], "f"
            )
        else:
            textureCoordinateArray = None
        return vertexArray, colorArray, normalArray, textureCoordinateArray

    def compile(
        self,
        visible: int = 1,
        lit: int = 1,
        textured: int = 1,
        transparent: int = 0,
        mode: Any = None,
    ) -> Any:
        """Compile the rendering structures for an ArrayGeometry version of IFS

        XXX Should redo to cache like so...
        cache tessellated triangle indices
            if any indices change, need to re-calculate everything
            coord -> [ pointIndices ], [ calcualtedNormals ]
            normal -> [ normalIndices ]

            when points change, just re-calculate:
                expanded-normals (if we are calculating normals)
                expanded-points
            when normals change (explicit normal/indices)
                expanded-normals

            fully-expanded normal, texCooord, and color
        """
        expanded = self.expandedArrays()
        if expanded is None:
            return DUMMY_RENDER
        vertexArray, colorArray, normalArray, textureCoordinateArray = expanded
        log.debug(
            "Arrays: \nvertex -- %s\nnormal -- %s",
            vertexArray,
            normalArray,
        )
        ag = arraygeometry.ArrayGeometry(
            vertexArray,
            colorArray,
            normalArray,
            textureCoordinateArray,
            objectType=GL_TRIANGLES,
            ccw=self.target.ccw,
            solid=self.target.solid,
        )
        return ag


COMPILER_CLASSES.append(ArrayGeometryCompiler)


class IndexedPolygonsCompiler(IFSCompiler):
    """Compile to set of equal-indexed vertex arrays"""

    @classmethod
    def weight(cls, target: Any) -> float:
        """Determine weighting for the target for this style of compilation"""
        if (
            # we have per-vertex normals...
            target.normalPerVertex
            and target.normal
            and len(target.normal.vector)
            and len(target.normalIndex)
        ) and (
            # we have per-vertex colors
            (
                target.colorPerVertex
                and target.color
                and len(target.color.color)
                and len(target.colorIndex)
            )
            or (
                # or no colors at all
                not target.color or not len(target.colorIndex)
            )
        ):
            return 1.05
        return False

    def compile(
        self,
        visible: int = 1,
        lit: int = 1,
        textured: int = 1,
        transparent: int = 0,
        mode: Any = None,
    ) -> Any:
        """Compile the rendering structures for an ArrayGeometry version of IFS

        XXX Should redo to cache like so...
        cache tessellated triangle indices
            if any indices change, need to re-calculate everything
            coord -> [ pointIndices ], [ calcualtedNormals ]
            normal -> [ normalIndices ]

            when points change, just re-calculate:
                expanded-normals (if we are calculating normals)
                expanded-points
            when normals change (explicit normal/indices)
                expanded-normals

            fully-expanded normal, texCooord, and color
        """
        ### XXX should store normals regardless of "lit" field and discard lit
        # XXX check to see if we are all using the same indices,
        # if so, we can possibly use IndexedPolygons instead
        # of IndexedFaceSet for rendering...
        sources = self.buildIndexedSources()
        vertices = self.tessellate(sources=sources)

        arrays: list[list[Any]] = [[] for source in sources]
        indices: list[int] = []

        seenVertices: dict[Any, int] = {}
        sourceArrays = list(enumerate(sources))
        for vert in vertices:
            if vert.indexKey not in seenVertices:
                i = len(arrays[0])
                seenVertices[vert.indexKey] = i
                indices.append(i)
                for arrayI, source in sourceArrays:
                    value = getattr(vert, source.vertexAttribute, None)
                    if value is not None:
                        arrays[arrayI].append(value)
            else:
                indices.append(seenVertices[vert.indexKey])
        ip = indexedpolygons.IndexedPolygons(
            polygonSides=3,
            index=indices,
            solid=self.target.solid,
            ccw=self.target.ccw,
        )
        for source, arr, nodetype in zip_longest(sources, arrays, self.indexedSourceNodes()):
            if arr:
                node = nodetype()
                setattr(node, source.attribute, arr)
                setattr(ip, source.name, node)
        return ip


COMPILER_CLASSES.append(IndexedPolygonsCompiler)


class DisplayListCompiler(IFSCompiler):
    """Compiles to a display-list for static geometry

    Note that this implementation is basically without real purpose,
    the arraygeometry version should be much faster on all modern
    hardware, particularly if VBO support is available.

    Also note that display lists are deprecated in OpenGL 3.x
    """

    @classmethod
    def weight(cls, target: Any) -> float:
        """Determine weighting for the target for this style of compilation"""
        return 0.9

    def compile(
        self,
        visible: int = 1,
        lit: int = 1,
        textured: int = 1,
        transparent: int = 0,
        mode: Any = None,
    ) -> Any:
        """Compile to an opaque textured display-list"""
        dl = displaylist.DisplayList()
        dl.start()
        try:
            if (not self.target.normal) or (
                self.target.normal and not len(self.target.normal.vector)
            ):
                # need to generate per-face or per-vertex-use vectors,
                # require tessellation!
                vertices = self.tessellate()
                if not vertices:
                    return None
                if self.target.normalPerVertex:
                    normalArray = build_normalPerVertex(vertices, self.target.creaseAngle)
                    normalStep = 1
                else:
                    vertexArray = array([vertex.point for vertex in vertices], "f")
                    normalArray = triangleutilities.normalPerFace(vertexArray)
                    normalArray = repeat(normalArray, [3] * len(normalArray), 0)
                    normalStep = 3
                glBegin(GL_TRIANGLES)
                if self.target.DEBUG_DRAW_NORMALS:
                    normalValues = []
                try:
                    normalIndex = -1
                    for vIndex in range(len(vertices)):
                        vertex = vertices[vIndex]
                        if vIndex % normalStep == 0:
                            normalIndex += 1
                        glNormal3dv(normalArray[normalIndex])
                        if vertex.color is not None:
                            glColor3dv(vertex.color)
                        if vertex.textureCoordinate is not None:
                            glTexCoord2dv(vertex.textureCoordinate)
                        glVertex3dv(vertex.point)
                        if self.target.DEBUG_DRAW_NORMALS:
                            normalValues.append(
                                (vertex.point, vertex.point + normalArray[normalIndex])
                            )
                finally:
                    glEnd()
                if self.target.DEBUG_DRAW_NORMALS:
                    glBegin(GL_LINES)
                    try:
                        for v, n in normalValues:
                            glColor3f(1, 0, 0)
                            glVertex3dv(v)
                            glColor3f(0, 1, 0)
                            glVertex3dv(n)
                    finally:
                        glEnd()
            else:
                # already has normals, can render without tessellation
                for polygon in self.polygons():
                    if len(polygon) == 3:
                        glBegin(GL_TRIANGLES)
                    elif len(polygon) == 4:
                        glBegin(GL_QUADS)
                    elif len(polygon) < 3:
                        continue
                    else:
                        glBegin(GL_POLYGON)
                    try:
                        for vertex in polygon:
                            if vertex.normal is not None:
                                glNormal3dv(vertex.normal)
                            if vertex.color is not None:
                                glColor3dv(vertex.color)
                            if vertex.textureCoordinate is not None:
                                glTexCoord2dv(vertex.textureCoordinate)
                            glVertex3dv(vertex.point)
                    finally:
                        glEnd()
            return DisplayListRenderer(dl)
        finally:
            dl.end()


COMPILER_CLASSES.append(DisplayListCompiler)


def getXNull(node: Any, attr: str) -> Any:
    """Get attribute or [] list"""
    if node:
        return getattr(node, attr)
    return []


def build_normalPerVertex(vertices: Any, creaseAngle: float, vertexArray: Any = None) -> Any:
    """Create a normal vector using creaseAngle to determine smoothing

    Note: the semantics of normalPerVertex requires using expanded
    (i.e. tessellated) values, as the generated normals are *not*
    supposed to be applied to each vertex, but instead to each
    *use* of each vertex (i.e. each triangle's ref to the vertex
    has a potentially different normal)

    vertices -- list of vertex objects in rendering order (triangles)
    creaseAngle -- radian angle above which faces do not smooth.
    vertexArray -- x*3*3 array of coordinates expanded into a flat
        data-array, if not provided, generated from vertices
    """
    if vertexArray is None:
        vertexArray = array([vertex.point for vertex in vertices], "f")
    faceNormals = triangleutilities.normalPerFace(vertexArray)
    vertexNormals = repeat(faceNormals, [3] * len(faceNormals), 0)
    faceNormals = array(vertexNormals[:])
    items: dict[Any, list[int]] = {}
    for index in range(len(vertices)):
        try:
            items.setdefault(vertices[index].coordIndex, []).append(index)
        except TypeError:
            print(vertices[index])
            print(type(vertices[index].coordIndex), vertices[index].coordIndex)
            raise
    #   verticies. We use ones instead of zeros because each face
    #   contributes to its own corner.  Note: will be promoted to float
    #   during the final division
    counts = ones((len(vertexNormals),), "f")
    for vertexSet in items.values():
        # For each primary user (triangle corner)
        for index in range(len(vertexSet)):
            primaryNormal = faceNormals[vertexSet[index]]
            # check to see if any of the remaining triangles should
            # be blended with this one
            for innerindex in range(index + 1, len(vertexSet)):
                secondaryNormal = faceNormals[vertexSet[innerindex]]
                # if angle < creaseAngle... should calculate
                # cos(creaseAngle) instead of using arccos each time
                try:
                    angle = arccos(dot(primaryNormal, secondaryNormal))
                except ValueError:  # pragma: no cover - numpy arccos returns nan for
                    angle = 0        # out-of-domain dot products, it never raises here
                if angle < creaseAngle:
                    # add to each other's cummulative total (in place)
                    add(
                        vertexNormals[vertexSet[index]],
                        secondaryNormal,
                        vertexNormals[vertexSet[index]],
                    )  # add in place
                    add(
                        vertexNormals[vertexSet[innerindex]],
                        primaryNormal,
                        vertexNormals[vertexSet[innerindex]],
                    )  # add in place
                    # and increment the element counts
                    counts[vertexSet[index]] = counts[vertexSet[index]] + 1
                    counts[vertexSet[innerindex]] = counts[vertexSet[innerindex]] + 1
    # reshape counts to allow for in-place division...
    counts.shape = (-1, 1)
    # divide in place, completing the averaging (and thereby hopefully
    # re-normalising the Normal vectors)
    divide(vertexNormals, counts, vertexNormals)
    return vertexNormals


class IndexedValueSource(object):
    """Holds data-arrays which together form a source for indexed values

    This object should make it possible to reliably
    calculate indexed values from multiple arrays
    without needing to duplicate the logic for each
    array being processed.

    """

    def __init__(
        self,
        vertexIndices: Any,
        indices: Any,
        values: Any,
        perFace: Any,
        name: str = "color",
        attribute: str = "color",
        vertexAttribute: str = "color",
    ) -> None:
        """Initialize the IndexedValueSource object

        vertexIndices -- the vertex indices for the indexedfaceset
            if indices is NULL, we will use these for-our indices
        indices -- index-values specific to this particular value-type
            or None if there are no specifically-defined values
        values -- array of values specific to this particular value type
            or None if there are no specifically-defined values
        perFace -- whether or not this particular type of source is
            defined on a per-polygon/face basis, that is whether values
            should be indexed by polygon or vertex position.
        name -- name to be reported in debugging logs
        """
        if (not len(indices)) and len(values):
            log.debug("""%s array using vertex indices""", name)
            indices = vertexIndices
        self.indices = indices
        self.values = values
        self.perFace = perFace
        self.name = name
        self.attribute = attribute
        self.vertexAttribute = vertexAttribute

    def __call__(self, metaIndex: Any, faceIndex: Any) -> tuple[Any, int]:
        """Return the value for the meta index or None"""
        if self.perFace:
            index = faceIndex
        else:
            index = metaIndex
        if len(self.values):
            if len(self.indices):
                # have both indices and values...
                try:
                    finalIndex = self.indices[index]
                except IndexError:
                    return None, -1
                if finalIndex < 0:
                    log.warning(
                        """%s array has a different polygon-length than vertex array, metaIndex=%s, faceIndex=%s""",
                        self.name,
                        metaIndex,
                        faceIndex,
                    )
                    return None, -1
                elif finalIndex >= len(self.values):
                    # XXX should be the last *index* not the last value!
                    finalIndex = self.lastNonNullIndex()
                    if finalIndex is None:  # pragma: no cover - reaching here needs
                        # every index == -1, but then indices[index] < 0 above wins first
                        return None, -1
                return self.values[finalIndex], finalIndex
            else:
                log.warning(
                    """No indices for %s array""",
                    self.name,
                )
        return None, -1

    def lastNonNullIndex(self) -> Any:
        for i in range(len(self.indices) - 1, -1, -1):
            if self.indices[i] != -1:
                return self.indices[i]
        return None

    def vertexIndex(self, metaIndex: Any, faceIndex: Any) -> Any:
        """Produce key-fragment for this index

        This is used to produce a key that allows us to uniquify the
        vertices in order to reduce the set of vertices passed to the
        GL.
        """
        if self.perFace:
            index = faceIndex
        else:
            index = metaIndex
        try:
            return self.indices[index]
        except IndexError:
            if index >= len(self.indices):
                return self.lastNonNullIndex()
            return None
