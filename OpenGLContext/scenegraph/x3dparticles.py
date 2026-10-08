"""X3D's ParticleSystems component (ISO/IEC 19775-1, 40) on the engine's particles

`ParticleSystem` simulates through
:mod:`~OpenGLContext.scenegraph.particlesim` and draws through
:class:`~OpenGLContext.scenegraph.particles.ParticleRenderer`, or, for a
`geometryType` of ``GEOMETRY``, as a shape placed once per particle, which the
render pass batches into one instanced draw. Each emitter answers
:meth:`X3DEmitter.particleSource` and each physics model
:meth:`X3DPhysicsModel.particleModel`; the engine's
:class:`~OpenGLContext.scenegraph.particles.ParticleEmitter` takes the same
nodes in its ``source`` and ``physics`` fields.

A system steps once a frame on the engine's clock through each context it is
bound to (:class:`~OpenGLContext.scenegraph.x3druntime.Ticked`), while it is
enabled and has particles alive or is still making them. Its particles live in
its own coordinate system, so a transform above it carries the particles it
has already made.

How the specification's open points are read:

- A system makes ``maxParticles / particleLifetime`` particles a second, so a
  full system holds about ``maxParticles``; an `ExplosionEmitter` makes all
  ``maxParticles`` at once when the system starts creating, and again each
  time creation is switched back on.
- ``colorKey`` and ``texCoordKey`` are a particle's age in seconds. Colours are
  interpolated between keys and texture-coordinate frames are stepped.
- A force on a particle of no mass is taken as an acceleration, so the default
  `ForcePhysicsModel` is the Earth's gravity whatever the emitter's mass.
- Particles drawn as sprites, quads, triangles, lines or points are unlit: the
  colour ramp where there is one, the material's colour otherwise (its
  emissive colour where it has one, its diffuse colour where not), times the
  texture. A ``GEOMETRY`` system is lit as any shape is.
- `VolumeEmitter`'s ``internal`` of FALSE starts particles on the volume's
  boundary rather than inside it.
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Iterator
from typing import Any, Optional

import numpy as np
from pydispatch import dispatcher
from vrml import cache, protofunctions
from vrml.x3d import nodes as x3d

from OpenGLContext.events import systemtime
from OpenGLContext.scenegraph import boundingvolume, drawproperties, meshdata
from OpenGLContext.scenegraph.instancedgl import GLLayer
from OpenGLContext.scenegraph.particles import ParticleLook, ParticleRenderer, models_of, ramp_colors
from OpenGLContext.scenegraph.particlesim import (
    MIN_LIFETIME, Bounds, ColorRamp, ConeSource, ConstantForce, Emission, FrameRamp,
    ParticleModel, ParticlePool, ParticleSource, PointSource, PolylineSource, SphereSource,
    StepClock, SurfaceSource, VolumeSource, Wind, launch,
)
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.x3druntime import Ticked

__all__ = [
    'BoundedPhysicsModel', 'ConeEmitter', 'ExplosionEmitter', 'ForcePhysicsModel',
    'ParticleSystem', 'PointEmitter', 'PolylineEmitter', 'SurfaceEmitter', 'VolumeEmitter',
    'WindPhysicsModel', 'X3DEmitter', 'X3DPhysicsModel', 'build_source', 'geometry_triangles',
]

log = logging.getLogger(__name__)

#: Where an emitter's source and a bounding model's simulation model are kept
#: in vrml's cache.
SOURCE_KEY = 'particle-source'
MODEL_KEY = 'particle-model'

#: What each `geometryType` other than GEOMETRY is drawn as, a
#: :data:`~OpenGLContext.scenegraph.particles.SHAPES` name.
SHAPE_OF = {'LINE': 'line', 'POINT': 'point', 'QUAD': 'quad', 'SPRITE': 'sprite',
            'TRIANGLE': 'quad'}


# ---------------------------------------------------------------------------
# Geometry read into arrays, and kept until a field it was read from changes
# ---------------------------------------------------------------------------

def _nodes_under(root: Any) -> Iterator[Any]:
    """``root`` and every node in its node fields, each once"""
    seen: set[int] = set()
    todo = [root]
    while todo:
        current = todo.pop()
        if current is None or id(current) in seen or not hasattr(current, 'PROTO'):
            continue
        seen.add(id(current))
        yield current
        for declared in protofunctions.getFields(current):
            if declared.name.startswith(' ') or declared.typeName() not in ('SFNode', 'MFNode'):
                continue
            value = getattr(current, declared.name, None)
            if declared.typeName() == 'SFNode':
                todo.append(value)
            else:
                todo.extend(value or ())


def _depend_on_tree(holder: Any, root: Any) -> None:
    """Make ``holder`` depend on every field of ``root`` and of the nodes under it"""
    for found in _nodes_under(root):
        for declared in protofunctions.getFields(found):
            if not declared.name.startswith(' '):
                holder.depend(found, declared)


def _kept(node: Any, key: str, build: Callable[[Any], Any]) -> Any:
    """``build(node)``, kept in vrml's cache until a field it read is set"""
    held = cache.CACHE.getData(node, key)
    if held is None:
        held = (build(node),)
        _depend_on_tree(cache.CACHE.holder(node, held, key), node)
    return held[0]


def geometry_triangles(geometry: Any) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """A geometry node's triangles, three corners each, and the normals at them

    Empty for no geometry, or one that draws no triangles (a line set, text).
    """
    found = meshdata.geometry_arrays(geometry) if geometry else None
    if found is None:
        return np.zeros((0, 3, 3), np.float32), None
    positions = found.attributes['POSITION']
    corners = (np.arange((len(positions) // 3) * 3) if found.indices is None
               else np.asarray(found.indices, dtype=np.int64).ravel())
    corners = corners[:(len(corners) // 3) * 3]
    normals = found.attributes.get('NORMAL')
    return (positions[corners].reshape(-1, 3, 3),
            None if normals is None else normals[corners].reshape(-1, 3, 3))


def _runs(index: Any, count: int) -> list[list[int]]:
    """The runs of ``index`` between its -1 entries, each kept to valid vertices

    No index at all is one run through every vertex in order.
    """
    values = [int(value) for value in np.asarray(index if index is not None else (),
                                                 dtype=np.int64).ravel()]
    if not any(value >= 0 for value in values):
        return [list(range(count))] if count else []
    runs: list[list[int]] = [[]]
    for value in values:
        if value < 0:
            runs.append([])
        elif value < count:
            runs[-1].append(value)
    return [run for run in runs if run]


def _points(coord: Any) -> np.ndarray:
    values = getattr(coord, 'point', None) if coord else None
    if values is None or not len(values):
        return np.zeros((0, 3))
    return np.asarray(values, dtype=np.float64).reshape(-1, 3)


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------

class X3DEmitter:
    """An X3D emitter as the engine's simulation reads it

    :meth:`particleSource` answers the
    :class:`~OpenGLContext.scenegraph.particlesim.ParticleSource` its fields
    describe, kept until one of them, or a field of a node under it, is set.
    """

    #: Whether the emitter makes its whole budget at once rather than steadily.
    explodes = False

    def particleSource(self) -> ParticleSource:
        """Where this emitter starts particles and which way it throws them"""
        found: ParticleSource = _kept(self, SOURCE_KEY, build_source)
        return found

    def buildSource(self) -> ParticleSource:
        """The source, read afresh from the fields"""
        raise NotImplementedError


def build_source(emitter: Any) -> ParticleSource:
    """``emitter``'s source, read afresh from its fields"""
    found: ParticleSource = emitter.buildSource()
    return found


class PointEmitter(X3DEmitter, x3d.PointEmitter):
    """X3D's PointEmitter: particles from one point along one direction

    A zero direction throws every way.
    """

    def buildSource(self) -> ParticleSource:
        return PointSource(self.position, self.direction)


class ConeEmitter(X3DEmitter, x3d.ConeEmitter):
    """X3D's ConeEmitter: particles from one point within `angle` of `direction`"""

    def buildSource(self) -> ParticleSource:
        return ConeSource(self.position, self.direction, float(self.angle))


class ExplosionEmitter(X3DEmitter, x3d.ExplosionEmitter):
    """X3D's ExplosionEmitter: the system's whole budget at once, every way from one point"""

    explodes = True

    def buildSource(self) -> ParticleSource:
        return SphereSource(self.position)


class _Reindexed(X3DEmitter):
    """An emitter whose `set_coordIndex` event sets its `coordIndex`"""

    def __init__(self, *args: Any, **named: Any) -> None:
        super().__init__(*args, **named)
        dispatcher.connect(self._onSetIndex, signal=('set', type(self).set_coordIndex),
                           sender=self)

    def _onSetIndex(self, value: Any = None) -> None:
        self.coordIndex = value


class PolylineEmitter(_Reindexed, x3d.PolylineEmitter):
    """X3D's PolylineEmitter: particles along the lines `coordIndex` draws through `coord`

    A point is chosen along the lines by length. A `coordIndex` with no
    vertex in it joins the points in order.
    """

    def buildSource(self) -> ParticleSource:
        points = _points(self.coord)
        segments = [(run[step], run[step + 1]) for run in _runs(self.coordIndex, len(points))
                    for step in range(len(run) - 1)]
        return PolylineSource(points, np.asarray(segments, dtype=np.int64).reshape(-1, 2),
                              self.direction)


class SurfaceEmitter(X3DEmitter, x3d.SurfaceEmitter):
    """X3D's SurfaceEmitter: particles from the surface of `surface`, along its normals

    A point is chosen on the surface by area. A surface that is not `solid`
    throws from either side.
    """

    def buildSource(self) -> ParticleSource:
        triangles, normals = geometry_triangles(self.surface)
        return SurfaceSource(triangles, normals,
                             two_sided=not bool(getattr(self.surface, 'solid', True)))


class VolumeEmitter(_Reindexed, x3d.VolumeEmitter):
    """X3D's VolumeEmitter: particles inside the closed faces `coordIndex` draws through `coord`

    Each face is a polygon, cut into a fan of triangles. An `internal` of
    FALSE starts particles on the faces rather than inside them.
    """

    def buildSource(self) -> ParticleSource:
        points = _points(self.coord)
        index = np.asarray(self.coordIndex if self.coordIndex is not None else (), np.int64)
        runs = _runs(index, len(points)) if (index >= 0).any() else []
        triangles = [points[[run[0], run[step], run[step + 1]]]
                     for run in runs for step in range(1, len(run) - 1)]
        return VolumeSource(np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3),
                            self.direction, internal=bool(self.internal))


@functools.cache
def _still() -> PointEmitter:
    """The emitter of a system that names none: a point at the origin, speed 0"""
    return PointEmitter()


# ---------------------------------------------------------------------------
# Physics models
# ---------------------------------------------------------------------------

class X3DPhysicsModel:
    """An X3D physics model as the engine's simulation reads it

    :meth:`particleModel` answers the
    :class:`~OpenGLContext.scenegraph.particlesim.ParticleModel` acting on
    particles of the emitter's ``mass`` and ``surfaceArea``.
    """

    def particleModel(self, mass: float = 0.0, surfaceArea: float = 0.0,
                      **named: Any) -> Optional[ParticleModel]:
        """The simulation's model of this node"""
        raise NotImplementedError


class ForcePhysicsModel(X3DPhysicsModel, x3d.ForcePhysicsModel):
    """X3D's ForcePhysicsModel: a constant force on every particle"""

    def particleModel(self, mass: float = 0.0, surfaceArea: float = 0.0,
                      **named: Any) -> Optional[ParticleModel]:
        return ConstantForce(self.force, mass=mass)


class WindPhysicsModel(X3DPhysicsModel, x3d.WindPhysicsModel):
    """X3D's WindPhysicsModel: wind on each particle's surface area

    The wind's pressure is 0.64615 times the square of its speed, in pascals.
    """

    def particleModel(self, mass: float = 0.0, surfaceArea: float = 0.0,
                      **named: Any) -> Optional[ParticleModel]:
        return Wind(self.direction, float(self.speed), gustiness=float(self.gustiness),
                    turbulence=float(self.turbulence), area=surfaceArea, mass=mass)


class BoundedPhysicsModel(X3DPhysicsModel, x3d.BoundedPhysicsModel):
    """X3D's BoundedPhysicsModel: particles bounce off the triangles of `geometry`"""

    def particleModel(self, mass: float = 0.0, surfaceArea: float = 0.0,
                      **named: Any) -> Optional[ParticleModel]:
        found: ParticleModel = _kept(self, MODEL_KEY, _bounds_of)
        return found


def _bounds_of(model: Any) -> Bounds:
    return Bounds(geometry_triangles(model.geometry)[0])


# ---------------------------------------------------------------------------
# The system
# ---------------------------------------------------------------------------

#: The fields whose change can start a system that has stopped, and of them
#: the switches that start an explosion again.
_WAKING = ('enabled', 'createParticles', 'emitter', 'maxParticles', 'particleLifetime',
           'geometryType')
_SWITCHES = ('enabled', 'createParticles')


class ParticleSystem(Ticked, Shape, x3d.ParticleSystem, GLLayer):
    """X3D's ParticleSystem on the engine's particles

    :meth:`advance` makes, moves and ages the particles; a frame's draw shows
    them. ``isActive`` is TRUE while the system is enabled and has particles
    alive or is still making them.
    """

    def __init__(self, *args: Any, **named: Any) -> None:
        super().__init__(*args, **named)
        self._pool: Optional[ParticlePool] = None
        self._emission = Emission()
        self._clock = StepClock()
        self._exploded = False
        self._watched: Any = None
        self._placements = np.zeros((0, 4, 4), np.float32)
        for name in _WAKING:
            dispatcher.connect(self._onSwitch if name in _SWITCHES else self._onWaking,
                               signal=('set', getattr(type(self), name)), sender=self)

    def _onWaking(self, value: Any = None) -> None:
        self.wake()

    def _onSwitch(self, value: Any = None) -> None:
        """Creation switched off or on: an explosion goes off again when it is next on"""
        if not value:
            self._exploded = False
        self.wake()

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    @property
    def pool(self) -> ParticlePool:
        """The particles, in a pool of ``maxParticles``; resized keeping the survivors"""
        capacity = max(0, int(self.maxParticles))
        if self._pool is None:
            self._pool = ParticlePool(capacity)
        elif self._pool.capacity != capacity:
            self._pool = self._pool.resized(capacity)
        return self._pool

    @property
    def particleCount(self) -> int:
        """How many particles are alive"""
        return self._pool.live if self._pool is not None else 0

    def currentEmitter(self) -> Any:
        """The emitter particles come from: `emitter`, or a still point at the origin"""
        return self.emitter or _still()

    def models(self) -> list[ParticleModel]:
        """The simulation models of the enabled `physics` nodes, in order"""
        emitter = self.currentEmitter()
        return models_of(self.physics, mass=float(getattr(emitter, 'mass', 0.0)),
                         surfaceArea=float(getattr(emitter, 'surfaceArea', 0.0)))

    def advance(self, now: float) -> bool:
        """Step to clock reading ``now``; whether the system is still active"""
        dt = self._clock.step(now)
        if not self.enabled or self.maxParticles <= 0:
            if self._pool is not None:
                self._pool.clear()
            self._emission.drop()
            self._exploded = False
            return self._active(False)
        pool = self.pool
        emitter = self.currentEmitter()
        self._watch(emitter)
        creating = bool(self.createParticles) and bool(getattr(emitter, 'on', True))
        lifetime = max(float(self.particleLifetime), MIN_LIFETIME)
        if not creating:
            self._emission.drop()
            self._exploded = False
            self._emission.rate = 0.0
        elif getattr(emitter, 'explodes', False):
            if not self._exploded:
                self._emission.burst(self.maxParticles)
                self._exploded = True
            self._emission.rate = 0.0
        else:
            self._emission.rate = float(self.maxParticles) / lifetime
        due = self._emission.due(dt)
        if due and self._spawn(emitter, due, lifetime) < due:
            # A full system makes particles as room comes free rather than
            # saving them up for a flood.
            self._emission.drop()
        pool.step(dt, models=self.models())
        making = creating and not getattr(emitter, 'explodes', False)
        return self._active(bool(pool.live) or making)

    def _spawn(self, emitter: Any, count: int, lifetime: float) -> int:
        pool = self.pool
        count = min(count, pool.capacity - pool.live)
        source = emitter.particleSource() if hasattr(emitter, 'particleSource') else None
        if count <= 0 or source is None or source.empty:
            return 0
        positions, velocities = launch(source, pool.rng, count, float(emitter.speed),
                                       float(emitter.variation))
        return pool.spawn(positions, velocities, lifetime=lifetime,
                          lifetime_variation=min(max(float(self.lifetimeVariation), 0.0), 1.0),
                          turned=False)

    def _active(self, active: bool) -> bool:
        if getattr(self, 'isActive', None) is not active:
            self.isActive = active
        return active

    def _watch(self, emitter: Any) -> None:
        """Wake when ``emitter`` is switched back on"""
        if emitter is self._watched or not hasattr(type(emitter), 'on'):
            return
        if self._watched is not None:
            dispatcher.disconnect(self._onSwitch, signal=('set', type(self._watched).on),
                                  sender=self._watched)
        dispatcher.connect(self._onSwitch, signal=('set', type(emitter).on), sender=emitter)
        self._watched = emitter

    # ------------------------------------------------------------------
    # How the particles look
    # ------------------------------------------------------------------

    def colorRampAt(self) -> ColorRamp:
        """The colour ramp of `colorKey` and `color`, keyed by age in seconds"""
        return ramp_colors(self.colorKey, self.color)

    def frameRampAt(self) -> FrameRamp:
        """The texture-coordinate frames of `texCoordKey` and `texCoord`, four points a key"""
        points = getattr(self.texCoord, 'point', None) if self.texCoord else None
        if points is None or len(points) < 4:
            return FrameRamp([], np.zeros((0, 4, 2)))
        points = np.asarray(points, dtype=np.float32).reshape(-1, 2)
        return FrameRamp(self.texCoordKey, points[:(len(points) // 4) * 4])

    def particleColors(self) -> Optional[np.ndarray]:
        """Each living particle's colour from the ramp; None where there is no ramp"""
        ramp = self.colorRampAt()
        if not ramp or self._pool is None:
            return None
        return ramp.at(self._pool.age[:self._pool.live])

    def particleFrames(self) -> Optional[np.ndarray]:
        """The texture frame each living particle shows; None where there are no frames"""
        ramp = self.frameRampAt()
        if not ramp or self._pool is None:
            return None
        return ramp.index(self._pool.age[:self._pool.live])

    def look(self, mode: Any) -> ParticleLook:
        """How the particles are drawn: their shape, size, colour, texture and blending"""
        from OpenGLContext.passes.shaderpass import appearance_solid_color
        appearance = self.appearance
        colour = appearance_solid_color(appearance)
        ramp = self.colorRampAt()
        start = (1.0, 1.0, 1.0, colour[3]) if ramp else colour
        texture, textureAlpha = _texture(appearance, mode)
        frames = self.frameRampAt()
        point = drawproperties.point_size(getattr(appearance, 'pointProperties', None)
                                          if appearance else None)
        blended = colour[3] < 1.0 or ramp.translucent or textureAlpha
        return ParticleLook(
            shape=SHAPE_OF.get(self.geometryType, 'quad'),
            size=(float(self.particleSize[0]), float(self.particleSize[1])),
            start_color=start, end_color=start, texture=texture, round=False,
            frames=frames.frames if frames else None,
            blending='alpha' if blended else 'opaque',
            point_size=(point.scale, point.minimum, point.maximum),
            point_attenuation=point.attenuation)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    @property
    def placesGeometry(self) -> bool:
        """Whether each particle is a copy of `geometry` (a `geometryType` of GEOMETRY)"""
        return self.geometryType == 'GEOMETRY'

    def drawsNothing(self) -> bool:
        """Whether the system is off, or places its geometry and has none, or no particles

        A system of sprites with no particles yet is drawn, since the draw
        steps it where nothing else does.
        """
        if self.placesGeometry:
            return not self.geometry or not self.enabled or not self.particleCount
        return not self.enabled

    def instancePlacements(self) -> Optional[np.ndarray]:
        """A matrix moving `geometry` to each particle, for a GEOMETRY system; else None"""
        if not self.placesGeometry or not self.geometry or not self.particleCount:
            return None
        pool = self.pool
        if len(self._placements) < pool.capacity:
            self._placements = np.zeros((pool.capacity, 4, 4), np.float32)
            self._placements[:] = np.identity(4, np.float32)
        placements = self._placements[:pool.live]
        placements[:, 3, :3] = pool.position[:pool.live]
        return placements

    def sortKey(self, mode: Any, matrix: Any) -> tuple[Any, ...]:
        """A GEOMETRY system sorts as its appearance does; the others draw with the blended geometry

        Sprites, quads, lines and points that are opaque write depth as they
        draw, so they are correct in either phase; drawn after the opaque
        geometry they are hidden by it where they should be.
        """
        if self.placesGeometry:
            return super().sortKey(mode, matrix)
        return (True, [], 0.0, None)

    def boundingVolume(self, mode: Any) -> Any:
        """A box over the living particles, where new ones start and how far they go

        Asked each frame; the particles move every frame, so it is not kept.
        A `bboxSize` the document gives is included.
        """
        emitter = self.currentEmitter()
        lifetime = max(float(self.particleLifetime), 0.0) * (1.0 + float(self.lifetimeVariation))
        reach = (float(getattr(emitter, 'speed', 0.0)) * (1.0 + float(getattr(emitter, 'variation', 0.0)))
                 * lifetime)
        margin = max(float(self.particleSize[0]), float(self.particleSize[1]))
        if self.placesGeometry:
            try:
                margin = _radius(self.geometry, mode)
            except boundingvolume.UnboundedObject:
                return boundingvolume.UnboundedVolume()
        low = np.full(3, -reach - margin)
        high = np.full(3, reach + margin)
        source = emitter.particleSource() if hasattr(emitter, 'particleSource') else None
        if source is not None and not source.empty:
            start, stop = source.extent()
            low, high = start - reach - margin, stop + reach + margin
        extent = self._pool.extent() if self._pool is not None else None
        if extent is not None:
            low = np.minimum(low, extent[0] - margin)
            high = np.maximum(high, extent[1] + margin)
        size = np.asarray(self.bboxSize, dtype=np.float64)
        if np.all(size >= 0.0):
            centre = np.asarray(self.bboxCenter, dtype=np.float64)
            low = np.minimum(low, centre - size / 2)
            high = np.maximum(high, centre + size / 2)
        return boundingvolume.AABoundingBox(
            size=tuple(float(value) for value in high - low),
            center=tuple(float(value) for value in (low + high) * 0.5))

    def Render(self, mode: Any = None) -> Any:
        """A GEOMETRY system's copies, one draw each where the pass does not batch them"""
        self.advance(systemtime.systemTime())
        if self.placesGeometry:
            self._drawPlacements(super().Render, mode)
        return 1

    def RenderTransparent(self, mode: Any = None) -> Any:
        """The particles: a GEOMETRY system's blended copies, or one instanced draw of the rest"""
        self.advance(systemtime.systemTime())
        if self.placesGeometry:
            self._drawPlacements(super().RenderTransparent, mode)
            return 1
        if getattr(mode, 'shadow_pass', False) or not getattr(mode, 'visible', True):
            return 1
        if not self.particleCount or not self.ensure_gl():
            return 1
        pool = self.pool
        look = self.look(mode)
        frames = self.particleFrames()
        self._gl.draw(pool.instances(colors=self.particleColors(), frames=frames),
                      look, mode, mode.matrix)
        return 1

    def _drawPlacements(self, draw: Callable[..., Any], mode: Any) -> None:
        """Call ``draw`` once per particle, at the modelview it belongs at"""
        placements = self.instancePlacements()
        if placements is None:
            return
        base = mode.matrix
        shader = getattr(mode, 'shader_program', None)
        set_matrices = getattr(shader, 'set_matrices', None)
        try:
            for placement in placements:
                mode.matrix = np.matmul(placement, base)
                if set_matrices is not None:
                    set_matrices(mode.matrix, mode.projection)
                draw(mode=mode)
        finally:
            mode.matrix = base
            if set_matrices is not None:
                set_matrices(base, mode.projection)

    def _init_gl(self) -> None:
        self._gl = ParticleRenderer()

    def dispose(self) -> None:
        """Delete the GL objects the sprites are drawn with"""
        renderer, self._gl = self._gl, None
        if renderer is not None:
            renderer.dispose()


def _radius(geometry: Any, mode: Any) -> float:
    """How far `geometry` reaches from its origin"""
    if not geometry or not hasattr(geometry, 'boundingVolume'):
        raise boundingvolume.UnboundedObject(geometry)
    points = np.asarray(geometry.boundingVolume(mode).getPoints(), dtype=np.float64)
    if not len(points):
        return 0.0
    return float(np.linalg.norm(points[:, :3], axis=1).max())


def _texture(appearance: Any, mode: Any) -> tuple[int, bool]:
    """The GL texture an appearance's (first) texture is, and whether it has alpha

    0 where there is no texture, no image yet, or no ``mode`` to make it in.
    """
    texture = getattr(appearance, 'texture', None) if appearance else None
    if isinstance(texture, x3d.MultiTexture):
        texture = texture.texture[0] if texture.texture else None
    if not texture or not hasattr(texture, 'cached'):
        return 0, False
    alpha = bool(getattr(texture, 'hasAlpha', lambda: False)())
    if mode is None:
        return 0, alpha
    made = texture.cached(mode)
    return (int(getattr(made, 'texture', 0) or 0) if made is not None else 0), alpha
