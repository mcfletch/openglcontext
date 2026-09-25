Particle systems
================

.. rst-class:: introduction

A particle system draws many small quads that face the camera, from a single
``ParticleEmitter`` node. Use it for fire, smoke, sparks, explosions, impacts
and trails. Each system is drawn with one instanced draw call, however many
particles it has. The simulation is numpy arrays stepped as whole arrays and
uses no OpenGL, so it can be driven and tested without a window.

.. figure:: images/demos/particles_effects.jpg
   :alt: Fire, smoke, sparks and an explosion burning side by side in the dark

   Five of the presets side by side, from ``tests/particles_effects.py``:
   fire, smoke, sparks, an explosion and a trail. None of them loads a
   texture; without one, a particle is a soft round dot computed in the
   fragment shader.

.. _particles-quickstart:

Using it
--------

A fire
~~~~~~

.. code-block:: python

   from OpenGLContext.scenegraph import particles
   from OpenGLContext.scenegraph.basenodes import Transform

   torch = Transform(translation=(0, 1, -3), children=[
       particles.preset('fire'),
   ])

That is a complete effect. ``ParticleEmitter`` is a rendering node in its own
right, not a geometry inside a ``Shape``: an effect has no material and no
surface, so an ``Appearance`` would have nothing to set.

Six presets are included: ``fire``, ``smoke``, ``sparks``, ``explosion``,
``trail`` and ``impact``. A preset is only a set of field values, so anything
a preset does can be written out by hand, and a preset's values are a
starting point for your own effect. Keyword arguments to ``preset()`` override
the preset's values.

An explosion on demand
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   burst = particles.preset('explosion', maxParticles=512, color=(0.6, 0.8, 1.0))
   burst.fire()          # again, later

``fire()`` releases a burst at the emitter's position on the next step. By
default an emitter also releases its first burst as soon as it is drawn. Set
``burstOnStart=False`` for an emitter that should only go off when fired;
otherwise every such emitter goes off at its own position the first time the
scene is drawn.

Sparks at each impact
~~~~~~~~~~~~~~~~~~~~~

When the same effect happens in many places, such as a shotgun's eight
impacts, one emitter can release a burst at each place. There is no need to
add a node per effect:

.. code-block:: python

   sparks = particles.preset('sparks', burstOnStart=False, worldSpace=True)
   for hit in shot.impacts:
       sparks.burst_at(hit.point, direction=hit.normal)     # count=... to override

The fields stay on the one node, and each burst gets its own position.
``position`` is in the frame the particles live in: world space for a
``worldSpace`` emitter, and the emitter's own space otherwise. ``direction``
is the axis the particles are thrown along; for an impact, that is the surface
normal. ``burst_at()`` returns how many particles it released. A disabled
emitter releases nothing, so a settings switch that turns an effect off turns
it off for bursts too.

Adding a node per effect would change the scenegraph as often as things
happen, and the render pass discards what it has gathered each time the
scenegraph changes.

.. _authored-particles:

Placing an effect in a model
----------------------------

A glTF file can say where its fires are. An object tagged with the
:ref:`OGLC_hook <hooks>` kind ``fire``, ``smoke`` or ``sparks`` loads with an
emitter from the preset of that name at the object's position, alongside any
mesh the object already has. In Blender, put the tag on the object (an empty,
or the brazier itself), either with the **Engine Hook** panel of the
``tools/blender/oglc_hook`` add-on or as a custom property:

.. code-block:: javascript

   {"OGLC_hook": {"kind": "fire", "scale": 2.0}}

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Parameter
     - Default
     - What it does
   * - ``scale``
     - 1
     - Multiplies every length in the effect: particle size at birth and
       death, launch speed and gravity. A flame at scale 2 is twice as tall
       and lasts as long. The object's own scale multiplies it too, so
       resizing the empty in Blender resizes the effect.
   * - ``density``
     - 1
     - Multiplies particles per second, the burst and ``maxParticles``.
   * - an emitter field
     - the preset's
     - Set by name before ``scale`` and ``density`` are applied:
       ``{"kind": "fire", "color": [0.3, 0.6, 1.0]}`` is a gas flame. Every
       :ref:`field <fields>` but ``externalURL`` may be set. A name that is
       not one of them, or a value the field does not accept, is logged and
       ignored.
   * - ``texture``
     - none
     - A sprite image named relative to the document, read only when the
       document was loaded from a file, and only from inside its directory.

What a file asks for is held to the fields' ranges, before and after
``scale`` and ``density`` multiply it: at most 2000 particles a second,
a ``maxParticles`` and a ``burst`` of at most 20000, sizes of at most 20 and
a speed of at most 100. ``scale`` (the object's own scale included) and
``density`` are each at most 100. A value that is no finite number is
logged and the preset's value is kept (``particlehooks.RANGES``).

The ``sparks`` preset is a single burst, for a game to fire on an impact. An
authored ``sparks`` emits a steady 60 a second instead, because nothing in a
world fires it; ``{"rate": 0, "burst": 60}`` gives the preset's burst.

The tag is read from objects only, since a material has no single position
for a flame. A material carrying one of these kinds loads unchanged.
``scene.hook_data['fire']`` (and ``'smoke'``, ``'sparks'``) holds one emitter
per tagged object. Each emitter steps on the engine clock as it is drawn, and
``scene.advance()`` reports whether any is still burning, which keeps
``oglc-view`` drawing frames.

``tools/blender/demos/lakeside.glb`` is a world authored this way, with a
campfire, a brazier and two torches;
``oglc-view tools/blender/demos/lakeside.glb`` shows it.

.. _fields:

Fields
------

Every field is a declared VRML field with a ``UI_HINTS`` entry, so an emitter
can be written into a scene file, carried in an ``MFNode``, watched for
changes, and edited on a generated settings page with no UI code. A
``*Variation`` field scatters each particle's value by up to that fraction of
the base value, either way.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Default
     - Meaning
   * - ``rate``
     - 50.0
     - Particles born per second. Fractions carry over between frames, so a
       rate below one per frame still emits.
   * - ``burst``
     - 0
     - Particles released at once when the emitter starts or ``fire()`` is
       called. A burst with ``rate=0`` is a one-shot, such as an explosion.
   * - ``maxParticles``
     - 500
     - The pool's capacity. Size it from ``rate × lifetime``, which is how many
       particles can be alive at once.
   * - ``lifetime``, ``lifetimeVariation``
     - 1.5, 0.3
     - Seconds a particle lives.
   * - ``enabled``
     - True
     - A disabled emitter emits nothing, but particles already out keep
       ageing, so smoke clears instead of freezing.
   * - ``burstOnStart``
     - True
     - Whether the first ``burst`` is released as soon as the emitter is drawn.
   * - ``direction``
     - (0, 1, 0)
     - Which way particles are thrown, in the emitter's own frame.
   * - ``speed``, ``speedVariation``
     - 2.0, 0.3
     - Speed in units per second.
   * - ``spread``
     - 0.4
     - Half-angle of the emission cone, in radians: 0 is a straight line, π a
       full sphere.
   * - ``gravity``
     - (0, −1, 0)
     - Constant acceleration. Negative Y falls; positive Y makes smoke rise.
   * - ``drag``
     - 0.0
     - Rate at which velocity decays, per second.
   * - ``size``, ``endSize``, ``sizeVariation``
     - 0.3, 0.0, 0.3
     - Size at birth and at death, in world units.
   * - ``spin``, ``spinVariation``
     - 0.0, 1.0
     - Radians per second each particle turns about the view axis.
   * - ``color``, ``endColor``
     - (1, 0.7, 0.3), (0.6, 0.1, 0)
     - Colour at birth and at death.
   * - ``alpha``, ``endAlpha``
     - 1.0, 0.0
     - Opacity at birth and at death.
   * - ``texture``
     - empty
     - A sprite image for each particle. Without one, a particle is a soft
       round dot computed in the fragment shader, which suits sparks, embers
       and explosions and needs no asset.
   * - ``blending``
     - ``additive``
     - ``additive`` for effects that give off light, ``alpha`` for effects
       that block it. See :ref:`rendering`.
   * - ``worldSpace``
     - True
     - True leaves particles behind when the emitter moves, as for a rocket
       trail. False carries them with it, as for a torch flame. A world-space
       emitter's ``direction`` is turned by the transforms above it but keeps
       its own length, so a scaled parent moves the effect without throwing
       particles faster.
   * - ``seed``
     - −1
     - A fixed value makes the sequence repeatable, for a reference image. −1
       draws from the :ref:`session's particle stream <randomness>`, so an
       emitter looks different each time the game is played and the same each
       time one recorded session is replayed.

.. _stepping:

When the simulation steps
-------------------------

Particles are stepped when they are drawn, because the draw is the only
per-frame hook a scenegraph node has. This has two consequences:

- A scene rendered twice in one frame, for example by a shadow pass and a
  selection pass, steps by almost zero the second time, not twice, because
  the step is measured from a clock rather than counted.

- When no frames are drawn, the simulation stops. An application showing
  effects has to keep requesting frames; the demo does this in ``OnIdle``.

To drive the simulation yourself, from a fixed-tick game loop or a test, call
``emitter.simulate(dt, origin=...)``. The draw uses the same method.

.. _particles-dataflow:

Each frame
----------

.. figure:: images/diagrams/particles-1.svg
   :alt: Per-frame flow: emit, step, compact, upload, one instanced draw
   :class: diagram

   Emit, step, compact, upload, draw. Each stage is a numpy operation over
   contiguous arrays. Nothing loops over particles in Python, and nothing
   allocates per particle.

.. _pool:

The pool
--------

Lifetimes vary, so particles die out of order. If dead particles stayed in
place, the pool would have gaps, and every stage would need a mask to skip
them.

Instead, the survivors are moved down over the gaps as particles die. The
living particles are therefore always ``arrays[0:live]``: the GPU upload is
one contiguous slice, the draw is one call, and each step is a whole-array
operation with no mask.

.. code-block:: python

   keep = age[:live] < lifetime[:live]
   index = np.flatnonzero(keep)
   for array in (position, velocity, age, ...):
       array[:survivors] = array[index]
   live = survivors

New particles are written after the last live one. When the pool is full, no
more are emitted and nothing is reported: ``maxParticles`` is a budget, and
reaching it is normal.

.. rst-class:: technical

``OpenGLContext/scenegraph/particles.py``, ``ParticlePool._bury``. The class
uses no GL, and ``tests/unit/test_particles.py`` tests it without one.

.. _split:

Per-particle and per-system values
----------------------------------

A particle stores only what differs between particles:

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

The data sent per instance is therefore seven floats rather than twenty.
Colour and size over a particle's life are two uniforms, not a gradient
texture with its own texture unit. Because the absolute size is a uniform,
changing ``size`` on a running emitter also resizes the particles already in
the air.

The per-particle random number lets a shader vary particles without the
simulation storing what it varied.

The step
--------

The step handles five details:

- Exponential drag - ``v -= v * drag * dt`` overshoots and reverses on a long
  frame, so particles fly backwards when the frame rate drops.
  ``v *= exp(-drag * dt)`` cannot overshoot at any step size.

- The engine's clock - the step comes from
  ``OpenGLContext.events.systemtime``, not the wall clock. A system therefore
  follows whatever drives the rest of the scene: a :doc:`recording
  <recording>` advancing one frame at a time, a replay reading the times the
  recording read, or a capture fixed so that the same frame count produces the
  same picture.

- Clamped frame time - each step is limited to ``MAX_STEP`` (0.1 s). Dragging
  a window or a stalled texture upload can produce a frame of several
  seconds, and integrating that would throw every particle out of sight. A
  fixed-timestep physics loop applies the same kind of clamp.

- Fractional emission - at 10 particles a second and 60 frames a second,
  ``int(rate * dt)`` is zero every frame, so the remainder is carried over.

- Random starting angles and uniform cones - each particle starts at a
  random rotation, and the emission cone samples its spherical cap uniformly
  rather than sampling the angle. Sampling the angle crowds particles towards
  the axis, giving a jet a bright core and a thin edge.

.. _rendering:

Rendering
---------

Billboarding is done in eye space. The particle's centre is transformed by
the model-view matrix, and the quad's corner is then added to its ``x`` and
``y``. Because the offset is added after the view transform, the quad faces
the camera at any camera orientation, with no per-particle matrix and no CPU
work.

.. code-block:: glsl

   vec4 centre = uModelView * vec4(aParticle.xyz, 1.0);
   centre.xy += rotate(aCorner, aParams.x) * size;
   gl_Position = uProjection * centre;

The node chooses which matrix to send. A world-space system's particles are
already in world coordinates, so it sends the view matrix. A local-space
system's particles are in the emitter's frame, so it sends the full
model-view matrix. Making this choice on the CPU keeps a branch out of the
vertex shader.

Particles are depth tested but do not write depth, so walls hide them and
they blend with each other instead of hiding each other. They are drawn in
the transparent pass, after opaque geometry (see :doc:`renderpasses`), and
are never drawn into a shadow map.

Blending is additive by default, which suits effects that give off light:
fire, sparks, explosions, muzzle flashes. ``blending='alpha'`` suits effects
that block light: smoke, dust, steam.

.. rst-class:: technical

The shaders are ``OpenGLContext/shaders/particle.vert`` and ``particle.frag``.
The GL helpers (``InstanceBuffer``, ``ensure_gl``) are shared with the terrain
and vegetation nodes in ``scenegraph/instancedgl.py``. If a shader fails to
compile or the driver fails, the node is disabled with one logged warning:
the effect is missing, and the rest of the scene still draws.

Bounding volume
---------------

A particle system's extent changes every frame, and a tight box would have to
be recomputed from the pool each time. Instead, the node reports a box sized
by how far its fastest particle could travel in its lifetime. This costs
nothing to compute and is never too small, so an effect that is on screen is
never culled.

.. _particles-testing:

Testing
-------

The pool is plain numpy, so a test checks it directly:

.. code-block:: python

   pool = particles.ParticlePool(capacity=16)
   pool.emit(1, velocity=(1, 0, 0), spread=0.0, speed_variation=0.0)
   pool.step(0.5)
   assert np.allclose(pool.position[0], (0.5, 0, 0))

The suite covers birth, motion under gravity and drag, ageing, death,
compaction that keeps the survivors' state intact, the budget, fractional
emission, the long-frame clamp, repeatability from a seed, and that a full
pool stepped thirty times allocates almost nothing. Rendering is covered by
the demo's reference image.

.. _particles-demos:

Demo
----

:doc:`tests/particles_effects.py <tutorials/particles_effects>` shows five
presets, continuous and burst, side by side over a floor, so you can compare
each effect's fields with how it looks. Press the space bar to fire the
bursts again, and ``p`` to pause emission without freezing the particles
already in the air.

.. code-block:: bash

   python tests/particles_effects.py
