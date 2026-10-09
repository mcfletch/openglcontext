"""X3D's Geospatial component: nodes placed on the Earth

The coordinates and frames are :mod:`vrml.x3d.geospatial`'s, worked out in
double precision; the engine composes transforms and the camera in double
precision too, so a node millions of metres from the origin is drawn where it
is (`passes._flat` converts to single precision only relative to the camera).

- :class:`GeoLocation` - its children in the frame at `geoCoords`: +Y up
  along the ellipsoid's normal, +X east, -Z north.
- :class:`GeoTransform` - its children transformed by translation, rotation,
  scale and scaleOrientation about the frame at `geoCenter`.
- :class:`GeoCoordinate` - points in a `geoSystem`, which geometry reads as
  the scene's points (:mod:`OpenGLContext.scenegraph.coordinates`).
- :class:`GeoViewpoint` - a viewpoint at `position`, turned by `orientation`
  from the frame there, navigated faster the higher it is.
- :class:`GeoLOD` - its root (`rootNode` and `rootUrl`) from afar, and the
  four scenes its `child1Url` to `child4Url` name within `range` of `center`.
- :class:`GeoElevationGrid` - heights along the ellipsoid's normal over a
  grid stepping `xSpacing` east and `zSpacing` north from `geoGridOrigin`.

Triangle geometry on GeoCoordinate, and GeoElevationGrid, is built relative
to the centre of its own points and placed by it in double precision
(:meth:`~OpenGLContext.scenegraph.meshgeometry.MeshDrawn.meshOrigin`), and a
GeoLocation or GeoTransform places its children exactly, with or without a
GeoOrigin. Lines and points on GeoCoordinate are single precision in the
scene's coordinates (about half a metre at the Earth's radius with no
GeoOrigin).

A node's `geoOrigin` (GeoOrigin) is subtracted from its geocentric
coordinates, and turned so its up is +Y where its `rotateYUp` is true.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from vrml import cache, protofunctions
from vrml.vrml97 import transformmatrix
from vrml.x3d import geospatial
from vrml.x3d import nodes as x3d

from OpenGLContext import quaternion
from OpenGLContext.scenegraph import lod
from OpenGLContext.scenegraph.framed import Framed
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.inline import Inline
from OpenGLContext.scenegraph.meshgeometry import GridDrawn
from OpenGLContext.scenegraph.viewpoint import Perspective

__all__ = ['GeoCoordinate', 'GeoElevationGrid', 'GeoLOD', 'GeoLocation', 'GeoTransform', 'GeoTransforming',
           'GeoViewpoint',
           'depend_on_origin', 'origin_fields']

#: The fields of a GeoOrigin a geospatial node's coordinates depend on.
ORIGIN_FIELDS = ('geoCoords', 'geoSystem', 'rotateYUp')


def origin_fields(node: Any) -> list[tuple[Any, str]]:
    """(node, field) for `node`'s geoSystem and geoOrigin, and that origin's fields"""
    found: list[tuple[Any, str]] = [(node, 'geoSystem'), (node, 'geoOrigin')]
    origin = getattr(node, 'geoOrigin', None)
    if origin:
        found += [(origin, name) for name in ORIGIN_FIELDS]
    return found


def depend_on_origin(holder: Any, node: Any) -> None:
    """Make `holder` depend on `node`'s geoSystem and geoOrigin, and that origin's fields"""
    for source, name in origin_fields(node):
        holder.depend(source, protofunctions.getField(source, name))


class GeoTransforming(Framed):
    """A group whose frame is worked out from geospatial fields, in double precision

    A subclass gives :meth:`geoMatrix` and the fields it reads in
    :attr:`MATRIX_FIELDS`; the frame also follows the node's geoSystem and
    geoOrigin.
    """

    FRAME_KEY = 'geo-local-matrices'

    def geoMatrix(self) -> np.ndarray:
        """The row-vector 4x4 frame the children are drawn in"""
        raise NotImplementedError('%s must give its frame' % type(self).__name__)

    def frameMatrix(self) -> np.ndarray:
        return self.geoMatrix()

    def frameDependencies(self) -> list[tuple[Any, str]]:
        return super().frameDependencies() + origin_fields(self)


class GeoLocation(GeoTransforming, x3d.GeoLocation):
    """X3D's GeoLocation: its children in the frame at `geoCoords`

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/geodata.html#GeoLocation
    """

    MATRIX_FIELDS = ('geoCoords',)

    def geoMatrix(self) -> np.ndarray:
        return geospatial.scene_matrix(self, self.geoCoords)


class GeoTransform(GeoTransforming, x3d.GeoTransform):
    """X3D's GeoTransform: translation, rotation, scale and scaleOrientation about
    the frame at `geoCenter`

    The children are in the GeoTransform's parent's coordinates; they are
    taken into the frame at `geoCenter`, transformed, and brought back.

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/geodata.html#GeoTransform
    """

    MATRIX_FIELDS = ('geoCenter', 'translation', 'rotation', 'scale', 'scaleOrientation')

    def geoMatrix(self) -> np.ndarray:
        frame = geospatial.scene_matrix(self, self.geoCenter)
        local = transformmatrix.transformMatrix(
            translation=self.translation, rotation=self.rotation, scale=self.scale,
            scaleOrientation=self.scaleOrientation)
        local = np.eye(4) if local is None else np.asarray(local, dtype=np.float64)
        found: np.ndarray = np.linalg.inv(frame) @ local @ frame
        return found


class GeoCoordinate(x3d.GeoCoordinate):
    """X3D's GeoCoordinate: points in its `geoSystem`

    Geometry reads them as the scene's points, geocentric metres less the
    GeoOrigin's, in double precision, kept until `point`, `geoSystem`,
    `geoOrigin` or a field of that origin is set.

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/geodata.html#GeoCoordinate
    """

    _KEY = 'geo-scene-points'

    def pointFields(self) -> list[tuple[Any, str]]:
        """(node, field name) for each field the scene's points are worked out from"""
        return [(self, 'point')] + origin_fields(self)

    def scenePoints(self) -> np.ndarray:
        """The points in the scene's coordinates, (N, 3) metres"""
        found = cache.CACHE.getData(self, self._KEY)
        if found is None:
            values = np.asarray(self.point, dtype=np.float64).reshape(-1, 3)
            found = (geospatial.scene_points(self, values) if len(values)
                     else np.zeros((0, 3), np.float64))
            holder = cache.CACHE.holder(self, found, self._KEY)
            for source, name in self.pointFields():
                holder.depend(source, protofunctions.getField(source, name))
        result: np.ndarray = found
        return result


class GeoElevationGrid(GridDrawn, x3d.GeoElevationGrid):
    """X3D's GeoElevationGrid: heights over a grid in its `geoSystem`

    The grid steps `xSpacing` along the longitude or easting and `zSpacing`
    along the latitude or northing from `geoGridOrigin`; each height, times
    `yScale`, is along the ellipsoid's normal. Colours, normals and texture
    coordinates are as on an ElevationGrid.

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/geodata.html#GeoElevationGrid
    """

    #: Rows run north, which is -Z in the local frame.
    MIRRORED = True

    def dependOn(self, holder: Any) -> None:
        """Make `holder` depend on every field the mesh is built from, and the origin's"""
        super().dependOn(holder)
        depend_on_origin(holder, self)

    def gridPoints(self, across: int, deep: int) -> np.ndarray:
        """The grid's points in the scene's coordinates, (across * deep, 3)"""
        found = geospatial.grid_coordinates(
            geospatial.node_system(self), self.geoGridOrigin, across, deep,
            float(self.xSpacing), float(self.zSpacing), self.height, float(self.yScale))
        return geospatial.scene_points(self, found)


class GeoViewpoint(Perspective, x3d.GeoViewpoint):
    """X3D's GeoViewpoint: a perspective view at `position` in its `geoSystem`

    `orientation` turns the view from the frame at `position`, which looks
    north with the ellipsoid's normal up. Navigation is `speedFactor` times
    faster at ten metres above the ellipsoid than at its surface, and faster
    again in proportion to the viewer's height above that.

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/geodata.html#GeoViewpoint
    """

    def placement(self) -> tuple[np.ndarray, quaternion.Quaternion]:
        """(position, orientation) in the scene's coordinates, in double precision"""
        frame = geospatial.scene_matrix(self, self.position)
        turned = quaternion.fromMatrix(frame) * quaternion.fromXYZR(*self.orientation)
        return frame[3, :3], turned

    def localCentre(self) -> np.ndarray:
        """`centerOfRotation` in the scene's coordinates"""
        centre: np.ndarray = geospatial.scene_points(self, self.centerOfRotation)[0]
        return centre

    def speedScale(self, position: Any) -> float:
        """`speedFactor` times one more than a tenth of the height at `position`, in metres"""
        height = float(geospatial.elevations(self, np.asarray(position, 'd')[:3])[0])
        return (max(height, 0.0) + 10.0) / 10.0 * float(self.speedFactor)


class GeoLOD(lod.Levelled, x3d.GeoLOD):
    """X3D's GeoLOD: a root from afar, and four scenes within `range` of `center`

    Level 0 is the scenes `child1Url` to `child4Url` name, each read as an
    `Inline` reads its url the first time the viewer comes within `range`
    metres of `center`; level 1 is `rootNode` and the scene `rootUrl` names.
    `level_changed` sends 1 as the children are drawn and 0 as the root is;
    `children` sends the children's Inline nodes, and nothing while the root
    is drawn.

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/geodata.html#GeoLOD
    """

    CHILD_URLS = ('child1Url', 'child2Url', 'child3Url', 'child4Url')

    def _inline(self, url: Any) -> Inline:
        """An Inline reading `url` against this node's document"""
        found = Inline()
        root = protofunctions.root(self)
        if root:
            protofunctions.root(found, root)
        found.url = list(url)
        return found

    def _groups(self) -> tuple[Group, Group]:
        """(children, root): the groups the two levels are drawn as"""
        inputs = (list(self.rootNode), list(self.rootUrl))
        held = self.__dict__.get('_levels')
        if held is None or held[0] != inputs:
            root = Group(children=list(self.rootNode))
            if len(self.rootUrl):
                root.children = list(root.children) + [self._inline(self.rootUrl)]
            near = held[1][0] if held is not None else Group()
            held = (inputs, (near, root))
            self.__dict__['_levels'] = held
        groups: tuple[Group, Group] = held[1]
        return groups

    def levelNodes(self) -> list[Group]:
        """The children's group, then the root's"""
        return list(self._groups())

    def thresholds(self) -> list[float]:
        """`range`: within it the children are drawn"""
        return [float(self.range)]

    def distanceCentre(self) -> np.ndarray:
        """`center` in the scene's coordinates, kept while its inputs are"""
        origin = self.geoOrigin
        inputs = (tuple(self.center), tuple(self.geoSystem),
                  (tuple(origin.geoCoords), tuple(origin.geoSystem), bool(origin.rotateYUp))
                  if origin else None)
        held = self.__dict__.get('_centre')
        if held is None or held[0] != inputs:
            held = (inputs, geospatial.scene_points(self, self.center)[0])
            self.__dict__['_centre'] = held
        centre: np.ndarray = held[1]
        return centre

    def levelFields(self) -> list[tuple[Any, str]]:
        """(node, field name) for each field the levels and thresholds are read from"""
        return [(self, 'range'), (self, 'rootNode'), (self, 'rootUrl'),
                *[(self, name) for name in self.CHILD_URLS]]

    def show(self, level: int) -> bool:
        """Draw level `level` from now on, reading the children the first time; True where that is a change"""
        near, _root = self._groups()
        if level == 0 and not near.children:
            near.children = [self._inline(urls) for urls in
                             (getattr(self, name) for name in self.CHILD_URLS) if len(urls)]
        first = not self._shown
        changed = super().show(level)
        if changed or first:
            self.level_changed = 1 if level == 0 else 0
            if level == 0 or self.__dict__.get('children'):
                self.children = list(near.children) if level == 0 else []
        return changed


for _name in ('range', 'center', 'rootNode', 'rootUrl', 'geoSystem', 'geoOrigin'):
    lod.watch_level_field(x3d.GeoLOD, _name)
for _name in ORIGIN_FIELDS:
    lod.watch_level_field(x3d.GeoOrigin, _name)
