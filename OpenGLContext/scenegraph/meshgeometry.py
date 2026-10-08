"""X3D geometry drawn as the mesh its fields build: the triangle and quad sets, ElevationGrid, LineSet

Each triangle set, quad set and `ElevationGrid` is drawn as the
:class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` its fields build
(:meth:`MeshDrawn.mesh`): its triangles come from
:mod:`~OpenGLContext.scenegraph.composedgeometry` (from its `index`,
`fanCount` or `stripCount`, or the grid), and its arrays from its
`Coordinate` (or `height`), `Normal`, `Tangent`, `Color` or `ColorRGBA`, and
`TextureCoordinate` or `MultiTextureCoordinate`. The mesh is kept in vrml's
cache until one of those fields is set. A texture coordinate set's `mapping`
label names it for a material's `...TextureMapping`
(:meth:`MeshDrawn.textureCoordinateSet`).

A `LineSet` is drawn as the engine's `IndexedLineSet` of the same points
(:meth:`LineSet.lines`).

The first `TextureCoordinate3D` or `TextureCoordinate4D` entry is the mesh's
3D texture coordinates, `TEXCOORD_3D` (:meth:`MeshDrawn.volumeCoordinates`);
it is no 2D set. A `TextureCoordinateGenerator` makes the first set in the
vertex shader, and a later set in the fragment shader where a
`MultiTexture` layer reads it (:mod:`~OpenGLContext.scenegraph.texturelayers`).
`FogCoordinate` and the `attrib` vertex attributes are kept and not drawn.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, Optional

import numpy as np
from vrml import cache, protofunctions
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import boundingvolume, composedgeometry, texgen
from OpenGLContext.scenegraph.texturemapping import label_set

log = logging.getLogger(__name__)

__all__ = ['DRAWN_KEY', 'DrawnAs', 'ElevationGrid', 'IndexedQuadSet', 'IndexedTriangleFanSet',
           'IndexedTriangleSet', 'IndexedTriangleStripSet', 'LineSet', 'MESH_KEY', 'MeshDrawn',
           'MeshGeometry', 'polylines', 'QuadSet',
           'TriangleFanSet', 'TriangleSet', 'TriangleStripSet']

#: The key a set's mesh is kept under in vrml's cache.
MESH_KEY = 'composed-mesh'
#: The key what a DrawnAs node is drawn as is kept under in vrml's cache.
DRAWN_KEY = 'drawn-as'
_reported: "set[tuple[str, str]]" = set()


def _report(target: Any, message: str) -> None:
    key = (str(protofunctions.protoName(target)), message)
    if key not in _reported:
        _reported.add(key)
        log.warning('%s %s', key[0], message)


def _sources(target: Any) -> Iterator[Any]:
    """`target` and each node whose fields its arrays are read from"""
    yield target
    for name in ('coord', 'normal', 'tangent', 'color', 'texCoord'):
        child = getattr(target, name, None)
        if child:
            yield child
            if isinstance(child, x3d.MultiTextureCoordinate):
                yield from (entry for entry in child.texCoord if entry)


def _depend_on_fields(holder: Any, target: Any) -> None:
    for source in _sources(target):
        for declared in protofunctions.getFields(source):
            if not declared.name.startswith(' '):
                holder.depend(source, declared)


def _values(child: Any, name: str) -> Any:
    """A property node's array, or None where there is no node"""
    return getattr(child, name, None) if child else None


class MeshDrawn:
    """A geometry node drawn as the mesh :meth:`buildMesh` makes of its fields

    The mesh is cached, drawn, shadowed and bounded here; a subclass gives
    :meth:`buildMesh`, usually through :meth:`meshFrom`.
    """

    texCoord: Any

    def buildMesh(self) -> Optional[Any]:
        """The mesh the fields build now, or None for a node with nothing to draw"""
        raise NotImplementedError('%s must build its mesh' % type(self).__name__)

    def coordinateNodes(self) -> "list[Any]":
        """The texture coordinate nodes, in set order (TEXCOORD_0, _1, ...)"""
        found = getattr(self, 'texCoord', None)
        if not found:
            return []
        if isinstance(found, x3d.MultiTextureCoordinate):
            return [entry for entry in found.texCoord if entry]
        return [found]

    def textureCoordinateSet(self, label: str) -> int:
        """The coordinate set a material's mapping label names on this geometry

        The texture coordinate node whose `mapping` is the label; otherwise
        the label read by itself (:func:`~OpenGLContext.scenegraph.texturemapping.label_set`).
        """
        if label:
            for number, entry in enumerate(self.coordinateNodes()):
                if str(getattr(entry, 'mapping', '')) == label:
                    return number
        return label_set(label)

    def coordinates(self) -> "list[Any]":
        """Each 2D texture coordinate set's points; None for a generator, made in
        the shader, and for a 3D set, which is :meth:`volumeCoordinates`"""
        found: "list[Any]" = []
        for entry in self.coordinateNodes():
            if isinstance(entry, (x3d.TextureCoordinateGenerator, x3d.TextureCoordinate3D,
                                  x3d.TextureCoordinate4D)):
                found.append(None)
            else:
                found.append(_values(entry, 'point'))
        return found

    def volumeCoordinates(self) -> Optional[np.ndarray]:
        """The first 3D or 4D coordinate set as ``(n, 4)`` (s, t, r, q), or None"""
        for entry in self.coordinateNodes():
            if isinstance(entry, x3d.TextureCoordinate4D):
                return np.asarray(entry.point, np.float32).reshape(-1, 4)
            if isinstance(entry, x3d.TextureCoordinate3D):
                points = np.asarray(entry.point, np.float32).reshape(-1, 3)
                return np.concatenate([points, np.ones((len(points), 1), np.float32)], 1)
        return None

    @property
    def texGen(self) -> Optional[texgen.TexGen]:
        """The generator the first texture coordinate set is made by, or None"""
        nodes = self.coordinateNodes()
        return texgen.texgen_of(nodes[0]) if nodes else None

    def meshFrom(self, arrays: Any, solid: bool) -> Any:
        """A mesh of composed arrays, with tangents where there are coordinates for them

        What the arrays left out is reported once.
        """
        from OpenGLContext.loaders.gltf.meshes import estimate_tangents  # noqa: PLC0415 the loader package imports GL
        from OpenGLContext.scenegraph.frommesh import mesh_from_primitive  # noqa: PLC0415 PBRMesh imports GL
        if arrays.dropped:
            _report(self, 'names coordinates it does not have; %d triangles are left out'
                    % arrays.dropped)
        for name in arrays.short:
            _report(self, 'has fewer %s values than it indexes; they are left out' % name)
        attributes = arrays.attributes
        if 'TANGENT' not in attributes and 'TEXCOORD_0' in attributes:
            attributes['TANGENT'] = estimate_tangents(
                attributes['POSITION'], attributes['NORMAL'], attributes['TEXCOORD_0'],
                arrays.indices)
        return mesh_from_primitive(arrays, solid=solid)

    def dependOn(self, holder: Any) -> None:
        """Make `holder` depend on every field the mesh is built from"""
        _depend_on_fields(holder, self)

    def mesh(self) -> Optional[Any]:
        """The mesh drawn for this set, kept in vrml's cache under :data:`MESH_KEY`"""
        held = cache.CACHE.getData(self, MESH_KEY)
        if held is None:
            held = (self.buildMesh(),)
            self.dependOn(cache.CACHE.holder(self, held, MESH_KEY))
        found: Optional[Any] = held[0]
        return found

    def meshArrays(self) -> Any:
        """The mesh's triangles; None for a node with nothing to draw"""
        found = self.mesh()
        return None if found is None else found.meshArrays()

    def render(self, visible: int = 1, lit: int = 1, textured: int = 1,
               transparent: int = 0, mode: Any = None) -> int:
        """Draw the mesh, in whichever profile is in use"""
        found = self.mesh()
        if found is None:
            return 0
        return int(found.render(visible=visible, lit=lit, textured=textured,
                                transparent=transparent, mode=mode))

    def depthDraw(self, mode: Any) -> bool:
        """Draw the mesh's positions into a depth map, as `PBRMesh.depthDraw` does"""
        found = self.mesh()
        return True if found is None else bool(found.depthDraw(mode))

    def boundingVolume(self, mode: Any = None) -> Any:
        """The mesh's bounds; an empty volume for a set with nothing to draw

        Kept until a field the mesh is built from is set, so a shape's
        bounds, which depend on this volume, follow its geometry.
        """
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        found = self.mesh()
        volume = (boundingvolume.BoundingVolume() if found is None
                  else found.boundingVolume(mode))
        self.dependOn(boundingvolume.holdVolume(self, volume))
        return volume


class MeshGeometry(MeshDrawn, x3d.X3DComposedGeometryNode):
    """An X3D composed geometry node: a subclass gives :meth:`triangles`"""

    #: Triangles each face is drawn as, so a colour or normal per face covers
    #: them all.
    TRIANGLES_PER_FACE = 1

    def perFace(self, values: Any, per_vertex: bool) -> Any:
        """`values` one per triangle, where they are one per face"""
        if values is None or per_vertex or self.TRIANGLES_PER_FACE == 1:
            return values
        return np.repeat(np.asarray(values), self.TRIANGLES_PER_FACE, axis=0)

    def triangles(self) -> np.ndarray:
        """The set's triangles, three coordinate indices each"""
        raise NotImplementedError('%s must give its triangles' % type(self).__name__)

    def buildMesh(self) -> Optional[Any]:
        """The mesh of the set's triangles, or None for a set with no coordinates"""
        points = _values(self.coord, 'point')
        if points is None or not len(points):
            return None
        return self.meshFrom(composedgeometry.composed_arrays(
            points, self.triangles(), ccw=bool(self.ccw),
            normals=self.perFace(_values(self.normal, 'vector'), bool(self.normalPerVertex)),
            normal_per_vertex=bool(self.normalPerVertex),
            colors=self.perFace(_values(self.color, 'color'), bool(self.colorPerVertex)),
            color_per_vertex=bool(self.colorPerVertex),
            texcoords=self.coordinates() or [composedgeometry.default_texcoords(points)],
            tangents=_values(self.tangent, 'vector'),
            volume_texcoords=self.volumeCoordinates()),
            solid=bool(self.solid))


class ElevationGrid(MeshDrawn, x3d.ElevationGrid):
    """A grid of heights, `xDimension` across and `zDimension` deep

    Colours and normals are one per point, or one per quad where
    `colorPerVertex`/`normalPerVertex` is false. Normals not given are
    smoothed across folds within `creaseAngle`. Without a `texCoord`, the
    texture spans the grid once.
    """

    def buildMesh(self) -> Optional[Any]:
        """The mesh of the grid, or None for one smaller than 2 by 2 or short of heights"""
        across, deep = int(self.xDimension), int(self.zDimension)
        heights = np.asarray(self.height, dtype=np.float32).ravel()
        if across < 2 or deep < 2:
            return None
        if len(heights) < across * deep:
            _report(self, 'has %d heights for %d points; it is not drawn'
                    % (len(heights), across * deep))
            return None
        colors = _values(self.color, 'color')
        normals = _values(self.normal, 'vector')
        if colors is not None and not self.colorPerVertex:
            colors = composedgeometry.per_quad(colors)
        if normals is not None and not self.normalPerVertex:
            normals = composedgeometry.per_quad(normals)
        coordinates = self.coordinates() or [composedgeometry.grid_texcoords(across, deep)]
        return self.meshFrom(composedgeometry.composed_arrays(
            composedgeometry.grid_points(heights, across, deep, self.xSpacing, self.zSpacing),
            composedgeometry.grid_triangles(across, deep), ccw=bool(self.ccw),
            normals=normals, normal_per_vertex=bool(self.normalPerVertex),
            colors=colors, color_per_vertex=bool(self.colorPerVertex),
            texcoords=coordinates, tangents=_values(getattr(self, 'tangent', None), 'vector'),
            crease_angle=float(self.creaseAngle),
            volume_texcoords=self.volumeCoordinates()), solid=bool(self.solid))


class TriangleSet(MeshGeometry, x3d.TriangleSet):
    """Triangles of the points taken three at a time"""

    def triangles(self) -> np.ndarray:
        points = _values(self.coord, 'point')
        return composedgeometry.triangle_set(0 if points is None else len(points))


class IndexedTriangleSet(MeshGeometry, x3d.IndexedTriangleSet):
    """Triangles of `index` taken three at a time"""

    def triangles(self) -> np.ndarray:
        return composedgeometry.indexed_triangles(self.index)


class TriangleFanSet(MeshGeometry, x3d.TriangleFanSet):
    """Fans of `fanCount` points each, the points taken in order"""

    def triangles(self) -> np.ndarray:
        return composedgeometry.fans(self.fanCount)


class IndexedTriangleFanSet(MeshGeometry, x3d.IndexedTriangleFanSet):
    """One fan per run of `index`, the runs separated by -1"""

    def triangles(self) -> np.ndarray:
        return composedgeometry.indexed_fans(self.index)


class TriangleStripSet(MeshGeometry, x3d.TriangleStripSet):
    """Strips of `stripCount` points each, the points taken in order"""

    def triangles(self) -> np.ndarray:
        return composedgeometry.strips(self.stripCount)


class IndexedTriangleStripSet(MeshGeometry, x3d.IndexedTriangleStripSet):
    """One strip per run of `index`, the runs separated by -1"""

    def triangles(self) -> np.ndarray:
        return composedgeometry.indexed_strips(self.index)


class QuadSet(MeshGeometry, x3d.QuadSet):
    """Quadrilaterals of the points taken four at a time, two triangles each"""

    TRIANGLES_PER_FACE = 2

    def triangles(self) -> np.ndarray:
        points = _values(self.coord, 'point')
        return composedgeometry.quad_set(0 if points is None else len(points))


class IndexedQuadSet(MeshGeometry, x3d.IndexedQuadSet):
    """Quadrilaterals of `index` taken four at a time, two triangles each"""

    TRIANGLES_PER_FACE = 2

    def triangles(self) -> np.ndarray:
        return composedgeometry.indexed_quads(self.index)


class DrawnAs:
    """A geometry node drawn as another engine node its fields build

    A line or point set is drawn as the engine's `IndexedLineSet` or
    `PointSet`; :meth:`drawn` keeps the one :meth:`buildDrawn` makes in vrml's
    cache until a field of this node is set.
    """

    def buildDrawn(self) -> Any:
        """The engine node this node is drawn as, made from its fields now"""
        raise NotImplementedError('%s must build what it is drawn as' % type(self).__name__)

    def drawn(self) -> Any:
        """The engine node this node is drawn as, kept under :data:`DRAWN_KEY`"""
        found = cache.CACHE.getData(self, DRAWN_KEY)
        if found is None:
            found = self.buildDrawn()
            holder = cache.CACHE.holder(self, found, DRAWN_KEY)
            for declared in protofunctions.getFields(self):
                if not declared.name.startswith(' '):
                    holder.depend(self, declared)
        return found

    def render(self, visible: int = 1, lit: int = 1, textured: int = 1,
               transparent: int = 0, mode: Any = None) -> Any:
        """Draw the engine node"""
        return self.drawn().render(visible=visible, lit=lit, textured=textured,
                                   transparent=transparent, mode=mode)

    def boundingVolume(self, mode: Any = None) -> Any:
        """The engine node's bounds"""
        return self.drawn().boundingVolume(mode)


def polylines(points: Any, counts: "list[int]") -> Any:
    """An engine IndexedLineSet of runs of `points`, `counts` points each"""
    from OpenGLContext.scenegraph.indexedlineset import IndexedLineSet  # noqa: PLC0415 imports GL
    index: "list[int]" = []
    start = 0
    for count in counts:
        if count >= 2:
            index.extend(range(start, start + count))
            index.append(-1)
        start += max(count, 0)
    coord = points if isinstance(points, x3d.X3DCoordinateNode) else x3d.Coordinate(point=points)
    return IndexedLineSet(coord=coord, coordIndex=index, colorPerVertex=True)


class LineSet(DrawnAs, x3d.LineSet):
    """Polylines of `vertexCount` points each, drawn as the engine's IndexedLineSet"""

    def buildDrawn(self) -> Any:
        """An IndexedLineSet of the set's own coordinates and colours"""
        lines = polylines(self.coord, [int(value) for value in self.vertexCount])
        lines.color = self.color
        return lines
