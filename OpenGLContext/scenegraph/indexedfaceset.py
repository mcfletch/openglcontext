"""VRML97's and X3D's IndexedFaceSet, drawn as the mesh its fields build

The faces are tessellated by :mod:`~OpenGLContext.scenegraph.ifscompiler`
(convex or not, `creaseAngle` normals, the per-face and per-vertex indices),
and the tessellated triangles become the same glTF-shaped arrays the X3D
triangle sets are drawn from (:meth:`IndexedFaceSet.composedArrays`), so the
face set is drawn, shadowed, bounded and instanced as their
:class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` is
(:class:`~OpenGLContext.scenegraph.meshgeometry.MeshDrawn`).

Each texture coordinate set of a `MultiTextureCoordinate` is a set of the mesh
(TEXCOORD_0, TEXCOORD_1, ...), indexed by `texCoordIndex`, or `coordIndex`
where that is empty; a `Tangent` is indexed as the normals are; `attrib`
values are one per coordinate. Double-precision coordinates are drawn from
the centre of their bounds.

The compilers in :mod:`~OpenGLContext.scenegraph.ifscompiler` are
re-exported here.
"""

import hashlib
import logging
from typing import Any, Optional

import numpy as np
from vrml.vrml97 import basenodes
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import composedgeometry, coordinates, x3dglsl
from OpenGLContext.scenegraph.ifscompiler import (  # noqa: F401 re-exported for importers of this module
    DummyRender,
    DUMMY_RENDER,
    COMPILER_CLASSES,
    IFSCompiler,
    ArrayGeometryCompiler,
    IndexedPolygonsCompiler,
    IndexedValueSource,
    getXNull,
    build_normalPerVertex,
)
from OpenGLContext.scenegraph.meshgeometry import MeshDrawn

log = logging.getLogger(__name__)


def _indexed(values: Any, index: Any, coord_index: Any, meta: np.ndarray,
             sources: np.ndarray, width: int) -> Optional[np.ndarray]:
    """`values` for each tessellated vertex, read through `index` at its place in `coordIndex`

    `index` is the node's own index for the values, or empty to read them
    through `coord_index`; an index past the values reads the last of them.
    A vertex the tessellator made, with no place, reads its nearest
    coordinate's value. None where there are no values.
    """
    found = np.asarray(values, dtype=np.float32).reshape(-1, width) if values is not None else None
    if found is None or not len(found):
        return None
    lookup = np.asarray(index if len(index) else coord_index, dtype=np.int64).ravel()
    picked = sources.copy()
    placed = (meta >= 0) & (meta < len(lookup))
    picked[placed] = lookup[meta[placed]]
    picked[picked < 0] = sources[picked < 0]
    result: np.ndarray = found[np.clip(picked, 0, len(found) - 1)]
    return result


class IndexedFaceSet(MeshDrawn, basenodes.IndexedFaceSet):
    """VRML97's and X3D's IndexedFaceSet: polygons of `coordIndex`, tessellated

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#IndexedFaceSet
    """

    #: Draws with the pass's lit programs alone, so one draw can serve every
    #: view of a frame that sees it; see :mod:`OpenGLContext.multiview.strategy`.
    multiviewShared = True

    def planeCoordinates(self) -> Any:
        """The TextureCoordinate the face set's first 2D texture coordinates are read from, or None

        ``texCoord`` itself, or the first TextureCoordinate entry of a
        MultiTextureCoordinate; None where there is none (a generator, a 3D
        set), and the faces take X3D's default coordinates.
        """
        found = self.texCoord
        if isinstance(found, x3d.MultiTextureCoordinate):
            entries = [entry for entry in found.texCoord
                       if isinstance(entry, x3d.TextureCoordinate)]
            return entries[0] if entries else None
        return found if isinstance(found, x3d.TextureCoordinate) else None

    def _hasGeometry(self) -> bool:
        return bool(len(self.coordIndex) and self.coord and len(coordinates.points(self.coord)))

    def buildMesh(self) -> Optional[Any]:
        """The mesh of the tessellated faces, or None for a set with nothing to draw"""
        arrays = self.composedArrays()
        return None if arrays is None else self.meshFrom(arrays, solid=bool(self.solid))

    def composedArrays(self) -> Optional[composedgeometry.ComposedArrays]:
        """The tessellated faces' arrays, every three vertices a triangle, naming
        the coordinate each vertex was read from

        None where there is nothing to draw.
        """
        if not self._hasGeometry():
            return None
        compiler = ArrayGeometryCompiler(self)
        found = compiler.expandedArraysAndSources()
        if found is None:
            return None
        (single, colours, normals, first), sources = found
        meta = np.array([vertex.metaIndex for vertex in compiler.vertices], np.int64)
        origin = self.drawOrigin(coordinates.points(self.coord))
        positions = single if origin is None else compiler.pointArray - origin
        attributes = {'POSITION': positions, 'NORMAL': normals}
        if colours is not None:
            attributes['COLOR_0'] = colours
        sets = self._coordinateSets(meta, sources, first)
        for number, values in enumerate(sets):
            if values is not None:
                attributes['TEXCOORD_%d' % number] = values
        volume = self.volumeCoordinates()
        if volume is not None:
            attributes['TEXCOORD_3D'] = _indexed(volume, self.texCoordIndex, self.coordIndex,
                                                 meta, sources, 4)
        tangents = _indexed(self.tangent.vector if self.tangent else None, self.normalIndex,
                            self.coordIndex, meta, sources, 4)
        if tangents is not None:
            attributes['TANGENT'] = tangents
        order = np.arange(len(positions))
        if not self.ccw:
            # The tessellation keeps the faces' own winding, which ccw false
            # says is clockwise: turn each triangle round.
            order = order.reshape(-1, 3)[:, [0, 2, 1]].ravel()
        named, missing = x3dglsl.per_vertex(x3dglsl.vertex_attributes(self.attrib),
                                            sources[order])
        return composedgeometry.ComposedArrays(
            attributes={name: np.ascontiguousarray(np.asarray(value)[order], dtype=np.float32)
                        for name, value in attributes.items()},
            indices=None, vertex_attributes=named, short_attributes=missing,
            sources=sources[order], origin=origin)

    def _coordinateSets(self, meta: np.ndarray, sources: np.ndarray,
                        first: Any) -> "list[Optional[np.ndarray]]":
        """Each 2D texture coordinate set for the tessellated vertices, in set order

        The first TextureCoordinate's are the tessellation's own (or X3D's
        default where the set has no coordinates at all); a generator's, made
        in the shader, are None.
        """
        nodes = self.coordinateNodes()
        if not nodes:
            return [first]
        flat = self.planeCoordinates()
        found: "list[Optional[np.ndarray]]" = []
        for entry, values in zip(nodes, self.coordinates()):
            if entry is flat:
                found.append(first)
            elif values is None:
                found.append(None)
            else:
                found.append(_indexed(values, self.texCoordIndex, self.coordIndex,
                                      meta, sources, 2))
        return found

    # -- instancing -------------------------------------------------------
    def instanceContentKey(self) -> Optional[tuple[Any, ...]]:
        """Hashable signature so distinct-but-identical IFS nodes share one draw.

        Covers the scatter case: a bolt, tile or leaf authored as an IFS and used
        hundreds of times collapses into a single instanced call. Hashes exactly
        the arrays and flags that determine the tessellated output. ``None`` when
        empty, or for a set with shader attributes (falls back to node identity
        in the grouper).
        """
        if not self._hasGeometry() or self.attrib:
            return None
        digest = hashlib.blake2b(digest_size=16)

        def feed(name: str, arr: Any) -> None:
            if arr is not None and len(arr):
                digest.update(name.encode('ascii'))
                digest.update(np.ascontiguousarray(arr).tobytes())

        feed('coordIndex', self.coordIndex)
        feed('point', coordinates.points(self.coord))
        feed('normalIndex', self.normalIndex)
        feed('normal', self.normal.vector if self.normal else None)
        feed('texCoordIndex', self.texCoordIndex)
        for number, values in enumerate(self.coordinates()):
            feed('texCoord%d' % number, values)
        feed('tangent', self.tangent.vector if self.tangent else None)
        feed('colorIndex', self.colorIndex)
        feed('color', self.color.color if self.color else None)
        return ('IndexedFaceSet', digest.hexdigest(),
                bool(self.normalPerVertex), bool(self.colorPerVertex),
                round(float(self.creaseAngle), 6),
                bool(self.ccw), bool(self.solid), bool(getattr(self, 'convex', True)))

    def instanceGPU(self, mode: Any) -> Any:
        """The mesh's GPU arrays, which the instanced draw path draws"""
        found = self.mesh()
        return None if found is None else found.instanceGPU(mode)
