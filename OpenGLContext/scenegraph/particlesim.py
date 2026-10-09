"""Particle simulation: the pool, where particles start, what moves them; no GL.

:class:`ParticlePool`
    Fixed-capacity arrays of position, velocity, age and the rest, stepped as
    whole arrays, with the living particles packed in ``[0:live]``.
Sources
    Where a particle starts and which way it is thrown: :class:`PointSource`,
    :class:`ConeSource`, :class:`SphereSource`, :class:`PolylineSource`,
    :class:`SurfaceSource` and :class:`VolumeSource`. :func:`launch` turns a
    source's sample into positions and velocities at a speed.
Models
    What acts on a particle once it is out, applied in the order given each
    step: :class:`ConstantForce`, :class:`Wind` and :class:`Bounds`, a mesh the
    particles bounce off.
Ramps
    How a particle looks over its life: :class:`ColorRamp` interpolates a
    colour, :class:`FrameRamp` steps through texture-coordinate frames.
:class:`Emission`, :class:`StepClock`
    How many particles are due each step, and the step itself, read from the
    engine's clock.

Nothing here loops in Python over particles: a step, an emission or a ramp is a
few numpy operations over the packed arrays.
:mod:`~OpenGLContext.scenegraph.particles` draws a pool;
:mod:`~OpenGLContext.scenegraph.x3dparticles` is X3D's ParticleSystems
component on it.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Optional

import numpy as np

from OpenGLContext import entropy

__all__ = [
    'MAX_STEP', 'MIN_LIFETIME', 'WIND_PRESSURE', 'ParticlePool', 'ParticleSource',
    'PointSource', 'ConeSource', 'SphereSource', 'PolylineSource', 'SurfaceSource',
    'VolumeSource', 'launch', 'ParticleModel', 'ConstantForce', 'Wind', 'Bounds',
    'ColorRamp', 'FrameRamp', 'Emission', 'StepClock',
]

#: Anything three numbers long: a tuple, a VRML field, or a numpy row.
Vector = Sequence[float] | np.ndarray

#: Layout of one instance row, in floats: position and base size, then
#: rotation, normalised age, a per-particle random number and the texture
#: frame, then an RGBA colour, then the velocity. Sixteen floats, 64 bytes.
INSTANCE_POSITION = 0
INSTANCE_SIZE = 3
INSTANCE_ROTATION = 4
INSTANCE_LIFE = 5
INSTANCE_RANDOM = 6
INSTANCE_FRAME = 7
INSTANCE_COLOR = 8
INSTANCE_VELOCITY = 12
INSTANCE_FLOATS = 16

#: Longest frame the simulation will accept, in seconds.  A window dragged, a
#: breakpoint hit or a texture upload stalling gives a frame of seconds rather
#: than milliseconds; integrating it honestly teleports every particle out of
#: sight.  Losing that time is the lesser artefact, and it is the same clamp a
#: fixed-timestep physics loop applies for the same reason.
MAX_STEP = 0.1

#: A particle with no life left is one that never appears; the pool substitutes
#: this rather than dividing by zero when it works out an age fraction.
MIN_LIFETIME = 1e-3

#: Pascals of wind pressure per (metre per second) squared: half the density of
#: air at sea level, the factor ISO/IEC 19775-1 gives WindPhysicsModel.
WIND_PRESSURE = 0.64615

#: Pairs of particles and triangles tested at once by :class:`Bounds` and
#: :class:`VolumeSource`, which bounds the temporary arrays a test makes.
PAIRS_PER_PASS = 1 << 16

#: How far off a surface a bounced particle is put, so the next step starts
#: on the side it bounced back to.
SURFACE_OFFSET = 1e-4


def unit(vector: Vector) -> np.ndarray:
    """``vector`` at unit length; a zero vector comes back unchanged."""
    array = np.asarray(vector, dtype=np.float64)[:3]
    length = float(np.linalg.norm(array))
    return array if length == 0.0 else np.asarray(array / length)


def vary(rng: Any, value: float, variation: float, count: int) -> np.ndarray:
    """``count`` samples of ``value`` scattered by a fraction of itself."""
    if variation <= 0.0:
        return np.full(count, value, dtype=np.float32)
    spread = abs(value) * variation
    return np.asarray(rng.uniform(value - spread, value + spread,
                                  count).astype(np.float32))


def random_directions(rng: Any, count: int) -> np.ndarray:
    """``count`` unit vectors spread evenly over the sphere."""
    heights = rng.uniform(-1.0, 1.0, count)
    angles = rng.uniform(0.0, 2.0 * math.pi, count)
    rings = np.sqrt(np.maximum(0.0, 1.0 - heights * heights))
    return np.stack([rings * np.cos(angles), rings * np.sin(angles), heights], axis=1)


def cone_directions(rng: Any, axis: Vector, angle: float, count: int) -> np.ndarray:
    """``count`` unit vectors within ``angle`` radians of ``axis``.

    Directions are drawn so that they are **uniform over the spherical cap**
    rather than uniform in the angle: sampling the angle directly crowds the
    particles towards the axis and gives a jet with a bright core and a thin
    skirt, which is a distinctive and wrong look. A zero ``axis`` throws every
    way.
    """
    axis = unit(axis)
    if not axis.any():
        return random_directions(rng, count)
    if angle <= 0.0:
        return np.repeat(axis[None, :], count, axis=0)
    cosines = rng.uniform(math.cos(min(angle, math.pi)), 1.0, count)
    sines = np.sqrt(np.maximum(0.0, 1.0 - cosines * cosines))
    angles = rng.uniform(0.0, 2.0 * math.pi, count)
    # Any two vectors at right angles to the axis will do for the cone's own
    # frame; picking the world axis the direction leans on least keeps the
    # cross product well conditioned.
    helper = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    right = unit(np.cross(axis, helper))
    up = np.cross(axis, right)
    return np.asarray(axis[None, :] * cosines[:, None]
                      + right[None, :] * (sines * np.cos(angles))[:, None]
                      + up[None, :] * (sines * np.sin(angles))[:, None])


class ParticlePool:
    """Fixed-capacity particle state, stepped as whole arrays.

    Every array is allocated once, at construction, and the living particles are
    kept packed in ``[0:live]``.  Emission writes at the end of that prefix;
    death compacts the survivors down over the gaps.  Nothing here allocates
    per particle and nothing here loops in Python over particles -- a thousand
    particles cost one pass of numpy arithmetic, not a thousand of anything.
    """

    def __init__(self, capacity: int = 1000, seed: Optional[int] = None) -> None:
        self.capacity = int(max(0, capacity))
        self.live = 0
        # No seed of its own means the session's particle stream rather than
        # nowhere in particular: an emitter still looks different every time
        # the game is played, and a recorded session replays with the same
        # sparks it had. See OpenGLContext.entropy.
        self._random = (np.random.default_rng(seed) if seed is not None
                        else entropy.generator('particles'))
        size = self.capacity
        self.position = np.zeros((size, 3), dtype=np.float32)
        self.velocity = np.zeros((size, 3), dtype=np.float32)
        #: Seconds since each particle was born.
        self.age = np.zeros(size, dtype=np.float32)
        self.lifetime = np.ones(size, dtype=np.float32)
        self.size = np.ones(size, dtype=np.float32)
        self.rotation = np.zeros(size, dtype=np.float32)
        self.spin = np.zeros(size, dtype=np.float32)
        #: One number per particle, so a shader can vary them without the
        #: simulation having to store what it varied.
        self.random = np.zeros(size, dtype=np.float32)
        self._previous = np.zeros((size, 3), dtype=np.float32)
        self._instances = np.zeros((size, INSTANCE_FLOATS), dtype=np.float32)

    def __len__(self) -> int:
        return self.live

    @property
    def rng(self) -> Any:
        """The generator this pool draws its randomness from."""
        return self._random

    def clear(self) -> None:
        """Kill every particle at once."""
        self.live = 0

    def resized(self, capacity: int) -> 'ParticlePool':
        """A pool of ``capacity`` holding as many of these particles as fit.

        The first particles are kept, and the new pool draws from this one's
        generator, so a sequence carries on rather than starting again.
        """
        other = ParticlePool(capacity, seed=0)
        other._random = self._random
        kept = min(self.live, other.capacity)
        for name in ('position', 'velocity', 'age', 'lifetime', 'size', 'rotation',
                     'spin', 'random'):
            getattr(other, name)[:kept] = getattr(self, name)[:kept]
        other.live = kept
        return other

    def emit(self, count: int, position: Vector = (0.0, 0.0, 0.0),
             velocity: Vector = (0.0, 1.0, 0.0),
             spread: float = 0.0, speed_variation: float = 0.0,
             lifetime: float = 1.0, lifetime_variation: float = 0.0,
             size: float = 1.0, size_variation: float = 0.0,
             spin: float = 0.0, spin_variation: float = 0.0) -> int:
        """Bring up to ``count`` new particles into being at one point; return how many.

        Fewer than asked for means the pool is full.  It is not an error and it
        is not reported: a pool is a *budget*, and the budget being reached is
        the system working.  Size it from the emission rate times the lifetime,
        which is how many can be alive at once.

        ``spread`` is the half-angle of a cone about ``velocity``, in radians;
        zero gives a perfectly straight jet.  ``*_variation`` values are
        fractions -- 0.5 means "plus or minus half".
        """
        count = min(int(count), self.capacity - self.live)
        if count <= 0:
            return 0
        rng = self._random
        speed = float(np.linalg.norm(np.asarray(velocity, dtype=np.float64)[:3]))
        speeds = vary(rng, speed, speed_variation, count)
        if speed == 0.0:
            velocities = np.zeros((count, 3), dtype=np.float32)
        else:
            velocities = cone_directions(rng, velocity, spread, count) * speeds[:, None]
        positions = np.broadcast_to(np.asarray(position, dtype=np.float32)[:3], (count, 3))
        return self.spawn(positions, velocities, lifetime=lifetime,
                          lifetime_variation=lifetime_variation, size=size,
                          size_variation=size_variation, spin=spin,
                          spin_variation=spin_variation)

    def spawn(self, positions: Any, velocities: Any, lifetime: float = 1.0,
              lifetime_variation: float = 0.0, size: float = 1.0,
              size_variation: float = 0.0, spin: float = 0.0,
              spin_variation: float = 0.0, turned: bool = True) -> int:
        """Bring particles into being, one per row of ``positions``; return how many.

        ``velocities`` has a row per particle too. ``turned`` starts each
        particle at a random rotation, which hides the repetition of a round
        sprite; a quad whose texture has an up starts unturned.
        """
        positions = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
        count = min(len(positions), self.capacity - self.live)
        if count <= 0:
            return 0
        start, end = self.live, self.live + count
        rng = self._random
        self.position[start:end] = positions[:count]
        self.velocity[start:end] = np.asarray(velocities, dtype=np.float32).reshape(-1, 3)[:count]
        self.age[start:end] = 0.0
        self.lifetime[start:end] = np.maximum(
            vary(rng, lifetime, lifetime_variation, count), MIN_LIFETIME)
        self.size[start:end] = vary(rng, size, size_variation, count)
        self.rotation[start:end] = (rng.uniform(0.0, 2.0 * math.pi, count)
                                    if turned else 0.0)
        self.spin[start:end] = vary(rng, spin, spin_variation, count)
        self.random[start:end] = rng.random(count)
        self.live = end
        return count

    def step(self, dt: float, gravity: Vector = (0.0, 0.0, 0.0),
             drag: float = 0.0, models: Sequence['ParticleModel'] = ()) -> None:
        """Advance every living particle by ``dt`` seconds, and bury the dead.

        ``drag`` is a per-second fraction of the velocity lost.  It is applied
        as an exponential decay rather than as ``v -= v * drag * dt``, which
        would overshoot into a *reversal* on a long frame -- the classic
        explicit-Euler damping bug, and one that shows up as particles that
        suddenly fly backwards when the frame rate drops.

        ``models`` act in the order given: each changes the velocities, the
        particles move, and then each holds the moved particles to whatever it
        confines them to.
        """
        if dt <= 0.0 or self.live == 0:
            return
        live = self.live
        velocity = self.velocity[:live]
        if drag > 0.0:
            velocity *= math.exp(-drag * dt)
        if any(gravity):
            velocity += np.asarray(gravity, dtype=np.float32)[:3] * dt
        for model in models:
            model.accelerate(velocity, dt, self._random)
        position = self.position[:live]
        previous = self._previous[:live]
        previous[:] = position
        position += velocity * dt
        for model in models:
            model.confine(previous, position, velocity)
        self.rotation[:live] += self.spin[:live] * dt
        self.age[:live] += dt
        self._bury()

    def _bury(self) -> None:
        """Compact the survivors to the front of the arrays."""
        live = self.live
        keep = self.age[:live] < self.lifetime[:live]
        survivors = int(np.count_nonzero(keep))
        if survivors == live:
            return
        if survivors == 0:
            self.live = 0
            return
        index = np.flatnonzero(keep)
        for array in (self.position, self.velocity, self.age, self.lifetime,
                      self.size, self.rotation, self.spin, self.random):
            array[:survivors] = array[index]
        self.live = survivors

    def life_fraction(self) -> np.ndarray:
        """How far through its life each living particle is, from 0 to 1."""
        live = self.live
        return np.asarray(self.age[:live] / self.lifetime[:live])

    def instances(self, colors: Optional[np.ndarray] = None,
                  frames: Optional[np.ndarray] = None) -> np.ndarray:
        """One row per living particle, ready for the instance buffer.

        ``colors`` is an RGBA row per living particle (white without),
        ``frames`` the texture frame each shows (the first without). A view of
        the pool's own array, rewritten in place, so following a thousand
        particles costs no allocation per frame.
        """
        live = self.live
        rows = self._instances[:live]
        rows[:, INSTANCE_POSITION:INSTANCE_POSITION + 3] = self.position[:live]
        rows[:, INSTANCE_SIZE] = self.size[:live]
        rows[:, INSTANCE_ROTATION] = self.rotation[:live]
        rows[:, INSTANCE_LIFE] = self.life_fraction()
        rows[:, INSTANCE_RANDOM] = self.random[:live]
        rows[:, INSTANCE_FRAME] = 0.0 if frames is None else frames
        rows[:, INSTANCE_COLOR:INSTANCE_COLOR + 4] = 1.0 if colors is None else colors
        rows[:, INSTANCE_VELOCITY:INSTANCE_VELOCITY + 3] = self.velocity[:live]
        return np.asarray(rows)

    def extent(self) -> Optional[tuple[np.ndarray, np.ndarray]]:
        """The lowest and highest corner of the living particles; None for none."""
        if not self.live:
            return None
        live = self.position[:self.live]
        return live.min(axis=0), live.max(axis=0)


# ---------------------------------------------------------------------------
# Where particles start
# ---------------------------------------------------------------------------

class ParticleSource:
    """Where particles start and which way they are thrown.

    :meth:`sample` answers ``(positions, directions)``, a row of three per
    particle each, the directions of unit length.
    """

    #: True for a source with nowhere to start a particle from.
    empty = False

    def sample(self, rng: Any, count: int) -> tuple[np.ndarray, np.ndarray]:
        """``count`` starting points and the unit direction each is thrown along"""
        raise NotImplementedError

    def extent(self) -> tuple[np.ndarray, np.ndarray]:
        """The lowest and highest corner of where particles start."""
        raise NotImplementedError


class PointSource(ParticleSource):
    """One point, one direction; a zero direction throws every way."""

    def __init__(self, position: Vector, direction: Vector) -> None:
        self.position = np.asarray(position, dtype=np.float64)[:3]
        self.direction = unit(direction)

    def sample(self, rng: Any, count: int) -> tuple[np.ndarray, np.ndarray]:
        positions = np.repeat(self.position[None, :], count, axis=0)
        return positions, _directions(rng, self.direction, count)

    def extent(self) -> tuple[np.ndarray, np.ndarray]:
        return self.position, self.position


class ConeSource(PointSource):
    """One point, directions within ``angle`` radians of ``direction``."""

    def __init__(self, position: Vector, direction: Vector, angle: float) -> None:
        super().__init__(position, direction)
        self.angle = max(0.0, float(angle))

    def sample(self, rng: Any, count: int) -> tuple[np.ndarray, np.ndarray]:
        positions = np.repeat(self.position[None, :], count, axis=0)
        return positions, cone_directions(rng, self.direction, self.angle, count)


class SphereSource(PointSource):
    """One point, every direction: an explosion."""

    def __init__(self, position: Vector) -> None:
        super().__init__(position, (0.0, 0.0, 0.0))


def _directions(rng: Any, direction: np.ndarray, count: int) -> np.ndarray:
    """``direction`` for each of ``count``, or every way for a zero direction"""
    if not direction.any():
        return random_directions(rng, count)
    return np.repeat(direction[None, :], count, axis=0)


def _empty_sample() -> tuple[np.ndarray, np.ndarray]:
    return np.zeros((0, 3)), np.zeros((0, 3))


class PolylineSource(ParticleSource):
    """Points along line segments, chosen by length; one direction for all.

    ``points`` is a row of three per vertex and ``segments`` a pair of vertex
    indices per segment.
    """

    def __init__(self, points: Any, segments: Any, direction: Vector) -> None:
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        pairs = np.asarray(segments, dtype=np.int64).reshape(-1, 2)
        self.starts = points[pairs[:, 0]] if len(pairs) else np.zeros((0, 3))
        self.ends = points[pairs[:, 1]] if len(pairs) else np.zeros((0, 3))
        self.direction = unit(direction)
        lengths = np.linalg.norm(self.ends - self.starts, axis=1)
        self._cumulative = np.cumsum(lengths)
        self.empty = not len(pairs) or not self._cumulative[-1] > 0.0

    def sample(self, rng: Any, count: int) -> tuple[np.ndarray, np.ndarray]:
        if self.empty:
            return _empty_sample()
        chosen = _weighted(rng, self._cumulative, count)
        along = rng.random(count)[:, None]
        positions = self.starts[chosen] + (self.ends[chosen] - self.starts[chosen]) * along
        return positions, _directions(rng, self.direction, count)

    def extent(self) -> tuple[np.ndarray, np.ndarray]:
        if not len(self.starts):
            return np.zeros(3), np.zeros(3)
        both = np.concatenate([self.starts, self.ends])
        return both.min(axis=0), both.max(axis=0)


def _weighted(rng: Any, cumulative: np.ndarray, count: int) -> np.ndarray:
    """``count`` indices, each chosen in proportion to its share of ``cumulative``"""
    picks = rng.random(count) * cumulative[-1]
    return np.asarray(np.minimum(np.searchsorted(cumulative, picks, side='right'),
                                 len(cumulative) - 1))


class _Triangles:
    """A triangle mesh's corners, edges and face normals, as arrays."""

    def __init__(self, triangles: Any) -> None:
        corners = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
        self.corners = corners
        self.origin = corners[:, 0]
        self.first = corners[:, 1] - corners[:, 0]
        self.second = corners[:, 2] - corners[:, 0]
        crossed = np.cross(self.first, self.second)
        doubled = np.linalg.norm(crossed, axis=1)
        self.areas = doubled * 0.5
        safe = np.where(doubled > 0.0, doubled, 1.0)
        self.normals = crossed / safe[:, None]
        self._cumulative = np.cumsum(self.areas)
        if len(corners):
            flat = corners.reshape(-1, 3)
            self.low, self.high = flat.min(axis=0), flat.max(axis=0)
        else:
            self.low = self.high = np.zeros(3)

    def __len__(self) -> int:
        return len(self.corners)

    @property
    def flat(self) -> bool:
        """True where the mesh has no area to place anything on"""
        return not len(self.corners) or not self._cumulative[-1] > 0.0

    def surface_points(self, rng: Any, count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``count`` points on the surface by area: the points, barycentric weights, triangles"""
        chosen = _weighted(rng, self._cumulative, count)
        u = rng.random(count)
        v = rng.random(count)
        outside = u + v > 1.0
        u[outside] = 1.0 - u[outside]
        v[outside] = 1.0 - v[outside]
        points = (self.origin[chosen] + self.first[chosen] * u[:, None]
                  + self.second[chosen] * v[:, None])
        weights = np.stack([1.0 - u - v, u, v], axis=1)
        return points, weights, chosen

    def crossings(self, starts: np.ndarray, travel: np.ndarray,
                  ray: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """Where each segment ``starts + t * travel`` first meets the mesh.

        Answers ``(t, triangle)`` per segment: the fraction along it of the
        nearest crossing, ``inf`` for none, and the triangle crossed (-1 for
        none). With ``ray`` the segment goes on past its end. Either face of a
        triangle counts.
        """
        count = len(starts)
        nearest = np.full(count, np.inf)
        which = np.full(count, -1, dtype=np.int64)
        if not count or not len(self.corners):
            return nearest, which
        chunk = max(1, PAIRS_PER_PASS // len(self.corners))
        for begin in range(0, count, chunk):
            stop = min(begin + chunk, count)
            t, index = _crossing(starts[begin:stop], travel[begin:stop], self, ray)
            nearest[begin:stop] = t
            which[begin:stop] = index
        return nearest, which

    def crossing_counts(self, starts: np.ndarray, travel: np.ndarray) -> np.ndarray:
        """How many triangles each ray ``starts + t * travel``, t > 0, passes through"""
        counts = np.zeros(len(starts), dtype=np.int64)
        if not len(starts) or not len(self.corners):
            return counts
        chunk = max(1, PAIRS_PER_PASS // len(self.corners))
        for begin in range(0, len(starts), chunk):
            stop = min(begin + chunk, len(starts))
            hits = _hits(starts[begin:stop], travel[begin:stop], self, ray=True)[0]
            counts[begin:stop] = np.count_nonzero(hits, axis=1)
        return counts


def _hits(starts: np.ndarray, travel: np.ndarray, mesh: _Triangles,
          ray: bool) -> tuple[np.ndarray, np.ndarray]:
    """Which (segment, triangle) pairs cross, and where along the segment.

    Möller and Trumbore's test, for every pair at once.
    """
    starts = np.asarray(starts, dtype=np.float64)
    travel = np.asarray(travel, dtype=np.float64)
    second = mesh.second[None, :, :]
    h = np.cross(travel[:, None, :], second)
    a = np.einsum('tk,ptk->pt', mesh.first, h)
    usable = np.abs(a) > 1e-12
    f = np.divide(1.0, a, out=np.zeros_like(a), where=usable)
    s = starts[:, None, :] - mesh.origin[None, :, :]
    u = f * np.einsum('ptk,ptk->pt', s, h)
    q = np.cross(s, mesh.first[None, :, :])
    v = f * np.einsum('pk,ptk->pt', travel, q)
    t = f * np.einsum('tk,ptk->pt', mesh.second, q)
    hits = usable & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (t > 0.0)
    if not ray:
        hits &= t <= 1.0
    return hits, t


def _crossing(starts: np.ndarray, travel: np.ndarray, mesh: _Triangles,
              ray: bool) -> tuple[np.ndarray, np.ndarray]:
    hits, t = _hits(starts, travel, mesh, ray)
    t = np.where(hits, t, np.inf)
    index = np.argmin(t, axis=1)
    nearest = t[np.arange(len(t)), index]
    return nearest, np.where(np.isfinite(nearest), index, -1)


class SurfaceSource(ParticleSource):
    """Points on a triangle mesh by area, thrown along its normal there.

    ``triangles`` is three corners per triangle; ``normals``, three per
    triangle too where given, are interpolated across each, and the face
    normals are used without. A ``two_sided`` surface throws from either face
    with even odds.
    """

    def __init__(self, triangles: Any, normals: Any = None, two_sided: bool = False) -> None:
        self.mesh = _Triangles(triangles)
        self.normals = (None if normals is None
                        else np.asarray(normals, dtype=np.float64).reshape(-1, 3, 3))
        self.two_sided = bool(two_sided)
        self.empty = self.mesh.flat

    def sample(self, rng: Any, count: int) -> tuple[np.ndarray, np.ndarray]:
        if self.empty:
            return _empty_sample()
        points, weights, chosen = self.mesh.surface_points(rng, count)
        if self.normals is None:
            directions = self.mesh.normals[chosen]
        else:
            blended = np.einsum('pc,pck->pk', weights, self.normals[chosen])
            lengths = np.linalg.norm(blended, axis=1, keepdims=True)
            directions = np.where(lengths > 0.0, blended / np.where(lengths > 0, lengths, 1.0),
                                  self.mesh.normals[chosen])
        if self.two_sided:
            directions = directions * np.where(rng.random(count) < 0.5, -1.0, 1.0)[:, None]
        return points, directions

    def extent(self) -> tuple[np.ndarray, np.ndarray]:
        return self.mesh.low, self.mesh.high


#: A direction for counting crossings that no axis-aligned edge lies along.
_PARITY_RAY = unit((1.0, 0.000731, 0.000419))

#: Rounds of candidates :class:`VolumeSource` draws before falling back to the
#: points it already has.
_VOLUME_ROUNDS = 8


class VolumeSource(ParticleSource):
    """Points inside a closed triangle mesh, thrown along one direction.

    A point is inside where a ray from it crosses the mesh an odd number of
    times; candidates are drawn in the mesh's box and those outside dropped. An
    ``internal`` of False starts particles on the mesh's surface instead. A
    zero ``direction`` throws every way.
    """

    def __init__(self, triangles: Any, direction: Vector, internal: bool = True) -> None:
        self.mesh = _Triangles(triangles)
        self.direction = unit(direction)
        self.internal = bool(internal)
        self.empty = self.mesh.flat

    def inside(self, points: np.ndarray) -> np.ndarray:
        """Which of ``points`` are inside the mesh"""
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        travel = np.broadcast_to(_PARITY_RAY, points.shape)
        return np.asarray(self.mesh.crossing_counts(points, travel) % 2 == 1)

    def sample(self, rng: Any, count: int) -> tuple[np.ndarray, np.ndarray]:
        if self.empty:
            return _empty_sample()
        if not self.internal:
            points = self.mesh.surface_points(rng, count)[0]
            return points, _directions(rng, self.direction, count)
        found: list[np.ndarray] = []
        wanted = count
        for _round in range(_VOLUME_ROUNDS):
            candidates = rng.uniform(self.mesh.low, self.mesh.high, (max(2 * wanted, 8), 3))
            kept = candidates[self.inside(candidates)][:wanted]
            found.append(kept)
            wanted -= len(kept)
            if wanted <= 0:
                break
        points = np.concatenate(found) if found else np.zeros((0, 3))
        if wanted > 0:
            # A mesh that is not closed has no inside; its surface is where
            # its particles start.
            points = np.concatenate([points, self.mesh.surface_points(rng, wanted)[0]])
        return points, _directions(rng, self.direction, count)

    def extent(self) -> tuple[np.ndarray, np.ndarray]:
        return self.mesh.low, self.mesh.high


def launch(source: ParticleSource, rng: Any, count: int, speed: float,
           variation: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """``count`` positions from ``source`` and velocities at ``speed``.

    Each speed is drawn evenly from ``speed`` give or take ``variation`` of
    itself, and is never below zero.
    """
    positions, directions = source.sample(rng, count)
    speeds = np.maximum(vary(rng, float(speed), float(variation), len(positions)), 0.0)
    return positions, directions * speeds[:, None]


# ---------------------------------------------------------------------------
# What acts on particles once they are out
# ---------------------------------------------------------------------------

class ParticleModel:
    """Something that acts on every particle each step.

    :meth:`accelerate` changes the velocities before the particles move;
    :meth:`confine` holds them to something after they have. Each does nothing
    unless a model overrides it.
    """

    def accelerate(self, velocity: np.ndarray, dt: float, rng: Any) -> None:
        """Change ``velocity``, a row per living particle, in place"""

    def confine(self, previous: np.ndarray, position: np.ndarray,
                velocity: np.ndarray) -> None:
        """Hold the particles that moved from ``previous`` to ``position``, in place"""


def _per_mass(mass: float) -> float:
    """What a force is multiplied by to be an acceleration.

    A particle of no mass takes the force as an acceleration, so a force
    given without a mass reads as the acceleration it names.
    """
    return 1.0 / mass if mass > 0.0 else 1.0


class ConstantForce(ParticleModel):
    """A force in newtons on every particle of ``mass`` kilograms."""

    def __init__(self, force: Vector, mass: float = 0.0) -> None:
        self.acceleration = (np.asarray(force, dtype=np.float32)[:3]
                             * np.float32(_per_mass(float(mass))))

    def accelerate(self, velocity: np.ndarray, dt: float, rng: Any) -> None:
        velocity += self.acceleration * np.float32(dt)


class Wind(ParticleModel):
    """Wind blowing on particles of ``area`` square metres and ``mass`` kilograms.

    The wind's pressure is :data:`WIND_PRESSURE` times the square of its speed.
    ``gustiness`` scatters the speed each step by up to that fraction of
    itself; ``turbulence``, from 0 to 1, turns each particle's push off the
    wind's direction by up to that fraction of half a turn. A zero
    ``direction`` blows a new way each step.
    """

    def __init__(self, direction: Vector, speed: float, gustiness: float = 0.0,
                 turbulence: float = 0.0, area: float = 1.0, mass: float = 0.0) -> None:
        self.direction = unit(direction)
        self.speed = max(0.0, float(speed))
        self.gustiness = max(0.0, float(gustiness))
        self.turbulence = min(max(float(turbulence), 0.0), 1.0)
        self.area = max(0.0, float(area))
        self.mass = float(mass)

    def accelerate(self, velocity: np.ndarray, dt: float, rng: Any) -> None:
        if not self.speed or not self.area or not len(velocity):
            return
        speed = float(vary(rng, self.speed, self.gustiness, 1)[0])
        push = (WIND_PRESSURE * speed * speed * self.area * _per_mass(self.mass) * dt)
        direction = self.direction if self.direction.any() else random_directions(rng, 1)[0]
        if self.turbulence > 0.0:
            directions = cone_directions(rng, direction, math.pi * self.turbulence,
                                         len(velocity))
            velocity += (directions * push).astype(np.float32)
        else:
            velocity += (direction * push).astype(np.float32)


class Bounds(ParticleModel):
    """A triangle mesh particles bounce off, from either side.

    A particle whose step crosses the mesh is put back just short of the
    crossing, on the side it came from, with its velocity reflected about the
    triangle it met. Particles are held on whichever side they start, so a
    closed mesh keeps those inside it in and those outside it out.
    """

    def __init__(self, triangles: Any) -> None:
        self.mesh = _Triangles(triangles)

    def confine(self, previous: np.ndarray, position: np.ndarray,
                velocity: np.ndarray) -> None:
        mesh = self.mesh
        if not len(mesh) or not len(position):
            return
        low = np.minimum(previous, position)
        high = np.maximum(previous, position)
        near = np.flatnonzero(np.all(high >= mesh.low, axis=1)
                              & np.all(low <= mesh.high, axis=1))
        if not len(near):
            return
        starts = previous[near].astype(np.float64)
        travel = position[near].astype(np.float64) - starts
        t, which = mesh.crossings(starts, travel)
        hit = np.flatnonzero(which >= 0)
        if not len(hit):
            return
        rows = near[hit]
        normals = mesh.normals[which[hit]]
        moving = velocity[rows].astype(np.float64)
        along = np.einsum('pk,pk->p', moving, normals)
        velocity[rows] = (moving - 2.0 * along[:, None] * normals).astype(np.float32)
        side = np.sign(np.einsum('pk,pk->p', starts[hit] - mesh.origin[which[hit]], normals))
        side[side == 0.0] = -np.sign(along[side == 0.0])
        crossing = starts[hit] + travel[hit] * t[hit][:, None]
        position[rows] = (crossing + normals * (side * SURFACE_OFFSET)[:, None]).astype(np.float32)


# ---------------------------------------------------------------------------
# How particles look over a life
# ---------------------------------------------------------------------------

class ColorRamp:
    """RGBA colours at keys, interpolated between them and held past either end.

    The keys are whatever the caller measures a particle's life in: seconds of
    age, or the fraction of its lifetime. Colours of three components are
    opaque. Only as many keys as there are colours, and the reverse, are used.
    """

    def __init__(self, keys: Any, colors: Any) -> None:
        keys = np.asarray(keys, dtype=np.float64).ravel()
        colors = np.asarray(colors, dtype=np.float64)
        colors = colors.reshape(len(colors), -1) if colors.size else np.zeros((0, 4))
        if colors.shape[1] == 3:
            colors = np.concatenate([colors, np.ones((len(colors), 1))], axis=1)
        count = min(len(keys), len(colors))
        order = np.argsort(keys[:count], kind='stable')
        self.keys = keys[:count][order]
        self.colors = colors[:count, :4][order]

    def __len__(self) -> int:
        return len(self.keys)

    def __bool__(self) -> bool:
        return bool(len(self.keys))

    @property
    def translucent(self) -> bool:
        """Whether any colour is less than opaque"""
        return bool(len(self.colors)) and bool((self.colors[:, 3] < 1.0).any())

    def at(self, values: np.ndarray) -> np.ndarray:
        """The colour at each of ``values``, a row of four each"""
        out = np.empty((len(values), 4), dtype=np.float32)
        for channel in range(4):
            out[:, channel] = np.interp(values, self.keys, self.colors[:, channel])
        return out


class FrameRamp:
    """Texture-coordinate frames shown in turn: each from its key until the next.

    ``frames`` is four ``(s, t)`` corners per key, in the order lower left,
    lower right, upper right, upper left. Before the first key the first frame
    is shown, after the last the last.
    """

    def __init__(self, keys: Any, frames: Any) -> None:
        keys = np.asarray(keys, dtype=np.float64).ravel()
        frames = np.asarray(frames, dtype=np.float32).reshape(-1, 4, 2)
        count = min(len(keys), len(frames))
        order = np.argsort(keys[:count], kind='stable')
        self.keys = keys[:count][order]
        self.frames = frames[:count][order]

    def __len__(self) -> int:
        return len(self.keys)

    def __bool__(self) -> bool:
        return bool(len(self.keys))

    def index(self, values: np.ndarray) -> np.ndarray:
        """The frame each of ``values`` shows"""
        found = np.searchsorted(self.keys, values, side='right') - 1
        return np.clip(found, 0, len(self.keys) - 1)


# ---------------------------------------------------------------------------
# When particles are made
# ---------------------------------------------------------------------------

class Emission:
    """How many particles are due each step: a steady rate and bursts.

    Fractions carry over, so a rate below one particle a step still emits.
    """

    def __init__(self, rate: float = 0.0) -> None:
        self.rate = float(rate)
        self._owed = 0.0

    def burst(self, count: float) -> None:
        """Have ``count`` more particles due at the next step"""
        self._owed += max(0.0, float(count))

    def drop(self) -> None:
        """Forget whatever is owed"""
        self._owed = 0.0

    def due(self, dt: float) -> int:
        """The particles to make over a step of ``dt`` seconds"""
        if self.rate > 0.0 and dt > 0.0:
            self._owed += self.rate * dt
        count = int(self._owed)
        self._owed -= count
        return count


class StepClock:
    """The step a simulation takes, from successive readings of a clock.

    The first reading steps nothing, a reading earlier than the last steps
    nothing, and no step is longer than ``longest`` seconds.
    """

    def __init__(self, longest: float = MAX_STEP) -> None:
        self.longest = float(longest)
        self._last: Optional[float] = None

    def reset(self) -> None:
        """Start again: the next reading steps nothing"""
        self._last = None

    def step(self, now: float) -> float:
        """Seconds to step at clock reading ``now``"""
        last, self._last = self._last, float(now)
        if last is None:
            return 0.0
        return min(max(float(now) - last, 0.0), self.longest)
