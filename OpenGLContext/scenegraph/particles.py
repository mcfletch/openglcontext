"""Particles: a numpy pool, an emitter node, and one instanced draw.

A particle system is a **simulation with a renderer bolted on**, and keeping
those two apart is most of the design:

:class:`ParticlePool`
    Fixed-capacity arrays of position, velocity, age and the rest, stepped as
    whole arrays.  No GL, no scenegraph, no node -- so the interesting behaviour
    (birth, motion, death, compaction, budget) is testable with nothing but
    numpy, and a bug in it is found in milliseconds rather than by watching.
:class:`ParticleEmitter`
    A scenegraph node holding a pool, the shape of what comes out of it, and the
    GL to draw it: one camera-facing quad per particle, all in a single
    instanced draw.

**What varies per particle is state; what is shared is a curve.**  A particle
carries a position, a velocity, an age, a base size, a rotation and one random
number.  Its colour and its size *over its life* are the emitter's, evaluated in
the shader from the normalised age.  That split is why the per-instance data is
seven floats rather than twenty, and why changing an effect's colour costs a
uniform rather than a rewrite of the pool.

The pool keeps its living particles **packed at the front** of its arrays.  A
dead particle is not a hole to skip; the survivors are compacted down over it, so
the live set is always ``[0:live]`` and the GPU upload is one contiguous slice.
That is what makes a thousand particles one ``glBufferSubData`` and one
``glDrawArraysInstanced``.

Everything is additive or alpha-blended and unlit: a particle effect is light
and smoke, not a surface, so it draws in the transparent pass with depth writes
off and never enters a shadow map.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional, Sequence, Tuple, Union

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_DEPTH_TEST, GL_FALSE, GL_FLOAT, GL_ONE,
    GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, GL_STATIC_DRAW, GL_TEXTURE0,
    GL_TEXTURE_2D, GL_TRIANGLE_STRIP, GL_CCW,
    glActiveTexture, glBindBuffer, glBindTexture, glBindVertexArray, glBlendFunc,
    glBufferData, glDepthMask, glDrawArraysInstanced, glEnable,
    glEnableVertexAttribArray, glGenBuffers, glGenVertexArrays, glGetUniformLocation, glUniform1i, glUniform2f, glUniform4f,
    glUniformMatrix4fv, glUseProgram, glVertexAttribDivisor, glVertexAttribPointer,
)
from vrml import field, node
from vrml.vrml97 import nodetypes

from OpenGLContext import entropy
from OpenGLContext.events import systemtime
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.instancedgl import (
    InstanceBuffer, delete_gl, ensure_gl, load_program, texture_rgba,
)

log = logging.getLogger(__name__)

#: Anything three numbers long: a tuple, a VRML field, or a numpy row.
Vector = Union[Sequence[float], np.ndarray]

#: Layout of one instance row, in floats.  Position, base size, rotation,
#: normalised age and a per-particle random number -- seven floats, 28 bytes.
INSTANCE_POSITION = 0
INSTANCE_SIZE = 3
INSTANCE_ROTATION = 4
INSTANCE_LIFE = 5
INSTANCE_RANDOM = 6
INSTANCE_FLOATS = 7

#: Blend factors by name.  Additive is the default because most effects are
#: light -- fire, sparks, explosions, muzzle flashes -- and light adds.  Alpha is
#: for the things that block light instead: smoke, dust, steam.
BLEND_MODES: Dict[str, Tuple[int, int]] = {
    'additive': (GL_SRC_ALPHA, GL_ONE),
    'alpha': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
}

#: Longest frame the simulation will accept, in seconds.  A window dragged, a
#: breakpoint hit or a texture upload stalling gives a frame of seconds rather
#: than milliseconds; integrating it honestly teleports every particle out of
#: sight.  Losing that time is the lesser artefact, and it is the same clamp a
#: fixed-timestep physics loop applies for the same reason.
MAX_STEP = 0.1

#: A particle with no life left is one that never appears; the pool substitutes
#: this rather than dividing by zero when it works out an age fraction.
MIN_LIFETIME = 1e-3


def _unit(vector: Vector) -> np.ndarray:
    """``vector`` at unit length; a zero vector comes back unchanged."""
    array = np.asarray(vector, dtype=np.float64)[:3]
    length = float(np.linalg.norm(array))
    return array if length == 0.0 else np.asarray(array / length)


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
        self.age = np.zeros(size, dtype=np.float32)
        self.lifetime = np.ones(size, dtype=np.float32)
        self.size = np.ones(size, dtype=np.float32)
        self.rotation = np.zeros(size, dtype=np.float32)
        self.spin = np.zeros(size, dtype=np.float32)
        #: One number per particle, so a shader can vary them without the
        #: simulation having to store what it varied.
        self.random = np.zeros(size, dtype=np.float32)
        self._instances = np.zeros((size, INSTANCE_FLOATS), dtype=np.float32)

    def __len__(self) -> int:
        return self.live

    def clear(self) -> None:
        """Kill every particle at once."""
        self.live = 0

    def emit(self, count: int, position: Vector = (0.0, 0.0, 0.0),
             velocity: Vector = (0.0, 1.0, 0.0),
             spread: float = 0.0, speed_variation: float = 0.0,
             lifetime: float = 1.0, lifetime_variation: float = 0.0,
             size: float = 1.0, size_variation: float = 0.0,
             spin: float = 0.0, spin_variation: float = 0.0) -> int:
        """Bring up to ``count`` new particles into being; return how many.

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
        start, end = self.live, self.live + count
        rng = self._random

        self.position[start:end] = np.asarray(position, dtype=np.float32)[:3]
        self.velocity[start:end] = _scatter(rng, velocity, spread, speed_variation,
                                            count)
        self.age[start:end] = 0.0
        self.lifetime[start:end] = np.maximum(
            _vary(rng, lifetime, lifetime_variation, count), MIN_LIFETIME)
        self.size[start:end] = _vary(rng, size, size_variation, count)
        self.rotation[start:end] = rng.uniform(0.0, 2.0 * math.pi, count)
        self.spin[start:end] = _vary(rng, spin, spin_variation, count)
        self.random[start:end] = rng.random(count)
        self.live = end
        return count

    def step(self, dt: float, gravity: Vector = (0.0, 0.0, 0.0),
             drag: float = 0.0) -> None:
        """Advance every living particle by ``dt`` seconds, and bury the dead.

        ``drag`` is a per-second fraction of the velocity lost.  It is applied
        as an exponential decay rather than as ``v -= v * drag * dt``, which
        would overshoot into a *reversal* on a long frame -- the classic
        explicit-Euler damping bug, and one that shows up as particles that
        suddenly fly backwards when the frame rate drops.
        """
        if dt <= 0.0 or self.live == 0:
            return
        live = self.live
        velocity = self.velocity[:live]
        if drag > 0.0:
            velocity *= math.exp(-drag * dt)
        if any(gravity):
            velocity += np.asarray(gravity, dtype=np.float32)[:3] * dt
        self.position[:live] += velocity * dt
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

    def instances(self) -> np.ndarray:
        """One row per living particle, ready for the instance buffer.

        A view of the pool's own array, rewritten in place, so following a
        thousand particles costs no allocation per frame.
        """
        live = self.live
        rows = self._instances[:live]
        rows[:, INSTANCE_POSITION:INSTANCE_POSITION + 3] = self.position[:live]
        rows[:, INSTANCE_SIZE] = self.size[:live]
        rows[:, INSTANCE_ROTATION] = self.rotation[:live]
        rows[:, INSTANCE_LIFE] = self.life_fraction()
        rows[:, INSTANCE_RANDOM] = self.random[:live]
        return np.asarray(rows)


def _vary(rng: Any, value: float, variation: float, count: int) -> np.ndarray:
    """``count`` samples of ``value`` scattered by a fraction of itself."""
    if variation <= 0.0:
        return np.full(count, value, dtype=np.float32)
    spread = abs(value) * variation
    return np.asarray(rng.uniform(value - spread, value + spread,
                                  count).astype(np.float32))


def _scatter(rng: Any, velocity: Vector, spread: float,
             speed_variation: float, count: int) -> np.ndarray:
    """``count`` velocities in a cone of half-angle ``spread`` about ``velocity``.

    Directions are drawn so that they are **uniform over the spherical cap**
    rather than uniform in the angle: sampling the angle directly crowds the
    particles towards the axis and gives a jet with a bright core and a thin
    skirt, which is a distinctive and wrong look.
    """
    speed = float(np.linalg.norm(np.asarray(velocity, dtype=np.float64)[:3]))
    speeds = _vary(rng, speed, speed_variation, count)
    if speed == 0.0:
        return np.zeros((count, 3), dtype=np.float32)
    axis = _unit(velocity)
    if spread <= 0.0:
        return np.asarray((axis[None, :] * speeds[:, None]).astype(np.float32))

    cosines = rng.uniform(math.cos(min(spread, math.pi)), 1.0, count)
    sines = np.sqrt(np.maximum(0.0, 1.0 - cosines * cosines))
    angles = rng.uniform(0.0, 2.0 * math.pi, count)
    # Any two vectors at right angles to the axis will do for the cone's own
    # frame; picking the world axis the direction leans on least keeps the
    # cross product well conditioned.
    helper = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    right = _unit(np.cross(axis, helper))
    up = np.cross(axis, right)
    directions = (axis[None, :] * cosines[:, None]
                  + right[None, :] * (sines * np.cos(angles))[:, None]
                  + up[None, :] * (sines * np.sin(angles))[:, None])
    return np.asarray((directions * speeds[:, None]).astype(np.float32))


class ParticleEmitter(nodetypes.Rendering, nodetypes.Children, node.Node):
    """A source of particles in the scene, drawn in one instanced call.

    Put it under a ``Transform`` and the particles come from there.  It is a
    *rendering* node in its own right rather than a geometry inside a ``Shape``:
    an effect has no material and no surface, and pretending it does would mean
    an ``Appearance`` whose every field is ignored.

    The fields divide into three groups, and it helps to read them that way:
    **how many and how often** (``rate``, ``burst``, ``maxParticles``,
    ``lifetime``), **which way and how fast** (``direction``, ``speed``,
    ``spread``, ``gravity``, ``drag``), and **what it looks like** (``size``,
    ``color``, ``alpha``, their ``end*`` counterparts, ``texture``,
    ``blending``).
    """

    PROTO = 'ParticleEmitter'

    #: Particles born per second.  Fractions accumulate, so a rate below one a
    #: frame still emits.
    rate = field.newField('rate', 'SFFloat', 1, 50.0)
    #: Particles released in one go when the emitter starts or :meth:`fire` is
    #: called.  An explosion is a burst with a rate of zero.
    burst = field.newField('burst', 'SFInt32', 1, 0)
    #: The pool's capacity.  Size it from ``rate * lifetime``, which is how many
    #: can be alive at once.
    maxParticles = field.newField('maxParticles', 'SFInt32', 1, 500)
    #: Seconds a particle lives, and the fraction that is scattered.
    lifetime = field.newField('lifetime', 'SFFloat', 1, 1.5)
    lifetimeVariation = field.newField('lifetimeVariation', 'SFFloat', 1, 0.3)

    #: Which way particles are thrown, in the emitter's own frame.
    direction = field.newField('direction', 'SFVec3f', 1, [0.0, 1.0, 0.0])
    #: How fast, in units per second, and the fraction that is scattered.
    speed = field.newField('speed', 'SFFloat', 1, 2.0)
    speedVariation = field.newField('speedVariation', 'SFFloat', 1, 0.3)
    #: Half-angle of the emission cone, radians.  0 is a laser, pi is a sphere.
    spread = field.newField('spread', 'SFFloat', 1, 0.4)
    #: Constant acceleration.  Negative Y falls; positive Y is what makes smoke
    #: rise.
    gravity = field.newField('gravity', 'SFVec3f', 1, [0.0, -1.0, 0.0])
    #: Fraction of velocity lost per second.  Air.
    drag = field.newField('drag', 'SFFloat', 1, 0.0)

    #: Size at birth and at death, in world units.
    size = field.newField('size', 'SFFloat', 1, 0.3)
    endSize = field.newField('endSize', 'SFFloat', 1, 0.0)
    sizeVariation = field.newField('sizeVariation', 'SFFloat', 1, 0.3)
    #: Radians per second each particle turns about the view axis.
    spin = field.newField('spin', 'SFFloat', 1, 0.0)
    spinVariation = field.newField('spinVariation', 'SFFloat', 1, 1.0)

    #: Colour and opacity at birth and at death.
    color = field.newField('color', 'SFColor', 1, [1.0, 0.7, 0.3])
    endColor = field.newField('endColor', 'SFColor', 1, [0.6, 0.1, 0.0])
    alpha = field.newField('alpha', 'SFFloat', 1, 1.0)
    endAlpha = field.newField('endAlpha', 'SFFloat', 1, 0.0)

    #: A sprite for each particle.  Without one, particles are soft round dots
    #: computed in the shader, which is enough for sparks, glows and embers and
    #: costs no asset.
    texture = field.newField('texture', 'SFString', 1, '')
    #: ``additive`` for light, ``alpha`` for smoke.
    blending = field.newField('blending', 'SFString', 1, 'additive')

    #: Whether particles keep moving once the emitter has moved on.  True is
    #: right for a rocket trail; False for a torch flame, which should travel
    #: with the torch.
    worldSpace = field.newField('worldSpace', 'SFBool', 1, True)
    #: A disabled emitter emits nothing but still ages what is already out, so
    #: switching it off lets the smoke clear rather than freezing it.
    enabled = field.newField('enabled', 'SFBool', 1, True)
    #: Whether the first :attr:`burst` is released as soon as the emitter is
    #: drawn.  True is what a firework or a one-shot puff in an authored scene
    #: wants.  **False is what an emitter that exists to be fired later wants**:
    #: an explosion put in a scene and driven by events would otherwise go off
    #: at its own origin the moment the level was first drawn.
    burstOnStart = field.newField('burstOnStart', 'SFBool', 1, True)
    #: Fixes the sequence of an emitter, for a reproducible reference image.
    seed = field.newField('seed', 'SFInt32', 1, -1)

    UI_HINTS = {
        'rate': {'label': 'Particles per second', 'minimum': 0.0,
                 'maximum': 2000.0, 'step': 10.0},
        'maxParticles': {'label': 'Budget', 'minimum': 1, 'maximum': 20000,
                         'step': 100},
        'lifetime': {'label': 'Lifetime', 'minimum': 0.05, 'maximum': 30.0,
                     'step': 0.05, 'suffix': 's'},
        'speed': {'label': 'Speed', 'minimum': 0.0, 'maximum': 100.0, 'step': 0.5},
        'spread': {'label': 'Cone half-angle', 'minimum': 0.0,
                   'maximum': math.pi, 'step': 0.05},
        'drag': {'label': 'Air drag', 'minimum': 0.0, 'maximum': 10.0, 'step': 0.1},
        'size': {'label': 'Size at birth', 'minimum': 0.0, 'maximum': 20.0,
                 'step': 0.05},
        'endSize': {'label': 'Size at death', 'minimum': 0.0, 'maximum': 20.0,
                    'step': 0.05},
        'blending': {'label': 'Blending', 'options': ('additive', 'alpha'),
                     'optionLabels': ('Light (additive)', 'Smoke (alpha)')},
        'enabled': {'label': 'Emitting'},
        'burstOnStart': {'label': 'Burst on start'},
    }

    def __init__(self, **named: Any) -> None:
        super(ParticleEmitter, self).__init__(**named)
        self._pool: Optional[ParticlePool] = None
        self._pending = float(self.burst) if self.burstOnStart else 0.0
        self._stepped: Optional[float] = None
        self._gl: Any = None
        self._disabled = False

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    @property
    def pool(self) -> ParticlePool:
        """The particle store, made on first use and resized with the budget."""
        if self._pool is None or self._pool.capacity != self.maxParticles:
            seed = None if self.seed < 0 else int(self.seed)
            self._pool = ParticlePool(capacity=self.maxParticles, seed=seed)
        return self._pool

    @property
    def particleCount(self) -> int:
        """How many particles are alive, for a debug overlay."""
        return self.pool.live

    def fire(self) -> None:
        """Release another burst on the next step.  An explosion, a muzzle flash."""
        self._pending += float(self.burst)

    def burst_at(self, position: Vector, direction: Optional[Vector] = None,
                 count: Optional[int] = None) -> int:
        """Release a burst at a point, without moving the emitter.  Returns how many.

        **One emitter, many places.**  A shotgun's eight pellets land eight
        metres apart and each wants its own puff; :meth:`fire` would give all
        eight the emitter's single position, and a node per impact would mean
        allocating scenegraph nodes in a firefight.  So the styling — colour,
        size, life, gravity, drag — stays with this one emitter and the *place*
        arrives per burst.

        ``position`` is in the frame the particles live in: world space for a
        ``worldSpace`` emitter, and the emitter's own space otherwise.
        ``direction`` is what the particles are thrown along, which for an
        impact is the surface normal; without one the emitter's own
        :attr:`direction` is used.  ``count`` overrides :attr:`burst`.

        A disabled emitter bursts nothing, so an effects setting that switches
        a kind off switches it off however it is asked.
        """
        if not self.enabled:
            return 0
        wanted = int(self.burst if count is None else count)
        if wanted <= 0:
            return 0
        return self._emit(wanted, position, direction)

    def _emit(self, count: int, position: Vector,
              direction: Optional[Vector]) -> int:
        """Bring ``count`` particles into being, styled by this emitter.

        The one place the node's fields are read into a pool emission, so
        :meth:`simulate` and :meth:`burst_at` cannot drift apart about what a
        particle of this emitter looks like when it is born.
        """
        return self.pool.emit(
            count,
            position=position,
            velocity=np.asarray(
                direction if direction is not None else self.direction,
                dtype=np.float64)[:3] * self.speed,
            spread=self.spread, speed_variation=self.speedVariation,
            lifetime=self.lifetime,
            lifetime_variation=self.lifetimeVariation,
            # A particle's own size is the *deviation* from the emitter's,
            # mean 1.0.  The absolute size, and how it changes over a life,
            # are the emitter's two uniforms -- so editing `size` on a live
            # emitter resizes the particles already in the air rather than
            # only the next ones.
            size=1.0, size_variation=self.sizeVariation,
            spin=self.spin, spin_variation=self.spinVariation)

    def simulate(self, dt: float, origin: Vector = (0.0, 0.0, 0.0),
                 direction: Optional[Vector] = None) -> None:
        """Emit, then advance, by ``dt`` seconds.

        ``origin`` and ``direction`` are where the emitter is in the frame the
        particles live in -- world space when ``worldSpace`` is set, and the
        emitter's own local origin when it is not.  The render pass supplies
        them from the node's accumulated transform.
        """
        if dt < 0.0:
            return
        dt = min(dt, MAX_STEP)
        pool = self.pool
        if self.enabled:
            self._pending += float(self.rate) * dt
            count = int(self._pending)
            if count > 0:
                self._pending -= count
                self._emit(count,
                           origin if self.worldSpace else (0.0, 0.0, 0.0),
                           direction)
        pool.step(dt, gravity=self.gravity, drag=self.drag)

    def _advance(self, origin: Vector,
                 direction: Optional[Vector]) -> None:
        """Step the simulation by however long it is since the last frame.

        Driven from the draw rather than from a clock of its own, because the
        draw is the only per-frame hook a scenegraph node has.  A scene rendered
        twice in one frame -- a shadow pass, a selection pass -- therefore steps
        by nearly zero the second time, which is harmless, rather than twice.

        The engine's clock, not the wall clock: a capture advances it a frame's
        worth per frame drawn and a recording steps it the same way, and a
        simulation that read real time would be the one thing in the scene not
        following.  See OpenGLContext.events.systemtime.
        """
        now = systemtime.systemTime()
        elapsed = 0.0 if self._stepped is None else now - self._stepped
        self._stepped = now
        self.simulate(elapsed, origin=origin, direction=direction)

    # ------------------------------------------------------------------
    # Appearance over a particle's life
    # ------------------------------------------------------------------

    def sizeAt(self, fraction: float) -> float:
        """A particle's size multiplier ``fraction`` of the way through its life."""
        return float(self.size + (self.endSize - self.size) * fraction)

    def colorAt(self, fraction: float) -> Tuple[float, float, float]:
        """A particle's colour ``fraction`` of the way through its life."""
        start = np.asarray(self.color, dtype='d')
        end = np.asarray(self.endColor, dtype='d')
        return tuple(start + (end - start) * fraction)

    def alphaAt(self, fraction: float) -> float:
        """A particle's opacity ``fraction`` of the way through its life."""
        return float(self.alpha + (self.endAlpha - self.alpha) * fraction)

    def lifeUniforms(self) -> Dict[str, Any]:
        """The life curves as the two ends the shader interpolates between.

        Two ends and a lerp rather than a gradient texture: it covers every
        effect this system is for, it costs two uniforms instead of a texture
        unit, and it can be edited from a settings screen.
        """
        return {
            'sizeRange': (float(self.size), float(self.endSize)),
            'startColor': tuple(self.color) + (float(self.alpha),),
            'endColor': tuple(self.endColor) + (float(self.endAlpha),),
        }

    def blendMode(self) -> Tuple[int, int]:
        """The GL blend factors for this emitter's ``blending``.

        An unrecognised name falls back to additive rather than raising: a
        misspelled string in a scene file should cost the effect its look, not
        the whole frame.
        """
        mode = BLEND_MODES.get(self.blending)
        if mode is None:
            log.warning('unknown particle blending %r; using additive',
                        self.blending)
            mode = BLEND_MODES['additive']
        return mode

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def sortKey(self, mode: Any, matrix: Any) -> Tuple[Any, ...]:
        """Always transparent, and sorted by depth like any other blended thing.

        Shape's key is ``(transparent, textures, distance, ...)``; this matches
        it so the pass needs no special case for an effect.
        """
        return (True, [], 0.0, None)

    def boundingVolume(self, mode: Any) -> Any:
        """A box covering both this emitter's reach and its living particles.

        **Where the particles are, not where the node is.**  An emitter driven
        by :meth:`burst_at` never moves -- the styling stays on one node and
        the *place* arrives per burst -- so a bound around the node is a bound
        around wherever that node happens to sit, and the frustum filter throws
        the whole system away whenever that point is off screen.  In a level
        that is almost always, and the effect is then born, never stepped and
        never drawn.

        The emitter's own reach is always included, so an emitter with a
        ``rate`` and an empty pool is still visited and still starts emitting.
        Beyond that the box is the living particles' own extent, which is one
        pass of numpy over a packed array and shrinks again as they die.
        """
        reach = float(self.speed) * float(self.lifetime) * (1.0 + self.speedVariation)
        reach += float(np.linalg.norm(self.gravity)) * self.lifetime ** 2 * 0.5
        reach = max(reach, float(self.size)) + float(self.size)
        low = np.full(3, -reach)
        high = np.full(3, reach)
        pool = self.pool
        if pool.live:
            # The particles' own size counts: a sprite is drawn about its
            # centre, so a burst exactly on the frustum edge is still visible.
            margin = max(float(self.size), float(self.endSize))
            live = pool.position[:pool.live]
            low = np.minimum(low, live.min(axis=0) - margin)
            high = np.maximum(high, live.max(axis=0) + margin)
        return boundingvolume.AABoundingBox(
            size=tuple(float(value) for value in (high - low)),
            center=tuple(float(value) for value in (low + high) * 0.5))

    def Render(self, mode: Any = None) -> int:
        """Nothing: an effect is blended, so it is drawn in the transparent pass."""
        return 1

    def RenderTransparent(self, mode: Any = None) -> int:
        """Step the simulation and draw every living particle in one call."""
        if getattr(mode, 'shadow_pass', False) or not getattr(mode, 'visible', True):
            return 1
        origin, direction = self._pose(mode)
        self._advance(origin, direction)
        if not self.pool.live or not ensure_gl(self):
            return 1
        self._draw(mode)
        return 1

    def _worldMatrix(self, mode: Any) -> Optional[np.ndarray]:
        """This node's accumulated model matrix, without the camera.

        The pass hands a node its *model-view*; the model half is on the node
        path it also publishes, and a ``NodePath`` caches it, so asking costs
        nothing per frame.
        """
        path = getattr(mode, 'renderPath', None)
        if path is None:
            return None
        return np.asarray(path.transformMatrix())

    def _pose(self, mode: Any) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Where the emitter is, in the frame its particles live in.

        A world-space system emits at the node's world position, with its
        emission direction rotated into world space, and thereafter ignores the
        node entirely -- which is what lets a rocket's trail stay behind the
        rocket.  A local-space system emits at its own origin and is carried
        along by the transform like any other geometry.
        """
        matrix = self._worldMatrix(mode) if self.worldSpace else None
        if matrix is None:
            return np.zeros(3), None
        direction = np.dot(np.append(np.asarray(self.direction, dtype='d')[:3], 0.0),
                           matrix)[:3]
        return matrix[3, :3], direction

    def _init_gl(self) -> None:
        """Compile the program and build the one quad every particle reuses."""
        program = load_program('particle.vert', 'particle.frag')
        uniforms = {name: int(glGetUniformLocation(program, name)) for name in (
            'uModelView', 'uProjection', 'uSizeRange', 'uStartColor',
            'uEndColor', 'uTexture', 'uHasTexture')}
        vao = int(glGenVertexArrays(1))
        glBindVertexArray(vao)
        # One unit quad as a triangle strip, in the corner coordinates the
        # vertex shader billboards and the fragment shader reads as a sprite.
        corners = np.array([[-0.5, -0.5], [0.5, -0.5], [-0.5, 0.5], [0.5, 0.5]],
                           dtype=np.float32)
        quad = int(glGenBuffers(1))
        glBindBuffer(GL_ARRAY_BUFFER, quad)
        glBufferData(GL_ARRAY_BUFFER, corners.nbytes, corners, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 8, None)
        glEnableVertexAttribArray(0)
        instances = InstanceBuffer()
        glBindBuffer(GL_ARRAY_BUFFER, instances.id)
        stride = INSTANCE_FLOATS * 4
        _instance_attribute(1, 4, stride, 0)                    # position + size
        _instance_attribute(2, 3, stride, INSTANCE_ROTATION * 4)  # spin, life, random
        glBindVertexArray(0)
        texture = 0
        if self.texture:
            try:
                texture = int(texture_rgba(self.texture, clamp=True))
            except Exception as error:
                log.warning('particle texture %r not loaded: %s', self.texture, error)
        self._gl = {'program': program, 'uniforms': uniforms, 'vao': vao,
                    'quad': quad, 'instances': instances, 'texture': texture}

    def _draw(self, mode: Any) -> None:
        """Upload this frame's particles and issue the instanced draw."""
        gl = self._gl
        uniforms = gl['uniforms']
        rows = self.pool.instances()
        from OpenGLContext.passes.instancing import set_cull_state
        previous = mode.current_program() if hasattr(mode, "current_program") else 0
        glUseProgram(gl['program'])
        glBindVertexArray(gl['vao'])
        gl['instances'].upload(rows)

        life = self.lifeUniforms()
        # World-space particles already carry the emitter's transform in their
        # positions, so only the camera part may be applied to them; local-space
        # ones have not, and want the whole model-view. Choosing the matrix here
        # keeps the shader free of a branch it would take per vertex.
        view = mode.getModelView() if self.worldSpace else mode.matrix
        glUniformMatrix4fv(uniforms['uModelView'], 1, GL_FALSE,
                           np.ascontiguousarray(view, np.float32))
        glUniformMatrix4fv(uniforms['uProjection'], 1, GL_FALSE,
                           np.ascontiguousarray(mode.projection, np.float32))
        glUniform2f(uniforms['uSizeRange'], *life['sizeRange'])
        glUniform4f(uniforms['uStartColor'], *life['startColor'])
        glUniform4f(uniforms['uEndColor'], *life['endColor'])
        glUniform1i(uniforms['uHasTexture'], 1 if gl['texture'] else 0)
        if gl['texture']:
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, gl['texture'])
            glUniform1i(uniforms['uTexture'], 0)

        glEnable(GL_BLEND)
        glBlendFunc(*self.blendMode())
        glEnable(GL_DEPTH_TEST)
        # Depth *tested* so particles disappear behind walls, depth *writes* off
        # so they never occlude each other -- which is what makes a cloud read as
        # a cloud instead of as a pile of squares. Blend and depth-write are the
        # transparent pass's own phase state, restored by it at phase end; only the
        # cull disable is ours, so it goes through the pass's cull memo (a quad has
        # no back face) rather than a glGet snapshot.
        glDepthMask(GL_FALSE)
        set_cull_state(mode, False, GL_CCW)
        glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, gl['instances'].count)
        glBindVertexArray(0)
        glUseProgram(previous)

    def delete(self) -> None:
        """Release the GL objects this emitter owns."""
        gl, self._gl = self._gl, None
        if gl:
            gl['instances'].delete()
            delete_gl(vaos=[gl['vao']], buffers=[gl['quad']],
                      textures=[gl['texture']] if gl['texture'] else [],
                      programs=[gl['program']])


def _instance_attribute(location: int, size: int, stride: int, offset: int) -> None:
    """One per-instance vertex attribute on the bound VAO."""
    import ctypes

    glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE, stride,
                          ctypes.c_void_p(offset))
    glEnableVertexAttribArray(location)
    glVertexAttribDivisor(location, 1)


#: Starting points for the effects this system exists to draw.  A preset is a
#: set of field values and nothing more, so anything it does can be done by hand
#: -- but an explosion should be one line, not twenty, and these are what the
#: numbers for one actually look like.
PRESETS: Dict[str, Dict[str, Any]] = {
    'explosion': dict(
        rate=0.0, burst=180, maxParticles=256, lifetime=0.9, lifetimeVariation=0.5,
        direction=(0.0, 1.0, 0.0), speed=9.0, speedVariation=0.7, spread=math.pi,
        gravity=(0.0, -3.0, 0.0), drag=2.5,
        size=0.9, endSize=0.05, sizeVariation=0.5,
        color=(1.0, 0.9, 0.5), endColor=(0.8, 0.15, 0.0),
        alpha=1.0, endAlpha=0.0, blending='additive'),
    'fire': dict(
        rate=140.0, burst=0, maxParticles=400, lifetime=1.1, lifetimeVariation=0.4,
        direction=(0.0, 1.0, 0.0), speed=1.6, speedVariation=0.4, spread=0.35,
        gravity=(0.0, 1.4, 0.0), drag=1.2,
        size=0.5, endSize=0.05, sizeVariation=0.4, spin=1.5,
        color=(1.0, 0.85, 0.35), endColor=(0.7, 0.08, 0.0),
        alpha=0.9, endAlpha=0.0, blending='additive'),
    'smoke': dict(
        rate=28.0, burst=0, maxParticles=200, lifetime=4.0, lifetimeVariation=0.4,
        direction=(0.0, 1.0, 0.0), speed=0.7, speedVariation=0.5, spread=0.5,
        gravity=(0.0, 0.35, 0.0), drag=0.6,
        size=0.4, endSize=2.4, sizeVariation=0.4, spin=0.5,
        color=(0.35, 0.35, 0.38), endColor=(0.12, 0.12, 0.14),
        alpha=0.45, endAlpha=0.0, blending='alpha'),
    'sparks': dict(
        rate=0.0, burst=60, maxParticles=128, lifetime=0.7, lifetimeVariation=0.6,
        direction=(0.0, 1.0, 0.0), speed=6.0, speedVariation=0.8, spread=math.pi / 2,
        gravity=(0.0, -12.0, 0.0), drag=0.3,
        size=0.09, endSize=0.01, sizeVariation=0.5,
        color=(1.0, 0.95, 0.7), endColor=(1.0, 0.4, 0.05),
        alpha=1.0, endAlpha=0.0, blending='additive'),
    'trail': dict(
        rate=90.0, burst=0, maxParticles=200, lifetime=1.0, lifetimeVariation=0.3,
        direction=(0.0, 0.0, 0.0), speed=0.0, spread=0.0,
        gravity=(0.0, 0.4, 0.0), drag=1.5,
        size=0.25, endSize=0.9, sizeVariation=0.4,
        color=(0.7, 0.7, 0.75), endColor=(0.2, 0.2, 0.22),
        alpha=0.5, endAlpha=0.0, blending='alpha'),
    # Stylised rather than realistic, on purpose: bright, brief and readable
    # across a room at speed is what this feedback is for.
    'impact': dict(
        rate=0.0, burst=40, maxParticles=96, lifetime=0.45, lifetimeVariation=0.5,
        direction=(0.0, 1.0, 0.0), speed=4.5, speedVariation=0.7, spread=1.2,
        gravity=(0.0, -9.0, 0.0), drag=1.0,
        size=0.18, endSize=0.02, sizeVariation=0.6,
        color=(1.0, 0.35, 0.3), endColor=(0.45, 0.02, 0.02),
        alpha=1.0, endAlpha=0.0, blending='additive'),
}


def preset(name: str, **overrides: Any) -> ParticleEmitter:
    """A :class:`ParticleEmitter` from a named preset, with fields overridden.

    Raises:
        KeyError: for a name that is not a preset.  Falling back to a default
            would give an effect that silently looks nothing like what was
            asked for, which is harder to notice than an exception.
    """
    if name not in PRESETS:
        raise KeyError('no particle preset named %r; have %s'
                       % (name, ', '.join(sorted(PRESETS))))
    fields = dict(PRESETS[name])
    fields.update(overrides)
    return ParticleEmitter(**fields)
