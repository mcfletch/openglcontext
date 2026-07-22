# Real-Time Physics & Collision for the Scenegraph

**Status:** Implemented (phases 0–7). The `OpenGLContext/physics/` package, the
`PhysicsBody` node, `PhysicsViewPlatform`, the `physics-cook` CLI, the debug
overlay, nine `tests/physics_*.py` demos, and `docs/physics.html` are all in
place; 91 unit/integration tests are green and the demos capture as
visual-regression references. The GPGPU `GLComputeBackend` (Phase 7) is now a
working GL 4.3 compute implementation of the per-body integration kernels
(`physics/glcompute.py`). The default `auto` policy runs on numpy and hands off to
the GPU only once the awake-body count crosses `gpu_threshold` (10k) — below that
numpy is faster (transfer-bound) — with hysteresis on the way back down and a numpy
fallback where compute is absent; the broad/narrow/solver stages remain on the CPU
(a full GPU-resident loop with LBVH + graph-colored solving is still future). See
`tests/test_backend_parity_gpu.py` for the parity suite (test 16).

**Relationship to other plans:** Reuses the CPU spatial-index / intersection machinery sketched by
[RAYCAST-PICKING.md](RAYCAST-PICKING.md) (`intersection.py` primitive math, an AABB tree). That plan
is *Shelved* for picking, but its `bvh.py` / `intersection.py` modules are the natural shared home for
the broad-phase and shape math here — this plan revives and extends them for a *dynamic* (moving-body)
index rather than a static pick index. Also gives the non-functional
[collision.py](../OpenGLContext/scenegraph/collision.py) `Collision` node an actual implementation
(navigation collision, §Phase 5).

## Goal

A **game-like** rigid-body physics layer that runs real-time alongside the scenegraph 
based on the glTF extensions for physics. It must:

- integrate **acceleration** (gravity + arbitrary applied forces) and **resistance** (linear +
  quadratic drag, restitution, Coulomb friction),
- handle **mesh↔mesh collision** (via convex proxies / triangle-soup, not brute triangle pairs),
- be **numerically simple, stable, and cheap** — approximate is fine, plausible-looking beats exact,
- drive scenegraph `Transform` nodes so existing rendering, culling, shadows, and picking are
  untouched, and
- **speak the OMI physics data model natively** (see below), so the loader imports real Godot/Blender
  physics assets with no translation layer and our own scenes round-trip out to glTF.

Non-goals for v1: soft bodies, cloth, fracture, fluid, deterministic lock-step networking. Joints,
triggers, collision filters, and gravity zones are **in scope** because the OMI model defines them —
they land in later phases but the data model carries them from day one.

## Core decision — the OMI physics model *is* our data model

The earlier draft invented a `RigidBody` node and mapped it onto OMI at the loader. That is backwards.
We instead adopt the **OMI physics extension family as the canonical in-memory schema**: the loader,
the scenegraph nodes, and the simulation world all speak the same structure, so glTF import/export is
(near) identity and there is no private format to keep in sync. The family, all shipping in
[omigroup/gltf-extensions](https://github.com/omigroup/gltf-extensions) and imported+exported by Godot:

| OMI extension | Provides | Our node(s) |
|---|---|---|
| **`OMI_physics_shape`** | document-level `shapes[]`: box, sphere, capsule, cylinder, convex, trimesh | `PhysicsShape` |
| **`OMI_physics_body`** | per-node `motion` / `collider` / `trigger`; document `physicsMaterials[]`, `collisionFilters[]` | `PhysicsBody` (+ `PhysicsMaterial`, `CollisionFilter`) |
| **`OMI_physics_gravity`** | document global gravity **and** per-volume gravity zones | `PhysicsGravity` |
| **`OMI_physics_joint`** | document `physicsJoints[]` (limits + drives); per-node joint attach | `PhysicsJoint` |

The Khronos **`KHR_physics_rigid_bodies`** (draft [PR #2424](https://github.com/KhronosGroup/glTF/pull/2424))
+ **glTF 2.1 top-level `shapes`** (superseding `KHR_implicit_shapes`,
[PR #2370](https://github.com/KhronosGroup/glTF/pull/2370)) express the **same concepts**. The internal
model is defined by these concepts, not by OMI's JSON spelling, so a `KHR_*` reader drops onto the same
structures when it ratifies. OMI is what real assets use **today**, so it is the reference spelling and
the first importer.

`.wrl`/X3D authoring gets the same nodes (they register through the
`OpenGLContext.scenegraph.nodes` entry points like every other node,
[basenodes.py](../OpenGLContext/scenegraph/basenodes.py)); field names track the X3D *Rigid Body
Physics* component where it and OMI agree (`mass`, `centerOfMass`, `linearVelocity`, etc.). Per the
project's priorities, **glTF/OMI is the reference and X3D follows**, not the other way round.

## Methodology — Red/Green TDD throughout

Every phase is **test-first**. The core (`model`, `collide`, `solver`, `broadphase`, integration,
cooking, loader) is pure-CPU numpy with **no GL**, so the red→green loop is fast and deterministic:

1. **Red** — write the failing test that pins the behavior (an analytic case with a known answer, a
   brute-force reference, or a round-trip identity). It must actually exercise the target code and
   assert on outputs, per [CLAUDE.md](../CLAUDE.md)'s test rules (no mock-through, realistic inputs).
2. **Green** — the minimum implementation that passes.
3. **Refactor** — with the test as the ratchet.

The **Testing strategy** section below is therefore the *specification*, authored ahead of each phase's
code, not an afterthought. GL-dependent pieces (debug render, frame-loop coupling) are driven in
subprocesses against captured output the way the existing visual suite is. Coverage tracks the repo's
80–100% goal, measured with `--cov=OpenGLContext`.

## Design stance — what the literature says to do for games

The OMI model is the *data*; the *simulation* is our own and follows the standard real-time recipe
(Catto/Box2D, Bullet, Erleben, Gaffer's *Fix Your Timestep*, Müller's PBD):

1. **Semi-implicit (symplectic) Euler**, not RK4. `v += a·dt` **then** `x += v·dt` — energy-stable at
   trivial cost, the integrator every game engine ships. RK4 buys nothing once collisions inject
   discontinuities.
2. **Fixed timestep with an accumulator.** Constant `dt` (e.g. 1/60 s) decoupled from render fps;
   render interpolates the last two states. Kills the #1 source of instability/non-determinism.
3. **Collision proxies, not render meshes.** Each body collides via its `OMI_physics_shape` proxy
   (sphere/box/capsule/cylinder/convex/trimesh), *separate* from its detailed render geometry. This is
   what makes "mesh↔mesh" tractable — and it is exactly what the OMI shape array already encodes.
4. **Broad phase → narrow phase → solver:**
   - **Broad phase:** dynamic AABB tree with *fattened* boxes (Box2D `b2DynamicTree`), respecting
     `collisionFilters`. Culls the O(N²) pair explosion.
   - **Narrow phase:** analytic tests for primitive pairs; **GJK** (distance) + **EPA** (penetration)
     for convex↔convex; convex↔triangle for dynamic-vs-static meshes.
   - **Solver:** **sequential impulses** with Baumgarte/split-impulse position correction (Catto) —
     projected Gauss-Seidel, a few iterations, stable stacks, restitution + friction in one loop.
5. **Sleeping.** Sub-threshold bodies deactivate and cost ~nothing until touched.

**Primary solver: sequential impulses** (best-documented, composes with velocity-level
friction/restitution and with OMI's `frictionCombine`/`restitutionCombine` modes). **Alternative: XPBD**
(Müller/Macklin) — unconditionally stable, one position-projection loop for contacts *and* joints;
kept as a drop-in swap (`solver='xpbd'`) since OMI joints map cleanly onto XPBD constraints.

## Architecture — a simulation world *beside* the tree

The scenegraph is a poor physics data structure (pointer-chasing, cache-hostile). Keep physics state in
a **flat, structure-of-arrays** world that *is* the OMI model in columnar form, syncing to/from the
tree only at step boundaries.

```
 render tree                         PhysicsWorld (SoA, float64) — the OMI model, columnar
 ───────────                         ────────────────────────────────────────────────────
 Transform.translation ◀─writeback──  position[i] (N,3)   ◀─┐ motion.type/mass/COM/inertia
 Transform.rotation    ◀───────────   orientation[i](N,4)   │ collider.shape → shapes[]
        │ read on bind/field-change   linVel[i], angVel[i]  │ collider.physicsMaterial → materials[]
        ▼                             invMass[i],invInertia │ collider.collisionFilter → filters[]
 PhysicsBody node ──registers──▶ i    gravityFactor[i]      │ trigger.shape → sensor (no impulse)
                                      aabb[i] (fat) ─▶ broad phase
 document tables:  shapes[]   physicsMaterials[]   collisionFilters[]   physicsJoints[]   gravity(global+volumes)
```

- **`PhysicsWorld`** (`physics/world.py`) owns the SoA arrays, the document-level tables (shapes,
  materials, filters, joints, gravity), and the step loop. Vectorized with the project's `arrays`
  (numpy) — integration and AABB refit are single array ops over all awake bodies.
- **`PhysicsBody`** scenegraph node (`scenegraph/physicsbody.py`) mirrors `OMI_physics_body`: three
  sub-nodes `motion` / `collider` / `trigger`. On bind it registers a body index; the world writes
  `translation`/`rotation` back to the enclosing `Transform` each step.
- **Sync contract.** Physics owns the transform while a body is *awake* (world → tree). Authoring owns
  it while *kinematic* or *sleeping* (tree → world on field-change, via the `pydispatch` signals
  `boundingvolume`/`grouping` already emit). `motion.type` drives which side owns it:
  `dynamic` = physics, `kinematic` = scripted (pushes others, unpushed), `static` = never moves.

### The step, hooked into the existing frame clock

The engine ticks from the **same** place TimeSensors do — `DoEventCascade`
([eventhandlermixin.py:149](../OpenGLContext/events/eventhandlermixin.py#L149)) already polls the
`TimeEventGeneratorManager` each frame. `PhysicsWorld` registers as a time generator (or is polled
right after), taking real `dt` from the same `internaltime` source
([internaltime.py](../OpenGLContext/events/internaltime.py)) — so pausing/slowing the context clock
pauses/slows physics for free.

```python
accumulator += dt_real
accumulator = min(accumulator, MAX_FRAME)          # spiral-of-death clamp
while accumulator >= FIXED_DT:
    world.step(FIXED_DT)                            # fixed, deterministic
    accumulator -= FIXED_DT
world.writeback(accumulator / FIXED_DT)            # interpolate x_prev→x for render
```

`world.step()` is the whole pipeline: integrate forces → refit broad phase → find pairs (filtered) →
narrow phase → build contacts → solve (contacts + joints) → integrate into positions → fire trigger
overlap events → sleep bookkeeping.

## `world.step(dt)` in detail

### 1. Integrate forces (symplectic Euler, vectorized)

```
g_i     = resolve_gravity(position[i])            # global gravity, overridden by any gravity volume
a       = g_i * gravityFactor + F_applied*invMass # motion.gravityFactor per body (OMI)
v      += a * dt
v      *= (1 - linearDamping * dt)                # linear resistance
v      -= k_drag * |v| * v * invMass * dt         # quadratic drag (air/water)
ω      *= (1 - angularDamping * dt)
x_prev  = x                                        # for render interpolation
```

`resolve_gravity` returns the global `OMI_physics_gravity` (direction × magnitude) unless the body sits
inside a higher-priority **gravity volume** (§gravity), which can replace/stop the accumulation.
`gravityFactor` is the per-body multiplier straight from `motion.gravityFactor`. Sleeping/static bodies
are masked out.

### 2. Broad phase — dynamic AABB tree (filter-aware)

`physics/broadphase.py` (shares/extends RAYCAST's `bvh.py`).

- Each body's world AABB comes from its `collider.shape` local extent transformed by its pose — the
  same `getPoints()`→transform→min/max the codebase already does for culling
  ([boundingvolume.py:245](../OpenGLContext/scenegraph/boundingvolume.py#L245)).
- Boxes are **fattened** so small motions don't re-insert (Box2D's trick → most frames refit, not
  rebuild). Static bodies insert once.
- Query = tree self-overlap → candidate pairs, then **`collisionFilters` masking** drops pairs whose
  collision groups don't interact (OMI filters = the standard layer/mask system). A persistent pair
  cache carries contact data for warm-starting; `onChildAdd`/`onChildRemove` `SGObserver` signals
  invalidate entries.
- Sweep-and-prune offered as an alternate for mostly-flat scenes.

### 3. Narrow phase — layered by shape pair

`physics/narrowphase.py` + math in `physics/collide.py`. Cheapest test that resolves the pair wins:

| Pair | Method |
|---|---|
| sphere↔sphere | centers distance vs. `r₁+r₂` |
| sphere↔plane / sphere↔box | closest-point-on-box, analytic |
| box↔box (AABB) | overlap intervals; min-overlap axis = normal |
| box↔box (oriented) / capsule↔* / cylinder↔* | **SAT** or GJK |
| convex↔convex | **GJK** (touching/distance) → **EPA** (penetration depth + normal) |
| convex↔**trimesh** (static) | convex vs. candidate triangles (mesh's own triangle AABB tree returns overlaps); per-triangle GJK/EPA |
| trimesh↔trimesh (both dynamic) | **convex decomposition** first (each mesh → a few hulls at load), then convex↔convex per hull pair |

**This is "mesh↔mesh," and it is exactly the OMI shape taxonomy.** `trimesh` is defined for *static*
world geometry (parthenon, terrain — a raw `IndexedFaceSet` with a cached triangle AABB tree keyed on
the coordinate node via [volumeFromCoordinate](../OpenGLContext/scenegraph/boundingvolume.py#L372)),
and `convex` for movers. A dynamic concave mesh becomes several `convex` shapes via approximate convex
decomposition (V-HACD-style) at load — which is representable as an OMI compound of `convex` shapes,
so it round-trips.

Each contact yields a **manifold** (up to 4 persistent points for stable box-on-box rest),
clipped/reduced Box2D-style: `(bodyA, bodyB, worldPoint, normal, penetration)`.

### 4. Solver — sequential impulses (+ joints)

`physics/solver.py`. Projected Gauss-Seidel, `velocityIterations` passes (default 8):

- **Normal impulse** removes approach velocity along `n`, applies **restitution** (small-velocity
  threshold so rests don't jitter), clamped ≥ 0, accumulated per contact for warm-starting. Restitution
  and friction combine per the contact's two materials using OMI's `restitutionCombine`/`frictionCombine`
  mode (average/min/max/multiply).
- **Friction impulse** on two tangents, clamped to the Coulomb cone `|j_t| ≤ μ·j_n` (μ from
  `staticFriction`/`dynamicFriction`).
- **Joint constraints** solved in the same Gauss-Seidel sweep: each `OMI_physics_joint` limit
  (`linearAxes`/`angularAxes`, `min`/`max`, `stiffness`, `damping`) and drive (`positionTarget`/
  `velocityTarget`, `maxForce`) becomes a constraint row. This is why XPBD is attractive as an
  alternative — joints and contacts unify.
- **Position correction:** Baumgarte, or split-impulse / NGS so restitution isn't polluted.
- **Warm starting** from the pair cache cuts stack iterations ~3×.

`invMass`/`invInertia` are stored inverted, computed from `motion.mass` + `inertiaDiagonal` +
`inertiaOrientation` (or auto-derived from the shape + mass + `centerOfMass` when `inertiaDiagonal` is
zero, as OMI intends). `static`/`kinematic` ⇒ `invMass=0`, so infinite mass needs no special-casing.

### 5. Triggers, sleeping

- **Triggers** (`OMI_physics_body.trigger`): a sensor shape that detects overlap but generates **no
  impulse**. The broad/narrow phase already computes the overlap; a trigger just emits enter/stay/exit
  events into the event system (a natural fit for VRML `TouchSensor`-style routing) instead of a
  contact. Ghost/region volumes, pickups, gravity-zone bounds all use this.
- **Sleeping:** a body under the velocity threshold for `T_sleep` deactivates — skipped in integration
  and solving, kept in the broad phase so movers still collide and wake it.

## Continuous collision (fast movers) — optional, Phase 6

Discrete stepping tunnels small/fast bodies. The cheap game fix is **speculative contacts** (Catto):
expand the broad-phase margin by `|v|·dt` and let the non-penetration constraint brake the body before
it passes through — no separate pass, no rewind. Reserve **conservative advancement** (binary-search
TOI) for flagged fast bodies. Both opt-in.

## Scaling to many movers — and a GPGPU-ready pipeline

The target is **non-trivial numbers of moving bodies** — design for 10³–10⁴ dynamic bodies
interactive on the CPU, and leave a clean path to 10⁵+ on the GPU **without a rewrite**. We do not
implement GPGPU in v1, but every structural choice keeps the door open.

**Why the layout is already GPU-shaped.** The SoA world (§architecture) is columnar contiguous numpy —
`position (N,3)`, `linVel (N,3)`, `invMass (N,)`, etc. Those arrays upload to GL buffers (SSBO / texture
buffers) as-is; there is no pointer-chasing object graph to flatten first. This is the single most
important decision for future GPGPU, and it is the same decision that makes the CPU path fast today
(vectorized numpy over all bodies, no Python per-body loop).

**Each `step` stage is a data-parallel kernel.** The pipeline is written as pure array-in/array-out
functions so each maps to a GPU compute dispatch later:

| Stage | Parallelism | CPU now | GPU later |
|---|---|---|---|
| Integrate forces | embarrassingly parallel per body | numpy vector ops | trivial compute kernel |
| AABB refit | per body | numpy | compute kernel |
| Broad phase | spatial | fattened AABB tree | **uniform grid / spatial hash** or **LBVH** (Morton-code radix sort) — the standard GPU broad phases |
| Narrow phase | per candidate pair | vectorized batches | one thread per pair (GJK/EPA in-kernel) |
| Solver | per constraint, but data-dependent | sequential impulses (Gauss-Seidel) | **graph-colored** or **Jacobi/XPBD** (see below) |

**The solver is the one stage that resists naïve parallelism**, because sequential impulses is
Gauss-Seidel (each impulse reads the latest velocities). Two escape hatches, both already in the design:

- **Islands.** Contacts partition into disjoint connected components; independent islands solve in
  parallel with zero interaction (also a CPU win — and sleeping removes settled islands entirely). The
  contact graph is built each step regardless, so island extraction is nearly free.
- **XPBD / Jacobi + graph coloring.** The `solver='xpbd'` swap is *also* the GPU-friendly solver:
  position-projection with graph-colored constraint batches runs each color in parallel. This is why
  XPBD was kept as a first-class alternative rather than a footnote — it is the path to a GPU solver.

**Compute backend abstraction.** A thin `physics/backend.py` defines the kernel surface
(`integrate`, `refit_aabbs`, `find_pairs`, `narrow`, `solve`) with a **`NumpyBackend`** (v1) and a
future **`GLComputeBackend`** (OpenGL 4.3 compute shaders via PyOpenGL — GL *is* available here, and
core-profile compute is in reach; transform-feedback is a fallback for older targets). The world calls
the backend; kernels never touch scenegraph objects. Swapping backends changes no simulation logic.

**Caveats, stated now.** GPU parallel reductions/atomics are not bit-deterministic, so the determinism
guarantee (test 5) holds for the CPU backend and is *best-effort* on GPU — acceptable for a game, noted
for anyone tempted to rely on lock-step. Readback latency argues for keeping the whole loop GPU-side
(bodies live in GL buffers, writeback reads them once per frame) rather than round-tripping per stage.

## The OMI data model, natively — nodes, glTF, and the engine

Each OMI concept is one node (authorable in `.wrl`), one glTF-extension reader, and one columnar slice
of the world. Because the node fields *are* the OMI fields, the "mapping" is identity.

### `OMI_physics_shape` → `PhysicsShape` (document `shapes[]`)

Shapes are shared, document-level, referenced by index — so 500 crates share one `box`. Types and
exact fields (defaults from the OMI spec):

| `type` | Fields | Engine proxy |
|---|---|---|
| `box` | `size` [3] = `[1,1,1]` | `BoxShape` |
| `sphere` | `radius` = `0.5` | `SphereShape` |
| `capsule` | `height` (mid), `radiusBottom`=`radiusTop`=`0.5` | `CapsuleShape` |
| `cylinder` | `height` (total)=`2.0`, `radiusBottom`=`radiusTop`=`0.5` | `CylinderShape` |
| `convex` | `mesh` (glTF mesh index) | `ConvexHullShape` (hull of the mesh) |
| `trimesh` | `mesh` (glTF mesh index) | `TriangleMeshShape` (static, triangle AABB tree) |

`mesh` reuses the glTF mesh the loader already builds. Geometry nodes still auto-derive a shape when a
`PhysicsBody` has no explicit collider (`Sphere→sphere`, `Box→box`, `IndexedFaceSet→convex`/`trimesh`).

### `OMI_physics_body` → `PhysicsBody` (`motion` / `collider` / `trigger`)

- **`motion`** — `type` (`static`|`kinematic`|`dynamic`, required), `mass` (kg, `1.0`), `centerOfMass`
  [3] (`0,0,0`), `inertiaDiagonal` [3] (`0` ⇒ auto), `inertiaOrientation` quat (`0,0,0,1`),
  `linearVelocity` [3], `angularVelocity` [3], `gravityFactor` (`1.0`). **This is the object-
  characteristics answer:** *immobile Earth* = `type:"static"` (or no `motion`); *weight* = `mass·|g|`;
  *centre of gravity* = `centerOfMass`. A `density` convenience field (VRML-side, non-OMI) derives
  `mass` from shape volume when authoring by hand; it bakes to `mass` on export so glTF stays standard.
- **`collider`** — `shape` (index into `shapes[]`), `physicsMaterial` (index, `-1`=default),
  `collisionFilter` (index, `-1`=default). Solid: generates contacts.
- **`trigger`** — a sensor shape (or a compound of child triggers); overlap events, no contact.

### `physicsMaterials[]` → `PhysicsMaterial`

`staticFriction` (`0.6`), `dynamicFriction` (`0.6`), `restitution` (`0.0`), `frictionCombine` /
`restitutionCombine` (`average`|`minimum`|`maximum`|`multiply`). A `MATERIAL_PRESETS` convenience map
(`wood`/`metal`/`rubber`/`ice`) fills these for hand-authoring; it resolves to a real material entry.

### `collisionFilters[]` → `CollisionFilter`

The standard layer/mask system: which collision groups a body belongs to and which it collides with.
Consulted in the broad phase (§2) to drop non-interacting pairs cheaply.

### `OMI_physics_gravity` → `PhysicsGravity` (global + volumes)

**This supplies world gravity** — the piece the earlier draft wrongly invented:

- **Global** (document-level): `gravity` (magnitude, m/s², required) × `direction` [3] (`0,-1,0`).
  Default world gravity is `9.81` down. Uniform and directional, as OMI specifies.
- **Gravity volumes** (per-node, on a trigger volume): `type`
  (`directional`|`point`|`disc`|`torus`|`line`|`shaped`), `gravity` magnitude, `priority` (`0`),
  `replace` (`false`), `stop` (`false`), plus type params (`direction`, `unitDistance`, `radius`,
  `points`, `shape`). Gives planet/`point` gravity, `directional` lift zones, etc., resolved in
  `resolve_gravity` (§step-1) by priority. Volumes are a Phase-4 feature; the global gravity is Phase 0.

### `OMI_physics_joint` → `PhysicsJoint`

Document `physicsJoints[]`, each a set of **limits** (`linearAxes`/`angularAxes` [int], `min`
=`-∞`, `max`=`+∞`, `stiffness`=`∞`, `damping`=`0`) and **drives** (`type`, `mode`, `axis`,
`maxForce`=`∞`, `positionTarget`, `velocityTarget`, `stiffness`=`0`, `damping`=`0`). A node attaches
via `joint` (index), `connectedNode` (index), `enableCollision` (`false`). This generalizes hinges,
sliders, ball joints, springs, and motors as constraint rows in the solver (§4). Phase 6.

## Cooking — collision geometry from an arbitrary IFS / glTF mesh

Most authored geometry has **no** hand-made collider, so we need a method that takes an arbitrary
loaded `IndexedFaceSet` (or glTF `mesh`) and produces a `model.Shape`. `physics/cookery.py` exposes
`cook_shape(mesh, strategy=…, dynamic=…) -> model.Shape`, choosing among:

| Strategy | Output OMI shape | Use |
|---|---|---|
| `primitive` | best-fit `box`/`sphere`/`capsule`/`cylinder` | cheapest; props that are roughly primitive (crates, barrels, balls). Fit by PCA extents / min-enclosing-sphere. |
| `convex` | one `convex` (hull of the vertices) | default for **dynamic** movers; QuickHull over the coordinate array. |
| `decompose` | compound of `convex` | concave dynamic meshes (a chair, an L-shape); approximate convex decomposition (V-HACD-style) in `hull.py`. |
| `trimesh` | `trimesh` | default for **static** world geometry (parthenon, terrain); raw triangles + cached triangle AABB tree. |
| `auto` | picks by `motion.type` + concavity | `static → trimesh`; `dynamic → convex`, escalating to `decompose` when the hull-to-mesh volume ratio shows significant concavity. |

- **Reuse & cache.** Cooking keys its result through the existing `cache.CACHE` on the coordinate
  node's `point` field — the exact mechanism
  [volumeFromCoordinate](../OpenGLContext/scenegraph/boundingvolume.py#L372) uses — so it invalidates
  automatically when vertices change and is computed once per mesh.
- **Load-time and offline.** The glTF loader calls `cook_shape` when a `PhysicsBody` references geometry
  with no explicit collider; the result is representable as OMI shapes, so a **bake step** (a
  `physics-cook` CLI, mirroring the existing `parthenon-bake` tool) can pre-compute colliders and write
  them back into the glTF, making import free and the decomposition a build-time artifact.
- **Shares the render mesh.** Cooking reads the same coordinate array the renderer already uploaded — no
  duplicate geometry load.

Auto-derivation from geometry nodes (`Sphere→sphere`, `Box→box`, `IndexedFaceSet→convex/trimesh`) is
just `cook_shape` with the strategy implied by the primitive type.

### Large-scene load performance (`gltf_world.extract_trimesh`) — investigated 2026-07-11

**Symptom:** loading large multi-part glTF scenes in the `oglc-gltf` viewer (physics
on by default) became *very* slow. Suspected per-sub-component hull cooking.

**What the code actually does:** `physics/gltf_world.py` walks the scenegraph and
merges **every** mesh's world-space triangles into **one** static `trimesh`
collider (`collision_world_from_scene`). There is no per-component hull/convex
decomposition on this path, so the cost is triangle *extraction*, not cooking.
`world.add_shape` only appends — no BVH is built at load (the triangle AABB tree is
lazy, on first narrowphase).

**Root cause found + fixed (O(M²) → O(M)):** `_collect` recomputed each mesh's
vertex offset as `base = sum(len(p) for p in points)` — a sum over *all* previously
collected arrays, run **once per mesh**. For a CAD assembly with M sub-meshes that
is O(M²): profiled at 49 ms → 176 ms going 2000 → 4000 meshes (≈3.6× for 2×, i.e.
quadratic), extrapolating to seconds at 10k+ parts. Replaced with a running vertex
counter (`state['n']`); now linear — 4000 meshes dropped 176 ms → 28 ms, 8000 → 57 ms.
Covered by `tests/test_gltf_collision_extract.py`.

**Min-AABB substitution (implemented, opt-in).** `extract_trimesh(group,
min_hull_size=…)` / `collision_world_from_scene(…, min_hull_size=…)`: any leaf mesh
whose world-space AABB diagonal is ≤ `min_hull_size` contributes that AABB's **box**
(8 verts / 12 tris) instead of its full triangle mesh — the user's "below this size,
don't bother with a detailed hull; use the AABB." Default `0.0` keeps exact geometry
(no behaviour change). It trades a small per-mesh AABB cost for a much smaller merged
trimesh (168k → 96k tris in a dense synthetic), so the payoff is the **runtime**
narrowphase + memory, not extraction. Imperceptible to a walking character for small
props; not appropriate for large walkable surfaces (hence a *size* threshold, not a
blanket switch).

**Still open / recommended next:**
- **Wire a default `min_hull_size` in the viewer** scaled to the scene (e.g. a small
  fraction of the model's bounding diagonal) so big scenes box-ify tiny props
  automatically. Needs the scene bounds first (the loader already computes
  `scene.radius`), and a decision on the fidelity/behaviour tradeoff before it is on
  by default.
- **Background / lazy physics build.** Even O(M) extraction of a huge scene blocks
  the first frame; build the collision world off the render thread (or on first
  entry to walk mode) with a progress line, so load is never gated on it. Pairs with
  the demo already defaulting to free-fly (no physics build at all).
- **Skip non-walkable geometry.** Only floors/large surfaces need collision; a
  height/orientation heuristic could drop most small triangles from the trimesh.

## Debug rendering of collision geometry

Physics bugs are visual — a proxy that doesn't match its render mesh, a contact normal pointing the
wrong way, a body asleep when it shouldn't be. A **`PhysicsDebugPass`** (or a debug branch in
`FlatPass`, modeled on the existing `debugBBox` path that already draws bounding boxes via
[AABoundingBox.debugRender](../OpenGLContext/scenegraph/boundingvolume.py#L268)) renders, each gated by
a bit in `debugPhysics`:

- **Collision proxies** — wireframe of every `collider.shape` (box/sphere/capsule/cylinder edges;
  `convex` hull edges; `trimesh` as wire triangles), drawn in the body's world pose so you can confirm
  the proxy matches the visible mesh. This is the "render the collision geometry" requirement.
- **Trigger volumes** — same, in a distinct colour (they're sensors, not solids).
- **Broad-phase AABBs**, **contact points + normals** (short lines), **velocity vectors**, **gravity
  direction**, **joint anchors/axes**, and **sleep state** (colour-coded awake/asleep).

Rendering is core-profile-friendly (the wire proxies go through the same VAO/VBO unlit shader path the
rest of the codebase uses, not fixed-function `glBegin`). Because the proxies are `model.Shape` objects,
the debug pass tessellates them directly — no dependence on the render geometry. Toggle via a
`debugPhysics` bitmask (proxies / aabbs / contacts / triggers / sleep / joints) so you render only what
you're investigating.

## Character controller & safe viewpoint binding

Navigation must stay game-usable: get around quickly, and never end up **stuck in the ground**.

**Movement states & actions.** `CharacterCapabilities` (a non-OMI gameplay node, §engine-config) drives
a small state machine on the `PhysicsViewPlatform` capsule body:

| Action | Effect | Capability fields |
|---|---|---|
| walk / **run** / **sprint** | tiered ground speed | `walkSpeed` `runSpeed` `sprintSpeed`, `canSprint` |
| **crouch** | shrink capsule to `crouchHeight`, slow to `crouchSpeed`, lower eye | `crouchHeight` `crouchSpeed` `canCrouch` |
| **jump** | vertical impulse, only when grounded (optional coyote-time) | `jumpHeight` `canJump` |
| **fly / noclip** | ignore gravity, free 3-axis at `flySpeed`; optionally disable collision | `canFly` `flySpeed` |
| ground handling | step up ≤ `stepHeight`, slide on slopes > `maxSlope` | `stepHeight` `maxSlope` |

State transitions respect the world: you can't stand from crouch under a low ceiling (overlap test
first), jump only fires grounded, sprint may gate on stamina if a game wants it. `eyeHeight`/`airControl`
round it out. These are the "jump/run/sprint/crouch to get around" requirement.

**Safe viewpoint binding — never spawn stuck.** VRML/glTF `Viewpoint`/camera nodes *teleport* the
camera on bind; a naïve bind can drop the capsule inside terrain or below the floor. On every bind (and
on any hard reposition) the platform runs **safe placement**:

1. **Depenetration.** Test the capsule against nearby static colliders; if overlapping, push it out
   along the minimum-translation vector (the EPA normal × depth the narrow phase already computes),
   iterating a few times for multiple contacts.
2. **Ground snap.** Cast the capsule (or a ray) downward to find the floor and seat the base on it, so a
   viewpoint authored slightly low doesn't clip — the camera ends at `base + eyeHeight`, not underground.
   Cast upward too if the bind point is *below* the floor, to pop up onto it.
3. **Fallback.** If no free space is found within a small search radius, keep the requested pose but flag
   it (log + optionally enter `fly` so the user is never trapped) rather than wedging into geometry.

Safe placement is off the physics step (it runs at bind time, using the same collision queries), so it
costs nothing during normal play. It also covers respawns, portals, and scripted camera jumps — anywhere
the camera is placed rather than moved.

## Engine config vs. asset data — kept separate

Three things are **not** part of the serialized OMI physics model and stay engine-side, so an asset
never carries solver-tuning or gameplay policy:

- **Solver tuning** — `fixedTimestep` (`1/60`), `maxSubSteps` (`4`), `velocityIterations` (`8`),
  `positionIterations` (`3`), `broadPhase` (`aabbtree`|`sweep`), `solver` (`impulse`|`xpbd`),
  `sleepEnabled`, `debugPhysics`. Live on the `contextDefinition` (a `PhysicsEngineConfig` node), not
  on any body. These are how the sim *runs*, not what the scene *is*.
- **World scale / units** — an **import-time** concern only. glTF/OMI is **metres by spec**, so the
  runtime works in metres and the glTF path needs no scaling. For `.wrl`/legacy assets in mm or km, the
  loader applies a `unitsPerMetre` factor once at load, converting geometry and physics constants into
  metres. Nothing scale-related enters the runtime model — the fix for the old "authored scenes need
  tuning" risk, without polluting the standard.
- **Character capabilities** — `walkSpeed`/`runSpeed`/`sprintSpeed`/`crouchSpeed`/`crouchHeight`/
  `jumpHeight`/`canJump`/`canSprint`/`canCrouch`/`canFly`/`flySpeed`/`stepHeight`/`maxSlope`/
  `eyeHeight`/`airControl` (see §Character controller). **Gameplay/controller** config, deliberately
  outside every asset-interchange standard — a physics asset describes bodies, not how an avatar is
  driven. Held on the `PhysicsViewPlatform` (§Phase 5) as a `CharacterCapabilities` node; serialized (if
  at all) to a vendor `OGLC_character` extension / glTF `extras`. It *drives* an OMI capsule body; it is
  not part of it.

## Files

**New package `OpenGLContext/physics/`**
- `model.py` — the OMI data structures shared by loader, nodes, and world: `Shape` (box/sphere/capsule/
  cylinder/convex/trimesh), `Motion`, `Collider`, `Trigger`, `Material`, `CollisionFilter`, `Gravity`
  (global + volume), `Joint` (limits/drives). Pure data + defaults from the OMI spec.
- `world.py` — `PhysicsWorld`: SoA state + document tables, `step(dt)`, `writeback(alpha)`, gravity
  resolution, add/remove.
- `body.py` — SoA helpers + engine shape proxies (`SphereShape`/`BoxShape`/`CapsuleShape`/
  `CylinderShape`/`ConvexHullShape`/`TriangleMeshShape`) built from `model.Shape`.
- `broadphase.py` — dynamic AABB tree (+ SAP) with `collisionFilters` masking; pair cache.
- `narrowphase.py` — pair dispatch; manifold generation.
- `collide.py` — the math: analytic tests, SAT, **GJK**, **EPA**, convex↔triangle, manifold clipping.
  Pure-CPU, numpy, no GL — the testable core.
- `solver.py` — sequential-impulse contact **and joint** solver (+ XPBD variant behind a flag);
  material combine modes; contact-island partitioning (parallelism + sleeping).
- `hull.py` — convex-hull build + approximate convex decomposition (load-time), cached per asset.
- `cookery.py` — `cook_shape(mesh, strategy, dynamic)`: IFS/glTF mesh → `model.Shape`
  (primitive-fit / convex / decompose / trimesh / auto); cached like `volumeFromCoordinate`.
- `backend.py` — compute-backend surface (`integrate_forces`/`integrate_positions`/`refit_aabbs`);
  `NumpyBackend` (CPU) + `select_backend('numpy'|'gpu'|'auto')` capability probe/fallback.
- `glcompute.py` — `GLComputeBackend` (GL 4.3 compute): the per-body integration kernels as compute
  shaders over the SoA arrays, with a fused single-dispatch fast path for collision-free steps; numpy
  remains the source of truth (each kernel uploads inputs, dispatches, reads outputs back).

**New rendering / tooling**
- `passes/physicsdebug.py` — `PhysicsDebugPass`: wire collision proxies, AABBs, contacts+normals,
  triggers, velocities, gravity, joints, sleep state; core-profile unlit VAO/VBO path, `debugPhysics`
  bitmask (§debug).
- `bin/physics_cook.py` — `physics-cook` CLI baking colliders into a glTF (mirrors `parthenon-bake`).

**New scenegraph nodes** (`scenegraph/`) — one per OMI concept, registered via the node entry points:
- `physicsbody.py` — `PhysicsBody` (+ `PhysicsMotion`/`PhysicsCollider`/`PhysicsTrigger` sub-nodes);
  registers in the world, auto-derives a shape from child geometry when the collider is unset.
- `physicsshape.py` — `PhysicsShape`.
- `physicsmaterial.py` — `PhysicsMaterial` (+ `CollisionFilter`); `MATERIAL_PRESETS`.
- `physicsgravity.py` — `PhysicsGravity` (global + volume).
- `physicsjoint.py` — `PhysicsJoint`.

**Modified**
- `loaders/gltf.py` — read `OMI_physics_shape` / `OMI_physics_body` / `OMI_physics_gravity` /
  `OMI_physics_joint` (and later `KHR_physics_rigid_bodies` / glTF-2.1 `shapes`) straight into
  `physics.model` structures, via the existing per-extension dispatch
  ([gltf.py:681](../OpenGLContext/loaders/gltf.py#L681)); list them in `extensionsSupported`. Export
  path writes them back out.
- `scenegraph/collision.py` — implement the VRML97/X3D `Collision` node's *navigation* collision
  (Phase 5): avatar capsule sliding against `collide` static children + terrain gravity. Today a no-op
  group ([collision.py:5](../OpenGLContext/scenegraph/collision.py#L5)).
- `scenegraph/quadrics.py`, `box.py`, `indexedfaceset.py` — `collisionShape()` delegation producing a
  `model.Shape` (Sphere/Cylinder/Cone→analytic; Box→box; IFS→convex/trimesh).
- `events/eventhandlermixin.py` (or `context.py` `DoEventCascade`) — poll `PhysicsWorld` with the
  fixed-timestep accumulator; trigger redraw when it advances (mirrors the TimeSensor path).
- **New `move/physicsplatform.py`** — `PhysicsViewPlatform` *subclass* (not an edit to the free-fly
  `ViewPlatform`, which writes `self.position` directly,
  [viewplatform.py:252](../OpenGLContext/move/viewplatform.py#L252)). It owns a capsule `PhysicsBody`:
  navigation input becomes desired-velocity / jump impulse (via
  [viewplatform.py:225](../OpenGLContext/move/viewplatform.py#L225) `relativePosition`), and
  `self.position` is read back from the solved body. Holds the movement state machine (walk/run/sprint/
  crouch/jump/fly) and **safe viewpoint binding** (depenetration + ground snap on bind, §Character
  controller). Free-fly and walk-with-gravity coexist by config.
- `move/movementmanager.py` — route input to whichever platform is active; sprint/crouch/jump actions.
- `scenegraph/viewpoint.py` (bind path) — on `Viewpoint` bind, invoke the platform's safe placement so a
  low/embedded viewpoint never leaves the user stuck in geometry.
- `contextdefinition.py` — a `physics` slot: a `PhysicsEngineConfig` (solver tuning, `backend`, and the
  `debugPhysics` bitmask) + the enable flag.
- `plans/PROJECT-PLAN.md` — summary-table entry.

**New demos & docs** (§Demos)
- `tests/physics_room_drop.py`, `physics_navigate.py`, `physics_bounce.py`, `physics_friction.py`,
  `physics_gravity_zones.py`, `physics_triggers.py`, `physics_joints.py`, `physics_cook_view.py`,
  `physics_stress.py` — interactive demos that double as visual-regression tests (auto-exit + capture).
- `docs/physics.html` — feature overview; linked from `docs/documentation.html`.
- `docs/tutorials/` — paired walk-throughs (add-physics, cook-shapes, character-controller,
  gravity/triggers/joints) with screenshots.

## Testing strategy

The whole core (`model`, `collide`, `solver`, `broadphase`, integration, loader) is **pure CPU, no
GL** — fast, deterministic unit tests, per the repo's rules.

1. **Integrator** (`test_physics_integrate.py`): gravity ⇒ `x=½gt²`; linear+quadratic drag ⇒ analytic
   terminal velocity; `gravityFactor` scales fall; zero net force ⇒ constant velocity.
2. **Primitive collision** (`test_collide_primitives.py`): sphere/sphere, sphere/box, sphere/plane,
   box/box — hit/miss and correct `(normal, penetration, point)`.
3. **GJK/EPA** (`test_gjk_epa.py`): random convex pairs vs. brute-force reference; EPA depth/normal on
   analytic overlaps.
4. **Broad phase + filters** (`test_broadphase.py`): AABB-tree pair set = brute-force O(N²); refit =
   rebuild; add/remove invalidation; `collisionFilters` groups that shouldn't collide never pair.
5. **Solver behavior** (`test_solver.py`): restitution energy (`e=1` returns to height, `e=0` rests);
   5-box resting stack stable over 300 steps; box-on-incline slides iff `tanθ>μ` with combine modes;
   determinism (fixed `dt` ⇒ bit-identical runs).
6. **Mesh collision** (`test_mesh_collision.py`): sphere onto a `trimesh` floor rests; a `convex` prop
   vs. its decomposition contacts the right face.
7. **Triggers** (`test_triggers.py`): a body entering/leaving a trigger volume fires enter/exit events,
   generates **no** impulse, and doesn't perturb trajectories.
8. **Joints** (`test_joints.py`): a distance/hinge joint holds its limit; a drive reaches its
   `velocityTarget` within `maxForce`.
9. **Gravity zones** (`test_gravity.py`): a `point` gravity volume pulls a body toward its centre; a
   higher-`priority` volume with `replace` overrides the global; `stop` halts accumulation.
10. **Scenegraph sync** (`test_physicsbody_sync.py`, mock context — no GL): stepping writes
    `Transform.translation`/`rotation`; `kinematic` reads authored motion; sleeping stops writeback.
11. **OMI round-trip** (`test_omi_physics_roundtrip.py`, no GL): a fixture glTF with all four OMI
    extensions loads into `physics.model` with exact fields (`motion.type`/`mass`/`centerOfMass`/shape
    index/material/filter/gravity/joint); re-export reproduces the JSON; `type:"static"` ⇒ immobile.
12. **Cooking** (`test_cookery.py`, no GL): `cook_shape` on a known IFS yields the expected proxy —
    box-ish mesh → `box` within tolerance, sphere-ish → `sphere`, concave L → a `decompose` compound
    whose union covers the mesh; `trimesh` for static; cache returns the same object on repeat.
13. **Character states** (`test_character.py`, no GL): speed tiers (walk<run<sprint); jump only when
    grounded; crouch shrinks the capsule and is blocked from standing under a low ceiling; `canFly`
    ignores gravity; step-up ≤ `stepHeight`, slide on slopes > `maxSlope`.
14. **Safe viewpoint binding** (`test_safe_bind.py`, no GL): binding to a pose embedded in a static box
    depenetrates to a non-overlapping pose; binding just below a floor snaps the base onto it (camera at
    `base+eyeHeight`); no-free-space falls back without wedging. **The "never stuck in the ground" test.**
15. **Performance & scale** (`test_physics_benchmark.py`): N=1000 (and a stretch N=5000) moving boxes,
    `step()` sub-frame, broad phase sub-quadratic, islands solved independently; sleeping scene ≈ free.
16. **Backend parity** (`test_backend_parity.py`, when a second backend lands): `NumpyBackend` and any
    future `GLComputeBackend` produce matching trajectories within tolerance on the same scene.
17. **Debug render** (GL, subprocess): `debugPhysics` proxy overlay draws the collider wireframes at the
    body poses; screenshot regression confirms proxy-vs-mesh alignment.
18. **Frame-loop / visual** (GL, subprocess): the **demos below** double as the visual-regression
    tests — each auto-exits after N frames and its screenshot is compared to a reference image.

## Demos & documentation

Every feature ships **a runnable demo and a doc page**, so users can see it work and verify it
interactively — and the same demo *is* the visual-regression test (auto-exit + screenshot capture via
the existing `OPENGLCONTEXT_AUTO_EXIT_FRAMES` / `_CAPTURE_DIR` harness). Demos live in `tests/` as
`physics_*.py` (the repo's interactive-demo convention, like `shadow_demo.py`/`particles_simple.py`);
docs follow the top-level `docs/*.html` feature-page pattern (`pbr.html`, `instancing.html`) plus paired
`docs/tutorials/` walk-throughs.

**Demo scripts** — each carries a HUD (fps, body count, active mode), on-screen key help, a reset key,
and a deterministic seed so screenshots are stable:

| Demo | Shows | Feature(s) |
|---|---|---|
| `physics_room_drop.py` | **N spheres/boxes fall into a room and settle into a stack**; keys add bodies / reset / colour by sleep state; HUD body-count + step-ms | integrator, primitive collision, solver, stacking, sleeping, scale |
| `physics_navigate.py` | **first-person walk through a level with walls, doors, stairs, ramps**: can't clip walls, climbs steps ≤ `stepHeight`, slides on steep ramps; walk/run/**sprint**/**crouch**/**jump**/**fly**; jump between named viewpoints with **safe binding** (never stuck) | navigation collision, character controller, safe viewpoint binding |
| `physics_bounce.py` | a row of balls with restitution `e = 0…1`, verify rebound heights | materials, restitution |
| `physics_friction.py` | boxes on ramps of increasing angle / different materials — slide threshold | materials, Coulomb friction, combine modes |
| `physics_gravity_zones.py` | a `point`/planet gravity well + a `directional` lift zone; objects fall toward the planet | `OMI_physics_gravity` volumes |
| `physics_triggers.py` | pickups and a pressure-plate door that opens on trigger enter/exit | triggers (sensors) |
| `physics_joints.py` | a pendulum, a hinged door, a rope/chain, a simple ragdoll | `OMI_physics_joint` limits + drives |
| `physics_cook_view.py` | load an arbitrary glTF/IFS, **cook colliders**, toggle the **debug proxy overlay** to compare proxy vs. render mesh, cycle cooking strategies | cooking, debug render, glTF import |
| `physics_stress.py` | scaling/perf demo, adjustable body count + backend selector, on-screen fps/step-ms | scale, islands/sleeping, GPGPU backend (later) |

**Documentation**
- `docs/physics.html` — the feature overview (matching `pbr.html`/`instancing.html`): the OMI data model,
  authoring a `PhysicsBody`/shape/material/gravity/joint, the character controller & config, cooking, the
  debug overlay, and the GPGPU roadmap. Linked from `docs/documentation.html`.
- `docs/tutorials/` — task walk-throughs paired with the demos (the `lightobject`-style page + `.py` +
  screenshots): *"add physics to a scene"*, *"author / cook collision shapes"*, *"build a character
  controller & viewpoints"*, *"gravity zones, triggers & joints"*.
- **Inline** — each demo's module docstring is a short tutorial (the repo's tutorial-code convention), so
  reading the demo teaches the API.

Because a demo is authored the same phase as its feature and is the phase's visual test, "demo +
doc page" is a **completion gate** for every phase, not a trailing chore.

## Phasing

| Phase | Deliverable |
|---|---|
Each phase is **test-first** (§Methodology) and gated on **its demo + doc page** (§Demos): the listed
tests are written red then made green, and the demo is the phase's visual regression.

| Phase | Deliverable | Demo + doc |
|---|---|---|
| **0 — Core + OMI model + global gravity** | `physics/model.py` (all OMI structures) + `physics/backend.py` (`NumpyBackend`) + `PhysicsWorld` SoA + symplectic-Euler integrate with **global `OMI_physics_gravity`** + linear/quadratic drag + `gravityFactor`; fixed-timestep accumulator in `DoEventCascade`; `PhysicsBody`/`PhysicsMotion` writing back to `Transform`; render interpolation. **No collision yet.** Tests 1, 10. | a falling-object demo (no-collision arc/drag); `docs/physics.html` skeleton |
| **1 — Primitive collision + impulse solver + materials/filters + debug render** | `OMI_physics_shape` primitives; analytic narrow phase; dynamic AABB-tree broad phase with `collisionFilters`; sequential-impulse solver with `physicsMaterials` (combine modes) + Baumgarte; islands + sleeping; **`PhysicsDebugPass`** landed early as the dev-visibility tool. Tests 2, 4, 5, 17. A *usable game engine*. | **`physics_room_drop.py`**, `physics_bounce.py`, `physics_friction.py`; physics overview doc |
| **2 — glTF `OMI_physics_*` import/export** | Read/write `OMI_physics_shape`/`_body` through `physics.model`; load real Godot/Blender assets. Test 11. The KHR/glTF-2.1 reader reuses the path. | import a Godot/Blender physics glTF; import tutorial |
| **3 — Convex & mesh collision + cooking** | GJK + EPA; `convex` hull proxy; `trimesh` static triangle-soup; approximate convex decomposition; **`cookery.cook_shape`** + `physics-cook` bake CLI. **mesh↔mesh.** Tests 3, 6, 12. | **`physics_cook_view.py`**; "author/cook collision shapes" tutorial |
| **4 — Triggers + gravity volumes** | `OMI_physics_body.trigger` sensors → enter/stay/exit events; `OMI_physics_gravity` volumes resolved by priority/replace/stop. Tests 7, 9. | `physics_triggers.py`, `physics_gravity_zones.py`; tutorial |
| **5 — Navigation, character controller & safe binding** | VRML97/X3D `Collision` node + `PhysicsViewPlatform` (capsule) with the full movement state machine (walk/run/**sprint**/**crouch**/**jump**/**fly**, step/slope) driven by `CharacterCapabilities`, and **safe viewpoint binding** (depenetration + ground snap — never stuck). Tests 13, 14. | **`physics_navigate.py`** (walls/doors/stairs); "character controller & viewpoints" tutorial |
| **6 — Joints, warm-start polish, CCD, XPBD (opt.)** | `OMI_physics_joint` (limits + drives) as solver constraints; warm starting + split impulse; speculative contacts / TOI; XPBD swap. Test 8. | `physics_joints.py`; joints tutorial |
| **7 — GPGPU backend** | `GLComputeBackend` (GL 4.3 compute, `physics/glcompute.py`): per-body **integrate forces + positions** run as compute shaders over the SoA arrays, fused into one dispatch when a step has no collision/joints (intermediate velocity stays GPU-side). Default `auto` policy: numpy below `gpu_threshold` (10k) awake bodies, GPU above (hysteresis on the return), numpy fallback where compute is absent (`OPENGLCONTEXT_PHYSICS_BACKEND` overrides); no simulation-logic change — the Phase-0 abstraction pays off. ~2.4× faster than numpy at 10⁵ movers. Broad/narrow/solve and a full GPU-resident loop (LBVH, graph-colored/XPBD solver) remain future. Test 16 (parity, `tests/test_backend_parity_gpu.py`). | **`physics_stress.py`** (body-count + live `b` backend toggle); GPGPU roadmap doc |

## Open questions / risks

- **Matrix convention.** Row-vector `point·matrix`; quaternion→matrix and inertia transforms must stay
  in that convention (the mismatch flagged in RAYCAST-PICKING and the glTF bounds code). Guarded by the
  sync test (10) and a pose round-trip.
- **float32 vs float64.** Render matrices are `float32`; physics wants `float64`. World stays `float64`,
  cast on writeback.
- **OMI is pre-1.0.** The extensions are shipping (Godot) but still evolving; field names could shift.
  Isolating them in `physics/model.py` keeps churn to one file, and the KHR reader lands on the same
  structures — so the *model* is stable even if a *spelling* changes.
- **Shape sharing / instancing.** OMI shapes are document-level shared — good — but the
  `volumeFromCoordinate` pathology ([boundingvolume.py:391](../OpenGLContext/scenegraph/boundingvolume.py#L391))
  (many shapes indexing one giant coordinate node) still weakens a `trimesh` triangle tree. Note it;
  require per-body distinct collision geometry in v1.
- **Convex decomposition cost/quality.** The fuzziest step; cache it as a load-time artifact and let an
  explicit `convex`/compound collider bypass it.
- **Gravity-volume overlap semantics.** `priority`/`replace`/`stop` interactions across overlapping
  volumes need care; test 9 pins the common cases, exotic stacks deferred.
- **Coupling physics to the render clock.** `dt` from the context clock means a stalled render stalls
  physics (fine for a game). A dedicated fixed-rate thread is a later option.
- **GPGPU determinism & solver serialism.** Sequential impulses is Gauss-Seidel (serial); a GPU path
  needs islands + graph-colored Jacobi or XPBD, and GPU atomics/reductions aren't bit-deterministic — so
  the determinism guarantee is CPU-backend-only, best-effort on GPU. Stated up front so nobody builds
  lock-step netcode on the GPU backend. The `backend.py` seam keeps this contained to one module.
- **Compute-shader availability.** `GLComputeBackend` needs GL 4.3 core (compute shaders). Fine on the
  NVIDIA dev container; a capability probe must fall back to `NumpyBackend` where compute is absent
  (same pattern as the instancing capability detection already in the codebase).
- **Cooked-collider fidelity.** A best-fit primitive or a coarse convex hull can mismatch the visible
  mesh (too fat/thin); the debug proxy overlay (test 17) is the guard, and `auto` escalates to
  `decompose` on high concavity — but authored/hand-tuned colliders always win.

## References

**Standards (the data model)**
- OMI: [OMI_physics_body](https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/OMI_physics_body),
  [OMI_physics_shape](https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/OMI_physics_shape),
  [OMI_physics_gravity](https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/OMI_physics_gravity),
  [OMI_physics_joint](https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/OMI_physics_joint).
- Khronos: [KHR_physics_rigid_bodies (PR #2424)](https://github.com/KhronosGroup/glTF/pull/2424),
  [KHR_implicit_shapes (PR #2370)](https://github.com/KhronosGroup/glTF/pull/2370), glTF 2.1 `shapes`.
- X3D *Rigid Body Physics* component (VRML/X3D field vocabulary).

**Simulation (the engine)**
- Erin Catto, *Iterative Dynamics with Temporal Coherence* (2005) + GDC 2006–2009 (sequential impulses,
  warm starting, split impulse) — the Box2D method.
- Glenn Fiedler, *Fix Your Timestep!* / *Integration Basics* (symplectic Euler, accumulator, interp).
- Gino van den Bergen, *Collision Detection in Interactive 3D Environments* (GJK/EPA).
- Christer Ericson, *Real-Time Collision Detection* (broad phase, AABB trees, SAT, manifolds).
- Müller et al., *Position Based Dynamics* (2007); Macklin et al., *XPBD* (2016).
- Mamou & Ghorbel, *approximate convex decomposition* (V-HACD).
