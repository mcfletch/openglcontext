"""Swept geometry: lathes, screws, spirals, tubes and VRML97's Extrusion.

Each node here holds the parameters of a shape and builds its vertex arrays with
:mod:`opengl_extrusions`, a NumPy geometry generator with no OpenGL in it. What comes
back is an ordinary indexed triangle mesh, so these draw through the same path as
every other piece of geometry in the scene: **core profile and compatibility
profile alike**, lit, shadowed, textured, pickable, depth-sorted, and eligible
for the pass-level instancing batcher.

The generated mesh is cached on the scenegraph cache and rebuilt when a field it
depends on changes, so editing ``sides`` or ``totalAngle`` at runtime costs one
regeneration rather than one per frame.

Node types
----------

``Lathe``
    A contour swept around the z axis with its plane staying radial, so the
    contour stays upright however steeply the sweep climbs. Screw threads,
    spiral ramps, washers.
``Spiral``
    A contour swept along the helix itself, its plane square to the path.
    Springs, coiled wire, handrails.
``Screw``
    A contour extruded along z while turning. Drill bits, twisted columns.
``PolyCylinder`` / ``PolyCone``
    A round tube along a path, of constant or of per-point radius. Pipes,
    cables, rails, branches.
``Extrusion``
    VRML97's own node, with the fields that specification gives it.

Contours for ``Lathe``, ``Spiral`` and ``Screw`` are read as ``(x, y)`` pairs:
for the rotational sweeps x is distance out from the axis and y is height, and
for ``Screw`` they are the cross-section's own axes.

See ``docs/extrusions.html``.
"""
from __future__ import annotations

import logging
from math import pi
from typing import Any, List, Optional

import numpy as np
from vrml import field, node, protofunctions
from vrml.vrml97 import nodetypes

from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.frommesh import mesh_from_primitive

log = logging.getLogger(__name__)

#: Fields every swept node shares.
_SHARED_DOC = """
    normals -- how the surface is shaded: 'facet' for flat faces, 'edge' for
        smooth around the contour, 'path_edge' for smooth both ways.
    texture -- 'normalized' for 0..1 both ways, 'arc_length' for model units,
        or '' for no texture coordinates.
"""


class SweptGeometry(nodetypes.Geometry, node.Node):
    """What the swept geometry nodes have in common.

    Subclasses declare their own fields and implement :meth:`build`, returning a
    mesh from :mod:`opengl_extrusions`. Everything else -- caching, bounding
    volumes, drawing, instancing -- is handled here.
    """

    normals = field.newField('normals', 'SFString', 1, 'edge')
    texture = field.newField('texture', 'SFString', 1, 'normalized')
    solid = field.newField('solid', 'SFBool', 1, True)

    #: Field names a change to which invalidates the generated geometry.
    #: Subclasses extend this with their own.
    depend_fields: tuple = ('normals', 'texture', 'solid')

    def build(self) -> Any:
        """Generate the mesh. Implemented by each subclass."""
        raise NotImplementedError('%s must implement build()' % type(self).__name__)

    def _texture_mode(self) -> Optional[str]:
        value = (self.texture or '').strip().lower()
        return value or None

    def _normal_mode(self) -> str:
        value = (self.normals or '').strip().lower() or 'edge'
        if value not in ('facet', 'edge', 'path_edge'):
            log.warning('%s: unknown normals mode %r; using "edge"',
                        type(self).__name__, self.normals)
            return 'edge'
        return value

    # -- the generated mesh, cached ---------------------------------------

    def geometry(self, mode: Any = None) -> Any:
        """The generated :class:`PBRMesh`, built once and kept.

        Held on the render pass's cache and dropped when any field the shape
        depends on changes, so a slider driving ``sides`` rebuilds exactly once
        per move rather than once per frame.
        """
        cache = getattr(mode, 'cache', None)
        built = cache.getData(self, key='swept') if cache is not None else None
        if built is not None:
            return built
        try:
            generated = self.build()
        except Exception:
            log.warning('%s could not be generated from its fields',
                        type(self).__name__, exc_info=True)
            return None
        merged = generated.merged()
        if not merged.primitives or merged.primitives[0].vertex_count == 0:
            return None
        built = mesh_from_primitive(merged.primitives[0], solid=bool(self.solid))
        if cache is not None:
            holder = cache.holder(self, built, key='swept')
            for name in self.depend_fields:
                holder.depend(self, protofunctions.getField(self, name))
        return built

    def render(self, visible: int = 1, lit: int = 1, textured: int = 1,
               transparent: int = 0, mode: Any = None) -> int:
        """Draw the generated mesh, in whichever profile is in use.

        A shader pass hands the mesh to :class:`PBRMesh`, which is what the glTF
        loader builds too. A compatibility pass draws the same arrays through the
        fixed-function pipeline instead: the geometry is data, so it can be drawn
        either way, and a node that only worked under one of them would leave
        every scene using the default profile empty.
        """
        built = self.geometry(mode)
        if built is None:
            return 0
        if getattr(mode, 'shader_mode', False):
            return built.render(visible=visible, lit=lit, textured=textured,
                                transparent=transparent, mode=mode)
        return self._render_legacy(built, lit=lit, textured=textured)

    def _render_legacy(self, built: Any, lit: int = 1, textured: int = 1) -> int:
        """Fixed-function draw of the generated arrays, through vertex buffers.

        The buffers are built once and hung on the mesh, so a compatibility
        profile pays the upload once rather than streaming the arrays every
        frame.
        """
        from OpenGL.GL import (
            GL_ARRAY_BUFFER, GL_ELEMENT_ARRAY_BUFFER, GL_FLOAT, GL_NORMAL_ARRAY,
            GL_TEXTURE_COORD_ARRAY, GL_TRIANGLES, GL_UNSIGNED_INT,
            GL_VERTEX_ARRAY, glDisableClientState, glDrawElements,
            glEnableClientState, glNormalPointer, glTexCoordPointer,
            glVertexPointer,
        )
        from OpenGL.arrays import vbo

        buffers = getattr(built, '_legacy_buffers', None)
        if buffers is None:
            buffers = {
                'positions': vbo.VBO(built.positions, target=GL_ARRAY_BUFFER),
                'indices': vbo.VBO(built.indices, target=GL_ELEMENT_ARRAY_BUFFER),
            }
            for name in ('normals', 'texcoords'):
                array = getattr(built, name, None)
                if array is not None and len(array):
                    buffers[name] = vbo.VBO(array, target=GL_ARRAY_BUFFER)
            built._legacy_buffers = buffers

        normals = buffers.get('normals') if lit else None
        texcoords = buffers.get('texcoords') if textured else None
        buffers['positions'].bind()
        try:
            glEnableClientState(GL_VERTEX_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, buffers['positions'])
            if normals is not None:
                normals.bind()
                glEnableClientState(GL_NORMAL_ARRAY)
                glNormalPointer(GL_FLOAT, 0, normals)
            if texcoords is not None:
                texcoords.bind()
                glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                glTexCoordPointer(2, GL_FLOAT, 0, texcoords)
            buffers['indices'].bind()
            try:
                glDrawElements(GL_TRIANGLES, len(built.indices),
                               GL_UNSIGNED_INT, buffers['indices'])
            finally:
                buffers['indices'].unbind()
        finally:
            glDisableClientState(GL_VERTEX_ARRAY)
            if normals is not None:
                glDisableClientState(GL_NORMAL_ARRAY)
                normals.unbind()
            if texcoords is not None:
                glDisableClientState(GL_TEXTURE_COORD_ARRAY)
                texcoords.unbind()
            buffers['positions'].unbind()
        return 1

    def boundingVolume(self, mode: Any = None) -> Any:
        """The generated mesh's own bounding volume."""
        built = self.geometry(mode)
        if built is None:
            return boundingvolume.AABoundingBox(size=(0, 0, 0), center=(0, 0, 0))
        return built.boundingVolume(mode)


class Lathe(SweptGeometry):
    """A contour swept around the z axis, its plane staying radial.

    contour -- (N, 2) points in the r-z plane: x out from the axis, y up
    normals2d -- optional outward normals for the contour
    startRadius -- distance from the axis where the sweep begins
    deltaRadius -- change in that radius per full turn
    startZ -- height where the sweep begins
    deltaZ -- rise per full turn
    startAngle -- where the sweep begins, in radians
    totalAngle -- how far it sweeps, in radians
    sides -- facets per full turn
    caps -- close the two cut ends of a partial sweep
    """

    contour = field.newField('contour', 'MFVec2f', 1, list)
    normals2d = field.newField('normals2d', 'MFVec2f', 1, list)
    startRadius = field.newField('startRadius', 'SFFloat', 1, 1.0)
    deltaRadius = field.newField('deltaRadius', 'SFFloat', 1, 0.0)
    startZ = field.newField('startZ', 'SFFloat', 1, 0.0)
    deltaZ = field.newField('deltaZ', 'SFFloat', 1, 0.0)
    startAngle = field.newField('startAngle', 'SFFloat', 1, 0.0)
    totalAngle = field.newField('totalAngle', 'SFFloat', 1, 2 * pi)
    sides = field.newField('sides', 'SFInt32', 1, 32)
    caps = field.newField('caps', 'SFBool', 1, True)

    depend_fields = SweptGeometry.depend_fields + (
        'contour', 'normals2d', 'startRadius', 'deltaRadius', 'startZ', 'deltaZ',
        'startAngle', 'totalAngle', 'sides', 'caps')

    def build(self) -> Any:
        from opengl_extrusions import lathe
        return lathe(_contour(self.contour), start_radius=float(self.startRadius),
                     delta_radius=float(self.deltaRadius), start_z=float(self.startZ),
                     delta_z=float(self.deltaZ), start_angle=float(self.startAngle),
                     sweep_angle=float(self.totalAngle), sides=int(self.sides),
                     contour_normals_2d=_optional(self.normals2d),
                     caps=bool(self.caps), normals=self._normal_mode(),
                     texture=self._texture_mode())


class Spiral(SweptGeometry):
    """A contour swept along a helix, its plane square to the path.

    The fields are :class:`Lathe`'s. The difference is that the contour tilts
    with the climb instead of staying upright, which is what a coiled length of
    something does.
    """

    contour = field.newField('contour', 'MFVec2f', 1, list)
    normals2d = field.newField('normals2d', 'MFVec2f', 1, list)
    startRadius = field.newField('startRadius', 'SFFloat', 1, 1.0)
    deltaRadius = field.newField('deltaRadius', 'SFFloat', 1, 0.0)
    startZ = field.newField('startZ', 'SFFloat', 1, 0.0)
    deltaZ = field.newField('deltaZ', 'SFFloat', 1, 0.0)
    startAngle = field.newField('startAngle', 'SFFloat', 1, 0.0)
    totalAngle = field.newField('totalAngle', 'SFFloat', 1, 2 * pi)
    sides = field.newField('sides', 'SFInt32', 1, 32)
    caps = field.newField('caps', 'SFBool', 1, True)

    depend_fields = SweptGeometry.depend_fields + (
        'contour', 'normals2d', 'startRadius', 'deltaRadius', 'startZ', 'deltaZ',
        'startAngle', 'totalAngle', 'sides', 'caps')

    def build(self) -> Any:
        from opengl_extrusions import spiral
        return spiral(_contour(self.contour), start_radius=float(self.startRadius),
                      delta_radius=float(self.deltaRadius), start_z=float(self.startZ),
                      delta_z=float(self.deltaZ), start_angle=float(self.startAngle),
                      sweep_angle=float(self.totalAngle), sides=int(self.sides),
                      contour_normals_2d=_optional(self.normals2d),
                      caps=bool(self.caps), normals=self._normal_mode(),
                      texture=self._texture_mode())


class Screw(SweptGeometry):
    """A contour extruded along the z axis while turning.

    contour -- (N, 2) cross-section
    startZ / endZ -- where the extrusion begins and ends
    totalAngle -- total rotation from one end to the other, in radians
    steps -- how many rings to place; 0 chooses enough for a smooth twist
    """

    contour = field.newField('contour', 'MFVec2f', 1, list)
    normals2d = field.newField('normals2d', 'MFVec2f', 1, list)
    startZ = field.newField('startZ', 'SFFloat', 1, -1.0)
    endZ = field.newField('endZ', 'SFFloat', 1, 1.0)
    totalAngle = field.newField('totalAngle', 'SFFloat', 1, pi)
    steps = field.newField('steps', 'SFInt32', 1, 0)
    caps = field.newField('caps', 'SFBool', 1, True)

    depend_fields = SweptGeometry.depend_fields + (
        'contour', 'normals2d', 'startZ', 'endZ', 'totalAngle', 'steps', 'caps')

    def build(self) -> Any:
        from opengl_extrusions import screw
        return screw(_contour(self.contour), start_z=float(self.startZ),
                     end_z=float(self.endZ), twist=float(self.totalAngle),
                     steps=int(self.steps) or None,
                     contour_normals_2d=_optional(self.normals2d),
                     caps=bool(self.caps), normals=self._normal_mode(),
                     texture=self._texture_mode())


class PolyCylinder(SweptGeometry):
    """A round tube of constant radius along a path.

    path -- (M, 3) points to run along
    radius -- the tube's radius
    sides -- facets around the tube
    join -- how corners are made: 'angle' (a mitre), 'raw', 'cut' or 'round'
    caps -- close the two ends
    """

    path = field.newField('path', 'MFVec3f', 1, list)
    radius = field.newField('radius', 'SFFloat', 1, 1.0)
    sides = field.newField('sides', 'SFInt32', 1, 20)
    join = field.newField('join', 'SFString', 1, 'angle')
    miterLimit = field.newField('miterLimit', 'SFFloat', 1, 4.0)
    roundSegments = field.newField('roundSegments', 'SFInt32', 1, 4)
    caps = field.newField('caps', 'SFBool', 1, True)
    up = field.newField('up', 'SFVec3f', 1, (0.0, 1.0, 0.0))
    frames = field.newField('frames', 'SFString', 1, 'rmf')

    depend_fields = SweptGeometry.depend_fields + (
        'path', 'radius', 'sides', 'join', 'miterLimit', 'roundSegments',
        'caps', 'up', 'frames')

    def build(self) -> Any:
        from opengl_extrusions import polycylinder
        return polycylinder(_path(self.path), radius=float(self.radius),
                            sides=int(self.sides), join=str(self.join),
                            miter_limit=float(self.miterLimit),
                            round_segments=int(self.roundSegments),
                            caps=bool(self.caps), up=tuple(self.up),
                            frames=str(self.frames), normals=self._normal_mode(),
                            texture=self._texture_mode())


class PolyCone(SweptGeometry):
    """A round tube whose radius is given separately at every path point.

    path -- (M, 3) points to run along
    radii -- one radius per path point; between two points it changes linearly
    """

    path = field.newField('path', 'MFVec3f', 1, list)
    radii = field.newField('radii', 'MFFloat', 1, list)
    sides = field.newField('sides', 'SFInt32', 1, 20)
    join = field.newField('join', 'SFString', 1, 'angle')
    miterLimit = field.newField('miterLimit', 'SFFloat', 1, 4.0)
    roundSegments = field.newField('roundSegments', 'SFInt32', 1, 4)
    caps = field.newField('caps', 'SFBool', 1, True)
    up = field.newField('up', 'SFVec3f', 1, (0.0, 1.0, 0.0))
    frames = field.newField('frames', 'SFString', 1, 'rmf')

    depend_fields = SweptGeometry.depend_fields + (
        'path', 'radii', 'sides', 'join', 'miterLimit', 'roundSegments',
        'caps', 'up', 'frames')

    def build(self) -> Any:
        from opengl_extrusions import polycone
        points = _path(self.path)
        radii = np.asarray(self.radii, dtype='d').ravel()
        if len(radii) != len(points):
            raise ValueError('PolyCone needs one radius per path point: %d radii '
                             'for %d points' % (len(radii), len(points)))
        return polycone(points, radii, sides=int(self.sides), join=str(self.join),
                        miter_limit=float(self.miterLimit),
                        round_segments=int(self.roundSegments),
                        caps=bool(self.caps), up=tuple(self.up),
                        frames=str(self.frames), normals=self._normal_mode(),
                        texture=self._texture_mode())


class Extrusion(SweptGeometry):
    """VRML97's ``Extrusion``: a cross-section swept along a spine.

    The fields are the specification's, with its own defaults: a unit square
    swept one unit along +y. A ``crossSection`` or ``spine`` whose last point
    repeats its first is closed, and the surface has no seam there.

    Reference: ISO/IEC 14772-1:1997 clause 6.23.
    """

    PROTO = 'Extrusion'

    crossSection = field.newField(
        'crossSection', 'MFVec2f', 0,
        [[1.0, 1.0], [1.0, -1.0], [-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0]])
    spine = field.newField('spine', 'MFVec3f', 0, [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    scale = field.newField('scale', 'MFVec2f', 0, [[1.0, 1.0]])
    orientation = field.newField('orientation', 'MFRotation', 0, [[0.0, 0.0, 1.0, 0.0]])
    beginCap = field.newField('beginCap', 'SFBool', 0, 1)
    endCap = field.newField('endCap', 'SFBool', 0, 1)
    ccw = field.newField('ccw', 'SFBool', 0, 1)
    convex = field.newField('convex', 'SFBool', 0, 1)
    creaseAngle = field.newField('creaseAngle', 'SFFloat', 0, 0.0)

    #: Events the specification declares for the node.
    set_crossSection = field.newEvent('set_crossSection', 'MFVec2f', 0)
    set_orientation = field.newEvent('set_orientation', 'MFRotation', 0)
    set_scale = field.newEvent('set_scale', 'MFVec2f', 0)
    set_spine = field.newEvent('set_spine', 'MFVec3f', 0)

    depend_fields = SweptGeometry.depend_fields + (
        'crossSection', 'spine', 'scale', 'orientation', 'beginCap', 'endCap',
        'ccw', 'creaseAngle')

    def build(self) -> Any:
        from opengl_extrusions import vrml97_extrusion
        return vrml97_extrusion(
            cross_section=np.asarray(self.crossSection, dtype='d'),
            spine=np.asarray(self.spine, dtype='d'),
            scale=np.asarray(self.scale, dtype='d'),
            orientation=np.asarray(self.orientation, dtype='d'),
            begin_cap=bool(self.beginCap), end_cap=bool(self.endCap),
            ccw=bool(self.ccw), crease_angle=float(self.creaseAngle),
            texture=self._texture_mode())


def _contour(value: Any) -> np.ndarray:
    """A contour field as an ``(N, 2)`` array, with a clear complaint if it is not."""
    points = np.asarray(value, dtype='d')
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
        raise ValueError('contour needs at least 3 (x, y) points, got %r'
                         % (points.shape,))
    return points


def _path(value: Any) -> np.ndarray:
    """A path field as an ``(M, 3)`` array."""
    points = np.asarray(value, dtype='d')
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2:
        raise ValueError('path needs at least 2 (x, y, z) points, got %r'
                         % (points.shape,))
    return points


def _optional(value: Any) -> Optional[np.ndarray]:
    """An optional MFVec2f field: empty means "work it out"."""
    if value is None or len(value) == 0:
        return None
    return np.asarray(value, dtype='d')


def _unused(value: List) -> None:                # pragma: no cover
    """Kept out of the public surface."""
