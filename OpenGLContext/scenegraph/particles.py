"""Particles: an emitter node, and one instanced draw per system.

A particle system is a **simulation with a renderer bolted on**, and keeping
those two apart is most of the design. The simulation (the pool, where
particles start, what moves them, how they look over a life) is
:mod:`~OpenGLContext.scenegraph.particlesim`, which uses no GL. This module
draws it:

:class:`ParticleRenderer`
    The GL for one system: a program, the quad every particle reuses, and an
    instance buffer, drawn in one ``glDrawArraysInstanced`` as sprites, quads,
    lines or points (:class:`ParticleLook`).
:class:`ParticleEmitter`
    A scenegraph node holding a pool, the shape of what comes out of it, and a
    renderer.

**What varies per particle is state; what is shared is a curve.**  A particle
carries a position, a velocity, an age, a base size, a rotation, one random
number and, where the system has a colour ramp, a colour.  Its size over its
life, and the two ends of its colour, are the system's, evaluated in the shader
from the normalised age, so changing an effect's colour costs a uniform rather
than a rewrite of the pool.

The pool keeps its living particles **packed at the front** of its arrays, so
the live set is always ``[0:live]`` and the GPU upload is one contiguous slice.
That is what makes a thousand particles one ``glBufferSubData`` and one
``glDrawArraysInstanced``.

Particles are unlit: a particle effect is light and smoke, not a surface. A
blended system draws in the transparent pass with depth writes off; an opaque
one (X3D's, where nothing is translucent) draws with the opaque geometry and
writes depth. Neither enters a shadow map.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_CCW, GL_DEPTH_TEST, GL_FALSE, GL_FLOAT, GL_LINES,
    GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_POINTS, GL_PROGRAM_POINT_SIZE, GL_SRC_ALPHA,
    GL_STATIC_DRAW, GL_TEXTURE0, GL_TEXTURE_2D, GL_TRIANGLE_STRIP, GL_TRUE,
    glActiveTexture, glBindBuffer, glBindTexture, glBindVertexArray, glBlendFunc,
    glBufferData, glDepthMask, glDisable, glDrawArraysInstanced, glEnable,
    glEnableVertexAttribArray, glGenBuffers, glGenVertexArrays, glGetUniformLocation,
    glUniform1f, glUniform1i, glUniform2f, glUniform2fv, glUniform3f, glUniform4f,
    glUniformMatrix4fv, glUseProgram, glVertexAttribDivisor, glVertexAttribPointer,
)
from vrml import field, node
from vrml.vrml97 import nodetypes

from OpenGLContext.events import systemtime
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.instancedgl import (
    GLLayer, InstanceBuffer, delete_gl, load_program, texture_rgba,
)
from OpenGLContext.scenegraph.particlesim import (
    INSTANCE_COLOR, INSTANCE_FLOATS, INSTANCE_FRAME, INSTANCE_LIFE, INSTANCE_POSITION,
    INSTANCE_RANDOM, INSTANCE_ROTATION, INSTANCE_SIZE, INSTANCE_VELOCITY,
    MAX_STEP, MIN_LIFETIME, ColorRamp, Emission, ParticleModel, ParticlePool,
    StepClock, launch,
)

__all__ = [
    'BLEND_MODES', 'SHAPES', 'MAX_FRAMES', 'ParticleLook', 'ParticleRenderer',
    'ParticleEmitter', 'ParticlePool', 'PRESETS', 'preset', 'ramp_colors',
    'MAX_STEP', 'MIN_LIFETIME', 'INSTANCE_POSITION', 'INSTANCE_SIZE',
    'INSTANCE_ROTATION', 'INSTANCE_LIFE', 'INSTANCE_RANDOM', 'INSTANCE_FRAME',
    'INSTANCE_COLOR', 'INSTANCE_VELOCITY', 'INSTANCE_FLOATS',
]

log = logging.getLogger(__name__)

#: Anything three numbers long: a tuple, a VRML field, or a numpy row.
Vector = Sequence[float] | np.ndarray

#: Blend factors by name.  Additive is the default because most effects are
#: light -- fire, sparks, explosions, muzzle flashes -- and light adds.  Alpha is
#: for the things that block light instead: smoke, dust, steam.  An opaque
#: system blends nothing and writes depth.
BLEND_MODES: dict[str, Optional[tuple[int, int]]] = {
    'additive': (GL_SRC_ALPHA, GL_ONE),
    'alpha': (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
    'opaque': None,
}

#: What a particle can be drawn as, by name, each the shader's ``uShape``: a
#: quad facing the camera, a quad in the system's XY plane, a line along its
#: velocity, a point.
SHAPES: dict[str, int] = {'sprite': 0, 'quad': 1, 'line': 2, 'point': 3}

#: The most texture-coordinate frames a system steps through; the shader's
#: ``MAX_FRAMES``.
MAX_FRAMES = 16

#: The fragments an opaque system cuts out of its texture, and the ones a
#: blended system does not bother to blend: those with no more alpha than this.
OPAQUE_CUTOFF = 0.5
BLENDED_CUTOFF = 0.002

#: The vertices every particle is drawn from: the four corners of the quad as a
#: triangle strip, the two ends of a line, and a point.
_CORNERS = np.array([[-0.5, -0.5], [0.5, -0.5], [-0.5, 0.5], [0.5, 0.5],
                     [0.0, -0.5], [0.0, 0.5], [0.0, 0.0]], dtype=np.float32)
#: (primitive, first vertex, vertex count) for each shape.
_DRAWS: dict[int, tuple[int, int, int]] = {
    0: (GL_TRIANGLE_STRIP, 0, 4), 1: (GL_TRIANGLE_STRIP, 0, 4),
    2: (GL_LINES, 4, 2), 3: (GL_POINTS, 6, 1),
}

_UNIFORMS = ('uModelView', 'uProjection', 'uShape', 'uSize', 'uSizeRange',
             'uStartColor', 'uEndColor', 'uFrameCount', 'uFrames', 'uPointSize',
             'uPointAttenuation', 'uTexture', 'uHasTexture', 'uRound', 'uCutoff')

Color4 = tuple[float, float, float, float]


@dataclass(frozen=True)
class ParticleLook:
    """How a system's particles are drawn, shared by all of them.

    ``shape`` is a key of :data:`SHAPES`. ``size`` is the width and height in
    world units, multiplied over a particle's life from ``size_range[0]`` to
    ``size_range[1]``; the colour likewise goes from ``start_color`` to
    ``end_color``, multiplied by each particle's own. ``texture`` is a GL
    texture name, 0 for none; a particle with no texture is a soft dot where
    ``round`` and its flat colour otherwise. ``frames`` holds four texture
    coordinates per frame, at most :data:`MAX_FRAMES` frames. ``blending`` is
    a key of :data:`BLEND_MODES`. A point is ``point_size`` pixels (scale,
    least and most) divided by ``point_attenuation`` (constant, linear and
    quadratic in the distance from the eye).
    """

    shape: str = 'sprite'
    size: tuple[float, float] = (1.0, 1.0)
    size_range: tuple[float, float] = (1.0, 1.0)
    start_color: Color4 = (1.0, 1.0, 1.0, 1.0)
    end_color: Color4 = (1.0, 1.0, 1.0, 1.0)
    texture: int = 0
    round: bool = True
    frames: Optional[np.ndarray] = None
    blending: str = 'additive'
    point_size: tuple[float, float, float] = (1.0, 1.0, 1.0)
    point_attenuation: tuple[float, float, float] = (1.0, 0.0, 0.0)

    @property
    def opaque(self) -> bool:
        """Whether the system draws with the opaque geometry, writing depth"""
        return self.blending == 'opaque'


def blend_factors(name: str) -> Optional[tuple[int, int]]:
    """The GL blend factors for a blending name; None for an opaque system.

    An unrecognised name falls back to additive rather than raising: a
    misspelled string in a scene file should cost the effect its look, not
    the whole frame.
    """
    if name not in BLEND_MODES:
        log.warning('unknown particle blending %r; using additive', name)
        return BLEND_MODES['additive']
    return BLEND_MODES[name]


def ramp_colors(keys: Any, colorNode: Any) -> ColorRamp:
    """A ramp of the colours of a ``Color`` or ``ColorRGBA`` node at ``keys``

    An empty ramp where there is no node or no colours.
    """
    values = getattr(colorNode, 'color', None) if colorNode else None
    if values is None or not len(values):
        return ColorRamp([], [])
    return ColorRamp(np.asarray(keys, dtype=np.float64), np.asarray(values, dtype=np.float64))


class ParticleRenderer:
    """The GL objects that draw one particle system, made with a context current.

    :meth:`draw` uploads the instance rows (:meth:`ParticlePool.instances`)
    and draws them all in one call, in the look given. The pass's program, its
    phase's blending and depth writes, and the face culling are put back as the
    pass keeps them.
    """

    def __init__(self) -> None:
        self.program = load_program('particle.vert', 'particle.frag')
        self.uniforms = {name: int(glGetUniformLocation(self.program, name))
                         for name in _UNIFORMS}
        self.vao = int(glGenVertexArrays(1))
        glBindVertexArray(self.vao)
        self.corners = int(glGenBuffers(1))
        glBindBuffer(GL_ARRAY_BUFFER, self.corners)
        glBufferData(GL_ARRAY_BUFFER, _CORNERS.nbytes, _CORNERS, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 8, None)
        glEnableVertexAttribArray(0)
        self.instances = InstanceBuffer()
        glBindBuffer(GL_ARRAY_BUFFER, self.instances.id)
        stride = INSTANCE_FLOATS * 4
        _instance_attribute(1, 4, stride, INSTANCE_POSITION * 4)   # position, size
        _instance_attribute(2, 4, stride, INSTANCE_ROTATION * 4)   # spin, life, random, frame
        _instance_attribute(3, 4, stride, INSTANCE_COLOR * 4)
        _instance_attribute(4, 3, stride, INSTANCE_VELOCITY * 4)
        glBindVertexArray(0)

    def dispose(self) -> None:
        """Delete the GL objects, with their context current"""
        self.instances.delete()
        delete_gl(vaos=[self.vao], buffers=[self.corners], programs=[self.program])

    def draw(self, rows: np.ndarray, look: ParticleLook, mode: Any,
             modelview: Any) -> None:
        """Draw ``rows`` in ``look``, placed by ``modelview``"""
        from OpenGLContext.passes.instancing import set_cull_state
        uniforms = self.uniforms
        shape = SHAPES.get(look.shape, 0)
        previous = mode.current_program() if hasattr(mode, 'current_program') else 0
        glUseProgram(self.program)
        glBindVertexArray(self.vao)
        self.instances.upload(rows)
        glUniformMatrix4fv(uniforms['uModelView'], 1, GL_FALSE,
                           np.ascontiguousarray(modelview, np.float32))
        glUniformMatrix4fv(uniforms['uProjection'], 1, GL_FALSE,
                           np.ascontiguousarray(mode.projection, np.float32))
        glUniform1i(uniforms['uShape'], shape)
        glUniform2f(uniforms['uSize'], *look.size)
        glUniform2f(uniforms['uSizeRange'], *look.size_range)
        glUniform4f(uniforms['uStartColor'], *look.start_color)
        glUniform4f(uniforms['uEndColor'], *look.end_color)
        frames = look.frames if shape in (0, 1) else None
        count = 0 if frames is None else min(len(frames), MAX_FRAMES)
        glUniform1i(uniforms['uFrameCount'], count)
        if count:
            corners = np.ascontiguousarray(np.asarray(frames, np.float32)[:count]
                                           .reshape(-1, 2))
            glUniform2fv(uniforms['uFrames'], len(corners), corners)
        glUniform3f(uniforms['uPointSize'], *look.point_size)
        glUniform3f(uniforms['uPointAttenuation'], *look.point_attenuation)
        glUniform1i(uniforms['uRound'], 1 if look.round else 0)
        glUniform1i(uniforms['uHasTexture'], 1 if look.texture else 0)
        if look.texture:
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, look.texture)
            glUniform1i(uniforms['uTexture'], 0)
        factors = blend_factors(look.blending)
        glUniform1f(uniforms['uCutoff'], OPAQUE_CUTOFF if factors is None else BLENDED_CUTOFF)
        glEnable(GL_DEPTH_TEST)
        if factors is not None:
            # Depth *tested* so particles disappear behind walls, depth *writes*
            # off so they never occlude each other -- which is what makes a
            # cloud read as a cloud instead of as a pile of squares.
            glEnable(GL_BLEND)
            glBlendFunc(*factors)
            glDepthMask(GL_FALSE)
        else:
            glDisable(GL_BLEND)
            glDepthMask(GL_TRUE)
        # Only the cull disable is ours, so it goes through the pass's cull memo
        # (a particle quad is seen from both sides) rather than a glGet snapshot.
        set_cull_state(mode, False, GL_CCW)
        primitive, first, vertices = _DRAWS[shape]
        if shape == 3:
            glEnable(GL_PROGRAM_POINT_SIZE)
        try:
            glDrawArraysInstanced(primitive, first, vertices, self.instances.count)
        finally:
            if shape == 3:
                glDisable(GL_PROGRAM_POINT_SIZE)
            _restore_phase(mode)
            glBindVertexArray(0)
            glUseProgram(previous)


def _restore_phase(mode: Any) -> None:
    """Put back the blending and depth writes of the phase ``mode`` is drawing

    The transparent phase blends straight alpha over without writing depth;
    the opaque phase does neither. A particle system draws in its own blend
    and leaves the shapes after it the phase's.
    """
    if getattr(mode, 'transparent', False):
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
    else:
        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)


def _instance_attribute(location: int, size: int, stride: int, offset: int) -> None:
    """One per-instance vertex attribute on the bound VAO."""
    import ctypes

    glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE, stride,
                          ctypes.c_void_p(offset))
    glEnableVertexAttribArray(location)
    glVertexAttribDivisor(location, 1)


def models_of(nodes: Any, **named: Any) -> list[ParticleModel]:
    """The simulation models of physics-model nodes, in order

    Each node answers ``particleModel(**named)``; a node without one, or one
    switched off (its ``enabled`` False), contributes nothing.
    """
    found: list[ParticleModel] = []
    for entry in nodes or ():
        answer = getattr(entry, 'particleModel', None)
        if answer is None or not getattr(entry, 'enabled', True):
            continue
        model = answer(**named)
        if model is not None:
            found.append(model)
    return found


class ParticleEmitter(nodetypes.Rendering, nodetypes.Children, node.Node, GLLayer):
    """A source of particles in the scene, drawn in one instanced call.

    Put it under a ``Transform`` and the particles come from there.  It is a
    *rendering* node in its own right rather than a geometry inside a ``Shape``:
    an effect has no material and no surface, and pretending it does would mean
    an ``Appearance`` whose every field is ignored.

    The fields divide into three groups, and it helps to read them that way:
    **how many and how often** (``rate``, ``burst``, ``maxParticles``,
    ``lifetime``), **where from, which way and how fast** (``source``,
    ``direction``, ``speed``, ``spread``, ``gravity``, ``drag``, ``physics``),
    and **what it looks like** (``size``, ``color``, ``alpha``, their ``end*``
    counterparts, ``colorKey`` and ``colorRamp``, ``texture``, ``shape``,
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

    #: Where particles start and which way they are thrown, in the emitter's own
    #: frame: one of X3D's emitter nodes (``ConeEmitter``, ``PolylineEmitter``,
    #: ``SurfaceEmitter``, ...). Without one they start at the emitter's origin
    #: and are thrown within ``spread`` of ``direction``.
    source = field.newField('source', 'SFNode', 1, node.NULL)
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
    #: Physics-model nodes acting on the particles after gravity and drag, in
    #: order: X3D's ``ForcePhysicsModel``, ``WindPhysicsModel`` and
    #: ``BoundedPhysicsModel``. Their geometry is in the frame the particles
    #: live in.
    physics = field.newField('physics', 'MFNode', 1, list)
    #: The mass and surface area of a particle, which a force and the wind act
    #: on; a mass of 0 takes a force as an acceleration.
    mass = field.newField('mass', 'SFFloat', 1, 0.0)
    surfaceArea = field.newField('surfaceArea', 'SFFloat', 1, 0.0)

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
    #: A colour ramp over a particle's life, in place of the two ends: the
    #: colours of a ``Color`` or ``ColorRGBA`` node, each at the fraction of
    #: the life in ``colorKey`` of the same index.
    colorKey = field.newField('colorKey', 'MFFloat', 1, list)
    colorRamp = field.newField('colorRamp', 'SFNode', 1, node.NULL)

    #: A sprite for each particle.  Without one, particles are soft round dots
    #: computed in the shader, which is enough for sparks, glows and embers and
    #: costs no asset.
    texture = field.newField('texture', 'SFString', 1, '')
    #: ``sprite`` for a quad facing the camera, ``line`` for a streak along the
    #: particle's velocity as long as its size.
    shape = field.newField('shape', 'SFString', 1, 'sprite')
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
        'shape': {'label': 'Drawn as', 'options': ('sprite', 'line'),
                  'optionLabels': ('Sprites', 'Streaks')},
        'blending': {'label': 'Blending', 'options': ('additive', 'alpha'),
                     'optionLabels': ('Light (additive)', 'Smoke (alpha)')},
        'enabled': {'label': 'Emitting'},
        'burstOnStart': {'label': 'Burst on start'},
    }

    def __init__(self, **named: Any) -> None:
        super(ParticleEmitter, self).__init__(**named)
        self._pool: Optional[ParticlePool] = None
        self._emission = Emission()
        if self.burstOnStart:
            self._emission.burst(self.burst)
        self._clock = StepClock(longest=math.inf)
        self._gl: Any = None
        self._texture = 0

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
        self._emission.burst(self.burst)

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
              direction: Optional[Vector], frame: Optional[np.ndarray] = None) -> int:
        """Bring ``count`` particles into being, styled by this emitter.

        The one place the node's fields are read into a pool emission, so
        :meth:`simulate` and :meth:`burst_at` cannot drift apart about what a
        particle of this emitter looks like when it is born. A ``source``
        node's positions are about ``position``, and turned by the rotation of
        ``frame`` where one is given.
        """
        # A particle's own size is the *deviation* from the emitter's, mean
        # 1.0.  The absolute size, and how it changes over a life, are the
        # emitter's two uniforms -- so editing `size` on a live emitter resizes
        # the particles already in the air rather than only the next ones.
        style = dict(lifetime=self.lifetime, lifetime_variation=self.lifetimeVariation,
                     size=1.0, size_variation=self.sizeVariation,
                     spin=self.spin, spin_variation=self.spinVariation)
        sampler = getattr(self.source, 'particleSource', None) if self.source else None
        source = sampler() if sampler is not None else None
        if source is None:
            return self.pool.emit(
                count, position=position,
                velocity=np.asarray(direction if direction is not None else self.direction,
                                    dtype=np.float64)[:3] * self.speed,
                spread=self.spread, speed_variation=self.speedVariation, **style)
        if source.empty:
            return 0
        pool = self.pool
        count = min(count, pool.capacity - pool.live)
        positions, velocities = launch(source, pool.rng, count, self.speed, self.speedVariation)
        if frame is not None:
            turn = _rotation(frame)
            positions = positions @ turn
            velocities = velocities @ turn
        return pool.spawn(positions + np.asarray(position, dtype=np.float64)[:3],
                          velocities, **style)

    def models(self) -> list[ParticleModel]:
        """The simulation models of the :attr:`physics` nodes, in order"""
        return models_of(self.physics, mass=float(self.mass),
                         surfaceArea=float(self.surfaceArea))

    def simulate(self, dt: float, origin: Vector = (0.0, 0.0, 0.0),
                 direction: Optional[Vector] = None,
                 frame: Optional[np.ndarray] = None) -> None:
        """Emit, then advance, by ``dt`` seconds.

        ``origin`` and ``direction`` are where the emitter is in the frame the
        particles live in -- world space when ``worldSpace`` is set, and the
        emitter's own local origin when it is not; ``frame`` is the emitter's
        world matrix, which turns a ``source`` node's positions into world
        space.  The render pass supplies them from the node's accumulated
        transform.
        """
        if dt < 0.0:
            return
        dt = min(dt, MAX_STEP)
        pool = self.pool
        self._emission.rate = float(self.rate)
        count = self._emission.due(dt)
        if self.enabled and count > 0:
            self._emit(count, origin if self.worldSpace else (0.0, 0.0, 0.0),
                       direction, frame if self.worldSpace else None)
        pool.step(dt, gravity=self.gravity, drag=self.drag, models=self.models())

    def _advance(self, origin: Vector, direction: Optional[Vector],
                 frame: Optional[np.ndarray] = None) -> None:
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
        elapsed = self._clock.step(systemtime.systemTime())
        self.simulate(elapsed, origin=origin, direction=direction, frame=frame)

    # ------------------------------------------------------------------
    # Appearance over a particle's life
    # ------------------------------------------------------------------

    def sizeAt(self, fraction: float) -> float:
        """A particle's size multiplier ``fraction`` of the way through its life."""
        return float(self.size + (self.endSize - self.size) * fraction)

    def colorAt(self, fraction: float) -> tuple[float, float, float]:
        """A particle's colour ``fraction`` of the way through its life."""
        ramp = self.colorRampAt()
        if ramp:
            red, green, blue = (float(value) for value in ramp.at(np.array([fraction]))[0, :3])
            return red, green, blue
        start = np.asarray(self.color, dtype='d')
        end = np.asarray(self.endColor, dtype='d')
        return tuple(start + (end - start) * fraction)

    def alphaAt(self, fraction: float) -> float:
        """A particle's opacity ``fraction`` of the way through its life."""
        ramp = self.colorRampAt()
        if ramp:
            return float(ramp.at(np.array([fraction]))[0, 3])
        return float(self.alpha + (self.endAlpha - self.alpha) * fraction)

    def colorRampAt(self) -> ColorRamp:
        """The colour ramp of :attr:`colorKey` and :attr:`colorRamp`; empty without"""
        return ramp_colors(self.colorKey, self.colorRamp)

    def lifeUniforms(self) -> dict[str, Any]:
        """The life curves as the two ends the shader interpolates between.

        Two ends and a lerp rather than a gradient texture: it covers every
        effect this system is for, it costs two uniforms instead of a texture
        unit, and it can be edited from a settings screen. With a colour ramp
        the ends are white and each particle carries its colour from the ramp.
        """
        if self.colorRampAt():
            white = (1.0, 1.0, 1.0, 1.0)
            return {'sizeRange': (float(self.size), float(self.endSize)),
                    'startColor': white, 'endColor': white}
        return {
            'sizeRange': (float(self.size), float(self.endSize)),
            'startColor': tuple(self.color) + (float(self.alpha),),
            'endColor': tuple(self.endColor) + (float(self.endAlpha),),
        }

    def blendMode(self) -> tuple[int, int]:
        """The GL blend factors for this emitter's ``blending``.

        An unrecognised name, or ``opaque``, which an effect does not take,
        falls back to additive rather than raising: a misspelled string in a
        scene file should cost the effect its look, not the whole frame.
        """
        factors = blend_factors(self.blending)
        if factors is None:
            return BLEND_MODES['additive'] or (GL_SRC_ALPHA, GL_ONE)
        return factors

    def look(self) -> ParticleLook:
        """How this emitter's particles are drawn"""
        life = self.lifeUniforms()
        shape = self.shape if self.shape in ('sprite', 'line') else 'sprite'
        blending = self.blending if self.blending in ('additive', 'alpha') else 'additive'
        return ParticleLook(shape=shape, size_range=life['sizeRange'],
                            start_color=life['startColor'], end_color=life['endColor'],
                            texture=self._texture, blending=blending)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def sortKey(self, mode: Any, matrix: Any) -> tuple[Any, ...]:
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
        sampler = getattr(self.source, 'particleSource', None) if self.source else None
        source = sampler() if sampler is not None else None
        if source is not None and not source.empty:
            start, stop = source.extent()
            low = np.minimum(low, start - reach)
            high = np.maximum(high, stop + reach)
        extent = self.pool.extent()
        if extent is not None:
            # The particles' own size counts: a sprite is drawn about its
            # centre, so a burst exactly on the frustum edge is still visible.
            margin = max(float(self.size), float(self.endSize))
            low = np.minimum(low, extent[0] - margin)
            high = np.maximum(high, extent[1] + margin)
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
        frame = self._worldMatrix(mode) if self.worldSpace else None
        self._advance(origin, direction, frame)
        if not self.pool.live or not self.ensure_gl():
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

    def _pose(self, mode: Any) -> tuple[np.ndarray, Optional[np.ndarray]]:
        """Where the emitter is, in the frame its particles live in.

        A world-space system emits at the node's world position, with its
        emission direction rotated into world space, and thereafter ignores the
        node entirely -- which is what lets a rocket's trail stay behind the
        rocket.  A local-space system emits at its own origin and is carried
        along by the transform like any other geometry.

        The direction keeps the length the field gives it. Size and gravity are
        world units the transform does not reach, so a direction stretched by a
        scaled parent would throw the particles faster and leave them the size
        and weight they were.
        """
        matrix = self._worldMatrix(mode) if self.worldSpace else None
        if matrix is None:
            return np.zeros(3), None
        authored = np.asarray(self.direction, dtype='d')[:3]
        direction = np.dot(np.append(authored, 0.0), matrix)[:3]
        turned = float(np.linalg.norm(direction))
        if turned > 0.0:
            direction *= float(np.linalg.norm(authored)) / turned
        return matrix[3, :3], direction

    def _init_gl(self) -> None:
        """Make the renderer, and load the sprite texture where there is one."""
        renderer = ParticleRenderer()
        texture = 0
        if self.texture:
            try:
                texture = int(texture_rgba(self.texture, clamp=True))
            except Exception as error:
                log.warning('particle texture %r not loaded: %s', self.texture, error)
        self._texture = texture
        self._gl = renderer

    def _draw(self, mode: Any) -> None:
        """Upload this frame's particles and issue the instanced draw."""
        pool = self.pool
        ramp = self.colorRampAt()
        colors = ramp.at(pool.life_fraction()) if ramp else None
        # World-space particles already carry the emitter's transform in their
        # positions, so only the camera part may be applied to them; local-space
        # ones have not, and want the whole model-view. Choosing the matrix here
        # keeps the shader free of a branch it would take per vertex.
        view = mode.getModelView() if self.worldSpace else mode.matrix
        self._gl.draw(pool.instances(colors=colors), self.look(), mode, view)

    def dispose(self) -> None:
        """Release the GL objects this emitter owns."""
        renderer, self._gl = self._gl, None
        if renderer is not None:
            renderer.dispose()
        if self._texture:
            delete_gl(textures=[self._texture])
            self._texture = 0


def _rotation(matrix: np.ndarray) -> np.ndarray:
    """The rotation of a row-vector matrix, with its scale divided out"""
    turn = np.asarray(matrix, dtype=np.float64)[:3, :3]
    lengths = np.linalg.norm(turn, axis=1, keepdims=True)
    return np.asarray(turn / np.where(lengths > 0.0, lengths, 1.0))


#: Starting points for the effects this system exists to draw.  A preset is a
#: set of field values and nothing more, so anything it does can be done by hand
#: -- but an explosion should be one line, not twenty, and these are what the
#: numbers for one actually look like.
PRESETS: dict[str, dict[str, Any]] = {
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
