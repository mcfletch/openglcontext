Particle Effects, Explained
===========================

.. rst-class:: introduction

Fire, smoke, sparks, explosions, impacts and trails, drawn as camera-facing
quads — one instanced draw call for a whole system, however many particles are
in it. The simulation is numpy arrays stepped as whole arrays; the renderer is
about a hundred lines of core-profile GL. The two are kept strictly apart,
which is why the interesting half can be tested with no window at all. The
indented technical notes point at the code.

.. figure:: images/demos/particles_effects.jpg
   :alt: Fire, smoke, sparks and an explosion burning side by side in the dark

   The five presets side by side, from ``tests/particles_effects.py``: fire,
   smoke, sparks, an explosion and a trail. None of them loads a texture —
   without one a particle is a soft round dot computed in the fragment shader.

.. _particles-quickstart:

The shortest thing that catches fire
------------------------------------

.. code-block:: python

   from OpenGLContext.scenegraph import particles
   from OpenGLContext.scenegraph.basenodes import Transform

   torch = Transform(translation=(0, 1, -3), children=[
       particles.preset('fire'),
   ])

That is a complete effect. A ``ParticleEmitter`` is a rendering node in its
own right, not a geometry inside a ``Shape``: an effect has no material and no
surface, and pretending it does would mean an ``Appearance`` whose every field
is ignored.

Six presets ship — ``fire``, ``smoke``, ``sparks``, ``explosion``, ``trail``,
``impact`` — and each is nothing but a set of field values, so anything a
preset does can be done by hand. They exist because an explosion should be one
line, and because seeing what the numbers for a real one look like is the
fastest way to learn the fields.

.. code-block:: python

   burst = particles.preset('explosion', maxParticles=512, color=(0.6, 0.8, 1.0))
   burst.fire()          # again, later

One emitter, many places
~~~~~~~~~~~~~~~~~~~~~~~~

``fire()`` releases a burst where the emitter *is*. When the same kind of
effect has to happen in a dozen places — a shotgun's eight impacts, a
firefight's worth of sparks — ``burst_at()`` is the one to reach for instead:
the styling stays on this one node and the *place* arrives per burst.

.. code-block:: python

   sparks = particles.preset('sparks', burstOnStart=False, worldSpace=True)
   for hit in shot.impacts:
       sparks.burst_at(hit.point, direction=hit.normal)     # count=... to override

A node per effect would mean editing the scenegraph at the rate things happen,
and everything the render pass had gathered would be thrown away with it.
``position`` is in the frame the particles live in — world space for a
``worldSpace`` emitter, the emitter's own space otherwise — and ``direction``
is what the particles are thrown along, which for an impact is the surface
normal. A disabled emitter bursts nothing, so an effects setting that switches
a kind off switches it off however it is asked.

``burstOnStart=False`` matters here. An emitter with a ``burst`` releases its
first one as soon as it is drawn, which is what a firework in an authored
scene wants and is exactly wrong for one that exists to be fired later: left
on, every such emitter goes off at its own origin the moment the level is
first drawn.

.. _particles-dataflow:

What happens each frame
-----------------------

.. figure:: images/diagrams/particles-1.svg
   :alt: Per-frame flow: emit, step, compact, upload, one instanced draw
   :class: diagram

   The whole per-frame cost is a handful of numpy passes over contiguous arrays
   and one buffer upload. Nothing loops in Python over particles, and nothing
   allocates per particle.

.. _pool:

The pool: why the living are packed at the front
------------------------------------------------

Particles die out of order — that is what lifetime variation means — so a
naive pool ends up as live particles with holes between them, and every
consumer of it has to carry a mask.

Instead, when particles die the survivors are **compacted down over the
gaps**. The living set is therefore always ``arrays[0:live]``. That single
invariant is what makes the GPU upload one contiguous slice, the draw one
call, and every step a whole-array operation with no masking anywhere.

.. code-block:: python

   keep = age[:live] < lifetime[:live]
   index = np.flatnonzero(keep)
   for array in (position, velocity, age, ...):
       array[:survivors] = array[index]
   live = survivors

Emission writes at the end of that prefix. A full pool emits nothing more, and
**that is not an error and is not reported**: a pool is a budget, and the
budget being reached is the system working. Size ``maxParticles`` from ``rate
× lifetime``, which is how many can be alive at once.

.. rst-class:: technical

``OpenGLContext/scenegraph/particles.py``, ``ParticlePool._bury``. Everything
in the class is testable with no GL; ``tests/unit/test_particles.py`` does
exactly that.

Two details that are easy to get wrong
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Drag is exponential, not linear.** ``v -= v * drag * dt`` overshoots into a
  *reversal* on a long frame, so particles suddenly fly backwards when the frame
  rate drops. ``v *= exp(-drag * dt)`` cannot, at any step size.

- **The step comes from the engine's clock**
  (``OpenGLContext.events.systemtime``), not from the wall clock, so a system
  follows whatever is driving the rest of the scene: a recording advancing a
  frame's worth at a time, a replay reading the instants the recording read, or
  a capture pinned so the same frame count produces the same picture.

- **The frame time is clamped** to ``MAX_STEP`` (0.1 s). A window drag or a
  stalled texture upload gives a frame of seconds; integrating it honestly
  throws every particle out of sight. Losing the time is the lesser artefact,
  and it is the same clamp a fixed-timestep physics loop applies for the same
  reason.

- **Emission accumulates fractions.** At 10 particles a second and a 60 Hz
  frame, ``int(rate * dt)`` is zero every single frame, for ever. The remainder
  is carried.

- **Starting angles are random.** Emitting every particle at rotation zero makes
  a cloud of sprites all pointing the same way, which reads as a grid rather
  than as smoke.

- **The emission cone samples the spherical cap uniformly**, not the angle.
  Sampling the angle crowds particles towards the axis and gives a jet with a
  bright core and a thin skirt — distinctive, and wrong.

.. _split:

What is per particle, and what is per system
--------------------------------------------

A particle carries only what genuinely varies between particles:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Per particle (in the pool)
     - Per system (a uniform)
   * - position, velocity
     - gravity, drag
   * - age, lifetime
     - —
   * - size *factor* (mean 1.0)
     - size at birth and at death
   * - rotation, spin
     - —
   * - one random number
     - colour and alpha at birth and at death

That split is why per-instance data is **seven floats** rather than twenty,
and why colour and size over life cost two uniforms rather than a gradient
texture and a texture unit. It has a second, less obvious payoff: because the
absolute size is a uniform rather than baked into each particle, editing
``size`` on a live emitter resizes the particles *already in the air* — which
is what makes a settings screen slider feel connected to what is on screen.

The per-particle random number exists so a shader can vary particles without
the simulation having to store what it varied.

.. _fields:

The fields
----------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Group
     - Fields
     - Notes
   * - How many, how often
     - ``rate``, ``burst``, ``maxParticles``, ``lifetime``, ``lifetimeVariation``,
       ``enabled``, ``burstOnStart``
     - A burst with ``rate=0`` is a one-shot; call ``fire()`` for another, or
       ``burst_at()`` to put one somewhere else. ``burstOnStart=False`` stops the
       first burst going off the moment the emitter is drawn.
   * - Which way, how fast
     - ``direction``, ``speed``, ``speedVariation``, ``spread``, ``gravity``,
       ``drag``
     - ``spread`` is a cone half-angle in radians: 0 is a laser, π is a sphere.
       Positive ``gravity`` Y is what makes smoke rise.
   * - What it looks like
     - ``size``, ``endSize``, ``sizeVariation``, ``spin``, ``color``, ``endColor``,
       ``alpha``, ``endAlpha``, ``texture``, ``blending``
     - Without a ``texture`` a particle is a soft round dot computed in the fragment
       shader — enough for sparks, embers and explosions, and no asset at all.
   * - Frame of reference
     - ``worldSpace``
     - True leaves particles behind when the emitter moves — a rocket trail. False
       carries them with it — a torch flame.
   * - Reproducibility
     - ``seed``
     - A fixed value pins the sequence, for a reference image. −1 draws from the
       :ref:`session's particle stream <randomness>`, so an emitter looks different
       every time the game is played and the same every time one recorded session is
       replayed.

Every one of them is a declared VRML field with a ``UI_HINTS`` entry, so an
emitter can be written into a scene file, carried in an ``MFNode``, watched
for change, and presented by the generated settings machinery with no UI code.

.. _rendering:

The renderer
------------

**Billboarding happens in eye space.** The particle's centre goes through the
model-view, and the quad's corner is then added to its ``x`` and ``y``.
Offsetting *after* the view transform is what makes the quad face the camera
exactly, at any camera orientation, with no per-particle matrix and no work on
the CPU.

.. code-block:: python

   vec4 centre = uModelView * vec4(aParticle.xyz, 1.0);
   centre.xy += rotate(aCorner, aParams.x) * size;
   gl_Position = uProjection * centre;

**One matrix, chosen by the node.** A world-space system's particles are
already in world coordinates, so it is sent the *view* matrix; a local-space
system's are in the emitter's frame, so it is sent the full *model-view*.
Choosing on the CPU keeps the shader free of a branch it would otherwise take
once per vertex.

**Depth tested, depth writes off.** Particles disappear behind walls because
they are tested against the depth buffer, and never occlude each other because
they do not write to it — which is what makes a cloud read as a cloud instead
of as a pile of squares. They draw in the transparent pass, after opaque
geometry, and never enter a shadow map.

**Additive by default**, because most effects are light — fire, sparks,
explosions, muzzle flashes — and light adds. Choose ``blending='alpha'`` for
the things that block light instead: smoke, dust, steam.

.. rst-class:: technical

Shaders are ``OpenGLContext/shaders/particle.vert`` and ``particle.frag``; the
GL helpers (``InstanceBuffer``, ``ensure_gl``) are shared with the terrain and
vegetation nodes in ``scenegraph/instancedgl.py``. A shader compile or driver
failure disables the node with one logged warning rather than taking down the
frame: the effect goes missing, the scene does not.

Bounding volume
~~~~~~~~~~~~~~~

A particle system's true extent changes every frame and would have to be
recomputed from the pool to be tight. Instead the node reports a box sized
from how far its fastest particle could travel in its lifetime. That costs
nothing and is never wrong in the direction that matters — culling away an
effect that is actually on screen.

.. _stepping:

When the simulation runs
------------------------

Particles are stepped **from the draw**, because the draw is the only
per-frame hook a scenegraph node has. Two consequences worth knowing:

- A scene rendered twice in one frame — a shadow pass, a selection pass — steps
  by nearly zero the second time rather than twice, because the step is measured
  from a wall clock rather than counted.

- A still frame is a stopped simulation. An application showing effects has to
  keep asking for frames; the demo does it in ``OnIdle``.

To drive the simulation yourself — a fixed-tick game loop, or a test — call
``emitter.simulate(dt, origin=...)`` directly. It is the same method the draw
uses.

.. _particles-testing:

Testing an effect without looking at it
---------------------------------------

The pool is the interesting half and it is pure numpy, so it is asserted about
directly:

.. code-block:: python

   pool = particles.ParticlePool(capacity=16)
   pool.emit(1, velocity=(1, 0, 0), spread=0.0, speed_variation=0.0)
   pool.step(0.5)
   assert np.allclose(pool.position[0], (0.5, 0, 0))

The suite covers birth, motion under gravity and drag, ageing, death,
compaction keeping the survivors' state intact, the budget, the fractional
emission accumulator, the long-frame clamp, reproducibility from a seed, and
that a full pool stepped thirty times allocates essentially nothing. Rendering
is covered by the demo's reference image.

.. _particles-demos:

Demo
----

``tests/particles_effects.py`` puts all five continuous and burst presets side
by side over a floor, so what each effect is made of can be read off against
what it looks like. Space re-fires the bursts, ``p`` pauses emission without
freezing what is already in the air.

.. code-block:: bash

   python tests/particles_effects.py
