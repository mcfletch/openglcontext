"""X3D's pick sensors told each frame what their picking geometry touches -- no GL

The sensors are pyvrml97's (:mod:`vrml.x3d.picking`). Once a frame, after the
views are placed, the pass calls :func:`sense` with every pick sensor's path.
Each sensor's `pickTarget` nodes are found where the scene draws them, and
every shape under them is a candidate: a shape below a `PickableGroup` whose
`pickable` is false, or whose `objectType` the sensor does not accept under
its `matchCriterion`, is passed over. Everything is measured in the sensor's
own coordinates, where its `pickingGeometry` is.

- `LinePickSensor`: the segments of an `IndexedLineSet` or `LineSet`. With
  `intersectionType` ``GEOMETRY`` each crossing of a shape's triangles gives
  a point, the surface's normal there and its texture coordinate (z zero);
  with ``BOUNDS`` the point each segment enters the shape's bounding box,
  that face's normal, and where in the box the point is, 0 to 1 on each
  axis, as the texture coordinate. A pick's distance is along its line from
  the line's first point to the first crossing.
- `PointPickSensor`: the points of a `PointSet` within the shape's bounding
  box, or within its triangles (by the winding number) for ``GEOMETRY``.
- `PrimitivePickSensor`: a `Box`, `Sphere`, `Cylinder` or `Cone`, centred on
  the sensor's origin; `VolumePickSensor`: any geometry with triangles, as a
  closed solid. ``BOUNDS`` tests the solid's bounding box against the
  shape's; ``GEOMETRY`` picks a shape whose triangles meet the solid or that
  holds the solid within it. Cylinders and cones are tested as solids of
  :data:`SIDES` walls. A pick's distance is between the centres of the two
  bounding boxes.

A shape is tested against its bounding box first, and its triangles are
asked for (`meshArrays`) only where that box is reached.
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any, NamedTuple, Optional

import numpy as np
from vrml.x3d import picking
from vrml.x3d.nodes import X3DPickableObject

from OpenGLContext.scenegraph import meshdata
from OpenGLContext.scenegraph import pickgeometry as pg

log = logging.getLogger(__name__)

__all__ = ['Segments', 'Target', 'line_segments', 'picks_for', 'points_of',
           'primitive_volume', 'sense', 'targets']

#: The walls a picking Cylinder or Cone is tested as.
SIDES = 32

#: Crossings of one segment closer than this, as a fraction of its length,
#: are one crossing.
EDGE_TOLERANCE = 1e-9


class Segments(NamedTuple):
    """A line geometry's segments: their ends, and how far along its line each starts"""

    starts: np.ndarray
    ends: np.ndarray
    along: np.ndarray


class Target(NamedTuple):
    """A shape a sensor may pick: the shape, its path, and its matrix into the sensor's coordinates"""

    shape: Any
    path: Any
    matrix: np.ndarray


def _points(geometry: Any) -> Optional[np.ndarray]:
    coord = getattr(geometry, 'coord', None)
    point = getattr(coord, 'point', None) if coord else None
    if point is None or not len(point):
        return None
    return np.asarray(point, dtype=np.float64).reshape(-1, 3)


def line_segments(geometry: Any) -> Optional[Segments]:
    """The segments of an `IndexedLineSet` or `LineSet`; None for other geometry"""
    points = _points(geometry)
    if points is None:
        return None
    if hasattr(geometry, 'vertexCount'):
        lines, first = [], 0
        for count in np.asarray(geometry.vertexCount, dtype=np.int64).ravel():
            lines.append(np.arange(first, first + int(count)))
            first += int(count)
    elif hasattr(geometry, 'coordIndex'):
        index = np.asarray(geometry.coordIndex, dtype=np.int64).ravel()
        breaks = np.nonzero(index < 0)[0]
        lines = [line for line in np.split(index, breaks) if len(line)]
        lines = [line[line >= 0] for line in lines]
    else:
        return None
    starts, ends, along = [], [], []
    for line in lines:
        line = line[(line >= 0) & (line < len(points))]
        if len(line) < 2:
            continue
        first_points, second_points = points[line[:-1]], points[line[1:]]
        lengths = np.linalg.norm(second_points - first_points, axis=1)
        starts.append(first_points)
        ends.append(second_points)
        along.append(np.concatenate([[0.0], np.cumsum(lengths)[:-1]]))
    if not starts:
        return None
    return Segments(np.concatenate(starts), np.concatenate(ends), np.concatenate(along))


def points_of(geometry: Any) -> Optional[np.ndarray]:
    """The points of a `PointSet`; None for other geometry"""
    if not hasattr(geometry, 'coord') or hasattr(geometry, 'coordIndex') \
            or hasattr(geometry, 'vertexCount'):
        return None
    return _points(geometry)


def primitive_volume(geometry: Any) -> Optional[pg.Volume]:
    """The solid a `Box`, `Sphere`, `Cylinder` or `Cone` is; None for other geometry"""
    name = getattr(geometry, 'PROTO', '')
    if name == 'Box':
        return pg.BoxVolume(np.asarray(geometry.size, dtype=np.float64) / 2.0)
    if name == 'Sphere':
        return pg.SphereVolume(float(geometry.radius))
    if name == 'Cylinder':
        return pg.MeshVolume(pg.cylinder_solid(float(geometry.radius), float(geometry.height),
                                               SIDES))
    if name == 'Cone':
        return pg.MeshVolume(pg.cone_solid(float(geometry.bottomRadius), float(geometry.height),
                                           SIDES))
    return None


def _mesh_volume(geometry: Any) -> Optional[pg.Volume]:
    mesh = _triangles(geometry)
    return None if mesh is None else pg.MeshVolume(mesh[0])


def _matrix(path: Any) -> np.ndarray:
    found = path.transformMatrix()
    return np.identity(4) if found is None else np.asarray(found, dtype=np.float64)


def _shapes(node: Any, path: Any) -> Iterator[tuple[Any, Any]]:
    """Each shape at or under `node`, reached by `path`, walked as the render pass walks"""
    if getattr(node, 'geometry', None):
        yield node, path
        return
    children = getattr(node, 'renderedChildren', None)
    if children is not None:
        for child in children():
            if child:
                yield from _shapes(child, path + child)


def _pickable(sensor: Any, path: Any) -> bool:
    """Whether every pickable object on `path` is picked and `sensor` accepts its labels"""
    for node in path:
        if isinstance(node, X3DPickableObject) and (
                not node.pickable or not sensor.accepts(getattr(node, 'objectType', ['ALL']))):
            return False
    return True


def targets(sensor: Any, nodePaths: Mapping[Any, Sequence[Any]],
            local: np.ndarray) -> Iterator[Target]:
    """The shapes under `sensor`'s pick targets that it may pick, each placement once

    local -- the sensor's world-to-local matrix
    """
    seen: set[tuple[Any, ...]] = set()
    for node in sensor.pickTarget:
        if not node:
            continue
        for base in nodePaths.get(node, ()):
            if getattr(base, 'broken', False):
                continue
            for shape, path in _shapes(node, base):
                key = tuple(path)
                if key in seen or not _pickable(sensor, path):
                    continue
                seen.add(key)
                yield Target(shape, path, _matrix(path) @ local)


def _bounds(geometry: Any) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """The geometry's bounding box in its own frame; None where it has none"""
    try:
        volume = geometry.boundingVolume(None)
        points = volume.getPoints() if volume is not None else None
    except Exception as err:
        log.debug('No bounds for %s: %s', geometry, err)
        return None
    if points is None or not len(points):
        return None
    corners = np.asarray(points, dtype=np.float64)[:, :3]
    if not np.all(np.isfinite(corners)):
        return None
    return corners.min(axis=0), corners.max(axis=0)


def _triangles(geometry: Any) -> Optional[tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]]:
    """The geometry's triangles, their corners' normals and texture coordinates, in its frame"""
    found = meshdata.geometry_arrays(geometry)
    if found is None:
        return None
    attributes = found.attributes
    positions = np.asarray(attributes['POSITION'], dtype=np.float64)
    corners = (np.arange((len(positions) // 3) * 3) if found.indices is None
               else np.asarray(found.indices, dtype=np.int64).ravel())
    corners = corners[:(len(corners) // 3) * 3]
    if not len(corners):
        return None
    normals = np.asarray(attributes['NORMAL'], dtype=np.float64)[corners].reshape(-1, 3, 3)
    texcoords = attributes.get('TEXCOORD_0')
    textured = (None if texcoords is None
                else np.asarray(texcoords, dtype=np.float64)[corners].reshape(-1, 3, 2))
    return positions[corners].reshape(-1, 3, 3), normals, textured


def _placed(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    placed: np.ndarray = points @ matrix[:3, :3] + matrix[3, :3]
    return placed


def _turned(normals: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """`normals` carried by `matrix`, of unit length"""
    turned = normals @ np.linalg.inv(matrix[:3, :3]).T
    length = np.linalg.norm(turned, axis=1, keepdims=True)
    length[~(length > 0)] = 1.0
    unit: np.ndarray = turned / length
    return unit


def _line_pick(target: Target, segments: Segments, geometry_test: bool) -> Optional[picking.Pick]:
    bounds = _bounds(target.shape.geometry)
    if bounds is None:
        return None
    into = np.linalg.inv(target.matrix)
    starts, ends = _placed(segments.starts, into), _placed(segments.ends, into)
    low, high = bounds
    entries = pg.segment_box(starts, ends, low, high)
    if not len(entries.segment):
        return None
    lengths = np.linalg.norm(segments.ends - segments.starts, axis=1)
    if geometry_test:
        mesh = _triangles(target.shape.geometry)
        if mesh is None:
            return None
        triangles, normals, texcoords = mesh
        reached = entries.segment
        hits = pg.segment_triangles(starts[reached], ends[reached], triangles)
        if not len(hits.t):
            return None
        segment = reached[hits.segment]
        weights = np.column_stack([1.0 - hits.u - hits.v, hits.u, hits.v])
        local = np.einsum('ij,ijk->ik', weights, triangles[hits.triangle])
        normal = np.einsum('ij,ijk->ik', weights, normals[hits.triangle])
        if texcoords is None:
            texcoord = np.zeros((len(hits.t), 3))
        else:
            texcoord = np.column_stack([np.einsum('ij,ijk->ik', weights,
                                                  texcoords[hits.triangle]),
                                        np.zeros(len(hits.t))])
        t = hits.t
    else:
        segment, t = entries.segment, entries.t
        local = starts[segment] + (ends[segment] - starts[segment]) * t[:, np.newaxis]
        normal = entries.normal
        size = np.where(high - low > 0, high - low, 1.0)
        texcoord = np.clip((local - low) / size, 0.0, 1.0)
    distance = segments.along[segment] + t * lengths[segment]
    order = np.lexsort((t, segment))
    # A crossing on an edge two triangles share is found in both
    repeated = np.zeros(len(order), dtype=bool)
    repeated[1:] = ((segment[order][1:] == segment[order][:-1])
                    & (np.abs(np.diff(t[order])) <= EDGE_TOLERANCE))
    order = order[~repeated]
    order = order[np.argsort(distance[order], kind='stable')]
    return picking.Pick(
        target.shape, float(distance[order[0]]),
        points=_placed(local[order], target.matrix),
        normals=_turned(normal[order], target.matrix),
        texCoords=texcoord[order])


def _centre_distance(low: np.ndarray, high: np.ndarray, target: Target,
                     bounds: tuple[np.ndarray, np.ndarray]) -> float:
    centre = _placed(((bounds[0] + bounds[1]) / 2.0)[np.newaxis], target.matrix)[0]
    return float(np.linalg.norm(centre - (low + high) / 2.0))


def _point_pick(target: Target, points: np.ndarray, geometry_test: bool) -> Optional[picking.Pick]:
    bounds = _bounds(target.shape.geometry)
    if bounds is None:
        return None
    local = _placed(points, np.linalg.inv(target.matrix))
    low, high = bounds
    with np.errstate(invalid='ignore'):
        inside = np.all((local >= low) & (local <= high), axis=1)
    if geometry_test and inside.any():
        mesh = _triangles(target.shape.geometry)
        if mesh is None:
            return None
        chosen = np.nonzero(inside)[0]
        inside[chosen] = pg.inside_mesh(local[chosen], mesh[0])
    if not inside.any():
        return None
    return picking.Pick(target.shape,
                        _centre_distance(points.min(axis=0), points.max(axis=0), target, bounds),
                        points=points[inside])


def _volume_pick(target: Target, volume: pg.Volume, geometry_test: bool) -> Optional[picking.Pick]:
    bounds = _bounds(target.shape.geometry)
    if bounds is None:
        return None
    reached = pg.boxes_overlap(pg.Box.from_bounds(volume.low, volume.high, np.identity(4)),
                               pg.Box.from_bounds(bounds[0], bounds[1], target.matrix))
    if reached and geometry_test:
        mesh = _triangles(target.shape.geometry)
        reached = mesh is not None and pg.target_meets(
            volume, _placed(mesh[0].reshape(-1, 3), target.matrix).reshape(-1, 3, 3))
    if not reached:
        return None
    return picking.Pick(target.shape, _centre_distance(volume.low, volume.high, target, bounds))


def picks_for(path: Any, nodePaths: Mapping[Any, Sequence[Any]]) -> list[picking.Pick]:
    """What the sensor at the end of `path` picks this frame, in the order found"""
    sensor = path[-1]
    geometry = sensor.pickingGeometry
    if not geometry:
        return []
    geometry_test = str(sensor.intersectionType) == 'GEOMETRY'
    try:
        local = np.linalg.inv(_matrix(path))
    except np.linalg.LinAlgError:
        return []
    if isinstance(sensor, picking.LinePickSensor):
        segments = line_segments(geometry)
        if segments is None:
            return []
        test: Callable[[Target], Optional[picking.Pick]] = functools.partial(
            _line_pick, segments=segments, geometry_test=geometry_test)
    elif isinstance(sensor, picking.PointPickSensor):
        points = points_of(geometry)
        if points is None:
            return []
        test = functools.partial(_point_pick, points=points, geometry_test=geometry_test)
    else:
        volume = (primitive_volume(geometry) if isinstance(sensor, picking.PrimitivePickSensor)
                  else _mesh_volume(geometry))
        if volume is None:
            return []
        test = functools.partial(_volume_pick, volume=volume, geometry_test=geometry_test)
    found = []
    for target in targets(sensor, nodePaths, local):
        pick = test(target)
        if pick is not None:
            found.append(pick)
    return found


def sense(paths: Iterable[Any], nodePaths: Mapping[Any, Sequence[Any]]) -> None:
    """Tell each pick sensor at the end of `paths` what it picks this frame

    nodePaths -- the paths the scene has to each node, for the pick targets
    """
    for path in paths:
        sensor = path[-1]
        sensor.observe(picks_for(path, nodePaths) if sensor.senses() else [])
