# Native physics behind the Physics service

Status: **Planned.** Research and a measured spike, 2026-10-26. No production code changed.

Recommendation: adopt Jolt Physics 5.6 (C++17, MIT) through a binding of our own, a batched
array-in array-out nanobind module shipped as a separate optional distribution. `omi_physics`
stays the default backend, the fallback and the differential-test oracle. The `Physics` service
API in OpenGLContext does not change; `PhysicsDefinition` gains a `backend` field.

On the spike's scenes, one thread each, Jolt steps active bodies 290 to 930 times faster than
`omi_physics`: 1,000 active boxes in 0.47 ms against 143 ms, 5,000 in 2.7 ms against 2,533 ms.
A pile of 1,000 boxes is 26 times faster, a 12-link chain 80 times (0.03 against 2.5 ms), 30
characters among 10,000 posts 15 times (0.29 against 4.2 ms) and on a heightfield 3.5 times
(0.31 against 1.10 ms). A scattered ray costs 0.54 us against 1,217 us.

## Why

The service measured on 2026-10-25 (inline, 60 Hz frames of two 120 Hz steps): 100 active
dynamic bodies 14 to 17 ms a frame, 1,000 active 136 to 174 ms, 30 characters 5 to 7 ms, 30
characters among 10,000 posts 13 ms, a settled world 0.05 ms. A game wants thousands of active
bodies, many characters, heightfields, trimeshes and joints inside a few milliseconds.
`omi_physics` already runs its solver and box and sphere collision in Cython; the remaining
cost is Python orchestration per pair, per body and per joint. Closing a gap of two to three
orders of magnitude means compiling the whole step, which is writing a native engine.

The goal: a simulator with no Python in its hot path. Python is called from inside it only for
callbacks (contacts, triggers, step hooks, character events), and those are batched. Broadphase,
narrowphase, solver, joints, character controller, CCD, raycast, sweep and overlap queries,
heightfields and trimeshes are native.

## The field

Checked on PyPI, GitHub and crates.io on 2026-10-26 (`pip index versions`, the PyPI JSON API,
the GitHub API, licence files).

| Engine | Licence | Language | Python binding | Wheels | Activity | Fit |
|---|---|---|---|---|---|---|
| Rapier 0.36 | Apache-2.0 | Rust | `rapier3d` 0.36.1, official (dimforge), Alpha, first on PyPI 2026-09-25 | abi3: Linux x86-64 and aarch64 (glibc, musl), macOS arm64, Windows x86-64; no macOS x86-64 | repo pushed 2026-10-10, 5.9k stars | every feature on the list; per-object API, no array calls; 18.8 MB `.so`, 5.0 to 6.1 MB wheel |
| Jolt 5.6.0 | MIT | C++17 | none official; Culverin 0.15 (MIT, one maintainer, 11 stars, since 2026-01); joltc C API (MIT) | Culverin: cp312 to cp314t, Linux x86-64, macOS arm64, Windows x86-64 | release 2026-07-11, repo pushed 2026-10-25, 11.8k stars; used in Horizon Forbidden West and Death Stranding 2 | every feature on the list, plus ragdolls, wheeled, tracked and motorcycle vehicles, soft bodies, state save and restore; spike module 2.8 MB stripped, 1.1 MB zipped |
| PhysX 5 | BSD-3 (SDK) | C++ | `ovphysx` 0.7, NVIDIA Omniverse licence, USD-stage scenes, Alpha | Linux, Windows | active | binding licence is not BSD-style; GPU parts are binary; heavy build |
| Bullet 3 | zlib | C++ | `pybullet` 3.2.7 (2025-01), no wheels for 3.12 and later | sdist only for 3.12+ | last release 3.25, 2022-04 | robotics API, per-object calls, older design |
| Box2D 3.2 | MIT | C | `box2d-py` 2.3.8 is the old v2 | | active | 2D only |
| ODE | LGPL-2.1 or BSD-3 | C++ | none current (`ode` on PyPI is an unrelated ODE solver) | | maintenance | old design; BSD option exists |
| MuJoCo 3.17 | Apache-2.0 | C | official | all | active | robotics; generalized coordinates; a model compiled up front; no game character controller |
| Newton 1.7, Warp 1.18, Genesis 0.2 | Apache-2.0 | Python on Warp/CUDA | official | | active | GPU robotics simulators; no CPU game path |

Rapier and Jolt are the two that meet the requirements. The rest are out for licence (PhysX's
Python layer), age (Bullet, ODE), dimension (Box2D) or purpose (MuJoCo, Newton, Warp, Genesis).

Feature mapping from the OMI model (`omi_physics.model`) to each:

| OMI | Jolt | Rapier |
|---|---|---|
| box, sphere, capsule, cylinder | Box, Sphere, Capsule, Cylinder shapes | cuboid, ball, capsule, cylinder |
| convex | ConvexHullShape | convex_hull |
| trimesh | MeshShape | trimesh |
| heightfield grid | HeightFieldShape (sample count padded to its block size) | heightfield |
| heightfield sample function | sampled to a grid on add; the function stays in Python | same |
| compound | StaticCompoundShape, MutableCompoundShape | compound |
| Material, combine modes, pair friction | per-body friction and restitution; combine through `SetCombineFriction` / contact listener | per-collider, combine rules min, max, average, multiply |
| CollisionFilter systems | ObjectLayer pair table plus GroupFilterTable | InteractionGroups (32 bits) |
| Trigger, sensor | `mIsSensor` bodies, contact added and removed | sensor colliders, intersection events |
| Joint limits and drives | SixDOFConstraint (limits, motors), Hinge, Point, Slider, Fixed | GenericJoint (limits, motors), impulse and multibody joints |
| gravity volumes | gravity factor plus a native PhysicsStepListener | per-body gravity scale plus forces |
| vehicle | VehicleConstraint | DynamicRayCastVehicleController |
| CharacterController | CharacterVirtual (move and slide, stairs, slopes, stick to floor, inner body for pushing) | KinematicCharacterController (move_shape) |

Determinism: both repeat a run bit for bit on one machine, and gave identical poses with 1 and 8
threads in the spike. Across platforms Jolt has `CROSS_PLATFORM_DETERMINISTIC` (measured 0 to 9%
slower here, 8% in Jolt's documentation); Rapier has the `enhanced-determinism` feature, which the
PyPI wheel is built without and which turns off SIMD and parallelism.

Threading: Jolt runs a step on its own job system and does not allow body reads, writes or
queries while `PhysicsSystem::Update` runs; queries are thread-safe between steps. Rapier's binding
raises if the world is used from a second thread during a step. Neither calls Python during a step
when events go to a native buffer: Jolt through a contact listener we write, Rapier through
`ChannelEventCollector`.

Build: Jolt is CMake and C++17, 153 source files, 5 seconds at 24 jobs (60 s CPU). Rapier with
our own binding needs a Rust toolchain and maturin in every wheel job; with the official wheel it
needs nothing.

## The spike

Scripts and builds are in
`/tmp/claude-1000/-workspaces-OpenGL-dev/cb190171-d05a-482b-9f96-5cc0d4e1e0b6/scratchpad/native/`:

- `scenes.py` - the scenes as arrays, after `framecost/bench.py`: a 200 m trimesh ground of
  20,000 triangles, 1,000 or 10,000 static posts, boxes (0.5 m, 1 kg) on a grid, an upward
  impulse of 3 N s to a quarter of them every 20 frames; a 10-layer pile of touching boxes;
  capsule characters (0.3 m radius, 1.8 m) running at 4 m/s, turning every 30 frames; a 256 x 256
  heightfield; chains of 12 capsule links on ball joints; 100,000 downward rays scattered over
  the world.
- `run_omi.py` - `omi_physics.PhysicsWorld` from the physics-services worktree, called directly,
  Cython accelerators loaded.
- `run_rapier.py` - the `rapier3d` 0.36.1 wheel.
- `run_jolt.py` and `jph/jphspike.cpp` (348 lines) - Jolt 5.6.0 through the boundary prototype:
  bodies added from arrays, poses read into a NumPy array, contacts drained as two arrays, rays,
  sweeps and characters in batches, the GIL released inside each call.
- `det_and_gil.py` - repeatability and the cost of a stepping thread to Python.
- `run_all.sh` rebuilds and reruns everything; `results/*.jsonl` hold the numbers below.

Machine: AMD Ryzen AI MAX+ 395, 32 threads, Python 3.14.7, g++ 13.3. Times are mean ms per 60 Hz
frame (two 120 Hz steps), 120 timed frames after 30 warm-up frames; `omi_physics` 5,000 boxes and
100 chains were timed over 30 frames. Rapier's characters, rays and pose reads include one Python
call per character, ray or body, since its binding has no batch calls.

| Case | omi_physics | Rapier 1 thread | Rapier 8 | Jolt 1 thread | Jolt 8 |
|---|---|---|---|---|---|
| 100 boxes, active | 15.2 | 0.10 | | 0.053 | |
| 100 boxes, settled | 0.18 | 0.005 | | 0.003 | |
| 1,000 boxes, active | 142.7 | 0.94 | 0.67 | 0.47 | 0.39 |
| 1,000 boxes, settled | 0.67 | 0.013 | 0.015 | 0.003 | 0.003 |
| 1,000 boxes, 10,000 posts, active | 143.1 | 0.91 | | 0.59 | |
| 5,000 boxes, active | 2,533 | 5.82 | 1.50 | 2.71 | 1.20 |
| 5,000 boxes, settled | 2.91 | 0.016 | 0.008 | 0.003 | 0.003 |
| 1,000 boxes and spheres, active | 73.6 | 1.57 | | 1.01 | |
| 1,000 boxes and spheres, after 3,000 frames (spheres still rolling) | 9.2 | 0.45 | | 0.42 | |
| 5,000 boxes and spheres, active | | 8.44 | 3.12 | 6.15 | 3.00 |
| pile of 1,000 boxes | 173.8 | 8.10 | | 6.76 | |
| pile of 5,000 boxes | | 83.7 | 14.9 | 44.5 | 13.4 |
| 1 character, 10,000 posts | 0.149 | 0.022 | | 0.010 | |
| 30 characters, 10,000 posts | 4.23 | 0.97 | | 0.29 | |
| 30 characters, heightfield | 1.10 | 1.28 | | 0.31 | |
| 300 characters, heightfield | | 13.9 | | 3.08 | |
| one 12-link chain | 2.55 | 0.054 | | 0.032 | |
| 100 12-link chains | 227.3 | 2.02 | 1.49 | 2.64 | 0.78 |
| 100,000 scattered rays | about 122,000 (1,217 us a ray, 2,000 timed) | 156 (1.56 us) | | 54.2 (0.54 us) | |
| 100,000 sphere sweeps, r 0.3 m | | | | 154.6 (1.55 us) | |
| read 5,000 poses | in-process arrays | 4.35 | | 0.68 | |

Further results:

- Stability. The piles kept their columns: largest sideways drift after 120 frames 0.053 m
  (`omi_physics`), 0.061 m (Rapier), 0.046 m (Jolt). Chain links stayed 0.25 to 0.27 m from
  their anchors.
- `omi_physics.raycast_many` is fast for a coherent bundle (22 us a ray for 100 rays within 2 m)
  and slow for scattered rays: 20 scattered rays took 961 ms, since the bundle's box covers the
  world and every ray is tested against every candidate.
- Contact events from Jolt's native buffer: 23 to 33 a frame at 5,000 bodies, drained as two
  arrays inside the frame times above.
- A Python thread stepping 5,000 boxes slowed a pure-Python loop on the main thread by 0.5%
  (Jolt) and 10% (Rapier). The stepping thread reached only 90 and 70 frames a second, against
  830 and 670 alone: it takes the GIL back between steps and waits out the 5 ms switch interval
  each time. A stepping thread owned by the native module, which never takes the GIL, removes
  that limit.
- Jolt builds: single precision, double precision (`DOUBLE_PRECISION`, positions in float64) and
  cross-platform deterministic ran the same cases within 0 to 10% of each other (5,000 boxes
  3.59, 3.69, 3.91 ms; 300 characters 3.77, 3.86, 3.48 ms; this run shared the machine with
  other work, so its absolute numbers sit above the table's).
- Service numbers on the same machine (`framecost/final.txt`, inline): 100 boxes 17.0 ms, 1,000
  boxes 174 ms, 30 characters 7.3 ms, 30 characters among 10,000 posts 13.3 ms, 1,000 settled
  boxes with 30 characters 36.8 ms. The direct `omi_physics` numbers above agree with them; the
  service's own share (snapshot, replica, node writes) is 0.3 to 2.4 ms of each frame.

## Options weighed

1. Adopt Jolt through our own binding (recommended). C++17 and nanobind, Jolt vendored with its
   MIT notice, as `opengl_basisu` vendors basis_universal. Fastest single-threaded engine in the
   spike, 2.8 MB module, compilers already in the CI matrix, the widest game feature set. Cost:
   the binding is ours to write and maintain (estimate below).
2. Adopt Rapier through the official `rapier3d` wheel. Usable today with no native code of ours.
   Each body, ray and character crosses the boundary as a Python call: 0.87 us a body to read a
   pose (4.4 ms a frame at 5,000), 1.56 us a ray, about 43 us a character. The binding is two
   months old and Alpha. A good prototype backend; it does not meet "no Python in the hot path"
   at scale.
3. Adopt Rapier through our own PyO3 binding. The same boundary design as option 1, a Rust
   toolchain in every wheel job, 1.2 to 2.1 times Jolt's single-threaded time in the spike
   (5,000 boxes 5.8 against 2.7 ms, pile of 5,000 83.7 against 44.5 ms) and faster on 100
   chains (2.0 against 2.6 ms); 1.04 to 1.9 times Jolt's time at 8 threads.
   The choice if the maintainer wants Rust's memory safety over C++.
4. Write our own native engine (Rust or C++), porting `omi_physics`'s algorithms. Jolt is 114,000
   lines of C++ with SIMD, a job graph, large-island splitting and CCD; `omi_physics` is 14,800
   lines of Python that run 300 times slower. Matching Jolt is a project of a year or more
   (opinion), with the result unproven. Rejected.
5. Keep `omi_physics` and add more compiled kernels. The solver and box and sphere collision
   are compiled already and 1,000 active boxes still cost 143 ms; the rest is per-pair and
   per-body Python. Removing it compiles the whole step, which is option 4. Rejected.

## The boundary

One native object, `World`, owns the Jolt `PhysicsSystem`, a job system, a temp allocator, a
command ring and two pose buffers. Every call takes or fills arrays for many bodies. Body ids are
`uint32` slot plus generation, the same scheme as `BodyRef` and the service's uids.

```python
world = native.World(max_bodies, threads=0, double_precision=False)

# shapes and materials, from the OMI model, once
shape = world.add_shape(kind, params)              # box, sphere, capsule, cylinder, convex(points),
                                                   # trimesh(points, tris), heightfield(heights, origin, spacing),
                                                   # compound(parts)
world.define_material(index, static_friction, dynamic_friction, restitution, friction_combine, restitution_combine)
world.set_pair_friction(material_a, material_b, friction)
world.set_filters(table)                           # (F, F) bool collides-with, from CollisionFilter

# bodies, in bulk
ids = world.add_bodies(shape, motion_kind, positions, orientations, masses, materials, filters, flags)
world.remove_bodies(ids)

# commands, applied at the start of the next step; callable from any thread, never blocks
world.post(op_codes, ids, values)                  # impulse, torque impulse, force, velocity,
                                                   # angular velocity, place, damping, wake, freeze,
                                                   # gravity, kinematic target

world.step(dt, steps=1)                            # inline: releases the GIL
world.start(tick_hz, max_catch_up)                 # thread: a native thread steps on its own clock
world.stop()

# results
snap = world.snapshot()                            # zero-copy views of the published buffer:
                                                   # rows, position, orientation, linear and angular
                                                   # velocity, awake, changed rows, step, time, applied_seq
pairs, contacts = world.drain_events()             # (E, 2) uint32 ids, (E, k) float32: phase, point,
                                                   # normal, approach, impulse, friction impulse, slip, depth,
                                                   # step; sorted by (step, a, b)

# queries: between steps, or holding the read side of the step lock in thread mode
hits = world.raycast(origins, directions, max_distance, filter, skip)    # (N,) distance, body, point, normal, triangle
hits = world.sweep(shape, origins, directions, max_distance, filter)
found = world.overlap(shape, positions, filter)

# characters, in bulk
chars = world.add_characters(feet, capabilities)   # radius, height, crouch height, step, slope, mass
world.drive_characters(chars, moves, actions, dt)  # moves (K, 3), action codes: jump, crouch, swim, fly
state = world.character_state(chars)               # position, velocity, ground state and normal, flags
```

Mapping to `OpenGLContext.physics.records`:

- `Command` stays the service's record. `WorldRuntime.apply` turns the `_op_*` set into rows of
  `post`; `add` and `add_many` become `add_bodies`; `run` and `post` of Python functions stay on
  the Python side and run between steps.
- `Snapshot` is built from `world.snapshot()` without copying: the native module publishes
  position, orientation and velocities for the moving rows into one buffer while the other is
  read, and lists the changed rows. `axis_angle` for the scenegraph is the one array computed in
  Python, over the changed rows.
- `PhysicsEvent` is made from `drain_events()` on the render thread, once a frame. Sorting by
  step and pair makes the order the same on every run, since Jolt calls its contact listener from
  several threads.
- Step hooks (`before-step`, `after-step`, `drive`) are Python and need the GIL per step. Inline,
  the frame calls `step` once per step and runs them between. In thread mode a world with step
  hooks hands the GIL over once a step; a world without them never touches Python.
- The `Replica` is not needed on the native backend: inline, queries run against the live world
  between steps; in thread mode they take the read side of a lock the stepping thread holds for
  the length of `Update` (1.2 ms at 5,000 active boxes on 8 threads).

Python that the native backend makes unused on its path: `replica.py`, the snapshot assembly in
`runtime.py`, `omi_physics`'s step, broadphase, narrowphase, solver, joints, raycast and
`CharacterController` collision. They stay in `omi_physics` as the reference backend.

What stays Python: the OMI model and glTF reader and writer (`model.py`, `omi_gltf.py`), the
service (`service.py`, `body.py`, `records.py`, `events.py`), proxies and cooking, X3D rigid body
mapping, debug drawing, character animation and locomotion, and the character state machine
until phase 4 moves it.

## Keeping the OMI model the source of truth

The native module knows shapes, materials, filters, joints and motions as numbers. The Python
layer reads the OMI model (`omi_physics.model` records and the glTF extension) and lowers it to
those calls; nothing in the native module parses glTF. A world exported to glTF is written from
the OMI records the service holds, whichever backend stepped it.

`omi_physics` keeps the same Python API and is the oracle:

- A backend protocol in `OpenGLContext.physics` (`OmiBackend`, `NativeBackend`) behind
  `WorldRuntime`. `PhysicsDefinition.backend` is `auto` (native when installed), `omi` or
  `native`.
- A differential suite runs each engine physics test on both backends and compares behaviour,
  since two solvers never agree to the bit: rest positions within a tolerance, the set of contact
  begin and end pairs, trigger occupancy, a character's arrival and ground state, ray hits to
  1 mm.
- `omi_physics`'s behaviour-level tests (characters, joints, contact events, triggers, materials,
  filters, heightfield; 1,073 test functions in 92 files) are the conformance list for the native
  backend. Tests of `omi_physics` internals stay where they are.

## Repository and distribution

A new project, by the rules in the workspace `CLAUDE.md` under New Projects: a submodule,
installed editable by `uv sync`, ruff and mypy configured in `pyproject.toml` and run in CI for
the Python layer and the `.pyi` stub, GitHub CI with tests and wheels.

- Name: `omi_physics_native` or `opengl_jolt` (open decision 2).
- Build: scikit-build-core with CMake and nanobind, Jolt 5.6.0 vendored under `vendor/` with
  its `LICENSE`; nanobind is BSD-3. Both notices go in `NOTICE` and into the wheel, as in
  `opengl_basisu`.
- Wheels: cibuildwheel on `ubuntu-latest`, `ubuntu-24.04-arm`, `macos-latest`, `macos-15-intel`,
  `windows-latest` (and `windows-11-arm` if wanted); CPython 3.12 to 3.14 and 3.14t. About
  1.1 MB a wheel compressed. Jolt's AVX2 path is chosen at build time, so x86-64 wheels are built
  for SSE4.2 (open decision 6).
- OpenGLContext declares it as an optional extra (`OpenGLContext[native-physics]`). Without it
  every program runs on `omi_physics`, as today.

## Phases

Estimates are in engineer-weeks (opinion).

| Phase | Work | Weeks | The games |
|---|---|---|---|
| 0 | This spike | done | unchanged |
| 1 | The new project: world, OMI shapes, materials and combine modes, filters, bodies in bulk, commands, step, pose buffer, sleep, contact and trigger events, raycast, sweep, overlap; wheels on every platform | 3 to 4 | unchanged |
| 2 | Backend protocol behind `WorldRuntime`; `PhysicsDefinition.backend`; the differential suite; engine physics tests on both backends | 2 to 3 | run on `omi` by default; `native` opt-in |
| 3 | Joints (limits, drives, motors), kinematic drive, gravity zones as a native step listener, CCD, compounds, vehicles | 2 | marble-demo and the X3D rigid body tutorials on `native` |
| 4 | Characters: CharacterVirtual in bulk with `CharacterCapabilities` (step height, slope, crouch shape, swim, fly, slide, knock-down), pushing bodies and knockback; the state machine moves native once the Python one is measured on top | 3 to 4 | twig-bb and hill-runner on `native` |
| 5 | Thread mode on a native thread: command ring, double-buffered snapshot, step lock for queries; `Replica` unused on this path | 2 | thread mode on `native` |
| 6 | Glisteel and the forest; `auto` becomes the default; docs (`docs/physics.rst`, a page for the backends), tutorials on both | 2 to 3 | all on `auto` |

Total 14 to 18 weeks. At every phase the games run, because `omi` stays the default until phase 6
and `native` is switched on per program.

## Risks

- Determinism across platforms needs the cross-platform build, measured 0 to 9% slower here. A
  telemetry replay on the machine that recorded it is deterministic with any build.
- Precision. Single-precision positions resolve about 1 mm at 10 km; glisteel's streamed worlds
  span kilometres. The double-precision build ran within 3% here; the other route is shifting
  the world origin with the camera.
- Behaviour differences from `omi_physics` (friction feel, restitution, sleep thresholds,
  character step-up) change how the games play; the differential suite finds them, and tuning
  constants per backend fixes most.
- C++ memory safety. A crash in the native module takes down the process. Jolt's own asserts
  build, ASan and UBSan runs of the conformance suite in CI, and argument checking on the Python
  side of every call (array shapes, dtypes, live ids) are the guards.
- Jolt does not allow queries during a step. Thread mode serialises queries against `Update`;
  the wait is at most one step.
- Two backends are maintained in parallel. `omi_physics` becomes the reference and stops
  growing features for speed.
- Wheel builds add a C++ project to the release; `opengl_basisu` already runs the same matrix.
- Licence: Jolt MIT, nanobind BSD-3, Rapier and its 114 dependencies Apache-2.0, MIT, BSD,
  Zlib or Unicode-3.0 (from the wheel's SBOM). No copyleft code is read or linked.

## Open decisions

1. Jolt with our binding (recommended), or Rapier (the official wheel now, or our own PyO3
   binding later).
2. The distribution's name, and whether `auto` picks the native backend when it is installed.
3. Whether replays must match across machines (the cross-platform deterministic build).
4. Single or double precision, or origin shifting, for kilometre-scale worlds.
5. Step hooks in thread mode: a GIL handoff each step, or hooks once a frame.
6. x86-64 wheels at SSE4.2, AVX2, or both with a runtime choice.
7. Whether `omi_physics` keeps growing features or becomes the reference implementation only.
