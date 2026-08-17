# Particle effects

**Status: ✅ Complete.** Shipped as `OpenGLContext/scenegraph/particles.py` plus
`shaders/particle.vert`/`.frag`, documented in
[docs/particles.html](../docs/particles.html) and demonstrated by
`tests/particles_effects.py`.

Fire, smoke, sparks, explosions, impacts and trails, drawn as camera-facing
quads — one instanced draw call per system, however many particles are in it.

## Shape

A particle system is a **simulation with a renderer bolted on**, and keeping
those apart is most of the design:

- **`ParticlePool`** — fixed-capacity numpy arrays, stepped as whole arrays. No
  GL, no scenegraph, no node, so birth, motion, death, compaction and the budget
  are all testable in milliseconds rather than by watching.
- **`ParticleEmitter`** — a scenegraph *rendering* node (not a geometry inside a
  `Shape`: an effect has no material and no surface) holding a pool, the shape
  of what comes out of it, and about a hundred lines of core-profile GL.

## Decisions worth keeping

- **The living are packed at the front.** Particles die out of order, so a naive
  pool grows holes and every consumer carries a mask. Compacting the survivors
  down keeps the live set at `arrays[0:live]`, which is what makes the GPU
  upload one contiguous slice and the draw one call.
- **Per particle is state; per system is a curve.** A particle carries position,
  velocity, age, a size *factor* (mean 1.0), a rotation and one random number.
  Colour and size *over life* are two uniforms the shader interpolates between.
  That is why per-instance data is seven floats rather than twenty — and why
  editing `size` on a live emitter resizes what is already in the air.
- **Drag is exponential.** `v -= v * drag * dt` overshoots into a reversal on a
  long frame; particles then fly backwards when the frame rate drops.
- **The frame time is clamped** to `MAX_STEP`. A window drag gives a frame of
  seconds, and integrating it honestly throws every particle out of sight.
- **Emission accumulates fractions.** At 10 a second and a 60 Hz frame,
  `int(rate * dt)` is zero every frame, for ever.
- **The cone samples the spherical cap uniformly**, not the angle. Sampling the
  angle crowds particles onto the axis and gives a bright core and a thin skirt.
- **Billboarding in eye space.** Transform the centre, then add the corner to
  `x` and `y`: exact at any camera orientation, no per-particle matrix, no CPU
  work. The node picks *which* matrix to send — view for a world-space system,
  model-view for a local-space one — so the shader has no branch.
- **Depth tested, depth writes off.** Particles hide behind walls and never
  occlude each other, which is what makes a cloud read as a cloud.
- **Additive by default**, because most effects are light and light adds; alpha
  for the things that block light.
- **No texture required.** Without one a particle is a soft round dot computed
  in the fragment shader — enough for sparks, embers and explosions, and no
  asset to license.
- **Presets are field values and nothing more.** An explosion should be one
  line; seeing what the numbers for a real one look like is the fastest way to
  learn the fields.
- **One emitter can burst in many places.** `burst_at(position, direction,
  count)` releases a burst *without moving the emitter*, so a kind of effect is
  one node however many of it are on screen. The alternative — a node per
  impact — means editing the scenegraph at the rate things happen, and
  everything the render pass had gathered goes with it. The styling stays on
  the node and the place arrives per burst.
- **An event-driven emitter must be told not to go off on its own.**
  `burstOnStart` (default true, which is what a firework in an authored scene
  wants) seeds the first burst when the emitter is drawn. Left on for an
  emitter that exists to be *fired later*, every one of them detonates at its
  own origin the moment a level first draws.

## Tests

`tests/unit/test_particles.py` — 85 tests with no GL: emission and its caps,
motion under gravity and drag, ageing, death, compaction keeping survivors'
state, the fractional accumulator, the long-frame clamp, reproducibility from a
seed, the instance-row layout, and that a full pool stepped thirty times
allocates essentially nothing. Rendering is covered by the demo's reference
image.

## Not done

- No collision, no sorting between particles within a system, no soft-particle
  depth fade, no GPU-side simulation. Each is a real feature; none is needed by
  the effects this exists to draw.
- `worldSpace` leaves particles where they were emitted but does not give them
  the emitter's velocity, so a fast-moving trail is a line of dots rather than a
  smear.
