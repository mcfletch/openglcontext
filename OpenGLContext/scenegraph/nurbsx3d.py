"""X3D's NURBS geometry: patch, trimmed, swept and swung surfaces, curves, trims and sets

The surfaces (`NurbsPatchSurface`, `NurbsTrimmedSurface`, `NurbsSweptSurface`,
`NurbsSwungSurface`) are drawn as the
:class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` their fields build
(:class:`~OpenGLContext.scenegraph.meshgeometry.MeshDrawn`), so they draw in
both renderers and the compatibility profile, cast shadows and are picked as
any mesh is. A `NurbsCurve` is drawn as the engine's `IndexedLineSet` of the
points along it, so `LineProperties` widen and dash it. The arithmetic -- the
specification's rules for knots, closure and tessellation counts, and the
evaluation -- is :mod:`~OpenGLContext.scenegraph.nurbseval`'s.

- A surface's texture coordinates are its parameters across the unit square;
  a `TextureCoordinate` of one point per control point, evaluated through the
  surface's own basis; or a `NurbsTextureCoordinate`'s own net, evaluated at
  the same fractions of its domain. A `TextureCoordinateGenerator` makes them
  in the shader.
- `NurbsTrimmedSurface` keeps the part of its domain inside an odd number of
  its `Contour2D` loops, each made of `ContourPolyline2D` and `NurbsCurve2D`
  pieces in the surface's own (u, v) knot range.
- `NurbsSweptSurface` sweeps its 2D `crossSectionCurve` along its
  `trajectoryCurve` as an `Extrusion` sweeps its cross-section along its
  spine; `NurbsSwungSurface` sweeps its `profileCurve` along its 2D
  `trajectoryCurve` laid in the xz-plane. Neither is capped.
- `NurbsSet` multiplies the tessellation of each geometry in its `geometry`
  by its `tessellationScale`.
- A surface far from the viewer is drawn from a coarser tessellation, each
  level kept separately (:data:`LOD_SCALES`, :mod:`tessellationlod`).

Every mesh is kept in vrml's cache until a field it is built from is set: the
node's own, its control points', its texture coordinates', its curves' and its
contours'.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, Optional

import numpy as np
from pydispatch import dispatcher
from vrml import cache, protofunctions
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import boundingvolume, composedgeometry, nurbseval
from OpenGLContext.scenegraph.meshgeometry import DRAWN_KEY, MESH_KEY, DrawnAs, MeshDrawn, polylines
from OpenGLContext.scenegraph.nurbstrim import join_loop

log = logging.getLogger(__name__)

__all__ = ['Contour2D', 'ContourPolyline2D', 'LOD_SCALES', 'NurbsCurve', 'NurbsCurve2D',
           'NurbsPatchSurface', 'NurbsSet', 'NurbsSweptSurface', 'NurbsSwungSurface',
           'NurbsTextureCoordinate', 'NurbsTrimmedSurface', 'SCALE_SIGNAL', 'control_points',
           'depend_on_sources', 'texture_net']

#: What a surface's tessellation is multiplied by at each distance level
#: (:func:`~OpenGLContext.scenegraph.tessellationlod.lod_level`); level 0 is
#: the tessellation the fields ask for.
LOD_SCALES = (1.0, 0.5, 0.25, 0.125)

#: Sent by a geometry whose `NurbsSet` scale has changed, so what is built
#: from its tessellation is built again.
SCALE_SIGNAL = 'nurbs-tessellation-scale'

_reported: "set[tuple[str, str]]" = set()


def _report(target: Any, message: str) -> None:
    key = (str(protofunctions.protoName(target)), message)
    if key not in _reported:
        _reported.add(key)
        log.warning('%s %s', key[0], message)


def control_points(node: Any) -> Optional[np.ndarray]:
    """A `Coordinate` or `CoordinateDouble` node's points, ``(N, 3)``; None for no node"""
    points = getattr(node, 'point', None) if node else None
    if points is None:
        return None
    return np.asarray(points, dtype=np.float64).reshape(-1, 3)


def depend_on_sources(holder: Any, sources: "Iterator[Any]") -> None:
    """Make a cache `holder` depend on every field of each of `sources`"""
    for source in sources:
        for declared in protofunctions.getFields(source):
            if not declared.name.startswith(' '):
                holder.depend(source, declared)


def _added(current: Any, value: Any) -> "list[Any]":
    found = list(current)
    return found + [entry for entry in value if entry and entry not in found]


def _removed(current: Any, value: Any) -> "list[Any]":
    gone = list(value)
    return [entry for entry in current if entry not in gone]


class Parametric:
    """What each X3D NURBS geometry shares: the tessellation scale a `NurbsSet` gives it"""

    def tessellationScale(self) -> float:
        """The scale of the `NurbsSet` holding this geometry; 1 for none"""
        return float(self.__dict__.get('_tessellationScale', 1.0))

    def setTessellationScale(self, scale: float) -> None:
        """Multiply this geometry's tessellation by `scale` (what `NurbsSet` calls)"""
        if scale != self.tessellationScale():
            self.__dict__['_tessellationScale'] = float(scale)
            dispatcher.send(SCALE_SIGNAL, sender=self)

    def sources(self) -> "Iterator[Any]":
        """This node and each node whose fields its geometry is built from"""
        yield self

    def dependOn(self, holder: Any) -> None:
        """Make `holder` depend on every field the geometry is built from, and the scale"""
        depend_on_sources(holder, self.sources())
        holder.depend_signal(SCALE_SIGNAL, self)


def _curve_of(node: Any) -> Any:
    """The :class:`~nurbseval.Curve` of a curve node; None for none"""
    make = getattr(node, 'curve', None) if node else None
    return make() if make is not None else None


def texture_net(node: Any) -> Optional[nurbseval.Net]:
    """The net a `NurbsTextureCoordinate`'s fields describe; None where they describe none"""
    return nurbseval.texture_net(node.controlPoint, node.uDimension, node.vDimension,
                                 node.uKnot, node.vKnot, node.uOrder, node.vOrder, node.weight)


class NurbsTextureCoordinate(x3d.NurbsTextureCoordinate):
    """A surface's texture coordinates as a NURBS net of their own"""

    def net(self) -> Optional[nurbseval.Net]:
        """The net its fields describe; None where they describe none"""
        return texture_net(self)


class SurfaceDrawn(Parametric, MeshDrawn):
    """A surface with a control net, drawn as its tessellation's mesh

    A subclass may give :meth:`contours`; :meth:`levelMesh` is the mesh at a
    distance level, :meth:`mesh` at level 0.
    """

    controlPoint: Any
    solid: Any
    texCoord: Any
    uClosed: Any
    uDimension: Any
    uKnot: Any
    uOrder: Any
    uTessellation: Any
    vClosed: Any
    vDimension: Any
    vKnot: Any
    vOrder: Any
    vTessellation: Any
    weight: Any

    def sources(self) -> "Iterator[Any]":
        yield self
        if self.controlPoint:
            yield self.controlPoint
        texture = self.texCoord
        if texture:
            yield texture
            if isinstance(texture, x3d.MultiTextureCoordinate):
                yield from (entry for entry in texture.texCoord if entry)

    def surface(self) -> Optional[nurbseval.Surface]:
        """The surface the fields describe; None (reported) where they describe none"""
        points = control_points(self.controlPoint)
        if points is None:
            return None
        found = nurbseval.surface(points, self.uDimension, self.vDimension, self.uKnot,
                                  self.vKnot, self.uOrder, self.vOrder, self.weight,
                                  bool(self.uClosed), bool(self.vClosed))
        if found is None:
            _report(self, 'has control points, dimensions or orders that describe no '
                          'surface; it is not drawn')
        return found

    def contours(self) -> "list[np.ndarray]":
        """The trimming loops, each ``(N, 2)`` in the surface's knot range"""
        return []

    def buildMesh(self, level: int = 0) -> Optional[Any]:
        """The mesh at distance level `level`; None for a surface with nothing to draw"""
        found = self.surface()
        if found is None:
            return None
        scale = self.tessellationScale() * LOD_SCALES[min(level, len(LOD_SCALES) - 1)]
        u_segments, v_segments = found.segments(int(self.uTessellation),
                                                int(self.vTessellation), scale)
        patch = found.tessellate(u_segments, v_segments, self.contours())
        if not len(patch.triangles):
            return None
        return self.meshFrom(composedgeometry.composed_arrays(
            patch.positions, patch.triangles, normals=patch.normals,
            texcoords=self.textureCoordinates(found, patch.fractions)),
            solid=bool(self.solid))

    def textureCoordinates(self, surface: nurbseval.Surface,
                           fractions: np.ndarray) -> "list[Any]":
        """Each texture coordinate set's coordinates at `fractions` of the domain"""
        nodes = self.coordinateNodes()
        if not nodes:
            return [fractions]
        found: "list[Any]" = []
        for entry in nodes:
            if isinstance(entry, x3d.TextureCoordinateGenerator):
                found.append(None)
                continue
            if isinstance(entry, x3d.NurbsTextureCoordinate):
                net = texture_net(entry)
            else:
                points = getattr(entry, 'point', None)
                net = None if points is None else surface.coordinate_net(points)
            if net is None:
                _report(self, 'has a %s that is not one coordinate per control point; '
                              'its parameters are used instead'
                        % protofunctions.protoName(entry))
                found.append(fractions)
            else:
                found.append(net.at(fractions))
        return found

    def levelMesh(self, level: int) -> Optional[Any]:
        """The mesh at distance level `level`, kept in vrml's cache"""
        if level <= 0:
            return self.mesh()
        key = (MESH_KEY, level)
        held = cache.CACHE.getData(self, key)
        if held is None:
            held = (self.buildMesh(level),)
            self.dependOn(cache.CACHE.holder(self, held, key))
        found: Optional[Any] = held[0]
        return found

    def lodLevel(self, mode: Any) -> int:
        """The distance level to draw at in `mode`; 0 without one"""
        from OpenGLContext.scenegraph import tessellationlod  # noqa: PLC0415 reads renderoptions
        points = control_points(self.controlPoint)
        if mode is None or points is None or not len(points):
            return 0
        low, high = points.min(axis=0), points.max(axis=0)
        radius = 0.5 * float(np.linalg.norm(high - low)) or 1.0
        level = tessellationlod.lod_level(mode, (low + high) * 0.5, radius)
        return min(int(level), len(LOD_SCALES) - 1)

    def render(self, visible: int = 1, lit: int = 1, textured: int = 1,
               transparent: int = 0, mode: Any = None) -> int:
        """Draw the mesh for the viewer's distance"""
        found = self.levelMesh(self.lodLevel(mode))
        if found is None:
            return 0
        return int(found.render(visible=visible, lit=lit, textured=textured,
                                transparent=transparent, mode=mode))

    def depthDraw(self, mode: Any) -> bool:
        """Draw the mesh for the viewer's distance into a depth map"""
        found = self.levelMesh(self.lodLevel(mode))
        return True if found is None else bool(found.depthDraw(mode))


class NurbsPatchSurface(SurfaceDrawn, x3d.NurbsPatchSurface):
    """A NURBS surface: a net of control points, a knot vector and order each way"""


class NurbsTrimmedSurface(SurfaceDrawn, x3d.NurbsTrimmedSurface):
    """A NURBS surface cut to the inside of its `trimmingContour` loops"""

    def sources(self) -> "Iterator[Any]":
        yield from super().sources()
        for contour in self.trimmingContour:
            if contour:
                yield contour
                for piece in getattr(contour, 'children', ()):
                    if piece:
                        yield piece

    def contours(self) -> "list[np.ndarray]":
        found = []
        for contour in self.trimmingContour:
            loop = getattr(contour, 'contour', None)
            if loop is not None:
                points = loop()
                if len(points) >= 3:
                    found.append(points)
        return found

    def on_addTrimmingContour(self, value: Any) -> None:
        self.trimmingContour = _added(self.trimmingContour, value)

    def on_removeTrimmingContour(self, value: Any) -> None:
        self.trimmingContour = _removed(self.trimmingContour, value)


class ContourPolyline2D(x3d.ContourPolyline2D):
    """A straight-sided piece of a trimming loop"""

    def points(self, steps: int = 0) -> np.ndarray:
        """The piece's own points, ``(N, 2)``"""
        return np.asarray(self.controlPoint, dtype=np.float64).reshape(-1, 2)


class NurbsCurve2D(x3d.NurbsCurve2D):
    """A curved piece of a trimming loop, or a swept or swung surface's curve"""

    def curve(self) -> Optional[nurbseval.Curve]:
        """The curve the fields describe; None where they describe none"""
        return nurbseval.curve(np.asarray(self.controlPoint, dtype=np.float64).reshape(-1, 2),
                               self.knot, self.order, self.weight, bool(self.closed))

    def points(self, steps: int = 0) -> np.ndarray:
        """``(N, 2)`` points along the curve, at its `tessellation`; `steps` where that is 0"""
        found = self.curve()
        if found is None:
            return np.zeros((0, 2), dtype=np.float64)
        tessellation = int(self.tessellation) or int(steps)
        return found.sample(found.segments(tessellation))


class Contour2D(x3d.Contour2D):
    """A closed trimming loop of `ContourPolyline2D` and `NurbsCurve2D` pieces"""

    def contour(self, steps: int = 0) -> np.ndarray:
        """The whole loop, ``(N, 2)`` (:func:`~OpenGLContext.scenegraph.nurbstrim.join_loop`)"""
        return join_loop(self.children, steps)

    def on_addChildren(self, value: Any) -> None:
        self.children = _added(self.children, value)

    def on_removeChildren(self, value: Any) -> None:
        self.children = _removed(self.children, value)


class NurbsCurve(Parametric, DrawnAs, x3d.NurbsCurve):
    """A NURBS curve in space, drawn as a line through `tessellation` segments"""

    def sources(self) -> "Iterator[Any]":
        yield self
        if self.controlPoint:
            yield self.controlPoint

    def curve(self) -> Optional[nurbseval.Curve]:
        """The curve the fields describe; None where they describe none"""
        points = control_points(self.controlPoint)
        if points is None:
            return None
        return nurbseval.curve(points, self.knot, self.order, self.weight, bool(self.closed))

    def buildDrawn(self) -> Any:
        """An IndexedLineSet of points along the curve; None for no curve"""
        found = self.curve()
        if found is None:
            return None
        points = found.sample(found.segments(int(self.tessellation), self.tessellationScale()))
        return polylines(points, [len(points)])

    def drawn(self) -> Any:
        """The line, kept in vrml's cache until the curve's fields or scale change"""
        found = cache.CACHE.getData(self, DRAWN_KEY)
        if found is None:
            found = self.buildDrawn()
            self.dependOn(cache.CACHE.holder(self, found, DRAWN_KEY))
        return found

    def render(self, visible: int = 1, lit: int = 1, textured: int = 1,
               transparent: int = 0, mode: Any = None) -> Any:
        """Draw the line; 0 for no curve"""
        found = self.drawn()
        if found is None:
            return 0
        return found.render(visible=visible, lit=lit, textured=textured,
                            transparent=transparent, mode=mode)

    def boundingVolume(self, mode: Any = None) -> Any:
        """The line's bounds; an empty volume for no curve"""
        found = self.drawn()
        if found is None:
            return boundingvolume.BoundingVolume()
        return found.boundingVolume(mode)


class SweepDrawn(Parametric, MeshDrawn):
    """A surface swept from two curves; a subclass gives :meth:`primitive`"""

    solid: Any

    def curves(self) -> "tuple[Any, ...]":
        """The curve nodes the sweep is made of"""
        raise NotImplementedError('%s must name its curves' % type(self).__name__)

    def sources(self) -> "Iterator[Any]":
        yield self
        for curve in self.curves():
            if curve:
                yield curve
                control = getattr(curve, 'controlPoint', None)
                if isinstance(control, x3d.X3DCoordinateNode):
                    yield control

    def primitive(self, first: nurbseval.Curve, second: nurbseval.Curve,
                  counts: "tuple[int, int]") -> Any:
        """The sweep's glTF-shaped primitive"""
        raise NotImplementedError('%s must sweep its curves' % type(self).__name__)

    def buildMesh(self) -> Optional[Any]:
        """The swept mesh; None where a curve is missing or describes none"""
        from OpenGLContext.scenegraph.frommesh import mesh_from_primitive  # noqa: PLC0415 PBRMesh imports GL
        nodes = self.curves()
        curves = [_curve_of(node) for node in nodes]
        if any(found is None for found in curves):
            return None
        scale = self.tessellationScale()
        first, second = curves
        counts = (first.segments(int(nodes[0].tessellation), scale),
                  second.segments(int(nodes[1].tessellation), scale))
        try:
            primitive = self.primitive(first, second, counts)
        except ValueError as err:
            _report(self, 'cannot be swept from its curves (%s); it is not drawn' % err)
            return None
        return mesh_from_primitive(primitive, solid=bool(self.solid))


class NurbsSweptSurface(SweepDrawn, x3d.NurbsSweptSurface):
    """A 2D cross-section curve swept along a NURBS curve in space"""

    def curves(self) -> "tuple[Any, ...]":
        return (self.crossSectionCurve, self.trajectoryCurve)

    def primitive(self, first: nurbseval.Curve, second: nurbseval.Curve,
                  counts: "tuple[int, int]") -> Any:
        return nurbseval.swept(first, second, bool(self.ccw), *counts)


class NurbsSwungSurface(SweepDrawn, x3d.NurbsSwungSurface):
    """A 2D profile curve swept along a 2D trajectory curve in the xz-plane"""

    def curves(self) -> "tuple[Any, ...]":
        return (self.profileCurve, self.trajectoryCurve)

    def primitive(self, first: nurbseval.Curve, second: nurbseval.Curve,
                  counts: "tuple[int, int]") -> Any:
        return nurbseval.swung(first, second, bool(self.ccw), *counts)


class NurbsSet(x3d.NurbsSet):
    """Geometry whose tessellation is multiplied by `tessellationScale`

    The set is not drawn; each geometry in it is drawn by the shapes that
    hold it, at the set's scale. A geometry taken out of the set goes back to
    its own tessellation.
    """

    def __init__(self, **named: Any) -> None:
        super().__init__(**named)
        for name in ('geometry', 'tessellationScale'):
            dispatcher.connect(self._rescale, signal=('set', protofunctions.getField(self, name)),
                               sender=self)
        self._rescale()

    def _rescale(self, **_named: Any) -> None:
        scale = float(self.tessellationScale)
        current = [entry for entry in self.geometry if hasattr(entry, 'setTessellationScale')]
        for entry in self.__dict__.get('_scaled', ()):
            if entry not in current:
                entry.setTessellationScale(1.0)
        for entry in current:
            entry.setTessellationScale(scale)
        self.__dict__['_scaled'] = current

    def on_addGeometry(self, value: Any) -> None:
        self.geometry = _added(self.geometry, value)

    def on_removeGeometry(self, value: Any) -> None:
        self.geometry = _removed(self.geometry, value)
